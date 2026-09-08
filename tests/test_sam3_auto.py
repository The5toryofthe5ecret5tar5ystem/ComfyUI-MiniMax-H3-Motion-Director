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
    _merge_mask_outputs,
    frames_to_pils,
    resolve_sam3_checkpoint,
    segment_window_frames,
)


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
    assert SAM3_DEFAULT_PROMPT == "the woman"
    assert SAM3_OBJ_ID_DEFAULT == 1
