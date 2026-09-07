"""Character Replace masked engine helpers (director.replace_engine, CPU)."""

from __future__ import annotations

import numpy as np
import pytest
import torch
from PIL import Image

from mmx_pkg.director.replace_spec import ReplaceSpec
from mmx_pkg.director.replace_engine import (
    gaussian_blur_frames,
    load_mask_window,
    replace_windows_in_user_order,
    resolve_segment_audio_policy,
    sanitize_source_frames,
    snap_window_length,
    to_latent_mask,
)


def test_snap_window_length_is_h3_valid():
    for raw in (240, 241, 360, 362, 123):
        snapped = snap_window_length(raw)
        assert snapped % 17 == 5
        assert snapped >= 1


def test_replace_windows_preserve_user_order():
    timeline = {
        "segments": [
            {"start": 400, "length": 100, "id": "b"},
            {"start": 0, "length": 20, "id": "a"},
            {"start": 700, "end": 900, "id": "c"},
            {"prompt": "no window"},
        ]
    }
    windows = replace_windows_in_user_order(timeline)
    assert [w["raw"]["id"] for w in windows] == ["b", "a", "c"]
    assert windows[0]["start"] == 400
    assert windows[1]["start"] == 0
    # 100 -> snapped to H3-valid; c uses explicit end (200 long).
    assert windows[0]["length"] % 17 == 5
    assert windows[2]["start"] == 700
    assert windows[2]["length"] == snap_window_length(200)


def test_resolve_audio_policy_override():
    assert resolve_segment_audio_policy("source", None) == "source"
    spec = ReplaceSpec(enabled=True, audio_policy="generate")
    assert resolve_segment_audio_policy("source", spec) == "generate"
    assert resolve_segment_audio_policy("source", ReplaceSpec(audio_policy="none")) == "none"
    assert resolve_segment_audio_policy("bogus", None) == "source"
    assert resolve_segment_audio_policy("generate", ReplaceSpec(audio_policy="bogus")) == "generate"


def _write_mask_frames(root, mapping: dict[int, int]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for frame_index, value in mapping.items():
        img = np.full((8, 8), 0, dtype=np.uint8)
        if value:
            img[4:, :] = 255
        Image.fromarray(img, mode="L").save(root / f"frame_{frame_index:08d}.png")


def test_load_mask_window_slices(tmp_path):
    _write_mask_frames(tmp_path, {0: 0, 1: 0, 2: 1, 3: 1, 4: 1})
    mask = {"kind": "frames", "dir": str(tmp_path), "offset": 0, "grow": 0, "feather": 0}
    out = load_mask_window(mask, start_frame=2, length=3)
    assert out is not None
    assert tuple(out.shape) == (3, 8, 8)
    assert out[0, 0, 0].item() == 0.0
    assert out[0, 7, 0].item() == 1.0
    assert out[:, 0, 0].max().item() == 0.0  # background rows kept 0


def test_load_mask_window_offset(tmp_path):
    # Rebased set: file frame_0 == source frame 10.
    _write_mask_frames(tmp_path, {0: 1})
    mask = {"kind": "frames", "dir": str(tmp_path), "offset": 10}
    out = load_mask_window(mask, start_frame=10, length=1)
    assert out is not None and out[0, 7, 0].item() == 1.0
    assert load_mask_window(mask, start_frame=11, length=1) is None


def test_load_mask_window_missing_and_invalid():
    assert load_mask_window(None, 0, 2) is None
    assert load_mask_window({"kind": "none", "dir": "/nope"}, 0, 2) is None
    assert load_mask_window({"kind": "frames", "dir": "/does/not/exist"}, 0, 2) is None


def test_to_latent_mask_shape_and_convention():
    hi = torch.zeros(2, 8, 8)
    hi[:, 4:, :] = 1.0  # regenerate lower half
    low = to_latent_mask(hi, latent_h=4, latent_w=4, grow=0, feather=0)
    assert tuple(low.shape) == (2, 4, 4)
    assert bool((low == 0.0).any()) and bool((low == 1.0).any())
    # lower half of the latent grid stays regenerate=1.
    assert low[:, 2:, :].min().item() == 1.0
    assert low[:, :2, :].max().item() == 0.0


def test_to_latent_mask_grow_and_feather():
    hi = torch.zeros(1, 16, 16)
    hi[0, 7:9, 7:9] = 1.0
    plain = to_latent_mask(hi, latent_h=8, latent_w=8, grow=0, feather=0)
    grown = to_latent_mask(hi, latent_h=8, latent_w=8, grow=1, feather=0)
    assert grown.sum().item() > plain.sum().item()
    assert bool(((grown == 0.0) | (grown == 1.0)).all())  # grow keeps binary
    soft = to_latent_mask(hi, latent_h=8, latent_w=8, grow=0, feather=1.0)
    assert bool(((soft > 0.0) & (soft < 1.0)).any())  # feather softens edges


def test_sanitize_invert_destroys_subject_keeps_background():
    torch.manual_seed(0)
    frames = torch.rand(2, 8, 8, 3)
    mask = torch.zeros(2, 8, 8)
    mask[:, :4, :] = 1.0  # top half is subject
    out = sanitize_source_frames(frames, mask, method="invert")
    assert torch.allclose(out[:, 4:, :, :], frames[:, 4:, :, :], atol=1e-5)
    assert torch.allclose(out[:, :4, :, :], 1.0 - frames[:, :4, :, :], atol=1e-5)


def test_gaussian_blur_changes_values():
    x = torch.zeros(1, 1, 8, 8)
    x[0, 0, 4, 4] = 1.0
    blurred = gaussian_blur_frames(x, sigma=1.0)
    assert blurred[0, 0, 4, 4].item() < 1.0
    assert blurred[0, 0, 4, 5].item() > 0.0
