"""Re-ground context-source selection for Director segments.

A segment marked ``reground`` sources its carried Motion Context from the chain
ROOT (Segment 1, timeline index 0) instead of the immediately-previous segment,
so accumulated visual/audio drift is reset to the canonical baseline.  The rule
only applies to non-root segments whose boundary already has visual Motion
Context enabled (a segment cannot re-ground a boundary that carries nothing).
"""

from __future__ import annotations

from director.context_links import resolve_reground_context_source


def test_root_segment_never_regrounds() -> None:
    # Timeline slot 0 is the chain root — there is nothing "before" it to
    # re-ground against, so it always keeps the previous-index source (-1).
    idx, active = resolve_reground_context_source(
        timeline_slot=0,
        reground=True,
        context_pipeline_active=True,
        apply_visual_context=True,
    )
    assert active is False
    assert idx == -1


def test_reground_sources_from_chain_root() -> None:
    idx, active = resolve_reground_context_source(
        timeline_slot=3,  # Segment 4
        reground=True,
        context_pipeline_active=True,
        apply_visual_context=True,
    )
    assert active is True
    assert idx == 0


def test_unmarked_segment_uses_previous() -> None:
    idx, active = resolve_reground_context_source(
        timeline_slot=3,
        reground=False,
        context_pipeline_active=True,
        apply_visual_context=True,
    )
    assert active is False
    assert idx == 2


def test_reground_requires_visual_context() -> None:
    # Boundary has no visual carry (Context Link visual OFF) -> re-ground is a
    # no-op; the segment still sources from the immediately-previous segment.
    idx, active = resolve_reground_context_source(
        timeline_slot=3,
        reground=True,
        context_pipeline_active=True,
        apply_visual_context=False,
    )
    assert active is False
    assert idx == 2


def test_reground_requires_motion_pipeline() -> None:
    idx, active = resolve_reground_context_source(
        timeline_slot=3,
        reground=True,
        context_pipeline_active=False,
        apply_visual_context=True,
    )
    assert active is False
    assert idx == 2


def test_segment_two_reground_is_already_root() -> None:
    # Segment 2 (slot 1) already sources from the root by default, so marking it
    # re-ground is harmless and still resolves to the root.
    idx, active = resolve_reground_context_source(
        timeline_slot=1,
        reground=True,
        context_pipeline_active=True,
        apply_visual_context=True,
    )
    assert active is True
    assert idx == 0
