# MiniMax H3 Motion Director - app-wide settings (machine profile, baselines, cache).
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""App-wide settings for the whole pack, stored once per ComfyUI user.

Why this exists next to the per-workflow widgets: a *baseline* is a property of the
machine, not of a project. Resolution and segment length decide how much VRAM a
render needs, so the same project wants different starting points on a 12 GB card
and a 32 GB one - and a value baked into every saved workflow cannot move between
two machines.

The store follows the Director preset store: one JSON document under ComfyUI's user
directory, written atomically, the browser never touches the file. The baselines are
always stored *explicitly* (seeded from the detected tier on first run and by an
explicit reset), so nothing silently changes under a project when the GPU changes.

Nothing here reads or writes a project. Applying a baseline is an explicit action in
the panel, because changing width/height or segment length invalidates segment
caches and the run manifest's Done marks.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import folder_paths

from ..lib.machine_profile import TIER_IDS
from .video_metadata import EMBED_CHOICES

SCHEMA_VERSION = 1

_SETTINGS_DIRNAME = "minimax_h3_motion_director"
_SETTINGS_FILENAME = "settings.json"

# Mirrors RESOLUTION_ASPECTS in web/js/minimax_gen_timeline.js. Stored locale-free
# (the UI owns the labels) so the file stays readable in any language.
ASPECT_RATIOS: tuple[str, ...] = ("1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9")
DEFAULT_ASPECT_RATIO = "16:9"
EXPORT_MODES: tuple[str, ...] = ("all", "segments")
LOCALES: tuple[str, ...] = ("auto", "zh", "en")
PROFILE_AUTO = "auto"
PROFILE_CUSTOM = "custom"

CANVAS_MULTIPLE = 32
MIN_FRAMES = 5
MAX_FRAMES = 512
FRAME_GRID_MODULUS = 17
FRAME_GRID_REMAINDER = 5

MIN_MEGAPIXELS = 0.1
MAX_MEGAPIXELS = 16.0
MIN_DIMENSION = 32
MAX_DIMENSION = 8192
MAX_REF_SIZE = 4096


class MotionSettingsError(ValueError):
    """Anything the caller can fix: bad field, unreadable file, bad patch."""


# ---------------------------------------------------------------------------
# Grid helpers (H3 rules, kept here so the numbers in this file stay valid)
# ---------------------------------------------------------------------------


def align_frames(value: Any, *, fallback: int = 124) -> int:
    """Snap a frame count to the H3 grid (17k+5) inside the model's range."""
    try:
        frames = int(value)
    except (TypeError, ValueError):
        frames = int(fallback)
    frames = max(MIN_FRAMES, min(MAX_FRAMES, frames))
    while frames <= MAX_FRAMES and (frames - FRAME_GRID_REMAINDER) % FRAME_GRID_MODULUS != 0:
        frames += 1
    if frames > MAX_FRAMES:  # 498 is the largest 17k+5 value <= 512
        frames = MAX_FRAMES - ((MAX_FRAMES - FRAME_GRID_REMAINDER) % FRAME_GRID_MODULUS)
    return frames


def snap_dimension(value: Any, *, fallback: int = 0) -> int:
    """Snap a pixel dimension to the H3 canvas multiple (0 means "derive it")."""
    try:
        pixels = int(value)
    except (TypeError, ValueError):
        return int(fallback)
    if pixels <= 0:
        return 0
    pixels = max(MIN_DIMENSION, min(MAX_DIMENSION, pixels))
    return int(round(pixels / CANVAS_MULTIPLE)) * CANVAS_MULTIPLE


def _bounded_float(value: Any, *, low: float, high: float, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    if number != number:  # NaN
        return float(fallback)
    return float(min(high, max(low, number)))


def _bounded_int(value: Any, *, low: int, high: int, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return int(fallback)
    return int(min(high, max(low, number)))


def _flag(value: Any, *, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return bool(fallback)


def _choice(value: Any, options: tuple[str, ...], *, fallback: str) -> str:
    text = str(value or "").strip()
    return text if text in options else fallback


# ---------------------------------------------------------------------------
# Defaults + validation
# ---------------------------------------------------------------------------


def default_settings(machine: dict[str, Any] | None = None) -> dict[str, Any]:
    """Defaults for a fresh install, seeded from the detected machine profile."""
    tier_baselines = dict((machine or {}).get("baselines") or {}) if machine else {}
    tier = {
        "megapixels": 1.0,
        "width": 1344,
        "height": 768,
        "segment_frames": 243,
        "max_segment_frames": 362,
        "ref_max_size": 1024,
    }
    tier.update({key: value for key, value in tier_baselines.items() if value is not None})
    return {
        "schema_version": SCHEMA_VERSION,
        "machine": {
            "profile": PROFILE_AUTO,
            "device_index": 0,
            "vram_gb_override": 0.0,
        },
        "baselines": {
            "aspect_ratio": DEFAULT_ASPECT_RATIO,
            "megapixels": tier["megapixels"],
            "width": tier["width"],
            "height": tier["height"],
            "segment_frames": tier["segment_frames"],
            "max_segment_frames": tier["max_segment_frames"],
            "ref_max_size": tier["ref_max_size"],
            "clear_vram_between_segments": True,
            "export_mode": "all",
            "continuity": True,
            "continuity_overlap_frames": 9,
        },
        "run": {
            "auto_save_workflow": True,
            "keep_models_resident": False,
            "verbose_logging": False,
        },
        "app": {
            "locale": "auto",
            "live_tae_preview": True,
            "preview_audio": True,
        },
        "export": {
            # auto/always/never: whether a saved video carries the workflow + prompt
            # tags. See director/video_metadata.py for the precedence rules.
            "embed_workflow": "auto",
        },
        "cache": {
            "warn_over_gb": 80.0,
        },
        "updated_at": 0,
    }


def _normalize_baselines(raw: Any, defaults: dict[str, Any]) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    fallback = defaults["baselines"]
    segment_frames = align_frames(
        data.get("segment_frames", fallback["segment_frames"]),
        fallback=int(fallback["segment_frames"]),
    )
    max_segment_frames = align_frames(
        data.get("max_segment_frames", fallback["max_segment_frames"]),
        fallback=int(fallback["max_segment_frames"]),
    )
    if max_segment_frames < segment_frames:
        max_segment_frames = segment_frames
    return {
        "aspect_ratio": _choice(
            data.get("aspect_ratio"), ASPECT_RATIOS, fallback=str(fallback["aspect_ratio"])
        ),
        "megapixels": round(
            _bounded_float(
                data.get("megapixels", fallback["megapixels"]),
                low=MIN_MEGAPIXELS,
                high=MAX_MEGAPIXELS,
                fallback=float(fallback["megapixels"]),
            ),
            2,
        ),
        "width": snap_dimension(data.get("width", fallback["width"]), fallback=int(fallback["width"])),
        "height": snap_dimension(
            data.get("height", fallback["height"]), fallback=int(fallback["height"])
        ),
        "segment_frames": segment_frames,
        "max_segment_frames": max_segment_frames,
        "ref_max_size": snap_dimension(
            data.get("ref_max_size", fallback["ref_max_size"]), fallback=int(fallback["ref_max_size"])
        ),
        "clear_vram_between_segments": _flag(
            data.get("clear_vram_between_segments", fallback["clear_vram_between_segments"]),
            fallback=bool(fallback["clear_vram_between_segments"]),
        ),
        "export_mode": _choice(
            data.get("export_mode"), EXPORT_MODES, fallback=str(fallback["export_mode"])
        ),
        "continuity": _flag(data.get("continuity", fallback["continuity"]), fallback=True),
        "continuity_overlap_frames": _bounded_int(
            data.get("continuity_overlap_frames", fallback["continuity_overlap_frames"]),
            low=1,
            high=81,
            fallback=int(fallback["continuity_overlap_frames"]),
        ),
    }


def normalize_settings(raw: Any, *, machine: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate and detach a settings document; unknown keys are dropped."""
    if raw is not None and not isinstance(raw, dict):
        raise MotionSettingsError("Settings must be a JSON object.")
    defaults = default_settings(machine)
    data = raw if isinstance(raw, dict) else {}

    machine_raw = data.get("machine") if isinstance(data.get("machine"), dict) else {}
    profile = _choice(
        machine_raw.get("profile"),
        (PROFILE_AUTO, PROFILE_CUSTOM) + tuple(TIER_IDS),
        fallback=PROFILE_AUTO,
    )
    run_raw = data.get("run") if isinstance(data.get("run"), dict) else {}
    app_raw = data.get("app") if isinstance(data.get("app"), dict) else {}
    export_raw = data.get("export") if isinstance(data.get("export"), dict) else {}
    cache_raw = data.get("cache") if isinstance(data.get("cache"), dict) else {}

    updated_at = data.get("updated_at")
    try:
        updated_at_value = int(updated_at or 0)
    except (TypeError, ValueError):
        updated_at_value = 0

    return {
        "schema_version": SCHEMA_VERSION,
        "machine": {
            "profile": profile,
            "device_index": _bounded_int(
                machine_raw.get("device_index"), low=0, high=16, fallback=0
            ),
            "vram_gb_override": round(
                _bounded_float(
                    machine_raw.get("vram_gb_override"), low=0.0, high=1024.0, fallback=0.0
                ),
                2,
            ),
        },
        "baselines": _normalize_baselines(data.get("baselines"), defaults),
        "run": {
            "auto_save_workflow": _flag(
                run_raw.get("auto_save_workflow"), fallback=defaults["run"]["auto_save_workflow"]
            ),
            "keep_models_resident": _flag(
                run_raw.get("keep_models_resident"), fallback=defaults["run"]["keep_models_resident"]
            ),
            "verbose_logging": _flag(
                run_raw.get("verbose_logging"), fallback=defaults["run"]["verbose_logging"]
            ),
        },
        "app": {
            "locale": _choice(app_raw.get("locale"), LOCALES, fallback="auto"),
            "live_tae_preview": _flag(
                app_raw.get("live_tae_preview"), fallback=defaults["app"]["live_tae_preview"]
            ),
            "preview_audio": _flag(
                app_raw.get("preview_audio"), fallback=defaults["app"]["preview_audio"]
            ),
        },
        "export": {
            "embed_workflow": _choice(
                export_raw.get("embed_workflow"),
                EMBED_CHOICES,
                fallback=str(defaults["export"]["embed_workflow"]),
            ),
        },
        "cache": {
            "warn_over_gb": round(
                _bounded_float(cache_raw.get("warn_over_gb"), low=0.0, high=10000.0, fallback=80.0),
                1,
            ),
        },
        "updated_at": updated_at_value,
    }


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = json.loads(json.dumps(base))
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def _user_directory() -> Path:
    getter = getattr(folder_paths, "get_user_directory", None)
    if callable(getter):
        try:
            value = getter()
            if value:
                return Path(value)
        except Exception:
            pass
    value = getattr(folder_paths, "user_directory", None)
    if value:
        return Path(value)
    base = getattr(folder_paths, "base_path", None)
    return Path(base or os.getcwd()) / "user"


def settings_root() -> Path:
    return _user_directory() / _SETTINGS_DIRNAME


def settings_path() -> Path:
    return settings_root() / _SETTINGS_FILENAME


class MotionSettingsStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()

    def ensure_dir(self) -> None:
        settings_root().mkdir(parents=True, exist_ok=True)

    def _read_unlocked(self) -> dict[str, Any] | None:
        path = settings_path()
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            # Loud rather than self-healing: starting from defaults would let the
            # next save erase every stored preference.
            raise MotionSettingsError(
                f"Settings file is unreadable ({path}): {exc}. "
                "Fix or remove that file, then reopen the node."
            ) from exc
        if not isinstance(data, dict):
            raise MotionSettingsError(f"Settings file has invalid root data ({path}).")
        return data

    def _write_unlocked(self, settings: dict[str, Any]) -> None:
        self.ensure_dir()
        path = settings_path()
        payload = json.dumps(settings, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
        temp = path.with_suffix(".json.tmp")
        temp.write_text(payload, encoding="utf-8")
        os.replace(temp, path)

    def load(self, *, machine: dict[str, Any] | None = None) -> dict[str, Any]:
        """Stored settings, filled in from ``default_settings(machine)``."""
        with self._lock:
            stored = self._read_unlocked()
        defaults = default_settings(machine)
        merged = _deep_merge(defaults, stored or {})
        return normalize_settings(merged, machine=machine)

    def save(
        self,
        patch: Any,
        *,
        machine: dict[str, Any] | None = None,
        reset_baselines: bool = False,
    ) -> dict[str, Any]:
        """Deep-merge a patch into the stored document and write it back."""
        if patch is not None and not isinstance(patch, dict):
            raise MotionSettingsError("Settings patch must be a JSON object.")
        with self._lock:
            current = self.load(machine=machine)
            merged = _deep_merge(current, patch or {})
            if reset_baselines:
                merged["baselines"] = default_settings(machine)["baselines"]
                merged["machine"] = dict(merged.get("machine") or {})
                merged["machine"]["profile"] = PROFILE_AUTO
            merged["updated_at"] = int(time.time() * 1000)
            settings = normalize_settings(merged, machine=machine)
            self._write_unlocked(settings)
            return settings


STORE = MotionSettingsStore()

__all__ = [
    "ASPECT_RATIOS",
    "EXPORT_MODES",
    "LOCALES",
    "MotionSettingsError",
    "MotionSettingsStore",
    "PROFILE_AUTO",
    "PROFILE_CUSTOM",
    "SCHEMA_VERSION",
    "STORE",
    "align_frames",
    "default_settings",
    "normalize_settings",
    "settings_path",
    "settings_root",
    "snap_dimension",
]
