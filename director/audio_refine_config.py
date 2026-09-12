"""Room / level post-processing config for Director audio.

Stored as the ``audio_refine`` section of the append-only ``postprocess_config``
STRING widget, alongside ``global_refine`` and ``face_refine``.

Two independent controls exist and they answer different questions:

* ``room`` + the six reverb values describe **where the scene happens**.  A
  per-scene ``room`` field in the timeline overrides it for that segment only,
  so a bathroom scene and a bedroom scene in one render do not share a space.
* ``per_segment`` answers **when the effect runs**.  Off (the default) applies
  the chain once to the finished track at final assembly, which leaves every
  existing segment and audio cache valid.  On, it also runs on each segment as
  it is produced, so per-segment previews carry the room sound -- at the cost of
  joining the segment cache fingerprint, which invalidates earlier caches.
"""

from __future__ import annotations

import math
from typing import Any

from .audio_effects import ROOM_PRESETS

AUDIO_REFINE_VERSION = 1

DEFAULT_AUDIO_REFINE: dict[str, Any] = {
    "version": AUDIO_REFINE_VERSION,
    "enabled": False,
    "per_segment": False,
    "room": "",
    "reverb_enabled": True,
    "reverberance": 40.0,
    "hf_damping": 55.0,
    "room_scale": 45.0,
    "stereo_depth": 70.0,
    "pre_delay_ms": 12.0,
    "wet_gain_db": -2.0,
    "normalize": False,
    "gain_db": 0.0,
    "use_limiter": True,
    "sox_path": "",
}


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off", ""}:
            return False
    if value is None:
        return default
    return bool(value)


def _float(value: Any, default: float, low: float, high: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if not math.isfinite(parsed):
        parsed = default
    return max(low, min(high, parsed))


def normalize_room_name(value: Any) -> str:
    """Return a known preset key, or ``""`` meaning "use the explicit values"."""
    key = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    return key if key in ROOM_PRESETS else ""


def normalize_audio_refine(raw: Any) -> dict[str, Any]:
    """Parse and bound the ``audio_refine`` section, tolerating legacy/partial input."""
    if not isinstance(raw, dict):
        raw = {}

    return {
        "version": AUDIO_REFINE_VERSION,
        "enabled": _bool(raw.get("enabled"), False),
        "per_segment": _bool(raw.get("per_segment", raw.get("perSegment")), False),
        "room": normalize_room_name(raw.get("room")),
        "reverb_enabled": _bool(raw.get("reverb_enabled", raw.get("reverbEnabled")), True),
        "reverberance": _float(raw.get("reverberance"), 40.0, 0.0, 100.0),
        "hf_damping": _float(raw.get("hf_damping", raw.get("hfDamping")), 55.0, 0.0, 100.0),
        "room_scale": _float(raw.get("room_scale", raw.get("roomScale")), 45.0, 0.0, 100.0),
        "stereo_depth": _float(
            raw.get("stereo_depth", raw.get("stereoDepth")), 70.0, 0.0, 100.0
        ),
        "pre_delay_ms": _float(raw.get("pre_delay_ms", raw.get("preDelayMs")), 12.0, 0.0, 500.0),
        "wet_gain_db": _float(raw.get("wet_gain_db", raw.get("wetGainDb")), -2.0, -10.0, 10.0),
        "normalize": _bool(raw.get("normalize"), False),
        "gain_db": _float(raw.get("gain_db", raw.get("gainDb")), 0.0, -20.0, 20.0),
        "use_limiter": _bool(raw.get("use_limiter", raw.get("useLimiter")), True),
        "sox_path": str(raw.get("sox_path") or raw.get("soxPath") or "").strip()[:2048],
    }


def audio_refine_is_active(config: Any) -> bool:
    """True when the config would actually change the audio."""
    if not isinstance(config, dict) or not config.get("enabled"):
        return False
    if config.get("reverb_enabled", True):
        if normalize_room_name(config.get("room")):
            return True
        if _float(config.get("reverberance"), 0.0, 0.0, 100.0) > 0.0 and _float(
            config.get("room_scale"), 0.0, 0.0, 100.0
        ) > 0.0:
            return True
    if _bool(config.get("normalize")):
        return True
    return abs(_float(config.get("gain_db"), 0.0, -20.0, 20.0)) >= 0.01


def audio_refine_fingerprint(config: Any) -> dict[str, Any] | bool:
    """Cache identity for per-segment audio post-processing.

    Returns ``False`` when the chain runs only at final assembly, because then it
    produces no per-segment artefact and must not invalidate segment caches.
    """
    normalized = normalize_audio_refine(config)
    if not normalized["enabled"] or not normalized["per_segment"]:
        return False
    if not audio_refine_is_active(normalized):
        return False
    return normalized


__all__ = [
    "AUDIO_REFINE_VERSION",
    "DEFAULT_AUDIO_REFINE",
    "audio_refine_fingerprint",
    "audio_refine_is_active",
    "normalize_audio_refine",
    "normalize_room_name",
]
