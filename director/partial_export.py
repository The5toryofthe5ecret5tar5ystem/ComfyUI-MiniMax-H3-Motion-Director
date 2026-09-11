# Portions derived from ComfyUI_MiniMaxH3_Director
# Copyright AIMixer and contributors
# Originally licensed under Apache License 2.0
# Modified for MiniMax H3 Motion Director, 2026-09-07
# This derivative project is distributed under GPL-3.0.
# See NOTICE and LICENSES/Apache-2.0-AIMixer.txt.

"""Partial export on Stop.

The executor's cooperative Stop ("finish the current segment, then stop") used to
raise ComfyUI's interrupt the moment the request was seen, which discarded every
segment that had already finished: the run ended with nothing on screen and the
work was only recoverable through Resume.

A stopped run still has a perfectly good finished prefix, so instead of aborting
the executor leaves the segment loop and lets the normal assemble path run over
just the segments that actually completed. ComfyUI's own Cancel button is
unaffected - it still hard-aborts through ``InterruptProcessingException`` raised
inside sampling, and that exception is never caught here.

This module owns the decision itself, kept free of torch and of the executor so it
can be unit-tested directly:

* ``narrow_to_completed_prefix`` reduces the run to what finished.
* ``PartialExport`` carries the narrowed run plus the report text.

Two invariants matter and are covered by tests:

* The resume manifest is never widened - only segments the executor already
  marked done are exported, so Resume still restarts at the first unfinished
  segment.
* A run that was not stopped is returned unchanged, so an uninterrupted render
  behaves exactly as before.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Collection, Iterable, Sequence

__all__ = ["PartialExport", "narrow_to_completed_prefix"]


@dataclass(frozen=True)
class PartialExport:
    """The subset of a run that finished before a cooperative Stop."""

    # Segments to assemble, in run order (0-based plan indices).
    run_list: list[int] = field(default_factory=list)
    run_indices: frozenset[int] = frozenset()
    # Source Bridges are only resolvable while BOTH of their sides exist.
    bridge_pairs: list[tuple[Any, Any]] = field(default_factory=list)
    # Total segments in the plan, so reports can say "3 of 10".
    segment_total: int = 0
    # Segments that were requested this run but never started.
    unsampled: list[int] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        """False when nothing finished, i.e. there is no prefix to export."""
        return bool(self.run_list)

    def summary(self) -> dict[str, Any]:
        return {
            "completed": [index + 1 for index in self.run_list],
            "completed_count": len(self.run_list),
            "segment_total": int(self.segment_total),
            "unsampled": [index + 1 for index in self.unsampled],
        }

    def report_lines(self) -> list[str]:
        """`[Final]` report body for a stopped run."""
        done = ", ".join(str(index + 1) for index in self.run_list) or "none"
        return [
            "STOPPED (partial export)",
            f"Segments completed: {done} ({len(self.run_list)} of {int(self.segment_total)})",
            "The segments above were assembled into this result. Nothing after the stop point was "
            "sampled, cached, or marked done — press Resume to continue from the first unfinished "
            "segment.",
        ]

    def warning(self) -> str:
        done = ", ".join(str(index + 1) for index in self.run_list) or "none"
        return f"Stopped early: exported the completed prefix only (segment(s) {done})."


def narrow_to_completed_prefix(
    *,
    run_list: Sequence[int],
    completed: Collection[int],
    bridge_pairs: Iterable[tuple[Any, Any]] = (),
    segment_total: int = 0,
) -> PartialExport:
    """Reduce a stopped run to the segments that finished, in run order.

    ``run_list`` is the run selection in plan order and ``completed`` is the set
    of plan indices that produced a usable result. Because the executor stops at
    the first request, the kept segments are always a prefix of ``run_list`` — but
    this function does not rely on that, it simply keeps the intersection so a
    partial run started at an offset still behaves sensibly.
    """
    completed_set = {int(index) for index in completed}
    requested = [int(index) for index in run_list]
    kept = [index for index in requested if index in completed_set]
    kept_set = frozenset(kept)
    pairs = [
        pair for pair in bridge_pairs
        if {int(pair[0].index), int(pair[1].index)} <= kept_set
    ]
    return PartialExport(
        run_list=kept,
        run_indices=kept_set,
        bridge_pairs=pairs,
        segment_total=int(segment_total),
        unsampled=[index for index in requested if index not in kept_set],
    )
