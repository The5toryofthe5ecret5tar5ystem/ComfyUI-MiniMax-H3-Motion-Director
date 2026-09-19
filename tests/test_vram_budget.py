# Tests for lib.vram_budget - the pre-flight fit check.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""The token model and the verdicts, pinned to measured values.

Every number asserted here comes from a real run: the token shapes from the
345-frame 1376x768 segments that failed, the attention workspace from the
allocation in the traceback (2.99 GiB with 63 MiB free). If a refactor changes
the arithmetic, these fail instead of the estimate silently drifting.
"""

import pathlib

import pytest

from lib import vram_budget as vb


def test_latent_frames_matches_measured_shapes():
    # 175 / 243 / 311 / 345 frames -> 44 / 61 / 78 / 87 latent frames.
    assert vb.latent_frames(175) == 44
    assert vb.latent_frames(243) == 61
    assert vb.latent_frames(311) == 78
    assert vb.latent_frames(345) == 87
    assert vb.latent_frames(0) == 0
    # The estimate must not disagree with the runtime about a segment's shape.
    # Importing director.segment_continuity pulls in the ComfyUI stack, so the
    # shared formula is pinned in source instead.
    source = pathlib.Path("director/segment_continuity.py").read_text(encoding="utf-8")
    assert "return max(1, (max(1, int(pixel_frames)) - 1) // 4 + 1)" in source
    assert vb.LATENT_FRAME_DIVISOR == 4 and vb.LATENT_FRAME_OFFSET == 1


def test_video_tokens_at_1376x768():
    # 43 x 24 = 1032 tokens per latent frame at this canvas.
    assert vb.video_tokens(175, 1376, 768) == 44 * 1032
    assert vb.video_tokens(345, 1376, 768) == 87 * 1032
    # The ratio is what makes a long segment expensive, not the frame count.
    assert round(vb.video_tokens(345, 1376, 768) / vb.video_tokens(175, 1376, 768), 2) == 1.98


def test_picture_tokens_scale_with_the_long_edge():
    assert vb.picture_tokens(1, 1376) == 43 * 24
    assert vb.picture_tokens(2, 1376) == 2 * 43 * 24
    assert vb.picture_tokens(2, 1024) == 2 * 32 * 18
    assert vb.picture_tokens(0, 1376) == 0


def test_attention_workspace_reproduces_the_failed_allocation():
    """345 frames at 1376x768 with 2 refs asked for 2.99 GiB in one block.

    The sequence is the video rows *and* the reference rows, which is why the
    shape - not just the frame count - is what has to be compared.
    """
    shape = vb.SegmentShape(index=0, frames=345, width=1376, height=768,
                            pictures=2, ref_long_edge=1376)
    assert vb.attention_workspace_gb(shape.tokens) == pytest.approx(2.99, abs=0.05)


def test_segment_shape_tokens_include_context_and_pictures():
    shape = vb.SegmentShape(
        index=3, frames=311, width=1376, height=768,
        pictures=2, ref_long_edge=1376, context_frames=34,
    )
    assert shape.sampled_frames == 345
    assert shape.tokens == vb.video_tokens(345, 1376, 768) + vb.picture_tokens(2, 1376)
    assert "2 ref(s) at 1376 px" in shape.describe()
    assert "345 sampled frames" in shape.describe()


BASELINES = {
    "segment_frames": 175,
    "max_segment_frames": 243,
    "width": 1344,
    "height": 768,
    "ref_max_size": 1024,
}


def _shape(frames=175, width=1344, height=768, pictures=2, edge=1024, context=0, index=0):
    return vb.SegmentShape(index=index, frames=frames, width=width, height=height,
                           pictures=pictures, ref_long_edge=edge, context_frames=context)


def test_a_baseline_shaped_segment_is_ok():
    report = vb.evaluate([_shape()], baselines=BASELINES, total_gb=31.43, free_gb=25.0)
    assert report.verdict == "ok"
    assert report.worst_ratio == pytest.approx(1.0, abs=0.01)
    assert report.suggestions == []


def test_a_tight_shape_warns_without_claiming_failure():
    # 243 frames is inside the tier's cap but 1.3x+ the tuned shape.
    report = vb.evaluate([_shape(frames=243)], baselines=BASELINES, total_gb=31.43, free_gb=25.0)
    assert report.verdict == "tight"
    assert "1.3" in report.reason or "x the shape" in report.reason


def test_the_measured_failure_is_reported_as_over():
    """The real segment: 345 sampled frames, 2 refs at 1376 px."""
    shape = _shape(frames=311, context=34, width=1376, height=768, edge=1376)
    report = vb.evaluate([shape], baselines=BASELINES, total_gb=31.43, free_gb=25.0)
    assert report.verdict == "over"
    assert report.worst_ratio > vb.RATIO_OVER
    assert "175 frames" in report.reason  # names the tier's tuned length
    assert any("reference size to 1024 px" in s for s in report.suggestions)


def test_placement_failure_beats_the_ratio_when_free_vram_is_known():
    """The actual traceback: 2.99 GiB wanted while 0.06 GiB was free."""
    shape = _shape(frames=311, context=34, width=1376, height=768, edge=1376)
    report = vb.evaluate([shape], baselines=BASELINES, total_gb=31.43, free_gb=0.06)
    assert report.verdict == "over"
    assert "in one piece" in report.reason
    assert "only 0.1 GB is free" in report.reason
    assert report.budget_gb == pytest.approx(0.06, abs=0.01)


def test_free_vram_of_a_busy_card_flags_a_shape_that_would_otherwise_pass():
    """A baseline segment on a card that something else is holding."""
    report = vb.evaluate([_shape()], baselines=BASELINES, total_gb=31.43, free_gb=1.0)
    assert report.verdict == "over"
    assert report.worst_ratio == pytest.approx(1.0, abs=0.01)


def test_evaluate_picks_the_worst_segment_not_the_last():
    shapes = [_shape(frames=175, index=0), _shape(frames=345, index=1), _shape(frames=175, index=2)]
    report = vb.evaluate(shapes, baselines=BASELINES)
    assert report.worst.index == 1
    assert report.segments[1]["frames"] == 345
    assert len(report.segments) == 3


def test_evaluate_ignores_empty_segments_and_reports_unknown_without_any():
    assert vb.evaluate([], baselines=BASELINES).verdict == "unknown"
    assert vb.evaluate([_shape(frames=0)], baselines=BASELINES).verdict == "unknown"


def test_report_serialises_for_the_validate_route():
    report = vb.evaluate([_shape(frames=311, context=34, width=1376, height=768, edge=1376)],
                         baselines=BASELINES, total_gb=31.43, free_gb=0.06)
    payload = report.as_dict()
    assert payload["verdict"] == "over"
    assert payload["segment"]["sampled_frames"] == 345
    assert payload["segment"]["tokens"] == 89900 or payload["segment"]["tokens"] > 89000
    assert payload["attention_gb"] == pytest.approx(2.99, abs=0.06)
    assert payload["notes"] and payload["suggestions"]


def test_reference_size_is_offered_before_shortening_the_segment():
    shape = _shape(frames=311, context=34, width=1376, height=768, edge=1376)
    suggestions = vb.suggest_fit(shape, BASELINES)
    assert suggestions[0].startswith("Set reference size to 1024 px")


def test_segment_length_is_offered_when_the_reference_alone_is_not_enough():
    shape = _shape(frames=345, width=1344, height=768, edge=1024)
    suggestions = vb.suggest_fit(shape, BASELINES)
    assert any("at most 243 frames" in s for s in suggestions)
    assert any("default is 175 frames" in s for s in suggestions)


def test_canvas_is_suggested_only_when_it_is_larger_than_the_tier():
    assert not any("Drop the canvas" in s for s in vb.suggest_fit(_shape(frames=345), BASELINES))
    bigger = _shape(frames=345, width=1600, height=896)
    assert any("Drop the canvas to 1344x768" in s for s in vb.suggest_fit(bigger, BASELINES))


def test_no_suggestions_for_a_shape_that_fits():
    assert vb.suggest_fit(_shape(), BASELINES) == []


def test_oom_message_carries_the_shape_and_the_numbers():
    shape = _shape(frames=311, context=34, width=1376, height=768, edge=1376)
    message = vb.oom_message("H3 sampling", shape=shape, free_gb=0.06,
                             suggestions=["Set reference size to 1024 px."])
    assert message.startswith("Motion Director ran out of VRAM during H3 sampling.")
    assert "345 sampled frames" in message
    assert "2.9 GB of attention workspace" in message or "3.0 GB of attention workspace" in message
    assert "0.1 GB" in message
    assert "Set reference size to 1024 px." in message


def test_oom_message_still_advises_when_no_shape_is_known():
    message = vb.oom_message("Global Refine/upscale")
    assert "Global Refine/upscale" in message
    assert "Reduce the segment length" in message
    assert "clear_vram_between_segments" in message


def test_oom_message_keeps_the_callers_own_tail():
    message = vb.oom_message("H3 sampling", tail="No context/reference was silently removed.")
    assert message.endswith("No context/reference was silently removed.")


def test_calibration_blends_towards_an_observation():
    # The observed run packed 89,784 video tokens plus 2,064 reference rows.
    sequence = vb.video_tokens(345, 1376, 768) + vb.picture_tokens(2, 1376)
    blended = vb.calibrate_attention_kb_per_token(tokens=sequence, workspace_gb=2.99, weight=1.0)
    assert blended == pytest.approx(vb.ATTENTION_KB_PER_TOKEN, abs=0.05)
    half = vb.calibrate_attention_kb_per_token(tokens=sequence, workspace_gb=6.0, weight=0.5)
    assert vb.ATTENTION_KB_PER_TOKEN < half < 68.0
    # Nonsense input must not move the constant.
    assert vb.calibrate_attention_kb_per_token(tokens=0, workspace_gb=3.0) == vb.ATTENTION_KB_PER_TOKEN
