# MiniMax H3 Motion Director — named Director presets (settings templates).
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Named presets for the Motion Director node.

A preset captures the *reusable* part of a project: the sampling, continuity and
output widget groups plus the shared reference block (``r2vCommon``). It
deliberately does NOT capture segments or prompts - those are the project, not the
setup, and a preset that silently rewrote someone's shot breakdown would be worse
than no preset at all.

Everything lives in a single JSON index under ComfyUI's user directory, written
atomically, mirroring the Material Library it sits next to. The store is the only
writer; the browser never touches the file. Because there are no per-preset files,
a preset id is only ever a dict key - there is no path to traverse.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import folder_paths

SCHEMA_VERSION = 1

_PRESET_DIRNAME = "minimax_h3_motion_director"
_PRESET_SUBDIR = "director_presets"
_INDEX_FILENAME = "presets.json"

# Ids are generated here and never accepted from the client; they stay alphanumeric
# so nothing id-shaped can ever be mistaken for a path component.
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_NAME_MAX = 80
_DESCRIPTION_MAX = 400
# A preset is a settings blob, not media. Generous for a widget group, small enough
# that a runaway client cannot quietly fill the user directory.
_PAYLOAD_MAX_BYTES = 256 * 1024
_MAX_PRESETS = 500


class DirectorPresetError(ValueError):
    """Anything the caller can fix: bad name, unknown id, oversized payload."""


def _now_ms() -> int:
    return int(time.time() * 1000)


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


def presets_root() -> Path:
    return _user_directory() / _PRESET_DIRNAME / _PRESET_SUBDIR


def presets_index_path() -> Path:
    return presets_root() / _INDEX_FILENAME


def _resolve_under(root: Path, candidate: Path) -> Path:
    """Keep the index inside its root even if the root is a symlink to elsewhere."""
    root_resolved = root.resolve()
    candidate_resolved = candidate.resolve()
    try:
        candidate_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise DirectorPresetError("Unsafe preset path.") from exc
    return candidate_resolved


def _normalize_name(value: Any, fallback: str = "") -> str:
    name = str(value or "").replace("\x00", "").strip()
    if not name:
        name = fallback
    if not name:
        raise DirectorPresetError("Preset name is required.")
    return name[:_NAME_MAX]


def _normalize_description(value: Any) -> str:
    return str(value or "").replace("\x00", "").strip()[:_DESCRIPTION_MAX]


def _normalize_preset_id(value: Any) -> str:
    preset_id = str(value or "").strip()
    if not _SAFE_ID.match(preset_id):
        raise DirectorPresetError("Invalid preset id.")
    return preset_id


def _new_preset_id() -> str:
    return uuid.uuid4().hex[:16]


def _normalize_payload(value: Any) -> dict[str, Any]:
    """Validate and detach a preset payload.

    Round-tripping through JSON means only plain data is ever stored: no NaN or
    Infinity (which are not valid JSON and would corrupt the file), no tuples, and
    no shared references that could let a caller mutate stored state afterwards.
    """
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise DirectorPresetError("Preset payload must be a JSON object.")
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise DirectorPresetError(f"Preset payload is not JSON-serializable: {exc}") from exc
    if len(encoded.encode("utf-8")) > _PAYLOAD_MAX_BYTES:
        raise DirectorPresetError(
            f"Preset payload is too large ({len(encoded)} bytes; limit {_PAYLOAD_MAX_BYTES})."
        )
    return json.loads(encoded)


def _default_document() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "presets": []}


class DirectorPresetStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()

    def ensure_dirs(self) -> None:
        presets_root().mkdir(parents=True, exist_ok=True)

    def _load_unlocked(self) -> dict[str, Any]:
        self.ensure_dirs()
        path = _resolve_under(presets_root(), presets_index_path())
        if not path.is_file():
            return _default_document()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            # Deliberately loud rather than self-healing: silently starting from an
            # empty document would let the next save erase every stored preset.
            raise DirectorPresetError(
                f"Preset index is unreadable ({path}): {exc}. "
                "Fix or remove that file, then reopen the node."
            ) from exc
        if not isinstance(data, dict):
            raise DirectorPresetError(f"Preset index has invalid root data ({path}).")
        presets = data.get("presets")
        if not isinstance(presets, list):
            raise DirectorPresetError(f"Preset index has invalid presets data ({path}).")
        return {"schema_version": SCHEMA_VERSION, "presets": [p for p in presets if isinstance(p, dict)]}

    def _save_unlocked(self, data: dict[str, Any]) -> None:
        self.ensure_dirs()
        path = _resolve_under(presets_root(), presets_index_path())
        temp = path.with_suffix(".json.tmp")
        payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
        temp.write_text(payload, encoding="utf-8")
        os.replace(temp, path)

    @staticmethod
    def _summary(record: dict[str, Any]) -> dict[str, Any]:
        """List view: metadata only, so a list of 200 presets stays small."""
        return {
            "id": record.get("id"),
            "name": record.get("name"),
            "description": record.get("description", ""),
            "created_at": record.get("created_at", 0),
            "updated_at": record.get("updated_at", 0),
        }

    @staticmethod
    def _public(record: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": record.get("id"),
            "name": record.get("name"),
            "description": record.get("description", ""),
            "created_at": record.get("created_at", 0),
            "updated_at": record.get("updated_at", 0),
            "payload": record.get("payload") or {},
        }

    def _find(self, data: dict[str, Any], preset_id: str) -> dict[str, Any]:
        for record in data["presets"]:
            if record.get("id") == preset_id:
                return record
        raise DirectorPresetError("Preset not found.")

    def list_presets(self) -> list[dict[str, Any]]:
        with self._lock:
            data = self._load_unlocked()
            return [self._summary(record) for record in data["presets"]]

    def get_preset(self, preset_id: Any) -> dict[str, Any]:
        safe_id = _normalize_preset_id(preset_id)
        with self._lock:
            return self._public(self._find(self._load_unlocked(), safe_id))

    def save_preset(self, *, name: Any, payload: Any = None, description: Any = "") -> dict[str, Any]:
        safe_name = _normalize_name(name)
        safe_payload = _normalize_payload(payload)
        safe_description = _normalize_description(description)
        now = _now_ms()
        with self._lock:
            data = self._load_unlocked()
            if len(data["presets"]) >= _MAX_PRESETS:
                raise DirectorPresetError(
                    f"Preset limit reached ({_MAX_PRESETS}). Delete a preset before adding another."
                )
            record = {
                "id": _new_preset_id(),
                "name": safe_name,
                "description": safe_description,
                "created_at": now,
                "updated_at": now,
                "payload": safe_payload,
            }
            # Newest first, so the picker opens on what was just saved.
            data["presets"].insert(0, record)
            self._save_unlocked(data)
            return self._public(record)

    def update_preset(
        self,
        preset_id: Any,
        *,
        name: Any = None,
        payload: Any = None,
        description: Any = None,
    ) -> dict[str, Any]:
        safe_id = _normalize_preset_id(preset_id)
        with self._lock:
            data = self._load_unlocked()
            record = self._find(data, safe_id)
            # Only fields actually supplied are touched, so renaming cannot wipe a
            # payload and vice versa.
            if name is not None:
                record["name"] = _normalize_name(name, fallback=str(record.get("name") or ""))
            if description is not None:
                record["description"] = _normalize_description(description)
            if payload is not None:
                record["payload"] = _normalize_payload(payload)
            record["updated_at"] = _now_ms()
            self._save_unlocked(data)
            return self._public(record)

    def delete_preset(self, preset_id: Any) -> str:
        safe_id = _normalize_preset_id(preset_id)
        with self._lock:
            data = self._load_unlocked()
            record = self._find(data, safe_id)
            data["presets"] = [p for p in data["presets"] if p is not record]
            self._save_unlocked(data)
            return safe_id


STORE = DirectorPresetStore()

__all__ = [
    "DirectorPresetError",
    "DirectorPresetStore",
    "STORE",
    "presets_index_path",
    "presets_root",
]
