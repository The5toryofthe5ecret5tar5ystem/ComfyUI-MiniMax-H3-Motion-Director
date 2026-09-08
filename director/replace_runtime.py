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
import torch.nn.functional as F

from .replace_engine import (
    MASK_KEEP,
    MASK_REGENERATE,
    dilate_soften_mask,
    load_mask_window_with_lead,
    negative_anchor_frames,
    pool_mask_to_latent_time,
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


def _resize_mask_spatial(mask_hi: torch.Tensor, height: int, width: int) -> torch.Tensor:
    """Nearest-resize each [T,H,W] mask frame to ``(height, width)``.

    Keeps mask pixels in the same coordinate frame as the fitted director clip
    (fit_canvas / fit_video_long_edge never crop, so a full-frame nearest
    resize preserves per-pixel correspondence with the resized video).
    """
    mask = mask_hi.float()
    if mask.ndim == 3:
        mask = mask.unsqueeze(1)  # [T,1,H,W]
    if (int(mask.shape[-2]), int(mask.shape[-1])) == (int(height), int(width)):
        return mask_hi.float().contiguous()
    resized = F.interpolate(mask, size=(int(height), int(width)), mode="nearest-exact")
    return resized[:, 0].contiguous()


def _align_mask_frames(mask_hi: torch.Tensor, count: int) -> torch.Tensor:
    """Trim or repeat-last pad a [T,H,W] mask to ``count`` frames."""
    count = max(1, int(count))
    have = int(mask_hi.shape[0])
    if have == count:
        return mask_hi
    if have > count:
        return mask_hi[:count]
    tail = mask_hi[-1:].repeat(count - have, 1, 1)
    return torch.cat([mask_hi, tail], dim=0)


def prepare_replace_window(
    *,
    mask_spec: dict[str, Any],
    start_frame: int,
    nominal_length: int,
    visible_frames: torch.Tensor,
    reference_frames: torch.Tensor,
    grow: int = 0,
    feather: float = 0.0,
    lead_frames: int = 0,
    mask_hi: torch.Tensor | None = None,
    render_mode: str = "blur",
    method: str = "blur",
    blur_sigma: float = 14.0,
) -> dict[str, Any] | None:
    """Load the window mask and derive echo-free motion conditioning.

    ``mask_spec`` is a ReplaceMaskSpec JSON (kind=frames asset). Mask PNGs are
    keyed to the source video; the window begins at ``start_frame`` and spans
    ``nominal_length`` frames (Phase-1 constraint: timeline frames == source
    frames, i.e. a straight single-clip source at matching fps).
    ``lead_frames`` extends the returned mask backward over the pre-roll runway
    (real asset frames when present, else a first-frame-silhouette repeat).

    When ``mask_hi`` is provided (in-run SAM3 auto-mask) it is used directly
    as the full per-frame mask - it must already cover the whole render window
    including any lead head - and the file loader is bypassed.

    ``render_mode`` selects what the motion reference becomes so the original
    identity cannot echo: ``"blur"`` (default, used by the inpaint path)
    destroys the subject with a heavy blur; ``"anchor"`` (CGlide-style full
    re-render) draws the subject as a photographic negative. Both keep the
    background as a normal photograph.

    Returns None when the mask cannot be obtained (caller falls back to a plain
    RV2V window). On success returns::

        {"mask_vis": [Tv,H,W] 0..1 aligned to visible_frames,
         "sanitized_reference": [Tr,H,W,3] echo-free motion clip,
         "grow": int, "feather": float}

    ``sanitized_reference`` is aligned to ``reference_frames`` (same pixels,
    possibly a longer aligned/tail-padded clip); ``mask_vis`` is aligned to
    ``visible_frames`` for the latent noise-mask build.
    """
    if visible_frames is None or reference_frames is None:
        return None
    if visible_frames.ndim != 4 or reference_frames.ndim != 4:
        return None
    nominal_length = max(1, int(nominal_length))
    if mask_hi is not None:
        if mask_hi.ndim != 3:
            return None
        mask_body = mask_hi.float().contiguous()
    else:
        mask_body = load_mask_window_with_lead(
            mask_spec,
            start_frame=int(start_frame),
            nominal_length=nominal_length,
            lead_frames=int(lead_frames or 0),
        )
        if mask_body is None:
            return None
    vh, vw = int(visible_frames.shape[1]), int(visible_frames.shape[2])
    rh, rw = int(reference_frames.shape[1]), int(reference_frames.shape[2])
    mask_vis = _align_mask_frames(
        _resize_mask_spatial(mask_body, vh, vw), int(visible_frames.shape[0])
    )
    mask_ref = _align_mask_frames(
        _resize_mask_spatial(mask_body, rh, rw), int(reference_frames.shape[0])
    )
    if str(render_mode or "").strip().lower() == "anchor":
        # grow/feather have no latent noise mask to act on in anchor mode, so
        # apply them in pixel space to the mask before drawing the negative:
        # grow expands the negated (regenerate) region by ~grow*16 px so no
        # sliver of the original performer survives at the boundary; feather
        # softens the negative's edge (0 = hard cut).
        _g = max(0, int(grow or 0))
        _f = max(0.0, float(feather or 0.0))
        _anchor_mask = mask_ref
        if _g or _f:
            _anchor_mask = dilate_soften_mask(
                mask_ref, grow=_g, feather=_f
            )
        motion_reference = negative_anchor_frames(reference_frames, _anchor_mask)
    else:
        motion_reference = sanitized_reference_frames(
            reference_frames,
            mask_ref,
            method=str(method or "blur"),
            blur_sigma=float(blur_sigma),
        )
    return {
        "mask_vis": mask_vis.contiguous(),
        "sanitized_reference": motion_reference.contiguous(),
        "grow": max(0, int(grow or 0)),
        "feather": max(0.0, float(feather or 0.0)),
    }


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

    # mask_hi is per PIXEL frame; the H3 video latent compresses time with the
    # (1,4,4,4,4) token schedule, so aggregate the mask onto latent tokens first
    # (a token is keep only when every pixel frame it covers is background),
    # then downscale each token spatially to the latent grid.
    pooled = pool_mask_to_latent_time(mask_hi, t_v)  # [t_v, H, W]
    video_mask_low = to_latent_mask(
        pooled, latent_h=h, latent_w=w, grow=int(grow), feather=float(feather)
    )  # [t_v, h, w]
    video_mask = video_mask_low.unsqueeze(0).unsqueeze(0)  # [1,1,t_v,h,w]

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
