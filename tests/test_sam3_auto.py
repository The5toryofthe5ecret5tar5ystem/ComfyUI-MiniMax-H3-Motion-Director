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
    resolve_sam3_checkpoint,
    segment_window_frames,
)


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
