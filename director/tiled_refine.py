"""Spatial tiling for the Global Refine second-sampling pass.

The whole-frame refine re-samples the entire upscaled H3 video latent at once,
so activation VRAM scales with the target resolution. This module re-samples
one spatial tile at a time (each tile carries the full audio stream), then
stitches the tiles with a linear cross-fade and a per-tile brightness match,
keeping peak VRAM bounded to a single tile.

Scoped by the caller: it is only used when there is no Motion Context repinning
and no H3 noise mask (those carry full-canvas conditioning that tiling must not
crop).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import torch

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.tiled_refine")

# H3 video latent spatial grid: one latent unit == 16 canvas pixels.
LATENT_UNIT = 16


def _split_streams(latent: dict[str, Any]) -> tuple[torch.Tensor, torch.Tensor | None, dict[str, Any]]:
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


def _tile_starts(size: int, tile: int, overlap: int) -> list[int]:
    if tile >= size:
        return [0]
    step = max(1, tile - overlap)
    starts: list[int] = []
    pos = 0
    while pos + tile < size:
        starts.append(pos)
        pos += step
    starts.append(max(0, size - tile))
    unique: list[int] = []
    for start in starts:
        if not unique or start != unique[-1]:
            unique.append(start)
    return unique


def _crop_keyframes(conditioning: Any, x0: int, x1: int, y0: int, y1: int) -> Any:
    """Spatially crop every native keyframe latent to the tile region."""
    if not isinstance(conditioning, (list, tuple)):
        return conditioning
    out = []
    for entry in conditioning:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            out.append(entry)
            continue
        cond_tensor, metadata = entry[0], entry[1]
        if not isinstance(metadata, dict):
            out.append(entry)
            continue
        meta = dict(metadata)
        keyframes = []
        for keyframe in list(metadata.get("minimax_keyframes") or []):
            if not isinstance(keyframe, dict):
                keyframes.append(keyframe)
                continue
            updated = dict(keyframe)
            latent = keyframe.get("latent")
            if isinstance(latent, torch.Tensor) and latent.ndim in {4, 5}:
                updated["latent"] = latent[..., y0:y1, x0:x1]
            keyframes.append(updated)
        meta["minimax_keyframes"] = keyframes
        new_entry = list(entry)
        new_entry[1] = meta
        out.append(new_entry)
    return out


def _ramp(size: int, overlap: int) -> torch.Tensor:
    weight = torch.ones(size, dtype=torch.float32)
    if overlap <= 0:
        return weight
    for i in range(min(overlap, size)):
        weight[i] = (i + 1) / (overlap + 1)
    for i in range(min(overlap, size)):
        index = size - 1 - i
        weight[index] = min(float(weight[index]), (i + 1) / (overlap + 1))
    return weight


def _tile_weight(
    y0: int, y1: int, x0: int, x1: int, height: int, width: int, overlap: int
) -> torch.Tensor:
    """Cross-fade weight for one tile: ramps only on interior (overlapping) edges."""
    tile_h, tile_w = y1 - y0, x1 - x0
    wy = _ramp(tile_h, overlap)
    if y0 == 0:
        wy[0] = 1.0
    if y1 >= height:
        wy[-1] = 1.0
    wx = _ramp(tile_w, overlap)
    if x0 == 0:
        wx[0] = 1.0
    if x1 >= width:
        wx[-1] = 1.0
    return wy[:, None] * wx[None, :]


def _brightness_match(tile_out: torch.Tensor, tile_in: torch.Tensor) -> torch.Tensor:
    """Match a tile's mean/std back to its input so tiles do not drift in brightness."""
    if tile_in is None or tile_out.shape != tile_in.shape:
        return tile_out
    out = tile_out.float()
    inp = tile_in.float()
    out_mean = out.mean()
    in_mean = inp.mean()
    out_std = out.std(unbiased=False)
    in_std = inp.std(unbiased=False)
    if out_std <= 1e-6 or in_std <= 1e-6:
        adjusted = out + (in_mean - out_mean)
    else:
        adjusted = (out - out_mean) * (in_std / out_std) + in_mean
    return adjusted.to(tile_out.dtype)


def sample_tiled_refine_pass(
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
    tile_size: int,
    tile_overlap: int,
    on_phase: Callable[[str, float], None] | None = None,
    on_step_preview: Callable[[int, int, Any, Any], None] | None = None,
    preview_every: int = 1,
) -> dict[str, Any]:
    """Re-sample one pass with spatial tiling and return the stitched AV latent."""
    import comfy.nested_tensor

    from .core_sampling import sample_single_stage

    video, audio, extra = _split_streams(latent)
    if video is None or video.ndim != 5:
        return sample_single_stage(
            model=model, positive=positive, negative=negative, latent=latent, seed=seed,
            cfg=cfg, steps=steps, sampler_name=sampler_name, scheduler=scheduler,
            shift_video=shift_video, shift_audio=shift_audio, denoise=denoise,
            phase_name="global_refine", on_phase=on_phase,
            on_step_preview=on_step_preview, preview_every=preview_every,
        )

    height = int(video.shape[-2])
    width = int(video.shape[-1])
    tile = max(2, int(tile_size) // LATENT_UNIT)
    overlap = min(tile - 1, max(0, int(tile_overlap) // LATENT_UNIT))

    if tile >= height and tile >= width:
        return sample_single_stage(
            model=model, positive=positive, negative=negative, latent=latent, seed=seed,
            cfg=cfg, steps=steps, sampler_name=sampler_name, scheduler=scheduler,
            shift_video=shift_video, shift_audio=shift_audio, denoise=denoise,
            phase_name="global_refine", on_phase=on_phase,
            on_step_preview=on_step_preview, preview_every=preview_every,
        )

    xs = _tile_starts(width, tile, overlap)
    ys = _tile_starts(height, tile, overlap)
    tile_count = len(xs) * len(ys)

    stitched = torch.zeros(
        video.shape, dtype=torch.float32, device=video.device,
    )
    weight = torch.zeros(
        (1, 1, 1, height, width), dtype=torch.float32, device=video.device,
    )
    base_latent = {key: value for key, value in extra.items() if key != "noise_mask"}

    tile_index = 0
    first_audio = None
    for y0 in ys:
        for x0 in xs:
            y1 = min(y0 + tile, height)
            x1 = min(x0 + tile, width)
            tile_video = video[..., y0:y1, x0:x1].contiguous()
            tile_positive = _crop_keyframes(positive, x0, x1, y0, y1)

            tile_latent = dict(base_latent)
            if audio is not None:
                tile_latent["samples"] = comfy.nested_tensor.NestedTensor(
                    (tile_video, audio)
                )
            else:
                tile_latent["samples"] = tile_video

            def _tile_phase(
                _phase: str, value: float, _idx: int = tile_index, _n: int = tile_count
            ) -> None:
                if on_phase is not None:
                    on_phase(
                        "global_refine",
                        (float(_idx) + max(0.0, min(1.0, float(value)))) / max(1, _n),
                    )

            out = sample_single_stage(
                model=model,
                positive=tile_positive,
                negative=negative,
                latent=tile_latent,
                seed=seed,
                cfg=cfg,
                steps=steps,
                sampler_name=sampler_name,
                scheduler=scheduler,
                shift_video=shift_video,
                shift_audio=shift_audio,
                denoise=denoise,
                phase_name="global_refine",
                on_phase=_tile_phase,
                on_step_preview=on_step_preview,
                preview_every=preview_every,
            )
            out_video, out_audio, _ = _split_streams(out)
            if first_audio is None and out_audio is not None:
                first_audio = out_audio
            out_video = _brightness_match(out_video, tile_video)

            tile_weight = _tile_weight(y0, y1, x0, x1, height, width, overlap).to(
                device=video.device
            )
            stitched[..., y0:y1, x0:x1] += out_video.float() * tile_weight
            weight[..., y0:y1, x0:x1] += tile_weight
            tile_index += 1

    stitched = (stitched / weight.clamp_min(1e-6)).to(video.dtype)
    result = dict(latent)
    result.pop("noise_mask", None)
    if audio is not None:
        result["samples"] = comfy.nested_tensor.NestedTensor(
            (stitched, first_audio if first_audio is not None else audio)
        )
    else:
        result["samples"] = stitched
    return result


__all__ = [
    "LATENT_UNIT",
    "sample_tiled_refine_pass",
]
