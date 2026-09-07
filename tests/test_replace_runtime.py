"""Character Replace runtime assembly helpers (director.replace_runtime, CPU)."""

from __future__ import annotations

import pytest
import torch

from mmx_pkg.director.replace_runtime import (
    build_replace_noise_mask,
    prepare_masked_replace_state,
    sanitized_reference_frames,
)
from mmx_pkg.director.replace_spec import ReplaceMaskSpec, ReplaceSpec
from mmx_pkg.director.h3_noise_mask import split_h3_mask


def _mask(t: int = 4, h: int = 8, w: int = 8) -> torch.Tensor:
    mask = torch.zeros(t, h, w)
    mask[:, h // 2 :, :] = 1.0
    return mask


def test_sanitized_reference_invert_keeps_background():
    torch.manual_seed(1)
    frames = torch.rand(3, 8, 8, 3)
    mask = torch.zeros(3, 8, 8)
    mask[:, :4, :] = 1.0
    out = sanitized_reference_frames(frames, mask, method="invert")
    assert torch.allclose(out[:, 4:, :, :], frames[:, 4:, :, :], atol=1e-5)
    assert torch.allclose(out[:, :4, :, :], 1.0 - frames[:, :4, :, :], atol=1e-5)


def test_build_replace_noise_mask_video_shape_and_values():
    video_latent = torch.zeros(1, 4, 4, 2, 2)   # [1,C,T,h,w]
    audio_latent = torch.zeros(1, 8, 40)
    mask_hi = _mask(t=4, h=8, w=8)
    mask = build_replace_noise_mask(
        video_latent, audio_latent, mask_hi, grow=0, feather=0, audio_policy="source"
    )
    video_mask, audio_mask, is_nested = split_h3_mask(mask)
    assert is_nested
    assert tuple(video_mask.shape) == (1, 1, 4, 2, 2)
    # lower half of source = regenerate (1), top = keep (0)
    assert video_mask[0, 0, :, 1, :].min().item() >= 0.5
    assert video_mask[0, 0, :, 0, :].max().item() <= 0.5
    assert audio_mask.abs().sum().item() == 0.0  # source policy keeps audio


def test_build_replace_noise_mask_generate_audio():
    video_latent = torch.zeros(1, 4, 4, 2, 2)
    audio_latent = torch.zeros(1, 8, 40)
    mask_hi = _mask(t=4)
    mask = build_replace_noise_mask(
        video_latent, audio_latent, mask_hi, audio_policy="generate"
    )
    _video_mask, audio_mask, is_nested = split_h3_mask(mask)
    assert is_nested
    assert audio_mask.float().sum().item() > 0  # regenerate audio


def test_build_replace_noise_mask_pads_short_mask_to_video_time():
    video_latent = torch.zeros(1, 4, 6, 2, 2)   # 6 latent frames
    audio_latent = torch.zeros(1, 8, 60)
    mask_hi = _mask(t=4)
    mask = build_replace_noise_mask(video_latent, audio_latent, mask_hi, grow=0, feather=0)
    video_mask, _audio_mask, is_nested = split_h3_mask(mask)
    assert is_nested
    assert video_mask.shape[2] == 6


def test_prepare_state_validates_shapes():
    frames = torch.rand(4, 8, 8, 3)
    ref = torch.rand(4, 8, 8, 3)
    mask_hi = _mask(t=4)
    spec = ReplaceSpec(enabled=True, audio_policy="generate", mask=ReplaceMaskSpec(grow=1, feather=0.5))
    state = prepare_masked_replace_state(
        source_frames=frames, reference_frames=ref, mask_hi=mask_hi, spec=spec
    )
    assert state["audio_policy"] == "generate"
    assert tuple(state["mask_hi"].shape) == (4, 8, 8)
    assert tuple(state["sanitized_reference"].shape) == (4, 8, 8, 3)
    assert state["grow"] == 1
    assert state["feather"] == 0.5


def test_prepare_state_rejects_bad_shapes():
    frames = torch.rand(4, 8, 8, 3)
    bad_mask = torch.zeros(4, 4, 4)  # spatial mismatch
    with pytest.raises(ValueError):
        prepare_masked_replace_state(
            source_frames=frames, reference_frames=frames, mask_hi=bad_mask,
            spec=ReplaceSpec(enabled=True),
        )
    short_mask = torch.zeros(2, 8, 8)
    with pytest.raises(ValueError):
        prepare_masked_replace_state(
            source_frames=frames, reference_frames=frames, mask_hi=short_mask,
            spec=ReplaceSpec(enabled=True),
        )
