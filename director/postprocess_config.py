"""v11 postprocess compatibility facade.

The v9 implementation is preserved verbatim in ``postprocess_config_legacy``.
This facade keeps its public API stable while making Face Refine part of the
final segment/cache identity, and adding the ``audio_refine`` room/level
section.

``audio_refine`` never joins the segment cache fingerprint.  Room simulation is
applied once at final output assembly, so it produces no per-segment artefact
and turning it on must NOT invalidate existing segment or context caches.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from . import postprocess_config_legacy as _legacy
from .audio_refine_config import (
    DEFAULT_AUDIO_REFINE,
    normalize_audio_refine,
)
from .postprocess_config_legacy import *  # noqa: F401,F403

POSTPROCESS_CONFIG_VERSION = 11
DEFAULT_POSTPROCESS_CONFIG = copy.deepcopy(_legacy.DEFAULT_POSTPROCESS_CONFIG)
DEFAULT_POSTPROCESS_CONFIG["version"] = POSTPROCESS_CONFIG_VERSION
DEFAULT_POSTPROCESS_CONFIG["audio_refine"] = copy.deepcopy(DEFAULT_AUDIO_REFINE)


def _raw_section(raw: Any, *keys: str) -> Any:
    """Pull one section out of a config that may still be a JSON string."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            raw = {}
    if not isinstance(raw, dict):
        return None
    for key in keys:
        value = raw.get(key)
        if value is not None:
            return value
    return None


def normalize_postprocess_config(raw: Any) -> dict[str, Any]:
    result = _legacy.normalize_postprocess_config(raw)
    result["audio_refine"] = normalize_audio_refine(
        _raw_section(raw, "audio_refine", "audioRefine")
    )
    result["version"] = POSTPROCESS_CONFIG_VERSION
    return result


def serialize_postprocess_config(raw: Any) -> str:
    return json.dumps(
        normalize_postprocess_config(raw),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def postprocess_cache_fingerprint(config: dict[str, Any]) -> dict[str, Any]:
    """Return the pixel/latent-producing postprocess identity.

    Face Refine now runs before segment/cache finalization on normal Motion
    Context chains, so its settings must invalidate stale segment/context
    caches. Result previews and the raw-vs-processed comparison export remain
    UI-only (they do not change the produced frames) and are deliberately
    excluded.

    Audio room simulation is deliberately excluded.  It is applied at final
    output assembly, after every segment cache has been written, so no room
    setting can change a per-segment artefact.
    """
    normalized = normalize_postprocess_config(config)
    global_refine = dict(normalized["global_refine"])
    face_refine = dict(normalized["face_refine"])
    global_refine.pop("result_previews_enabled", None)
    global_refine.pop("export_comparison", None)
    return {
        "global_refine": global_refine if global_refine["enabled"] else False,
        "face_refine": face_refine if face_refine["enabled"] else False,
        "audio_refine": False,
    }


def __getattr__(name: str):
    return getattr(_legacy, name)


__all__ = list(_legacy.__all__)
for _name in (
    "DEFAULT_POSTPROCESS_CONFIG",
    "POSTPROCESS_CONFIG_VERSION",
    "normalize_postprocess_config",
    "serialize_postprocess_config",
    "postprocess_cache_fingerprint",
    "DEFAULT_AUDIO_REFINE",
    "normalize_audio_refine",
):
    if _name not in __all__:
        __all__.append(_name)
