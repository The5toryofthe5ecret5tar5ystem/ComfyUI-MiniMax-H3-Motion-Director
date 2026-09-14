"""Room / level post-processing config for Director audio.

Stored as the ``audio_refine`` section of the append-only ``postprocess_config``
STRING widget, alongside ``global_refine`` and ``face_refine``.

The chain runs once, at final output assembly - never while a segment is being
rendered - so it produces no per-segment artefact and never participates in the
segment cache fingerprint.  Tuning a room or its level is therefore free: every
existing segment, context, and audio cache stays valid.

``room`` + the six reverb values describe **where the scene happens**.  A
per-scene ``room`` field in the timeline overrides it for that segment only, so
a bathroom scene and a bedroom scene in one render do not share a space.
"""

from __future__ import annotations

import math
from typing import Any

from .audio_effects import ROOM_PRESETS

AUDIO_REFINE_VERSION = 1

DEFAULT_AUDIO_REFINE: dict[str, Any] = {
    "version": AUDIO_REFINE_VERSION,
    "enabled": False,
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


__all__ = [
    "AUDIO_REFINE_VERSION",
    "DEFAULT_AUDIO_REFINE",
    "audio_refine_is_active",
    "normalize_audio_refine",
    "normalize_room_name",
]
