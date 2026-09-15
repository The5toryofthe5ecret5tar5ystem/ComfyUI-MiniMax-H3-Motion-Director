"""Full first-pass AV-latent cache for postprocess-only re-runs.

The expensive part of "render once, then iterate on postprocess" is the
first-pass H3 sample. This cache stores the raw sampled AV latent keyed on
everything that produced it EXCEPT postprocess settings, so a later run with
the same seed / prompt / refs / resolution / sampler but different Global
Refine / Face Refine / Audio Room settings can reuse it and only run the
postprocess stages.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import torch

import folder_paths

from .cache_path import cache_root
from .context_cache import context_fingerprint
from .context_identity import _json_identity
from .latent_context_cache import av_latent_to_cpu
from .segment_cache import _write_via_temp

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.first_pass_cache")

FIRST_PASS_CACHE_VERSION = 1
FIRST_PASS_CACHE_FORMAT = "minimax_h3_motion_director_first_pass_av_latent_v1"
FIRST_PASS_CACHE_PIPELINE = "first_pass_av_latent_v1"


def _cache_root(node_id: str | None) -> Path | None:
    if not node_id:
        return None
    try:
        return cache_root(
            folder_paths.get_output_directory(),
            "minimax_first_pass_cache",
            node_id,
        )
    except OSError as exc:
        log.warning("First-pass latent cache directory unavailable: %s", exc)
        return None


def _cache_filename(slot: int) -> str:
    return "seg_%04d.firstpass.av.pt" % int(slot)


# Postprocess keys folded into ``cache_settings`` by the executor. They change
# the FINAL result but not the first-pass latent, so they are excluded from the
# first-pass identity.
POSTPROCESS_CACHE_KEYS = frozenset({"global_refine", "face_refine", "audio_refine"})


def build_first_pass_settings(
    cache_settings: dict[str, Any] | None,
    *,
    seed: int,
    context_length: int,
) -> dict[str, Any]:
    """Identity of everything that produced the first-pass latent, minus postprocess.

    ``context_producer_fingerprint`` treats ``seed`` and ``context_length`` as
    consumer-only (they do not change the cached producer it validates), but
    they DO change the first-pass latent itself, so they are folded in under
    distinct key names that survive its filter.
    """
    settings = {
        key: value for key, value in (cache_settings or {}).items()
        if key not in POSTPROCESS_CACHE_KEYS
    }
    settings["first_pass_seed"] = int(seed)
    settings["first_pass_context_length"] = int(context_length or 0)
    return settings


def replace_first_pass_identity(
    replace_spec,
    *,
    mask_vis=None,
    source_frames=None,
    mode: str = "inpaint",
) -> dict[str, Any]:
    """Identity of the replace-specific inputs that shaped the first pass.

    The caller folds this into the first-pass settings, whose fingerprint hashes
    tensor values directly, so ``mask_vis`` / ``source_frames`` (effective mask
    and source window) invalidate the cache when their content changes even if
    the spec's file paths stay the same.
    """
    to_json = getattr(replace_spec, "to_json", None)
    spec = to_json() if callable(to_json) else dict(getattr(replace_spec, "__dict__", {}) or {})
    identity: dict[str, Any] = {"mode": mode, "spec": spec}
    if mask_vis is not None:
        identity["mask_vis"] = mask_vis
    if source_frames is not None:
        identity["source"] = source_frames
    return identity


def restore_av_latent(latent: dict[str, Any], device: torch.device) -> dict[str, Any]:
    """Rebuild a sampled AV latent dict with its ``samples`` NestedTensor on device."""
    import comfy.nested_tensor

    out: dict[str, Any] = {}
    for key, value in (latent or {}).items():
        if key == "samples":
            if isinstance(value, torch.Tensor):
                out[key] = value.to(device)
            elif isinstance(value, (tuple, list)):
                parts = tuple(part.to(device) for part in value)
                out[key] = (
                    comfy.nested_tensor.NestedTensor(parts)
                    if len(parts) > 1
                    else parts[0]
                )
            else:
                out[key] = value
        elif isinstance(value, torch.Tensor):
            out[key] = value.to(device)
        else:
            out[key] = value
    return out


def first_pass_device(latent: dict[str, Any]) -> torch.device:
    """Return the device the restored latent should live on."""
    samples = latent.get("samples") if isinstance(latent, dict) else None
    if hasattr(samples, "unbind"):
        streams = list(samples.unbind())
        if streams:
            return streams[0].device
    elif isinstance(samples, torch.Tensor):
        return samples.device
    from comfy.model_management import get_torch_device

    return get_torch_device()


def _diff_paths(stored: Any, current: Any, path: str = "") -> list[tuple[str, str, str]]:
    """Recursively find leaf values that differ between two identity dicts."""
    if isinstance(stored, dict) and isinstance(current, dict):
        out: list[tuple[str, str, str]] = []
        for key in sorted(set(stored) | set(current)):
            out.extend(_diff_paths(stored.get(key), current.get(key), f"{path}.{key}" if path else str(key)))
        return out
    if isinstance(stored, list) and isinstance(current, list):
        if len(stored) != len(current):
            return [(path, repr(stored)[:220], repr(current)[:220])]
        out = []
        for index, (left, right) in enumerate(zip(stored, current)):
            out.extend(_diff_paths(left, right, f"{path}[{index}]"))
        return out
    if stored != current:
        return [(path, str(stored)[:220], str(current)[:220])]
    return []


def save_first_pass_latent(
    node_id: str | None,
    seg,
    plan,
    *,
    latent: dict[str, Any],
    settings: dict[str, Any],
) -> bool:
    """Persist one segment's first-pass AV latent. Never raises."""
    root = _cache_root(node_id)
    if root is None:
        return False
    try:
        slot = int(getattr(seg, "timeline_index", seg.index))
        cpu_latent = av_latent_to_cpu(latent)
        # The replace noise mask is a NestedTensor that torch.load(weights_only=True)
        # cannot deserialize, and it is never read after sampling (the masked
        # replace path keeps the first pass). Drop it before persisting.
        cpu_latent.pop("noise_mask", None)
        metadata = {
            "pipeline": FIRST_PASS_CACHE_PIPELINE,
            "segment_index": slot,
            "fps": float(plan.frame_rate),
            "fingerprint": context_fingerprint(seg, plan, settings),
            "settings_snapshot": _json_identity(settings),
        }
        payload = {
            "format": FIRST_PASS_CACHE_FORMAT,
            "version": FIRST_PASS_CACHE_VERSION,
            "metadata": metadata,
            "latent": cpu_latent,
        }
        destination = root / _cache_filename(slot)
        _write_via_temp(destination, lambda path: torch.save(payload, path))
        return True
    except Exception as exc:
        log.warning(
            "First-pass latent cache write failed for segment %d: %s",
            int(getattr(seg, "timeline_index", seg.index)) + 1,
            exc,
        )
        return False


def load_first_pass_latent(
    node_id: str | None,
    seg,
    plan,
    *,
    settings: dict[str, Any],
) -> dict[str, Any] | None:
    """Load a validated first-pass AV latent for the segment, or None."""
    root = _cache_root(node_id)
    if root is None:
        return None
    try:
        slot = int(getattr(seg, "timeline_index", seg.index))
        path = root / _cache_filename(slot)
        if not path.is_file():
            log.info(
                "first-pass cache miss for segment %d: no file at %s",
                slot + 1, path,
            )
            return None
        payload = torch.load(path, map_location="cpu", weights_only=True)
        if not isinstance(payload, dict):
            log.info("first-pass cache miss for segment %d: payload is not a dict", slot + 1)
            return None
        if payload.get("format") != FIRST_PASS_CACHE_FORMAT:
            log.info("first-pass cache miss for segment %d: format mismatch", slot + 1)
            return None
        if int(payload.get("version", -1)) != FIRST_PASS_CACHE_VERSION:
            log.info("first-pass cache miss for segment %d: version mismatch", slot + 1)
            return None
        metadata = payload.get("metadata")
        latent = payload.get("latent")
        if not isinstance(metadata, dict) or not isinstance(latent, dict):
            log.info("first-pass cache miss for segment %d: bad metadata/latent", slot + 1)
            return None
        if metadata.get("pipeline") != FIRST_PASS_CACHE_PIPELINE:
            log.info("first-pass cache miss for segment %d: pipeline mismatch", slot + 1)
            return None
        if int(metadata.get("segment_index", -1)) != slot:
            log.info("first-pass cache miss for segment %d: segment index mismatch", slot + 1)
            return None
        if abs(float(metadata.get("fps", 0.0)) - float(plan.frame_rate)) > 1e-9:
            log.info(
                "first-pass cache miss for segment %d: fps mismatch (saved %s vs %s)",
                slot + 1, metadata.get("fps"), plan.frame_rate,
            )
            return None
        expected = context_fingerprint(seg, plan, settings)
        stored = metadata.get("fingerprint")
        if stored != expected:
            log.info(
                "first-pass cache miss for segment %d: fingerprint mismatch",
                slot + 1,
            )
            if isinstance(stored, dict) and isinstance(expected, dict):
                for key in sorted(set(stored) | set(expected)):
                    if stored.get(key) != expected.get(key):
                        log.info(
                            "  fingerprint[%s] differs:\n    stored   = %s\n    expected = %s",
                            key, str(stored.get(key))[:220], str(expected.get(key))[:220],
                        )
            else:
                log.info("  stored   = %s", str(stored)[:220])
                log.info("  expected = %s", str(expected)[:220])
            try:
                from .context_identity import generation_environment_identity

                environment = generation_environment_identity(plan, settings)
                log.info(
                    "  current environment = %s",
                    json.dumps(environment, sort_keys=True, default=str),
                )
            except Exception as exc:  # noqa: BLE001
                log.info("  environment dump failed: %s", exc)
            stored_settings = metadata.get("settings_snapshot")
            if isinstance(stored_settings, dict):
                differences = _diff_paths(stored_settings, _json_identity(settings))
                if differences:
                    log.info("  settings drift (stored -> current):")
                    for path, left, right in differences:
                        log.info("    %s:\n      stored   = %s\n      expected = %s", path, left, right)
                else:
                    log.info(
                        "  settings identical; drift is in plan geometry "
                        "(width/height/fps/stride), not settings."
                    )
            return None
        if "samples" not in latent:
            log.info("first-pass cache miss for segment %d: no samples in latent", slot + 1)
            return None
        log.info("first-pass cache HIT for segment %d (%s)", slot + 1, path)
        return latent
    except Exception as exc:
        log.warning(
            "First-pass latent cache read failed for segment %d: %s",
            int(getattr(seg, "timeline_index", seg.index)) + 1,
            exc,
        )
        return None


__all__ = [
    "FIRST_PASS_CACHE_FORMAT",
    "FIRST_PASS_CACHE_VERSION",
    "FIRST_PASS_CACHE_PIPELINE",
    "POSTPROCESS_CACHE_KEYS",
    "build_first_pass_settings",
    "first_pass_device",
    "load_first_pass_latent",
    "replace_first_pass_identity",
    "restore_av_latent",
    "save_first_pass_latent",
]
