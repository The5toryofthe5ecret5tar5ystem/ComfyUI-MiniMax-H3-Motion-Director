"""A replace job may carry generated rows that render without source footage.

A Character Replace job is a list of rows. Historically every row was a masked
*replace window* over the source video, so the plan builder assumed every row had
a source range, every row was snapped as a window and no row was allowed past the
end of the footage. A **generated row** (``kind: "generate"``) breaks all three
assumptions: it has no source range, its length is the number of frames it
renders, and it exists precisely so a chain can leave the footage - on the end or
in the middle.

These tests pin the row-kind contract: what the kind parses to, what the plan
builder emits for it, and that rows without a kind behave exactly as before.
"""

import json

import pytest

try:
    from mmx_pkg.director.context_identity import segment_identity
    from mmx_pkg.director.plan import build_director_plan, plan_summary
    from mmx_pkg.lib.segment_kind import (
        GENERATED_SEGMENT_TASK,
        SEGMENT_KIND_GENERATE,
        SEGMENT_KIND_REPLACE,
        generated_row_length,
        is_generated_segment,
        segment_kind,
    )
except ImportError as exc:  # pragma: no cover - environment guard
    pytest.skip(f"Director package unavailable: {exc}", allow_module_level=True)


_KW = dict(
    global_task_type="v2v",
    global_prompt="global prompt",
    total_frames=1137,
    frame_rate=24.0,
    width=512,
    height=512,
    ref_max_size=1024,
)


def _replace_timeline(segments, **extra):
    """A minimal Character Replace timeline: source video + one row per window."""
    timeline = {
        "editMode": "segment",
        "replaceMode": True,
        "video": {"videoFile": "source.mp4", "sourceFrameCount": 1137, "frameMap": []},
        "totalFrames": 1137,
        "global": {"taskType": "v2v", "prompt": "global prompt"},
        "output": {},
        "segments": segments,
    }
    timeline.update(extra)
    return timeline


def _window(start, length, prompt="window"):
    return {"start": start, "length": length, "prompt": prompt, "replace": {"enabled": True}}


def _generated(start, length, **extra):
    row = {
        "kind": "generate",
        "start": start,
        "length": length,
        "prompt": "she rolls onto her back and settles",
        "taskType": "r2v",
    }
    row.update(extra)
    return row


def _build(segments, **extra):
    return build_director_plan(json.dumps(_replace_timeline(segments, **extra)), **_KW)


# --------------------------------------------------------------------------
# the kind parser
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "row",
    [
        {"kind": "generate"},
        {"kind": "GENERATE"},
        {"segmentKind": "generated"},
        {"kind": "ref2va"},
        {"generate": True},
        {"isGenerated": True},
    ],
)
def test_a_generated_row_is_recognised_under_its_aliases(row):
    assert segment_kind(row) == SEGMENT_KIND_GENERATE
    assert is_generated_segment(row) is True


@pytest.mark.parametrize(
    "row",
    [
        {},
        {"kind": "replace"},
        {"kind": "window"},
        {"kind": "banana"},
        {"start": 0, "length": 240, "replace": {"enabled": True}},
        {"generate": False},
        None,
        "generate",
    ],
)
def test_everything_else_is_a_replace_window(row):
    """Unknown values must fall back to a window: a window still renders."""
    assert segment_kind(row) == SEGMENT_KIND_REPLACE
    assert is_generated_segment(row) is False


def test_generated_row_length_reads_length_end_or_frame_count():
    assert generated_row_length({"length": 243}) == 243
    assert generated_row_length({"start": 100, "end": 343}) == 243
    assert generated_row_length({"frameCount": 120}) == 120
    assert generated_row_length({}) == 0
    assert generated_row_length({"length": "nonsense"}) == 0


# --------------------------------------------------------------------------
# the plan builder
# --------------------------------------------------------------------------


def test_a_generated_row_between_two_windows_keeps_the_row_order():
    plan = _build([_window(0, 240), _generated(240, 243), _window(240, 240)])

    assert [seg.kind for seg in plan.segments] == [
        SEGMENT_KIND_REPLACE,
        SEGMENT_KIND_GENERATE,
        SEGMENT_KIND_REPLACE,
    ]
    generated = plan.segments[1]
    assert generated.is_generated is True
    assert generated.frame_count == 243
    assert generated.prompt == "she rolls onto her back and settles"


def test_a_generated_row_renders_source_free():
    """No replace window, no source task, and its own prompt/refs."""
    plan = _build([_window(0, 240), _generated(240, 243)])
    generated = plan.segments[1]

    assert generated.task_key == GENERATED_SEGMENT_TASK
    assert generated.use_global is False
    # A generated row is not a window, so the masked path must stay off.
    assert getattr(generated.replace, "enabled", False) is False


def test_a_generated_row_snaps_its_length_like_a_window():
    """240 frames is not an H3 length (17k+5); 243 is."""
    plan = _build([_window(0, 240), _generated(240, 240)])
    assert plan.segments[1].frame_count == 243


def test_a_generated_row_past_the_source_end_survives_the_export_cap():
    """This is the "extend past the footage" case.

    The export cap trims rows whose source start is past the window; a generated
    row has no source range, so dropping it here would silently delete exactly
    the frames the feature exists to render.
    """
    plan = _build([_window(0, 240), _generated(1137, 243)], output={"maxExportFrames": 240})

    assert [seg.kind for seg in plan.segments] == [SEGMENT_KIND_REPLACE, SEGMENT_KIND_GENERATE]
    trailing = plan.segments[1]
    assert trailing.frame_count == 243
    assert trailing.is_generated is True


def test_a_generated_row_ignores_a_leftover_replace_window():
    """Switching a row to generated in the UI can leave the old mask behind."""
    plan = _build([_generated(0, 243, replace={"enabled": True, "lead": 12})])
    generated = plan.segments[0]

    assert generated.kind == SEGMENT_KIND_GENERATE
    assert getattr(generated.replace, "enabled", False) is False


def test_a_generated_row_refuses_a_task_that_needs_source_frames():
    """v2v reads source pixels; a generated row has none to give it."""
    plan = _build([_generated(0, 243, taskType="v2v")])
    assert plan.segments[0].task_key == GENERATED_SEGMENT_TASK


def test_a_generated_row_without_a_length_is_skipped():
    plan = _build([_window(0, 240), {"kind": "generate", "start": 240, "prompt": "x"}])
    assert len(plan.segments) == 1
    assert plan.segments[0].kind == SEGMENT_KIND_REPLACE


def test_a_generated_row_may_carry_its_length_as_frame_count():
    """The UI writes length and frameCount; a hand-authored row may write one."""
    plan = _build([
        _window(0, 240),
        {"kind": "generate", "start": 240, "frameCount": 240, "prompt": "continues"},
    ])
    assert [seg.kind for seg in plan.segments] == [SEGMENT_KIND_REPLACE, SEGMENT_KIND_GENERATE]
    assert plan.segments[1].frame_count == 243


def test_a_generated_row_may_be_first_or_last():
    plan = _build([_generated(0, 243), _window(0, 240)])
    assert [seg.kind for seg in plan.segments] == [SEGMENT_KIND_GENERATE, SEGMENT_KIND_REPLACE]


# --------------------------------------------------------------------------
# a hard first frame from the segment in front
# --------------------------------------------------------------------------


def test_a_generated_row_may_run_i2v_to_lock_its_first_frame():
    """i2v reads no source pixels: it locks frame 0 to the previous render.

    That is the difference between "the chain continues near where the last
    segment stopped" (r2v, conditioned on context) and a real join at frame 0.
    """
    plan = _build([_window(0, 240), _generated(240, 243, taskType="i2v")])
    assert plan.segments[1].task_key == "i2v"
    assert plan.segments[1].is_generated is True


@pytest.mark.parametrize("task", ["i2v", "r2v", "t2v"])
def test_a_generated_row_never_resolves_source_pixels(task):
    """Whatever it runs, a generated row must not pull the source window.

    i2v is the case that makes this load-bearing: allowed to reach the
    video-timeline loader it would open from the *source* performer instead of
    the previous segment's rendered frame.
    """
    from mmx_pkg.director.segment_runtime import resolve_segment_raw_clip

    plan = _build([_window(0, 240), _generated(240, 243, taskType=task)])
    clip = resolve_segment_raw_clip(plan, plan.segments[1])
    assert int(clip.shape[0]) == 0


def test_a_generated_row_keeps_its_continuity_switch():
    """The row's own switch decides whether it opens from the previous segment."""
    plan = _build([
        _window(0, 240),
        _generated(240, 243, replace={"enabled": True, "continuity": False, "mask": {"dir": "masks/x"}}),
    ])
    generated = plan.segments[1]

    assert getattr(generated.replace, "enabled", False) is False
    assert generated.replace.continuity is False
    # The recipe stays on the row: switching it back to a window in the UI must
    # not lose the mask setup it had.
    assert generated.replace.mask.dir == "masks/x"


# --------------------------------------------------------------------------
# nothing changes for jobs that never asked for this
# --------------------------------------------------------------------------


def test_a_window_only_job_plans_exactly_as_before():
    plan = _build([_window(0, 240, "one"), _window(240, 240, "two")])

    assert [seg.kind for seg in plan.segments] == [SEGMENT_KIND_REPLACE] * 2
    assert [seg.task_key for seg in plan.segments] == ["v2v", "v2v"]
    assert all(getattr(seg.replace, "enabled", False) for seg in plan.segments)
    assert all(seg.use_global is False for seg in plan.segments)


def test_the_plan_summary_names_generated_rows():
    plan = _build([_window(0, 240, "one"), _generated(240, 243)])
    text = plan_summary(plan, include_prompts=False)

    assert "— generated" in text
    # The window line must stay exactly as it always printed (window rows snap to
    # the H3 grid, which is the existing behaviour this change must not touch).
    assert "#1 [0:243] 243f — v2v" in text
    assert "#2 [240:483] 243f — r2v — generated" in text


def test_the_row_kind_is_part_of_the_context_identity():
    """Switching a row between window and generated must invalidate its cache."""
    plan = _build([_window(0, 240), _generated(240, 243)])

    assert segment_identity(plan.segments[1], plan)["kind"] == SEGMENT_KIND_GENERATE
    assert segment_identity(plan.segments[0], plan)["kind"] == SEGMENT_KIND_REPLACE
