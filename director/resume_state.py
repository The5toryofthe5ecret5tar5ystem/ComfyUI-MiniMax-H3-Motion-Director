# Portions derived from ComfyUI_MiniMaxH3_Director
# Copyright AIMixer and contributors
# Originally licensed under Apache License 2.0
# Modified for MiniMax H3 Motion Director, 2026-09-07
# This derivative project is distributed under GPL-3.0.
# See NOTICE and LICENSES/Apache-2.0-AIMixer.txt.

"""Resume / stop bookkeeping for MiniMax H3 Motion Director.

Owns three things, all keyed by ComfyUI node id:

* Graceful-stop requests ("finish the current segment, then stop"): the
  preserved executor checks a per-node flag between segments and, when set,
  raises ComfyUI's standard ``InterruptProcessingException`` so the run is
  cancelled cleanly (not an error) with every finished segment cached.

* The on-disk run manifest (which segments completed and the run state), used
  by the frontend's Resume / Stop / Start-over UI and the HTTP resume-status
  route.  The manifest lives next to the segment caches, is written by the
  engine (never the browser), and therefore survives ComfyUI restarts.

* "Start over" cache clearing (segment caches + manifest + best-effort
  motion/latent context caches).

State intentionally lives on this module (not on ``executor_core_legacy``):
``executor_core`` re-runs the preserved executor through a shallow copy of its
globals, so a plain module-level flag there would not be observed.  Functions
here read/write attributes of THIS module, which every caller shares by module
object, so live state is always visible.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import folder_paths

from .cache_path import cache_node_dir_name, cache_root

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.director.resume")

# Segment cache folder name kept in lock-step with director/segment_cache.py.
SEGMENT_CACHE_NAME = "minimax_seg_cache"
MANIFEST_FILE = "run_manifest.json"

_STOP_REQUESTS: dict[str, bool] = {}

# ---------------------------------------------------------------------------
# Graceful-stop request
# ---------------------------------------------------------------------------


def request_graceful_stop(node_id: Any) -> None:
    """Ask the running executor to finish the current segment, then stop."""
    if node_id is None:
        return
    _STOP_REQUESTS[str(node_id)] = True


def clear_stop_request(node_id: Any) -> None:
    if node_id is None:
        return
    _STOP_REQUESTS.pop(str(node_id), None)


def stop_requested(node_id: Any) -> bool:
    if node_id is None:
        return False
    return bool(_STOP_REQUESTS.get(str(node_id)))


def raise_graceful_stop(node_id: Any) -> None:
    """Consume a stop request and raise ComfyUI's clean interrupt.

    Every finished segment has already been cached by the executor before this
    is called (it is checked between segments), so the partial run can later be
    resumed from the next segment.  Never returns.
    """
    clear_stop_request(node_id)
    mark_run_state(node_id, "stopped")
    try:
        from comfy import model_management

        model_management.interrupt_current_processing(True)
        model_management.throw_exception_if_processing_interrupted()
    except Exception as exc:
        # Never mask the interrupt; re-raise what ComfyUI expects if possible.
        if exc.__class__.__name__ == "InterruptProcessingException":
            raise
        log.warning("Graceful stop raised %r: %s", exc.__class__.__name__, exc)
        raise


# ---------------------------------------------------------------------------
# Manifest (disk, written by the engine)
# ---------------------------------------------------------------------------


def segment_cache_dir(node_id: Any) -> Path | None:
    try:
        return cache_root(
            folder_paths.get_output_directory(),
            SEGMENT_CACHE_NAME,
            node_id,
        )
    except OSError as exc:
        log.warning("Segment cache dir unavailable (%s); resume manifest disabled.", exc)
        return None


def _manifest_path(node_id: Any) -> Path | None:
    root = segment_cache_dir(node_id)
    return root / MANIFEST_FILE if root is not None else None


def _read_manifest(node_id: Any) -> dict[str, Any]:
    path = _manifest_path(node_id)
    if path is None or not path.is_file():
        return {"state": "idle", "updated": 0, "segment_total": 0, "done": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("malformed manifest")
        data.setdefault("state", "idle")
        data.setdefault("updated", 0)
        data.setdefault("segment_total", 0)
        data.setdefault("done", {})
        return data
    except Exception as exc:
        log.warning("Resume manifest unreadable for node %s: %s", node_id, exc)
        return {"state": "idle", "updated": 0, "segment_total": 0, "done": {}}


def _write_manifest(node_id: Any, data: dict[str, Any]) -> None:
    path = _manifest_path(node_id)
    if path is None:
        return
    data["updated"] = int(time.time())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        try:
            os.replace(tmp, path)
        except OSError:
            if path.exists():
                path.unlink()
            os.replace(tmp, path)
    except Exception as exc:
        log.warning("Resume manifest write failed for node %s: %s", node_id, exc)


def begin_run(node_id: Any, segment_total: int, reset_done: bool = True) -> None:
    """Start-of-run bookkeeping. ``reset_done`` is False for a Resume run (the
    previously finished prefix is kept) and True for a fresh Start run."""
    if node_id is None:
        return
    data = _read_manifest(node_id) if not reset_done else {
        "state": "running", "updated": 0, "segment_total": 0, "done": {},
    }
    data["state"] = "running"
    data["segment_total"] = int(segment_total)
    if reset_done:
        data["done"] = {}
    _write_manifest(node_id, data)


def mark_segment_done(node_id: Any, segment_index: int, timeline_index: int) -> None:
    """Best-effort: record one completed segment in the run manifest."""
    if node_id is None:
        return
    try:
        data = _read_manifest(node_id)
        data.setdefault("state", "running")
        data["done"][str(int(timeline_index))] = {
            "index": int(segment_index),
            "timeline_index": int(timeline_index),
            "completed_at": int(time.time()),
        }
        _write_manifest(node_id, data)
    except Exception as exc:
        log.warning("Resume manifest segment-done update failed for node %s: %s", node_id, exc)


def mark_run_state(node_id: Any, state: str) -> None:
    if node_id is None:
        return
    try:
        data = _read_manifest(node_id)
        data["state"] = str(state)
        _write_manifest(node_id, data)
    except Exception as exc:
        log.warning("Resume manifest state update failed for node %s: %s", node_id, exc)


def resume_status(node_id: Any) -> dict[str, Any]:
    """Read the manifest for the frontend Resume UI.

    ``done`` lists 0-based timeline indices in ascending order.  ``next`` is the
    first index NOT marked done (contiguous from 0), or ``segment_total`` when
    everything is done.  ``segment_total`` is the total from the last run.
    """
    if node_id is None:
        return {"state": "idle", "segment_total": 0, "done": [], "next": 0,
                "cached_complete": 0}
    data = _read_manifest(node_id)
    done_map = data.get("done") or {}
    total = int(data.get("segment_total") or 0)
    done = sorted({int(v.get("timeline_index", int(k))) for k, v in done_map.items()})
    done_set = set(done)
    next_index = 0
    while next_index in done_set:
        next_index += 1
    # A Resume reuses the on-disk segment CACHES, not this done list, so the UI
    # must not require a done mark to offer it. A fresh run clears ``done``
    # (begin_run with reset_done=True) and an interrupted one never re-adds it,
    # yet its finished segments stay perfectly reusable - which left Resume
    # permanently greyed out while 31 cache files sat on disk.
    try:
        cached_complete = sum(
            1 for entry in segment_cache_preview(node_id) if entry.get("complete")
        )
    except Exception:  # never let a cache read break the status call
        cached_complete = 0
    return {
        "node_id": str(node_id),
        "state": str(data.get("state") or "idle"),
        "updated": int(data.get("updated") or 0),
        "segment_total": max(0, total),
        "done": done,
        "next": min(max(0, next_index), max(0, total)),
        "cached_complete": int(cached_complete),
    }


def _clear_dir_best_effort(root: Path | None) -> None:
    """Remove every child of a cache dir without aborting on RO mounts."""
    if root is None or not root.exists():
        return
    try:
        for child in list(root.iterdir()):
            try:
                if child.is_dir() and not child.is_symlink():
                    import shutil

                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink()
            except OSError:
                continue
    except OSError as exc:
        log.warning("Resume cache clear partially failed in %s: %s", root, exc)


def clear_run(node_id: Any) -> bool:
    """Start-over: clear the run manifest and best-effort this node's segment,
    motion-context and latent-context caches.  Returns True when the segment
    cache root existed (even if removal was partial)."""
    if node_id is None:
        return False
    seg_root = segment_cache_dir(node_id)
    existed = bool(seg_root is not None and seg_root.exists())
    _clear_dir_best_effort(seg_root)
    for mod_name in ("context_cache", "latent_context_cache"):
        try:
            import importlib

            mod = importlib.import_module(f".{mod_name}", __package__)
            root_fn = getattr(mod, "_cache_root", None)
            if callable(root_fn):
                _clear_dir_best_effort(root_fn(node_id))
        except Exception as exc:
            log.debug("Resume clear skipped %s cache: %s", mod_name, exc)
    clear_stop_request(node_id)
    return existed


def segment_cache_preview(node_id: Any) -> list[dict[str, Any]]:
    """Summarize on-disk per-segment caches for the Resume popup.

    Reads each stored fingerprint meta (width/height/ref_max/output_mode etc.)
    so the frontend can compare them against the current node settings and
    explain why a cached prefix is (or is not) reusable.  Best-effort: never
    raises for unreadable/partial entries.
    """
    if node_id is None:
        return []
    root = segment_cache_dir(node_id)
    if root is None or not root.is_dir():
        return []
    preview: list[dict[str, Any]] = []
    for meta_path in root.glob("seg_*.meta.json"):
        try:
            # meta_path.name is "seg_0003.meta.json"; derive the index robustly.
            base_name = meta_path.name
            if base_name.endswith(".meta.json"):
                base_name = base_name[: -len(".meta.json")]
            parts = base_name.split("_")
            idx = int(parts[1]) if len(parts) == 2 else None
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if idx is None or not isinstance(meta, dict):
                continue
            pt = root / f"seg_{idx:04d}.pt"
            audio = root / f"seg_{idx:04d}.audio.pt"
            refs = meta.get("refs")
            preview.append({
                "index": int(meta.get("index", idx)),
                "complete": pt.is_file(),
                "audio_cached": audio.is_file(),
                "width": meta.get("width"),
                "height": meta.get("height"),
                "ref_max": meta.get("ref_max"),
                "output_mode": meta.get("output_mode"),
                "task_key": meta.get("task_key"),
                "start": meta.get("start"),
                "end": meta.get("end"),
                "prompt_chars": int(len(str(meta.get("prompt") or ""))),
                "refs": list(refs) if isinstance(refs, list) else [],
                "ref_audios": list(meta.get("ref_audios") or []),
                "ref_videos": list(meta.get("ref_videos") or []),
                "updated_ms": int(meta_path.stat().st_mtime * 1000),
            })
        except Exception as exc:
            log.warning("Segment cache preview skipped %s: %s", meta_path.name, exc)
    preview.sort(key=lambda item: int(item["index"]))
    return preview
