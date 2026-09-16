"""The masked (keep) replace path must actually replace the subject.

Field bug (2026-09-15): a 97-frame inpaint run reported "masked replace ready"
with a video noise mask of mean 0.71 attached to the sampler, yet the rendered
clip came back frame-for-frame identical to the source (mean |diff| 8/255 vs
51+/255 for the same window in anchor mode). ComfyUI starts masked sampling from
``latent_image + noise``, so the encoded source inside the regenerate region is a
strong hint the denoiser simply refines - the replacement is never invented.

The fix erases the source inside the regenerate region before the latent reaches
the sampler. The keep region and the nested noise mask are untouched, so the
background still comes back pixel-exact.
"""

from __future__ import annotations

import torch

from director.replace_runtime import (
    assemble_masked_replace_latent,
    erase_source_in_regenerate_region,
)


def _latent(t: int = 2, c: int = 24, h: int = 6, w: int = 8) -> torch.Tensor:
    return torch.ones((1, c, t, h, w), dtype=torch.float32)


def _video_mask(t: int = 2, h: int = 6, w: int = 8) -> torch.Tensor:
    mask = torch.zeros((t, h, w), dtype=torch.float32)
    mask[:, :, : w // 2] = 1.0  # regenerate the left half
    return mask


def test_regenerate_region_is_zeroed_and_keep_region_survives():
    latent = _latent()
    out = erase_source_in_regenerate_region(latent, _video_mask())
    assert tuple(out.shape) == tuple(latent.shape)
    # left half (mask 1) erased, right half (mask 0) untouched
    assert torch.all(out[..., :4] == 0.0)
    assert torch.all(out[..., 4:] == 1.0)


def test_all_keep_mask_leaves_the_latent_untouched():
    latent = _latent()
    keep = torch.zeros((2, 6, 8), dtype=torch.float32)
    out = erase_source_in_regenerate_region(latent, keep)
    assert torch.equal(out, latent)


def test_nested_mask_uses_the_video_stream():
    nested = torch.ones((1, 1, 2, 6, 8), dtype=torch.float32)
    nested[..., :4] = 0.0  # keep the left half, regenerate the right half
    latent = _latent()
    out = erase_source_in_regenerate_region(latent, nested)
    assert torch.all(out[..., :4] == 1.0)
    assert torch.all(out[..., 4:] == 0.0)


def test_mismatched_mask_is_ignored_rather_than_misaligned():
    latent = _latent()
    wrong_shape = torch.ones((2, 4, 5), dtype=torch.float32)  # different h/w
    assert torch.equal(erase_source_in_regenerate_region(latent, wrong_shape), latent)
    wrong_time = torch.ones((3, 6, 8), dtype=torch.float32)
    assert torch.equal(erase_source_in_regenerate_region(latent, wrong_time), latent)
    assert torch.equal(erase_source_in_regenerate_region(latent, None), latent)


def test_assemble_erases_the_video_stream_only():
    import comfy.nested_tensor

    video = _latent()
    audio = torch.full((1, 32, 2, 178), 0.5, dtype=torch.float32)
    video_mask = torch.ones((1, 1, 2, 6, 8), dtype=torch.float32)
    audio_mask = torch.zeros((1, 32, 2, 178), dtype=torch.float32)
    mask = comfy.nested_tensor.NestedTensor((video_mask, audio_mask))

    out = assemble_masked_replace_latent(
        {"samples": comfy.nested_tensor.NestedTensor((video, audio))},
        source_video_latent={"samples": video},
        video_latent=video,
        audio_latent=audio,
        mask=mask,
    )
    streams = out["samples"].unbind()
    video_out, audio_out = streams[0], streams[1]
    assert torch.all(video_out == 0.0), "regenerate region source was not erased"
    assert torch.equal(audio_out, audio), "audio stream must be untouched"
    assert out["noise_mask"] is mask
