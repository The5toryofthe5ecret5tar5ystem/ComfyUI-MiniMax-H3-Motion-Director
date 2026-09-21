# MiniMax H3 Motion Director - anchor progress labels.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Anchor chunks must not report themselves as timeline segments.

``build_anchor_segment`` gives every anchor chunk a synthetic index of
``1000 + boundary`` so it can never collide with a segment. That index leaked
straight into the progress log, so a Pre-roll grinding through ten poses printed
lines like ``S1014/20: first-pass sampling`` - which reads exactly like a
thousand-segment fill run and sent the user looking for a job that was not
running. ``_progress_tag`` names the work for what it is.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

EXECUTOR = Path("director/executor_core_legacy.py")


def test_progress_tag_names_anchor_work():
    from mmx_pkg.director.executor_core_legacy import _progress_tag

    anchor = SimpleNamespace(index=1014, ui_index=1014, anchor_index=14)
    fill = SimpleNamespace(index=2, ui_index=2, anchor_index=None)

    assert _progress_tag(anchor, "S15/20") == "anchor for boundary 15"
    # a real segment keeps the label its caller built (unchanged behaviour)
    assert _progress_tag(fill, "S3/20") == "S3/20"
    # a segment-like object without the attribute never trips the anchor branch
    assert _progress_tag(SimpleNamespace(index=0), "S1/20") == "S1/20"


def test_every_progress_line_goes_through_the_tag_helper():
    source = EXECUTOR.read_text(encoding="utf-8")

    assert "def _progress_tag(seg, label: str) -> str:" in source
    # reference set, first-pass sampling and the done line
    assert source.count("_progress_tag(seg, f\"S{int(timeline_slot) + 1}/{int(seg_total)}\")") == 2
    assert '_progress_tag(seg, f"segment {int(ui_idx) + 1}/{int(timeline_seg_total)}")' in source
    # and no line went back to the raw index
    assert "S%d/%d: first-pass sampling" not in source
    assert "S%d/%d: %d picture(s)" not in source
