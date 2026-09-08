"""Character Replace runtime assembly helpers (director.replace_runtime, CPU)."""

from __future__ import annotations

import numpy as np
import pytest
import torch
from PIL import Image

from mmx_pkg.director.replace_runtime import (
    build_replace_noise_mask,
    prepare_masked_replace_state,
    prepare_replace_window,
    sanitized_reference_frames,
)
from mmx_pkg.director.replace_engine import (
    pixel_frames_for_latent_tokens,
    pool_mask_to_latent_time,
    video_latent_tokens_for_frames,
)
from mmx_pkg.director.replace_spec import ReplaceMaskSpec, ReplaceSpec
from mmx_pkg.director.h3_noise_mask import split_h3_mask


def _mask(t: int = 4, h: int = 8, w: int = 8) -> torch.Tensor:
    mask = torch.zeros(t, h, w)
    mask[:, h // 2 :, :] = 1.0
    return mask


def _write_mask_frames(root, count: int, *, h: int = 8, w: int = 8) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for frame_index in range(count):
        img = np.full((h, w), 0, dtype=np.uint8)
        if frame_index % 2 == 0:
            img[h // 2 :, :] = 255
        Image.fromarray(img, mode="L").save(root / f"frame_{frame_index:08d}.png")


def test_prepare_replace_window_sanitizes_and_aligns(tmp_path):
    _write_mask_frames(tmp_path, 4)
    torch.manual_seed(3)
    visible = torch.rand(4, 8, 8, 3)
    reference = torch.rand(6, 8, 8, 3)  # longer: aligned/padded motion clip
    mask_spec = {"kind": "frames", "dir": str(tmp_path), "offset": 0}
    prepared = prepare_replace_window(
        mask_spec=mask_spec,
        start_frame=0,
        nominal_length=4,
        visible_frames=visible,
        reference_frames=reference,
        grow=1,
        feather=0.5,
    )
    assert prepared is not None
    assert tuple(prepared["sanitized_reference"].shape) == (6, 8, 8, 3)
    assert tuple(prepared["mask_vis"].shape) == (4, 8, 8)
    assert prepared["grow"] == 1
    assert prepared["feather"] == 0.5
    # Background rows (mask=0) survive exactly; subject rows are destroyed.
    assert torch.allclose(
        prepared["sanitized_reference"][:, :4, :, :],
        reference[:, :4, :, :],
        atol=1e-5,
    )
    # Sanitized clip never equals the original subject rows anywhere.
    assert not torch.allclose(
        prepared["sanitized_reference"][:, 4:, :, :],
        reference[:, 4:, :, :],
        atol=1e-5,
    )


def test_prepare_replace_window_aligned_offsets(tmp_path):
    # Mask set rebased at source frame 10; window starts at frame 10.
    _write_mask_frames(tmp_path, 3)
    visible = torch.rand(3, 8, 8, 3)
    reference = torch.rand(3, 8, 8, 3)
    mask_spec = {"kind": "frames", "dir": str(tmp_path), "offset": 10}
    prepared = prepare_replace_window(
        mask_spec=mask_spec,
        start_frame=10,
        nominal_length=3,
        visible_frames=visible,
        reference_frames=reference,
    )
    assert prepared is not None
    # Even frames in the written set are subject = regenerate; frame 0 of the
    # window is even -> bottom rows masked.
    assert prepared["mask_vis"][0, 7, 0].item() == 1.0
    assert prepared["mask_vis"][1, 0, 0].item() == 0.0


def test_prepare_replace_window_missing_mask_returns_none(tmp_path):
    _write_mask_frames(tmp_path, 2)  # not enough frames for nominal_length=4
    frames = torch.rand(4, 8, 8, 3)
    mask_spec = {"kind": "frames", "dir": str(tmp_path), "offset": 0}
    assert (
        prepare_replace_window(
            mask_spec=mask_spec,
            start_frame=0,
            nominal_length=4,
            visible_frames=frames,
            reference_frames=frames,
        )
        is None
    )
    assert (
        prepare_replace_window(
            mask_spec={"kind": "none", "dir": "/nope"},
            start_frame=0,
            nominal_length=4,
            visible_frames=frames,
            reference_frames=frames,
        )
        is None
    )
    assert prepare_replace_window(
        mask_spec=mask_spec, start_frame=0, nominal_length=4,
        visible_frames=None, reference_frames=frames,
    ) is None


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


def test_video_latent_token_schedule():
    # (1,4,4,4,4) schedule: 17 pixel frames per 5 tokens.
    assert video_latent_tokens_for_frames(0) == 0
    assert video_latent_tokens_for_frames(1) == 1
    assert video_latent_tokens_for_frames(2) == 2
    assert video_latent_tokens_for_frames(5) == 2
    assert video_latent_tokens_for_frames(6) == 3
    assert video_latent_tokens_for_frames(17) == 5
    assert video_latent_tokens_for_frames(124) == 37  # 17*7 + 5
    assert pixel_frames_for_latent_tokens(5) == 17
    assert pixel_frames_for_latent_tokens(37) == 124


def test_pool_mask_to_latent_time_token_boundaries():
    # 17 pixel frames -> 5 tokens; subject presence maps to covering token.
    mask = torch.zeros(17, 4, 4)
    mask[0, 2, 2] = 1.0            # token 0 (pixel 0)
    mask[4, 2, 2] = 1.0            # token 1 (pixels 1..4)
    mask[5, 2, 2] = 1.0            # token 2 (pixels 5..8)
    mask[13, 2, 2] = 1.0           # token 4 (pixels 13..16)
    pooled = pool_mask_to_latent_time(mask, 5)
    assert tuple(pooled.shape) == (5, 4, 4)
    assert pooled[0, 2, 2].item() == 1.0
    assert pooled[1, 2, 2].item() == 1.0
    assert pooled[2, 2, 2].item() == 1.0
    assert pooled[3, 2, 2].item() == 0.0  # pixels 9..12 untouched
    assert pooled[4, 2, 2].item() == 1.0


def test_build_replace_noise_mask_pools_pixel_frames_to_tokens():
    # 17 source frames -> video latent with 5 tokens.
    video_latent = torch.zeros(1, 4, 5, 2, 2)
    audio_latent = torch.zeros(1, 8, 40)
    mask_hi = torch.zeros(17, 8, 8)
    mask_hi[0:1, 4:, :] = 1.0  # only the first pixel frame has the subject
    mask = build_replace_noise_mask(video_latent, audio_latent, mask_hi, grow=0, feather=0)
    video_mask, _audio_mask, is_nested = split_h3_mask(mask)
    assert is_nested
    assert tuple(video_mask.shape) == (1, 1, 5, 2, 2)
    # Token 0 covers only pixel 0 -> regenerate; later tokens are pure background.
    assert video_mask[0, 0, 0, 1, :].min().item() >= 0.5
    assert video_mask[0, 0, 1:, :, :].max().item() <= 0.5


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


def _write_frames_mapping(root, mapping) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for frame_index, value in mapping.items():
        img = np.full((8, 8), 0, dtype=np.uint8)
        if value:
            img[4:, :] = 255
        Image.fromarray(img, mode="L").save(root / f"frame_{frame_index:08d}.png")


def test_prepare_replace_window_lead_reuses_real_head(tmp_path):
    # Asset covers frames 0..3 (even = subject); nominal window is 2..4.
    _write_mask_frames(tmp_path, 4)
    visible = torch.rand(5, 8, 8, 3)
    reference = torch.rand(5, 8, 8, 3)
    prepared = prepare_replace_window(
        mask_spec={"kind": "frames", "dir": str(tmp_path), "offset": 0},
        start_frame=2,
        nominal_length=2,
        visible_frames=visible,
        reference_frames=reference,
        lead_frames=2,
    )
    assert prepared is not None
    # Mask covers lead+nominal and is then aligned to the visible length.
    assert tuple(prepared["mask_vis"].shape) == (5, 8, 8)
    # Lead head used the real earlier asset frame (frame 0 even -> subject).
    assert prepared["mask_vis"][0, 7, 0].item() == 1.0
    assert prepared["mask_vis"][1, 0, 0].item() == 0.0  # frame 1 odd -> bg
    assert tuple(prepared["sanitized_reference"].shape) == (5, 8, 8, 3)


def test_prepare_replace_window_lead_replicates_head_when_missing(tmp_path):
    # Asset covers only the nominal window frames (2..3); no real head frames.
    _write_frames_mapping(tmp_path, {2: 0, 3: 1})
    visible = torch.rand(4, 8, 8, 3)
    reference = torch.rand(4, 8, 8, 3)
    prepared = prepare_replace_window(
        mask_spec={"kind": "frames", "dir": str(tmp_path), "offset": 0},
        start_frame=2,
        nominal_length=2,
        visible_frames=visible,
        reference_frames=reference,
        lead_frames=2,
    )
    assert prepared is not None
    mask = prepared["mask_vis"]
    assert tuple(mask.shape) == (4, 8, 8)
    # Head is body[0] replicated (frame 2 -> background), then the body follows.
    assert mask[0, 0, 0].item() == 0.0
    assert torch.equal(mask[0], mask[1])
    assert mask[2, 0, 0].item() == 0.0   # body[0] == frame 2
    assert mask[3, 7, 0].item() == 1.0   # body[1] == frame 3 (subject)


def test_prepare_replace_window_uses_mask_hi_override():
    # In-run SAM3 auto-mask: mask_hi replaces file loading entirely, so a
    # missing dir must not matter. Aligns to visible length (repeat-last pad).
    torch.manual_seed(1)
    visible = torch.rand(5, 8, 8, 3)
    reference = torch.rand(5, 8, 8, 3)
    mask_hi = torch.zeros(4, 8, 8)
    mask_hi[:, 4:, :] = 1.0  # subject = lower half
    prepared = prepare_replace_window(
        mask_spec={"kind": "sam3", "dir": "/does/not/exist"},
        start_frame=0,
        nominal_length=4,
        visible_frames=visible,
        reference_frames=reference,
        mask_hi=mask_hi,
    )
    assert prepared is not None
    assert tuple(prepared["mask_vis"].shape) == (5, 8, 8)
    assert prepared["mask_vis"][0, 7, 0].item() == 1.0
    assert torch.equal(prepared["mask_vis"][3], prepared["mask_vis"][4])
    assert tuple(prepared["sanitized_reference"].shape) == (5, 8, 8, 3)
    # Background rows survive in the echo-free reference.
    assert torch.allclose(
        prepared["sanitized_reference"][0, :4, :, :],
        reference[0, :4, :, :],
        atol=1e-5,
    )
    # A non-3D mask_hi is rejected (caller falls back).
    assert (
        prepare_replace_window(
            mask_spec={"kind": "sam3"},
            start_frame=0,
            nominal_length=4,
            visible_frames=visible,
            reference_frames=reference,
            mask_hi=torch.zeros(1, 1, 8, 8, 3),
        )
        is None
    )


def test_prepare_replace_window_anchor_negative_reference(tmp_path):
    # render_mode="anchor" builds the CGlide negative-anchor reference: the
    # subject region is inverted, the background is kept as a normal photo.
    _write_frames_mapping(tmp_path, {0: 1, 1: 0})
    torch.manual_seed(4)
    visible = torch.rand(2, 8, 8, 3)
    reference = torch.rand(2, 8, 8, 3)
    prepared = prepare_replace_window(
        mask_spec={"kind": "frames", "dir": str(tmp_path), "offset": 0},
        start_frame=0,
        nominal_length=2,
        visible_frames=visible,
        reference_frames=reference,
        render_mode="anchor",
    )
    assert prepared is not None
    ref = prepared["sanitized_reference"]
    assert tuple(ref.shape) == (2, 8, 8, 3)
    # Frame 0 mask value 1 -> subject rows 4.. inverted, background kept.
    assert torch.allclose(ref[0, 4:, :, :], 1.0 - reference[0, 4:, :, :], atol=1e-5)
    assert torch.allclose(ref[0, :4, :, :], reference[0, :4, :, :], atol=1e-5)
    # Frame 1 mask value 0 -> no subject, whole frame kept.
    assert torch.allclose(ref[1], reference[1], atol=1e-5)
