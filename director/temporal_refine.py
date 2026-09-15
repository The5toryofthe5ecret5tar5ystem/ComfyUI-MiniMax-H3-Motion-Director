"""Temporal chunking for the Global Refine second-sampling pass.

The whole-clip refine re-samples the entire upscaled H3 video latent at once,
so activation VRAM scales with sequence length. This module re-samples one
overlapping time chunk at a time and cross-fades the overlaps, keeping peak
VRAM bounded to a single chunk. Audio is carried through unchanged (never
re-sampled), mirroring the temporal split in Comfyui-MMH3-UltimateUpscale.

Scoped by the caller: it is only used when there is no Motion Context repinning
and no H3 noise mask, so the conditioning (spatial reference keyframes) applies
uniformly to every chunk and needs no per-chunk time re-anchoring.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import torch

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.temporal_refine")

# H3 temporal grid (mirrors director/motion_context.py). Kept local so this
# module can be imported without pulling in motion_context's package-relative
# imports (the bare-``director`` import path used by some tests).
FPS = 24.0
AUDIO_LATENT_HZ = 40.0
FRAME_PER_TOKEN = (1, 4, 4, 4, 4)
TOKENS_PER_GROUP = len(FRAME_PER_TOKEN)  # 5
FRAMES_PER_GROUP = sum(FRAME_PER_TOKEN)  # 17


def _pixel_frames_for_latent_steps(latent_t: int) -> int:
    return sum(FRAME_PER_TOKEN[i % len(FRAME_PER_TOKEN)] for i in range(int(latent_t)))


def _split_streams(latent: dict[str, Any]) -> tuple[torch.Tensor | None, torch.Tensor | None, dict[str, Any]]:
    samples = latent.get("samples") if isinstance(latent, dict) else None
    extra = {key: value for key, value in (latent or {}).items() if key != "samples"}
    if isinstance(samples, torch.Tensor):
        streams = [samples]
    elif hasattr(samples, "unbind"):
        streams = list(samples.unbind())
    elif isinstance(samples, (tuple, list)):
        streams = list(samples)
    else:
        streams = []
    video = streams[0] if streams else None
    audio = streams[1] if len(streams) > 1 else None
    return video, audio, extra


def _snap_group(value: int) -> int:
    return max(0, int(round(float(value) / FRAMES_PER_GROUP)) * FRAMES_PER_GROUP)


def _edge_ramp(size: int, overlap: int, *, left: bool, right: bool) -> torch.Tensor:
    """Per-token cross-fade weight: ramps on interior (overlapping) edges only."""
    weight = torch.ones(size, dtype=torch.float32)
    if left and overlap > 0:
        for i in range(min(overlap, size)):
            weight[i] = (i + 1) / (overlap + 1)
    if right and overlap > 0:
        for i in range(min(overlap, size)):
            index = size - 1 - i
            weight[index] = min(float(weight[index]), (i + 1) / (overlap + 1))
    return weight


def sample_temporal_chunked_refine(
    *,
    model,
    positive,
    negative,
    latent: dict[str, Any],
    seed: int,
    cfg: float,
    steps: int,
    sampler_name: str,
    scheduler: str,
    shift_video: float,
    shift_audio: float,
    denoise: float,
    chunk_frames: int,
    overlap_frames: int,
    tile_size: int = 0,
    tile_overlap: int = 0,
    on_phase: Callable[[str, float], None] | None = None,
    on_step_preview: Callable[[int, int, Any, Any], None] | None = None,
    preview_every: int = 1,
) -> dict[str, Any]:
    """Re-sample one refine pass in overlapping time chunks and stitch them.

    ``tile_size > 0`` additionally spatially tiles each chunk (the inner loop),
    so temporal + spatial split can be combined on very small cards.
    """
    import comfy.nested_tensor

    from .core_sampling import sample_single_stage
    from .tiled_refine import sample_tiled_refine_pass

    video, audio, extra = _split_streams(latent)
    if video is None or video.ndim != 5:
        return sample_single_stage(
            model=model, positive=positive, negative=negative, latent=latent, seed=seed,
            cfg=cfg, steps=steps, sampler_name=sampler_name, scheduler=scheduler,
            shift_video=shift_video, shift_audio=shift_audio, denoise=denoise,
            phase_name="global_refine", on_phase=on_phase,
            on_step_preview=on_step_preview, preview_every=preview_every,
        )

    total_tokens = int(video.shape[2])
    total_frames = _pixel_frames_for_latent_steps(total_tokens)
    chunk = _snap_group(int(chunk_frames))
    overlap = _snap_group(int(overlap_frames))
    chunk = max(FRAMES_PER_GROUP, chunk)
    overlap = min(max(0, overlap), max(0, chunk - FRAMES_PER_GROUP))

    if chunk >= total_frames:
        if tile_size > 0:
            return sample_tiled_refine_pass(
                model=model, positive=positive, negative=negative, latent=latent, seed=seed,
                cfg=cfg, steps=steps, sampler_name=sampler_name, scheduler=scheduler,
                shift_video=shift_video, shift_audio=shift_audio, denoise=denoise,
                tile_size=tile_size, tile_overlap=tile_overlap,
                on_phase=on_phase, on_step_preview=on_step_preview, preview_every=preview_every,
            )
        return sample_single_stage(
            model=model, positive=positive, negative=negative, latent=latent, seed=seed,
            cfg=cfg, steps=steps, sampler_name=sampler_name, scheduler=scheduler,
            shift_video=shift_video, shift_audio=shift_audio, denoise=denoise,
            phase_name="global_refine", on_phase=on_phase,
            on_step_preview=on_step_preview, preview_every=preview_every,
        )

    step = max(FRAMES_PER_GROUP, chunk - overlap)
    starts: list[int] = []
    pos = 0
    while pos < total_frames:
        starts.append(pos)
        if pos + chunk >= total_frames:
            break
        pos += step
    unique: list[int] = []
    for start in starts:
        if not unique or start != unique[-1]:
            unique.append(start)
    starts = unique

    overlap_tokens = overlap // FRAMES_PER_GROUP * TOKENS_PER_GROUP
    chunk_count = len(starts)
    base_latent = {key: value for key, value in extra.items() if key != "noise_mask"}
    stitched = torch.zeros(video.shape, dtype=torch.float32, device=video.device)
    weight = torch.zeros(
        (1, 1, total_tokens, 1, 1), dtype=torch.float32, device=video.device
    )

    for index, f0 in enumerate(starts):
        f1 = min(f0 + chunk, total_frames)
        k0 = f0 // FRAMES_PER_GROUP * TOKENS_PER_GROUP
        k1 = (f1 // FRAMES_PER_GROUP * TOKENS_PER_GROUP) if f1 < total_frames else total_tokens
        if k1 <= k0:
            continue
        chunk_video = video[:, :, k0:k1].contiguous()

        chunk_audio = None
        if audio is not None:
            a0 = int(round(float(f0) / FPS * AUDIO_LATENT_HZ))
            a1 = min(int(audio.shape[-1]), int(round(float(f1) / FPS * AUDIO_LATENT_HZ)))
            if a1 > a0:
                chunk_audio = audio[..., a0:a1].contiguous()

        chunk_latent = dict(base_latent)
        if chunk_audio is not None:
            chunk_latent["samples"] = comfy.nested_tensor.NestedTensor((chunk_video, chunk_audio))
        else:
            chunk_latent["samples"] = chunk_video

        def _chunk_phase(_phase: str, value: float, *, _index: int = index, _n: int = chunk_count) -> None:
            if on_phase is not None:
                on_phase(
                    "global_refine",
                    (float(_index) + max(0.0, min(1.0, float(value)))) / max(1, _n),
                )

        if tile_size > 0:
            out = sample_tiled_refine_pass(
                model=model, positive=positive, negative=negative, latent=chunk_latent,
                seed=seed, cfg=cfg, steps=steps, sampler_name=sampler_name,
                scheduler=scheduler, shift_video=shift_video, shift_audio=shift_audio,
                denoise=denoise, tile_size=tile_size, tile_overlap=tile_overlap,
                on_phase=_chunk_phase, on_step_preview=on_step_preview, preview_every=preview_every,
            )
        else:
            out = sample_single_stage(
                model=model, positive=positive, negative=negative, latent=chunk_latent,
                seed=seed, cfg=cfg, steps=steps, sampler_name=sampler_name,
                scheduler=scheduler, shift_video=shift_video, shift_audio=shift_audio,
                denoise=denoise, phase_name="global_refine", on_phase=_chunk_phase,
                on_step_preview=on_step_preview, preview_every=preview_every,
            )

        out_video, _out_audio, _ = _split_streams(out)
        out_video = out_video.float()
        produced = int(out_video.shape[2])
        k1 = min(k1, k0 + produced)
        out_video = out_video[:, :, : k1 - k0].contiguous()

        chunk_weight = _edge_ramp(
            k1 - k0,
            overlap_tokens,
            left=k0 > 0,
            right=k1 < total_tokens,
        ).to(device=video.device)
        stitched[:, :, k0:k1] += out_video * chunk_weight[None, None, :, None, None]
        weight[:, :, k0:k1] += chunk_weight[None, None, :, None, None]

    stitched = (stitched / weight.clamp_min(1e-6)).to(video.dtype)
    result = dict(latent)
    result.pop("noise_mask", None)
    if audio is not None:
        result["samples"] = comfy.nested_tensor.NestedTensor((stitched, audio))
    else:
        result["samples"] = stitched
    return result


__all__ = ["sample_temporal_chunked_refine"]
