"""Plan summary logging must not spill scene text into the console.

The builder re-runs on every rebuild - including every Validate click - so its INFO
log is a hot path for scrollback. These tests pin the two halves of the fix: the
prompt-free form used at INFO contains no scene text, and the default form still
carries the detail (so the run report and DEBUG logging are unchanged).
"""

from __future__ import annotations

from types import SimpleNamespace

from mmx_pkg.director.plan import plan_summary

SECRET = "a very specific private scene prompt about the client"

# Real label so get_task_prompt_spec resolves; only text AFTER the separator is safe.
_TASK_TYPE = "r2v — Reference images to video"


def _seg(index: int, *, prompt: str = SECRET) -> SimpleNamespace:
    return SimpleNamespace(
        index=index,
        start_frame=index * 124,
        end_frame=(index + 1) * 124,
        frame_count=124,
        task_key="r2v",
        prompt=prompt,
    )


def _plan(*, segments=None, continuity: bool = False):
    segments = segments if segments is not None else [_seg(0), _seg(1)]
    return SimpleNamespace(
        raw={"timelineMode": "video"},
        edit_mode="segment",
        segment_count=len(segments),
        total_frames=sum(s.frame_count for s in segments),
        frame_rate=24.0,
        width=960,
        height=544,
        output_mode="fixed",
        global_task_type=_TASK_TYPE,
        global_task_key="r2v",
        segments=segments,
        export_max_frames=0,
        source_total_frames=0,
        export_mode="all",
        continuity_enabled=continuity,
        continuity_overlap_frames=9,
        run_indices=None,
    )


def test_prompt_free_summary_omits_scene_text():
    summary = plan_summary(_plan(), include_prompts=False)
    assert SECRET not in summary
    assert "very specific private" not in summary
    # It still has to be a useful summary.
    assert "segment(s)" in summary
    assert "Export mode" in summary
    assert "Global task" in summary
    assert "#1" in summary and "#2" in summary
    assert "r2v" in summary


def test_default_summary_still_carries_prompts():
    # The run report and DEBUG logging rely on this staying unchanged.
    summary = plan_summary(_plan())
    assert SECRET in summary


def test_prompt_free_summary_keeps_segment_geometry():
    summary = plan_summary(_plan(), include_prompts=False)
    assert "[0:124]" in summary
    assert "[124:248]" in summary
    assert "124f" in summary


def test_prompt_free_summary_is_shorter_than_the_full_one():
    plan = _plan()
    assert len(plan_summary(plan, include_prompts=False)) < len(plan_summary(plan))


def test_prompt_free_summary_works_for_the_batch_builder():
    # The prompt-batch / gen branch has its own per-segment loop.
    batch = _plan()
    batch.raw = {"timelineMode": "prompt_batch"}
    full = plan_summary(batch)
    lean = plan_summary(batch, include_prompts=False)
    assert SECRET in full
    assert SECRET not in lean
    assert "#1" in lean and "#2" in lean
    # The batch branch is the one that carries the output dimensions line.
    assert "960×544" in lean


def test_prompt_free_summary_keeps_run_selection_and_export_notes():
    plan = _plan()
    plan.run_indices = frozenset({0})
    lean = plan_summary(plan, include_prompts=False)
    assert "Run selection: 1/2" in lean
    assert "Export mode" in lean
    assert SECRET not in lean


def test_prompt_free_summary_keeps_continuity_note():
    lean = plan_summary(_plan(continuity=True), include_prompts=False)
    assert "Segment continuity: ON" in lean
    assert SECRET not in lean


def test_summary_survives_a_segment_without_a_prompt():
    plan = _plan(segments=[_seg(0, prompt="")])
    assert plan_summary(plan, include_prompts=False)
    assert plan_summary(plan)
