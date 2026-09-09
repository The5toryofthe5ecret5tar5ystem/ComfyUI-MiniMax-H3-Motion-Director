"""MiniMax H3 reference-audio encode guard (OOM-safe, transparent).

ComfyUI's generic ``VAE.encode()`` has a broken out-of-memory fallback for the
MiniMax H3 *audio* VAE: the wrapper reports ``latent_dim = 2`` (its latents are
shaped ``[B, 32, stereo-2, T]``) while the input waveform is 1-D
``[B, 2, samples]``.  When the untiled encode runs out of VRAM ComfyUI retries
with the 2D image tiler ``encode_tiled_``, which reads ``pixel_samples.shape[3]``
on a rank-3 tensor and raises ``IndexError: tuple index out of range`` - killing
the whole job.

This guard replaces ``comfy_extras.nodes_minimax_h3._encode_ref_audio`` with an
encode that runs on the audio VAE's first-stage model directly (identical math
for this VAE: no crop, identity process/input, fp32, direct conv encode), so the
broken tiled fallback is never reached.  It first tries a full-length untiled
encode and, only when that runs out of VRAM, transparently falls back to a
causal-warmup chunked encode: the waveform is padded to the 800-sample latent
hop, encoded in payload chunks (each non-first chunk prefixed by a warm-up
context segment whose latent output is discarded) and the ``[1, 32, 2, T]``
results concatenated so the returned latent length is identical to an untiled
encode.

Transparent to users: no new inputs/settings/workflows.  When the encode fits in
VRAM the produced latent is identical to today's; the chunked path is only
reached in the OOM case that previously crashed.
"""

from __future__ import annotations

import logging

import torch

_HOP = 800  # audio samples per H3 audio-latent frame (2*4*4*5*5)
_WARMUP_LAT = 40  # ~1 s causal warm-up context per chunk (except the first)
_CHUNK_LAT = 240  # default payload per chunk: ~6 s at 40 latents/s
_MIN_CHUNK_LAT = 16  # ~0.4 s - below this there is no point retrying

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.audio_vae_guard")

_INSTALLED = False
_COMFY_MM = None


def _is_oom(exc: BaseException) -> bool:
    if isinstance(exc, RuntimeError) and "out of memory" in str(exc).lower():
        return True
    return False


def _comfy_model_management():
    global _COMFY_MM
    if _COMFY_MM is None:
        try:
            import comfy.model_management  # type: ignore

            _COMFY_MM = comfy.model_management
        except Exception:  # pragma: no cover - offline tests / non-ComfyUI envs
            _COMFY_MM = False
    return _COMFY_MM or None


def pad_to_hop(waveform: torch.Tensor, hop: int = _HOP) -> torch.Tensor:
    """Right-pad channels-first ``[B, C, L]`` audio to a multiple of ``hop``."""
    length = int(waveform.shape[-1])
    rem = length % hop
    if rem == 0:
        return waveform
    pad = torch.zeros(
        waveform.shape[:-1] + (hop - rem,),
        dtype=waveform.dtype,
        device=waveform.device,
    )
    return torch.cat([waveform, pad], dim=-1)


def chunked_encode_latents(
    encode_one,
    waveform: torch.Tensor,
    *,
    chunk_lat: int = _CHUNK_LAT,
    warmup_lat: int = _WARMUP_LAT,
    hop: int = _HOP,
) -> torch.Tensor:
    """Encode channels-first ``[1, C, L]`` audio in causal-warmup chunks.

    ``encode_one(seg_channels_first) -> latent`` must return latents shaped
    ``[1, 32, 2, T]`` with ``T == seg_len // hop`` (chunks are hop-aligned so
    this holds exactly).  The first chunk is encoded from stream start; every
    later chunk carries up to ``warmup_lat`` extra latent frames of preceding
    context whose latent output is discarded, approximating the full-stream
    causal context each payload would have seen in an untiled encode.
    """
    if int(waveform.shape[0]) != 1:
        raise ValueError("Reference audio must be batch 1, got %d." % int(waveform.shape[0]))
    padded = pad_to_hop(waveform, hop=hop)
    total_lat = int(padded.shape[-1]) // hop
    outs = []
    start_lat = 0
    first = True
    while start_lat < total_lat:
        payload = min(int(chunk_lat), total_lat - start_lat)
        s0 = start_lat * hop
        s1 = s0 + payload * hop
        if first:
            seg = padded[:, :, s0:s1]
            drop = 0
        else:
            ctx = int(min(warmup_lat, start_lat)) * hop
            seg = padded[:, :, s0 - ctx : s1]
            drop = int(min(warmup_lat, start_lat))
        z = encode_one(seg.contiguous())
        if drop:
            z = z[..., drop:]
        outs.append(z)
        start_lat += payload
        first = False
    return torch.cat(outs, dim=-1)


def _first_stage_encode(av, seg_cf: torch.Tensor) -> torch.Tensor:
    """Untiled encode through the audio VAE's first stage, mirroring ComfyUI's
    wrapper math for this VAE (no crop, identity process, fp32, direct encode).

    This deliberately bypasses ``av.encode()`` so an OOM can never enter
    ComfyUI's broken 2D tiled fallback for the H3 audio VAE.
    """
    seg_cf = seg_cf.float()
    mm = _comfy_model_management()
    if hasattr(av, "patcher") and mm is not None:
        mem = None
        if hasattr(av, "memory_used_encode"):
            try:
                mem = av.memory_used_encode(tuple(seg_cf.shape), torch.float32)
            except Exception:  # pragma: no cover - defensive
                mem = None
        try:
            mm.load_models_gpu(
                [av.patcher],
                memory_required=mem,
                force_full_load=bool(getattr(av, "disable_offload", False)),
            )
        except Exception:  # pragma: no cover - defensive fallback load
            mm.soft_empty_cache()
            mm.load_models_gpu([av.patcher], force_full_load=False)
    device = getattr(av, "device", None) or seg_cf.device
    out = av.first_stage_model.encode(seg_cf.to(device))
    out_device = getattr(av, "output_device", None)
    if out_device is not None:
        out = out.to(out_device)
    dtype_fn = getattr(av, "vae_output_dtype", None)
    if callable(dtype_fn):
        try:
            out = out.to(dtype_fn())
        except Exception:  # pragma: no cover - defensive
            pass
    return out


def _encode_chunked_with_oom_handling(audio_vae, wave: torch.Tensor):
    mm = _comfy_model_management()
    if mm is not None:
        mm.soft_empty_cache()
    last_exc = None
    chunk_lat = _CHUNK_LAT
    while chunk_lat >= _MIN_CHUNK_LAT:
        try:
            z = chunked_encode_latents(
                lambda seg: _first_stage_encode(audio_vae, seg),
                wave,
                chunk_lat=chunk_lat,
                warmup_lat=min(_WARMUP_LAT, max(_MIN_CHUNK_LAT, chunk_lat // 2)),
            )
            return z, int(z.shape[-1])
        except RuntimeError as exc:  # noqa: PERF203 - retry only on OOM
            last_exc = exc
            if not _is_oom(exc):
                raise
            if mm is not None:
                mm.soft_empty_cache()
            chunk_lat //= 2
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("MiniMax H3 reference audio could not be encoded (out of VRAM).")


def encode_reference_audio(audio_vae, audio):
    """OOM-guarded replacement for the official ``_encode_ref_audio``.

    Accepts the same ``(audio_vae, audio)`` contract and returns
    ``(z, z.shape[-1])`` with ``z`` shaped ``[1, 32, 2, T]``.
    """
    waveform = audio["waveform"]  # [B, C, L], channels-first
    if int(waveform.shape[0]) != 1:
        waveform = waveform[:1]
    sr = int(audio["sample_rate"])
    vae_sr = int(getattr(audio_vae, "audio_sample_rate", 32000))
    if sr != vae_sr:
        import torchaudio

        waveform = torchaudio.functional.resample(waveform, sr, vae_sr)
    wave = waveform[:1].contiguous()
    try:
        z = _first_stage_encode(audio_vae, wave)
        return z, int(z.shape[-1])
    except RuntimeError as exc:
        if not _is_oom(exc):
            raise
        log.warning(
            "MiniMax H3 reference audio encode ran out of VRAM; "
            "retrying with a chunked encode."
        )
        return _encode_chunked_with_oom_handling(audio_vae, wave)


def install_audio_vae_guard() -> None:
    """Replace ``comfy_extras.nodes_minimax_h3._encode_ref_audio`` with the guard."""
    global _INSTALLED
    if _INSTALLED:
        return
    try:
        from comfy_extras import nodes_minimax_h3 as _h3  # type: ignore
    except Exception as exc:  # pragma: no cover - non-ComfyUI environment
        log.warning("Reference-audio encode guard not installed (comfy_extras unavailable): %s", exc)
        return

    def guarded(audio_vae, audio):
        return encode_reference_audio(audio_vae, audio)

    _h3._encode_ref_audio = guarded
    _INSTALLED = True
    log.info("MiniMax H3 reference-audio encode guard installed.")


__all__ = [
    "chunked_encode_latents",
    "encode_reference_audio",
    "install_audio_vae_guard",
    "pad_to_hop",
]
