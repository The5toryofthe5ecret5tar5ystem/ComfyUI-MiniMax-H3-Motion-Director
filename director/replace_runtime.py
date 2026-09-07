# MiniMax H3 Motion Director - Character Replace runtime helpers (Phase 1).
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Masked AV-latent assembly for background-true character replacement.

Mirrors the engine's proven masked-sampling patterns:

* ``segment_continuity.apply_scail_prefix_to_latent`` (video-only): video
  latent ``samples`` [1, C, T, H, W], ``noise_mask`` [1, 1, T, H, W] with
  0 = keep / 1 = regenerate.
* ``audio_drive`` (joint AV): ``samples`` = NestedTensor((video, audio)) and
  ``noise_mask`` = NestedTensor((video_mask, audio_mask)).

The encode step needs a live VAE so it is intentionally thin; everything else
in this module is testable on CPU.
"""

from __future__ import annotations

from typing import Any

import torch

from .replace_engine import (
    MASK_KEEP,
    MASK_REGENERATE,
    sanitize_source_frames,
    to_latent_mask,
)
from .replace_spec import ReplaceSpec


def sanitized_reference_frames(
    frames: torch.Tensor,
    mask_hi: torch.Tensor,
    *,
    method: str = "blur",
    blur_sigma: float = 14.0,
) -> torch.Tensor:
    """Echo-free motion reference: source with the subject identity destroyed."""
    return sanitize_source_frames(
        frames, mask_hi, method=method, blur_sigma=blur_sigma
    )


def _video_latent_grid(video_latent: torch.Tensor) -> tuple[int, int]:
    """Spatial latent grid (h, w) of an H3 video-latent stream (5D or 4D)."""
    if video_latent.ndim == 5:
        return int(video_latent.shape[-2]), int(video_latent.shape[-1])
    if video_latent.ndim == 4:
        return int(video_latent.shape[-2]), int(video_latent.shape[-1])
    raise ValueError(f"video latent must be 4D/5D, got {tuple(video_latent.shape)}")


def build_replace_noise_mask(
    video_latent: torch.Tensor,
    audio_latent: torch.Tensor,
    mask_hi: torch.Tensor,
    *,
    grow: int = 0,
    feather: float = 0.0,
    audio_policy: str = "source",
) -> Any:
    """Build the nested AV noise mask for a masked replace sample.

    ``mask_hi`` [T, H, W] 0..1 with 1 = regenerate (subject). Returns a
    ``comfy.nested_tensor.NestedTensor((video_mask, audio_mask))``:
      video_mask [1, 1, T_v, h, w] (h/w on the video-latent grid)
      audio_mask 1 = regenerate audio, 0 = keep (mirrors the video convention).
    """
    h, w = _video_latent_grid(video_latent)
    t_v = int(video_latent.shape[2]) if video_latent.ndim == 5 else int(video_latent.shape[0])
    t = int(mask_hi.shape[0])

    video_mask_low = to_latent_mask(
        mask_hi, latent_h=h, latent_w=w, grow=int(grow), feather=float(feather)
    )  # [T, h, w]
    # Match the latent time length: repeat/trim (mask is per source frame).
    if video_mask_low.shape[0] < t_v:
        pad = video_mask_low[-1:].repeat(t_v - video_mask_low.shape[0], 1, 1)
        video_mask_low = torch.cat([video_mask_low, pad], dim=0)
    elif video_mask_low.shape[0] > t_v:
        video_mask_low = video_mask_low[:t_v]
    video_mask = video_mask_low.unsqueeze(0).unsqueeze(0)  # [1,1,T,h,w]

    if audio_policy == "source":
        audio_mask = torch.zeros_like(audio_latent)
    elif audio_policy == "none":
        audio_mask = torch.zeros_like(audio_latent)
    else:  # generate
        audio_mask = torch.ones_like(audio_latent)

    try:
        import comfy.nested_tensor
    except Exception as exc:  # pragma: no cover - ComfyUI is a runtime dep
        raise ValueError(f"comfy.nested_tensor unavailable for replace mask: {exc}") from exc

    return comfy.nested_tensor.NestedTensor((video_mask, audio_mask))


def encode_source_video(vae, source_frames: torch.Tensor) -> dict:
    """VAE-encode [T, H, W, 3] float source frames into a video latent dict."""
    from .refine_sampling import _encode_video

    return _encode_video(vae, source_frames)


def assemble_masked_replace_latent(
    template_latent: dict,
    *,
    source_video_latent: dict,
    video_latent: torch.Tensor,
    audio_latent: torch.Tensor,
    mask: Any,
) -> dict:
    """Return the AV latent to sample: source video stream + template audio + mask.

    ``template_latent`` is the conditioning latent from the H3 path (its audio
    stream is reused so stream length/shape stay valid); its video stream is
    replaced with the VAE-encoded source window. ``mask`` is the nested noise
    mask from :func:`build_replace_noise_mask`.
    """
    out = dict(template_latent)
    try:
        import comfy.nested_tensor
    except Exception as exc:  # pragma: no cover
        raise ValueError(f"comfy.nested_tensor unavailable: {exc}") from exc
    out["samples"] = comfy.nested_tensor.NestedTensor((video_latent, audio_latent))
    out["noise_mask"] = mask
    return out


def prepare_masked_replace_state(
    *,
    source_frames: torch.Tensor,
    reference_frames: torch.Tensor,
    mask_hi: torch.Tensor,
    spec: ReplaceSpec,
) -> dict:
    """Package everything the executor call site needs for one replace window.

    Returns sanitized reference frames (echo-free conditioning) and the raw
    pieces for latent assembly (already validated for shape compatibility).
    """
    if tuple(mask_hi.shape[-2:]) != tuple(source_frames.shape[-3:-1]):
        raise ValueError("replace mask spatial size must match the fitted source window")
    if int(mask_hi.shape[0]) < int(source_frames.shape[0]):
        raise ValueError("replace mask has fewer frames than the source window")
    mask_window = mask_hi[: int(source_frames.shape[0])]
    sanitized = sanitized_reference_frames(
        reference_frames, mask_window, method="blur", blur_sigma=14.0
    )
    audio_policy = str(spec.audio_policy or "source").strip().lower()
    if audio_policy not in ("source", "generate", "none"):
        audio_policy = "source"
    return {
        "mask_hi": mask_window.contiguous(),
        "sanitized_reference": sanitized.contiguous(),
        "grow": int(getattr(spec.mask, "grow", 0) or 0),
        "feather": float(getattr(spec.mask, "feather", 0.0) or 0.0),
        "audio_policy": audio_policy,
    }
