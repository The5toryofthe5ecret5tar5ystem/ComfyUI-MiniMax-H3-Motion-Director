"""Latent-space continuation ("continue in latent space") for H3 chaining.

The previous clip's final latent window is injected directly into the next
clip's sampling stream and locked with a nested H3 noise mask (0 = preserve,
1 = generate), so the next generation continues from the previous latent instead
of recreating its ending from conditioning keyframes alone.

This is the mechanism behind the community "video joiner / continue in latent
space" workflow, ported natively. It is the `masked_av` family of continuation,
distinct from the Director's conditioning-only Motion Context.
"""

from __future__ import annotations

import logging
from typing import Any

import torch

from .motion_context import (
    FPS,
    _audio_context_from_latent,
    _latent_audio_stream,
    _latent_video_stream,
    video_context_from_latent,
)

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.latent_continuation")


def _has_audio_stream(latent: dict[str, Any]) -> bool:
    samples = latent.get("samples") if isinstance(latent, dict) else None
    if hasattr(samples, "unbind"):
        streams = list(samples.unbind())
    elif isinstance(samples, (tuple, list)):
        streams = list(samples)
    else:
        streams = []
    return len(streams) >= 2


def build_pinned_latent(
    template_latent: dict[str, Any],
    previous_latent: dict[str, Any],
    *,
    span: int,
    fps: float = FPS,
) -> dict[str, Any]:
    """Inject the previous latent's final ``span`` frames into the template head.

    Returns a new latent dict whose first tokens are the previous clip's tail and
    whose ``noise_mask`` (a nested H3 mask) preserves those tokens (0) while
    regenerating the remainder (1). Audio is handled the same way on its own
    40 Hz grid.

    The previous tail token ``i`` maps to the template head token ``i``: both are
    whole H3 latent tokens with the same ``(1,4,4,4,4)`` per-token frame coverage,
    so no temporal rescale is required.
    """
    import comfy.nested_tensor

    if abs(float(fps) - FPS) > 1e-6:
        raise ValueError("Latent continuation requires H3's native 24 fps.")

    template_video = _latent_video_stream(template_latent)
    template_has_audio = _has_audio_stream(template_latent)
    template_audio = _latent_audio_stream(template_latent) if template_has_audio else None

    blocks, _offsets, _selected_end = video_context_from_latent(
        previous_latent, span=int(span), context_end_frame=None
    )
    needed_steps = len(blocks)
    if needed_steps <= 0:
        raise ValueError("Latent continuation produced no carry-forward blocks.")

    new_video = template_video.clone()
    for index, block in enumerate(blocks):
        new_video[:, :, index : index + 1] = block.to(
            device=new_video.device, dtype=new_video.dtype
        )

    total_steps = int(new_video.shape[2])
    video_mask = torch.ones(
        (1, 1, total_steps, int(new_video.shape[3]), int(new_video.shape[4])),
        dtype=torch.float32,
        device=new_video.device,
    )
    video_mask[..., :needed_steps, :, :] = 0.0

    out = dict(template_latent)
    if template_audio is not None:
        audio_tail, audio_steps = _audio_context_from_latent(
            previous_latent, span=int(span), context_end_frame=None
        )
        prev_audio = audio_tail["audio_latent"]
        new_audio = template_audio.clone()
        insert = min(int(audio_steps), int(new_audio.shape[-1]))
        if insert > 0:
            new_audio[..., :insert] = prev_audio[..., :insert].to(
                device=new_audio.device, dtype=new_audio.dtype
            )
        audio_mask = torch.ones(
            (1, 1, int(new_audio.shape[2]), int(new_audio.shape[3])),
            dtype=torch.float32,
            device=new_audio.device,
        )
        audio_mask[..., :insert] = 0.0
        out["samples"] = comfy.nested_tensor.NestedTensor((new_video, new_audio))
        out["noise_mask"] = comfy.nested_tensor.NestedTensor((video_mask, audio_mask))
    else:
        out["samples"] = new_video
        out["noise_mask"] = video_mask
    return out


__all__ = ["build_pinned_latent"]
