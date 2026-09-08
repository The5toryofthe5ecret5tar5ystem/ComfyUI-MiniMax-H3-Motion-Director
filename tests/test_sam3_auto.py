"""In-run SAM3 auto-mask helpers (director.sam3_auto, CPU-tested parts).

The GPU session path (predictor build + propagate) is intentionally not unit
tested - it needs the SAM3 model + CUDA. Only the pure helpers and the
import-guard behaviour are covered here.
"""

from __future__ import annotations

import numpy as np
import torch

import mmx_pkg.director.sam3_auto as sam3_auto
from mmx_pkg.director.sam3_auto import (
    SAM3_DEFAULT_PROMPT,
    SAM3_OBJ_ID_DEFAULT,
    _apply_detection_profile,
    _merge_mask_outputs,
    _restore_detection_profile,
    candidate_prompt_frames,
    frames_to_pils,
    mask_attempt_plan,
    resolve_sam3_checkpoint,
    run_window_auto_mask,
    segment_window_frames,
)


def test_mask_attempt_plan_covers_anchors_then_relaxed():
    # total 238, 12-frame lead -> anchors [0,12,125,237] + relaxed on [12,125].
    plan = mask_attempt_plan(238, lead=12)
    assert plan == [
        (0, False),
        (12, False),
        (125, False),
        (237, False),
        (12, True),
        (125, True),
    ]
    # No lead: anchors [0, mid, last] + relaxed on the two real anchors.
    plan0 = mask_attempt_plan(238, lead=0)
    assert plan0[0] == (0, False)
    assert sum(1 for _, relaxed in plan0 if relaxed) == 2


def test_run_window_auto_mask_stops_on_first_nonempty(monkeypatch):
    calls: list[tuple[int, bool]] = []
    released = []

    def fake_segment(frames, *, prompts=None, obj_id=None, prompt_frame=0, relaxed=False, checkpoint=None, boxes=None):
        calls.append((int(prompt_frame), bool(relaxed)))
        if int(prompt_frame) == 12 and not relaxed:
            mask = torch.zeros(int(frames.shape[0]), 16, 16)
            mask[:, 4:12, 4:12] = 1.0
            return mask
        return torch.zeros(int(frames.shape[0]), 16, 16)

    monkeypatch.setattr(sam3_auto, "segment_window_frames", fake_segment)
    monkeypatch.setattr(sam3_auto, "release_sam3", lambda *a, **k: released.append(True))

    frames = torch.rand(238, 16, 16, 3)
    result = run_window_auto_mask(frames, prompts=["the woman"], obj_id=1, lead_frames=12)
    assert result["mask"] is not None
    assert result["attempts"] == ["pf=0:0", "pf=12:238"]
    assert calls == [(0, False), (12, False)]
    assert released  # predictor always released


def test_run_window_auto_mask_full_miss_reports_all_attempts(monkeypatch):
    def fake_segment(frames, *, prompts=None, obj_id=None, prompt_frame=0, relaxed=False, checkpoint=None, boxes=None):
        return torch.zeros(int(frames.shape[0]), 16, 16)

    monkeypatch.setattr(sam3_auto, "segment_window_frames", fake_segment)
    monkeypatch.setattr(sam3_auto, "release_sam3", lambda *a, **k: None)

    frames = torch.rand(238, 16, 16, 3)
    result = run_window_auto_mask(frames, prompts=["the woman"], obj_id=1, lead_frames=12)
    assert result["mask"] is None
    assert result["coverage"] is None
    assert len(result["attempts"]) == 6  # 4 anchors normal + 2 relaxed
    assert all(item.endswith(":0") for item in result["attempts"])
    assert "pf=125/relaxed:0" in result["attempts"]


def test_run_window_auto_mask_box_seeded_first_and_wins(monkeypatch):
    calls: list[tuple] = []
    released = []

    def fake_segment(frames, *, prompts=None, obj_id=None, prompt_frame=0, relaxed=False, boxes=None, checkpoint=None):
        calls.append((int(prompt_frame), bool(relaxed), boxes))
        if boxes is not None:
            mask = torch.zeros(int(frames.shape[0]), 16, 16)
            mask[:, 3:13, 3:13] = 1.0
            return mask
        return torch.zeros(int(frames.shape[0]), 16, 16)

    monkeypatch.setattr(sam3_auto, "segment_window_frames", fake_segment)
    monkeypatch.setattr(sam3_auto, "release_sam3", lambda *a, **k: released.append(True))

    box = [0.2, 0.3, 0.4, 0.5]
    frames = torch.rand(238, 16, 16, 3)
    result = run_window_auto_mask(
        frames, prompts=["the woman"], obj_id=1, lead_frames=12, boxes=box, boxes_frame=12
    )
    assert result["mask"] is not None
    assert result["used_box"] is True
    assert calls[0][0] == 12 and calls[0][2] == box
    assert len(calls) == 1  # box attempt won immediately
    assert result["attempts"][0].startswith("box=12:")
    assert released


def test_run_window_auto_mask_box_miss_falls_back_to_text(monkeypatch):
    calls: list[tuple] = []

    def fake_segment(frames, *, prompts=None, obj_id=None, prompt_frame=0, relaxed=False, boxes=None, checkpoint=None):
        calls.append((int(prompt_frame), bool(relaxed), boxes is not None))
        return torch.zeros(int(frames.shape[0]), 16, 16)

    monkeypatch.setattr(sam3_auto, "segment_window_frames", fake_segment)
    monkeypatch.setattr(sam3_auto, "release_sam3", lambda *a, **k: None)

    frames = torch.rand(238, 16, 16, 3)
    result = run_window_auto_mask(
        frames, prompts=["the woman"], obj_id=1, lead_frames=12,
        boxes=[0.2, 0.3, 0.4, 0.5], boxes_frame=12,
    )
    assert result["mask"] is None
    assert result["attempts"][0].startswith("box=12:")
    assert len(result["attempts"]) == 1 + 6  # box attempt + full text plan
    assert calls[0][2] is True  # first call carried a box
    assert all(c[2] is False for c in calls[1:])  # text attempts have no box


def test_sanitize_box_rejects_bad_shapes():
    assert sam3_auto._sanitize_box([0.1, 0.2, 0.3, 0.4]) == [0.1, 0.2, 0.3, 0.4]
    assert sam3_auto._sanitize_box([1.5, 0.2, 0.3, 0.4]) is None
    assert sam3_auto._sanitize_box([0.1, 0.2, 0.0, 0.4]) is None
    assert sam3_auto._sanitize_box([0.1, 0.2, 0.3]) is None
    assert sam3_auto._sanitize_box(None) is None
    clipped = sam3_auto._sanitize_box([0.9, 0.9, 0.5, 0.5])
    assert clipped is not None and clipped[2] <= 0.1 and clipped[3] <= 0.1


def test_candidate_prompt_frames_starts_at_zero_and_includes_real_window():
    # 12-frame pre-roll head over a 250-frame mask window -> 238 real frames.
    frames = candidate_prompt_frames(250, lead=12)
    assert frames[0] == 0
    assert 12 in frames  # true window start
    assert 0 < frames[2] < 249  # a mid-window anchor
    assert frames[-1] == 249
    assert frames == sorted(set(frames))


def test_candidate_prompt_frames_without_lead_and_clamped():
    frames = candidate_prompt_frames(238, lead=0)
    assert frames[0] == 0
    assert 0 in frames
    assert frames[-1] == 237
    # Mid anchor sits inside the window.
    assert 0 < frames[1] < 237
    assert candidate_prompt_frames(0, lead=0) == []
    assert candidate_prompt_frames(10, lead=99)[0] == 0
    assert all(0 <= f < 10 for f in candidate_prompt_frames(10, lead=99))


def test_detection_profile_applies_and_restores():
    class _FakeModel:
        score_threshold_detection = 0.5
        new_det_thresh = 0.7
        assoc_iou_thresh = 0.1
        det_nms_thresh = 0.1

    class _FakePredictor:
        model = _FakeModel()

    pred = _FakePredictor()
    prev = _apply_detection_profile(pred, relaxed=True)
    # Relaxed profile is actually more permissive.
    assert prev["score_threshold_detection"] == 0.5
    assert prev["new_det_thresh"] == 0.7
    assert pred.model.score_threshold_detection < 0.5
    assert pred.model.new_det_thresh < 0.7
    _restore_detection_profile(pred, prev)
    assert pred.model.score_threshold_detection == 0.5
    assert pred.model.new_det_thresh == 0.7


def test_detection_profile_normal_is_noop_values():
    class _FakeModel:
        score_threshold_detection = 0.9
        new_det_thresh = 0.9

    class _FakePredictor:
        model = _FakeModel()

    pred = _FakePredictor()
    prev = _apply_detection_profile(pred, relaxed=False)
    assert pred.model.score_threshold_detection == 0.5
    assert pred.model.new_det_thresh == 0.7
    _restore_detection_profile(pred, prev)
    assert pred.model.score_threshold_detection == 0.9


def test_frames_to_pils_converts_float_rgb():
    torch.manual_seed(0)
    frames = torch.rand(3, 6, 7, 3)
    pils = frames_to_pils(frames)
    assert len(pils) == 3
    assert pils[0].size == (7, 6)
    assert pils[0].mode == "RGB"
    # 0..1 float maps onto 0..255 bytes (spot check).
    px = pils[0].getpixel((0, 0))
    assert all(0 <= v <= 255 for v in px)


def test_frames_to_pils_empty():
    assert frames_to_pils(torch.zeros(0, 6, 7, 3)) == []


def test_merge_mask_outputs():
    obj_masks = np.zeros((2, 4, 5), dtype=bool)
    obj_masks[0, 0, 0] = True
    obj_masks[1, 2, 3] = True
    merged = _merge_mask_outputs({"out_binary_masks": obj_masks})
    assert merged is not None
    assert merged[0, 0] and merged[2, 3]
    assert not merged[1, 1]
    assert _merge_mask_outputs({"out_binary_masks": None}) is None
    assert _merge_mask_outputs({}) is None
    assert _merge_mask_outputs(None) is None


def test_segment_window_frames_graceful_without_sam3(monkeypatch):
    # Force the import guard off so the test never tries to build the GPU
    # predictor; the function must return None (never raise).
    monkeypatch.setattr(sam3_auto, "_ensure_sam3_importable", lambda: False)
    frames = torch.rand(4, 16, 16, 3)
    assert segment_window_frames(frames, prompts=["the woman"]) is None


def test_resolve_checkpoint_never_raises():
    # Without ComfyUI this returns None; with it, a path string. Never raises.
    result = resolve_sam3_checkpoint()
    assert result is None or isinstance(result, str)


def test_defaults_contract():
    # Default prompt should request the full figure + hair coverage.
    assert "full body" in SAM3_DEFAULT_PROMPT
    assert "every strand" in SAM3_DEFAULT_PROMPT
    assert SAM3_OBJ_ID_DEFAULT == 1
