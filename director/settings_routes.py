# MiniMax H3 Motion Director - app-wide settings, cache manager and diagnostics routes.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""HTTP surface for the Setup panel: settings, machine profile, cache, diagnostics.

Reads are cheap and side-effect free. The two writes are deliberately explicit:

* ``PATCH /settings`` changes app-wide settings (never a project);
* ``POST /cache_clear`` deletes segment/context caches, so it refuses while a run
  looks active and requires the caller to name exactly which cache it means.

Diagnostics gather only facts the pack already knows - versions, the detected
machine, the stored settings and cache totals - so a bug report can be a single
JSON blob instead of a screenshot of a console.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

from aiohttp import web

import folder_paths

from ..lib.machine_profile import collect_machine_profile
from .motion_settings import (
    MotionSettingsError,
    STORE,
    default_settings,
    settings_path,
)
from .video_metadata import resolve as resolve_embed_metadata
from .video_metadata import resolve_output_file, strip_file

# Cache roots the pack writes under the ComfyUI output directory.
CACHE_KINDS: tuple[tuple[str, str, str], ...] = (
    ("segments", "minimax_seg_cache", "Segment caches (frames, audio, run manifest)"),
    ("motion_context", "minimax_motion_context_cache", "Motion context and AV latent caches"),
    ("first_pass", "minimax_first_pass_cache", "First-pass latent caches"),
)

# A manifest that says "running" is only trusted while it is fresh: a crashed run
# leaves the flag behind, and refusing to clean a cache forever because of it would
# be worse than the tiny window this protects.
RUN_ACTIVE_WINDOW_SECONDS = 30 * 60

_ERROR_STATUS = {
    "not found": 404,
    "unknown cache": 400,
    "unknown": 400,
    "required": 400,
    "active": 409,
}


def _json_error(message: str, status: int = 400) -> web.Response:
    return web.json_response({"error": str(message)}, status=status)


def _status_for(exc: Exception) -> int:
    text = str(exc).lower()
    for key, status in _ERROR_STATUS.items():
        if key in text:
            return status
    return 400


def _route(routes, method: str, path: str, handler) -> None:
    add_route = getattr(routes, "add_route", None)
    if callable(add_route):
        routes.add_route(method, path, handler)
        return
    getattr(routes, method.lower())(path)(handler)


async def _read_json(request) -> dict:
    try:
        body = await request.json()
    except Exception as exc:
        raise MotionSettingsError(f"Invalid JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise MotionSettingsError("JSON body must be an object.")
    return body


# ---------------------------------------------------------------------------
# Settings + machine
# ---------------------------------------------------------------------------


def _machine(settings: dict[str, Any], *, refresh: bool = False) -> dict[str, Any]:
    machine_settings = settings.get("machine") or {}
    return collect_machine_profile(
        refresh=refresh,
        device_index=int(machine_settings.get("device_index") or 0),
        vram_gb_override=float(machine_settings.get("vram_gb_override") or 0.0) or None,
    )


def _settings_payload(settings: dict[str, Any], machine: dict[str, Any]) -> dict[str, Any]:
    app_policy = (settings.get("export") or {}).get("embed_workflow")
    return {
        "settings": settings,
        "machine": machine,
        "detected_baselines": machine.get("baselines") or {},
        "defaults": default_settings(machine),
        "export_state": resolve_embed_metadata(None, app_policy=app_policy),
        "path": str(settings_path()),
    }


async def minimax_settings_get(request):
    try:
        machine = _machine_without_settings()
        settings = STORE.load(machine=machine)
        return web.json_response(_settings_payload(settings, machine))
    except MotionSettingsError as exc:
        return _json_error(str(exc), 500)
    except Exception as exc:  # pragma: no cover - defensive
        return _json_error(f"Settings load failed: {exc}", 500)


def _machine_without_settings() -> dict[str, Any]:
    """Detect with defaults, so the very first load already knows the GPU."""
    return collect_machine_profile()


async def minimax_settings_patch(request):
    try:
        body = await _read_json(request)
        machine = _machine_without_settings()
        reset_baselines = bool(body.get("reset_baselines"))
        patch = body.get("settings")
        if patch is None and not reset_baselines:
            raise MotionSettingsError("Provide 'settings', 'reset_baselines', or both.")
        settings = STORE.save(patch, machine=machine, reset_baselines=reset_baselines)
        return web.json_response(_settings_payload(settings, machine))
    except MotionSettingsError as exc:
        return _json_error(str(exc), _status_for(exc))
    except Exception as exc:  # pragma: no cover - defensive
        return _json_error(f"Settings save failed: {exc}", 500)


async def minimax_machine_get(request):
    try:
        settings = STORE.load()
        refresh = str(request.query.get("refresh") or "").strip() not in {"", "0", "false"}
        machine = _machine(settings, refresh=refresh)
        return web.json_response({"machine": machine, "settings": settings})
    except MotionSettingsError as exc:
        return _json_error(str(exc), 500)


# ---------------------------------------------------------------------------
# Cache manager
# ---------------------------------------------------------------------------


def _directory_size(root: Path) -> tuple[int, int]:
    """(bytes, files) for a directory tree, skipping symlinks."""
    total = 0
    files = 0
    try:
        stack = [root]
        while stack:
            current = stack.pop()
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                            files += 1
                    except OSError:
                        continue
    except OSError:
        return total, files
    return total, files


def _segment_count(node_dir: Path) -> int:
    try:
        return sum(1 for _ in node_dir.glob("seg_*.meta.json"))
    except OSError:
        return 0


def _manifest_state(node_dir: Path) -> dict[str, Any]:
    path = node_dir / "run_manifest.json"
    if not path.is_file():
        return {"state": "none", "done": 0, "segment_total": 0, "updated": 0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"state": "unreadable", "done": 0, "segment_total": 0, "updated": 0, "error": str(exc)}
    done = data.get("done") if isinstance(data.get("done"), dict) else {}
    return {
        "state": str(data.get("state") or "idle"),
        "done": len(done),
        "segment_total": int(data.get("segment_total") or 0),
        "updated": int(data.get("updated") or 0),
    }


def _cache_kind_root(name: str) -> Path:
    return Path(folder_paths.get_output_directory()) / name


def _cache_root_for(kind: str) -> tuple[str, str, Path]:
    for cache_id, dirname, label in CACHE_KINDS:
        if cache_id == kind:
            return cache_id, label, _cache_kind_root(dirname)
    raise MotionSettingsError(f"Unknown cache kind: {kind!r}")


def _node_rows(kind_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not kind_root.is_dir():
        return rows
    for entry in sorted(kind_root.iterdir(), key=lambda item: item.name.lower()):
        try:
            if entry.is_symlink() or not entry.is_dir():
                continue
        except OSError:
            continue
        size, files = _directory_size(entry)
        state = _manifest_state(entry)
        try:
            updated_ms = int(entry.stat().st_mtime * 1000)
        except OSError:
            updated_ms = 0
        rows.append(
            {
                "node": entry.name,
                "bytes": int(size),
                "files": int(files),
                "segments": _segment_count(entry),
                "updated_ms": updated_ms,
                **state,
            }
        )
    rows.sort(key=lambda row: int(row.get("bytes") or 0), reverse=True)
    return rows


def cache_report() -> dict[str, Any]:
    """Every cache the pack owns, with the sizes the Setup panel shows."""
    output_dir = Path(folder_paths.get_output_directory())
    kinds: list[dict[str, Any]] = []
    total_bytes = 0
    for cache_id, dirname, label in CACHE_KINDS:
        root = output_dir / dirname
        size, files = _directory_size(root) if root.is_dir() else (0, 0)
        rows = _node_rows(root)
        total_bytes += size
        kinds.append(
            {
                "id": cache_id,
                "label": label,
                "path": str(root),
                "exists": root.is_dir(),
                "bytes": int(size),
                "files": int(files),
                "nodes": rows,
            }
        )
    disk = {}
    try:
        usage = shutil.disk_usage(output_dir if output_dir.is_dir() else output_dir.parent)
        disk = {
            "total_gb": round(usage.total / (1024**3), 1),
            "free_gb": round(usage.free / (1024**3), 1),
        }
    except OSError:
        disk = {}
    return {
        "output_dir": str(output_dir),
        "disk": disk,
        "kinds": kinds,
        "total_bytes": int(total_bytes),
        "total_gb": round(total_bytes / (1024**3), 2),
        "generated_at": int(time.time() * 1000),
    }


async def minimax_cache_report(_request):
    try:
        settings = STORE.load()
        report = cache_report()
        report["warn_over_gb"] = float((settings.get("cache") or {}).get("warn_over_gb") or 0.0)
        return web.json_response(report)
    except Exception as exc:  # pragma: no cover - defensive
        return _json_error(f"Cache report failed: {exc}", 500)


def _run_is_active(kind_root: Path, node: str | None) -> tuple[bool, str]:
    now = time.time()
    candidates = [kind_root / node] if node else [entry for entry in kind_root.glob("*") if entry.is_dir()]
    for entry in candidates:
        state = _manifest_state(entry)
        if state.get("state") != "running":
            continue
        updated = int(state.get("updated") or 0)
        if updated and (now - updated) <= RUN_ACTIVE_WINDOW_SECONDS:
            return True, entry.name
    return False, ""


def _assert_inside(root: Path, candidate: Path) -> Path:
    root_resolved = root.resolve()
    candidate_resolved = candidate.resolve()
    try:
        candidate_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise MotionSettingsError("Unsafe cache path.") from exc
    return candidate_resolved


def clear_cache(*, kind: str, node: str | None = None, all_nodes: bool = False) -> dict[str, Any]:
    """Delete one node's cache, or every node's, inside one cache kind."""
    cache_id, label, kind_root = _cache_root_for(kind)
    if not kind_root.is_dir():
        return {"kind": cache_id, "removed": [], "bytes": 0, "note": "nothing to clear"}
    node_name = str(node or "").strip()
    if not all_nodes and not node_name:
        raise MotionSettingsError("A cache node name is required (or set all_nodes).")
    if node_name and ("/" in node_name or "\\" in node_name or node_name in {".", ".."}):
        raise MotionSettingsError("Invalid cache node name.")

    active, active_node = _run_is_active(kind_root, node_name or None)
    if active:
        raise MotionSettingsError(
            f"Cache is active: node {active_node!r} has a running render. "
            "Stop it (or wait for it to finish) before clearing caches."
        )

    targets: list[Path] = []
    if all_nodes:
        for entry in sorted(kind_root.glob("*")):
            if entry.is_dir() and not entry.is_symlink():
                targets.append(entry)
    else:
        candidate = kind_root / node_name
        if not candidate.is_dir():
            raise MotionSettingsError("Cache not found.")
        targets.append(candidate)

    removed: list[str] = []
    freed = 0
    for target in targets:
        safe = _assert_inside(kind_root, target)
        size, _files = _directory_size(safe)
        try:
            shutil.rmtree(safe)
        except OSError as exc:
            raise MotionSettingsError(f"Could not remove {safe.name}: {exc}") from exc
        removed.append(safe.name)
        freed += size
    return {
        "kind": cache_id,
        "label": label,
        "removed": removed,
        "bytes": int(freed),
        "gb": round(freed / (1024**3), 2),
    }


async def minimax_cache_clear(request):
    try:
        body = await _read_json(request)
        result = clear_cache(
            kind=str(body.get("kind") or ""),
            node=body.get("node"),
            all_nodes=bool(body.get("all")),
        )
        return web.json_response(result)
    except MotionSettingsError as exc:
        return _json_error(str(exc), _status_for(exc))
    except Exception as exc:  # pragma: no cover - defensive
        return _json_error(f"Cache clear failed: {exc}", 500)


async def minimax_strip_metadata(request):
    """Remove the workflow/prompt tags from an already saved video (ffmpeg remux)."""
    try:
        body = await _read_json(request)
        path = resolve_output_file(
            body.get("filename") or body.get("path"),
            subfolder=body.get("subfolder"),
            kind=str(body.get("type") or "output"),
        )
        return web.json_response(strip_file(path))
    except FileNotFoundError as exc:
        return _json_error(str(exc), 404)
    except MotionSettingsError as exc:
        return _json_error(str(exc), _status_for(exc))
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except Exception as exc:  # pragma: no cover - defensive
        return _json_error(f"Metadata strip failed: {exc}", 500)


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def diagnostics_bundle() -> dict[str, Any]:
    """One JSON blob with everything worth attaching to a bug report."""
    settings = STORE.load()
    machine = _machine(settings)
    report = cache_report()
    runs: list[dict[str, Any]] = []
    for kind in report["kinds"]:
        for row in kind["nodes"]:
            runs.append(
                {
                    "cache": kind["id"],
                    "node": row["node"],
                    "segments": row["segments"],
                    "state": row["state"],
                    "done": row["done"],
                    "segment_total": row["segment_total"],
                    "updated": row["updated"],
                }
            )
    return {
        "generated_at": int(time.time() * 1000),
        "pack": {
            "version": machine.get("pack_version"),
            "comfyui": machine.get("comfyui_version"),
            "python": machine.get("python_version"),
            "torch": machine.get("torch_version"),
            "cuda": machine.get("cuda_version"),
            "platform": machine.get("platform"),
        },
        "machine": machine,
        "settings": settings,
        "settings_path": str(settings_path()),
        "cache": {
            "total_gb": report["total_gb"],
            "disk": report["disk"],
            "kinds": [
                {
                    "id": kind["id"],
                    "path": kind["path"],
                    "bytes": kind["bytes"],
                    "files": kind["files"],
                    "nodes": len(kind["nodes"]),
                }
                for kind in report["kinds"]
            ],
        },
        "runs": runs,
    }


async def minimax_diagnostics(request):
    try:
        return web.json_response(diagnostics_bundle())
    except Exception as exc:  # pragma: no cover - defensive
        return _json_error(f"Diagnostics failed: {exc}", 500)


def register_motion_settings_routes(routes) -> None:
    base = "/minimax/motion-director"
    _route(routes, "GET", base + "/settings", minimax_settings_get)
    _route(routes, "PATCH", base + "/settings", minimax_settings_patch)
    _route(routes, "POST", base + "/settings", minimax_settings_patch)
    _route(routes, "GET", base + "/machine", minimax_machine_get)
    _route(routes, "GET", base + "/cache_report", minimax_cache_report)
    _route(routes, "POST", base + "/cache_clear", minimax_cache_clear)
    _route(routes, "POST", base + "/strip_metadata", minimax_strip_metadata)
    _route(routes, "GET", base + "/diagnostics", minimax_diagnostics)


__all__ = [
    "CACHE_KINDS",
    "cache_report",
    "clear_cache",
    "diagnostics_bundle",
    "register_motion_settings_routes",
]