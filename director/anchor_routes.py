# MiniMax H3 Motion Director - anchor-ladder HTTP routes (P2).
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Anchor strip backend: list / approve / reject / delete boundary anchors.

The executor writes one PNG + sidecar JSON per boundary into
``<output>/minimax_seg_cache/<node_id>/anchors`` (see ``director/anchor_ladder.py``).
The strip UI needs three things the run path cannot give it:

* what is on disk right now (thumbnail, status, seed, beat),
* approve / reject / delete / clear actions on a single boundary,
* a cheap preflight estimate of the anchor pass so the cost is visible before
  the node is queued.

Everything here is best effort: anchors are an optional accelerator, so no route
may raise when the cache directory is missing, unreadable or half-written.

Routes (all under ``/minimax/motion-director/anchors``):

* ``GET  /``          -> ``{ok, items, counts, ...}``
* ``POST /action``    -> ``{ok, action, items, ...}`` (approve|reject|pending|delete|clear|prune)
* ``POST /plan``      -> preflight numbers for the current timeline
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

import folder_paths
from aiohttp import web

from ..lib.vram_budget import attention_workspace_gb, picture_tokens, video_tokens
from . import anchor_ladder
from .cache_path import cache_node_dir_name

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.anchors.routes")

BASE = "/minimax/motion-director/anchors"
CACHE_NAME = "minimax_seg_cache"
ANCHOR_DIR_NAME = "anchors"
DEFAULT_REF_LONG_EDGE = 768
DEFAULT_CONTEXT_FRAMES = 22

_FILE_RE = re.compile(r"^A(?P<index>\d+)_s(?P<seed>\d+)_v(?P<variant>\d+)(?:_f(?P<frames>\d+))?\.png$")

_ACTIONS = ("approve", "reject", "pending", "delete", "clear", "approve_all", "prune")
_STATUS_FOR_ACTION = {"approve": "approved", "reject": "rejected", "pending": "pending"}


# --------------------------------------------------------------------------- #
# route table helper (matches the other sub-registrars in this package)
# --------------------------------------------------------------------------- #
def _route(routes, method: str, path: str, handler) -> None:
    if hasattr(routes, "add_route"):
        routes.add_route(method, path, handler)
    elif method == "POST" and hasattr(routes, "post"):
        routes.post(path)(handler)
    elif method == "GET" and hasattr(routes, "get"):
        routes.get(path)(handler)
    elif method == "PATCH" and hasattr(routes, "patch"):
        routes.patch(path)(handler)
    elif method == "DELETE" and hasattr(routes, "delete"):
        routes.delete(path)(handler)
    else:
        raise AttributeError("Unsupported ComfyUI route table API")


def _json_error(message: str, status: int = 400) -> web.Response:
    return web.json_response({"ok": False, "error": str(message)}, status=status)


# --------------------------------------------------------------------------- #
# disk helpers
# --------------------------------------------------------------------------- #
def anchor_root(node_id: object) -> Path:
    """Directory holding this node's anchor PNGs.

    Read-only on purpose: this module never creates cache directories. The
    executor creates them when it renders (``_anchor_directory``), and until
    then the directory is simply reported as missing.
    """
    base = Path(folder_paths.get_output_directory()) / CACHE_NAME
    return base / cache_node_dir_name(node_id or "unknown") / ANCHOR_DIR_NAME


def _view_url(name: str, node_id: object, mtime: float) -> str:
    subfolder = f"{CACHE_NAME}/{cache_node_dir_name(node_id or 'unknown')}/{ANCHOR_DIR_NAME}"
    params = urlencode(
        {
            "filename": name,
            "subfolder": subfolder,
            "type": "output",
            "c": str(int(mtime or 0)),
        }
    )
    return f"/view?{params}"


def _entry_from_path(path: Path, node_id: object) -> dict | None:
    match = _FILE_RE.match(path.name)
    if match is None:
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    side = anchor_ladder.read_sidecar(path)
    status = str(side.get("status") or "").strip().lower() or "ready"
    chunk_frames = int(side.get("chunk_frames") or match.group("frames") or 0)
    return {
        "index": int(match.group("index")),
        "seed": int(match.group("seed")),
        "variant": int(match.group("variant")),
        "chunkFrames": chunk_frames,
        "status": status,
        "beat": str(side.get("beat") or ""),
        "file": path.name,
        "url": _view_url(path.name, node_id, stat.st_mtime),
        "mtime": int(stat.st_mtime),
        "size": int(stat.st_size),
        "approved": status == "approved",
        "rejected": status == "rejected",
    }


def _scan(root: Path | None, node_id: object) -> list[dict]:
    if root is None or not root.is_dir():
        return []
    try:
        files = sorted(root.glob("A*_s*_v*.png"))
    except OSError:
        return []
    items: list[dict] = []
    for path in files:
        entry = _entry_from_path(path, node_id)
        if entry is not None:
            items.append(entry)
    items.sort(key=lambda item: (item["index"], item["variant"], item["seed"]))
    return items


def _item_files(root: Path | None, index: int) -> list[Path]:
    """Every PNG on disk for one boundary index (across seeds/variants)."""
    if root is None:
        return []
    out: list[Path] = []
    for path in _scan_paths(root):
        match = _FILE_RE.match(path.name)
        if match is not None and int(match.group("index")) == int(index):
            out.append(path)
    return out


def _scan_paths(root: Path | None) -> list[Path]:
    if root is None or not root.is_dir():
        return []
    try:
        return sorted(root.glob("A*_s*_v*.png"))
    except OSError:
        return []


def _unlink_with_sidecar(path: Path) -> int:
    removed = 0
    for target in (path, Path(str(path) + anchor_ladder.SIDECAR_SUFFIX)):
        try:
            if target.exists():
                target.unlink()
                removed += 1
        except OSError as exc:
            log.debug("Anchor routes: could not remove %s (%s).", target, exc)
    return removed


def _status_code_for(action: str) -> str:
    """Sidecar status written by an approve/reject/pending action."""
    return _STATUS_FOR_ACTION.get(str(action or "").strip().lower(), "pending")


def _apply_status(root: Path | None, index: int, status: str) -> int:
    """Write a new sidecar status onto every file of one boundary."""
    written = 0
    for path in _item_files(root, index):
        match = _FILE_RE.match(path.name)
        if match is None:
            continue
        existing = anchor_ladder.read_sidecar(path)
        item = anchor_ladder.AnchorItem(
            index=index,
            seed=int(existing.get("seed") or match.group("seed")),
            beat=str(existing.get("beat") or ""),
            chunk_frames=int(existing.get("chunk_frames") or match.group("frames") or 0),
            variant=int(match.group("variant")),
            path=str(path),
        )
        anchor_ladder.write_sidecar(path, item, status=status)
        written += 1
    return written


def _indices_on_disk(root: Path | None) -> list[int]:
    indices: set[int] = set()
    for path in _scan_paths(root):
        match = _FILE_RE.match(path.name)
        if match is not None:
            indices.add(int(match.group("index")))
    return sorted(indices)


def _list_payload(node_id: str, *, action: str = "", extra: dict | None = None) -> dict:
    root = anchor_root(node_id)
    items = _scan(root, node_id)
    approved = sum(1 for item in items if item.get("approved"))
    rejected = sum(1 for item in items if item.get("rejected"))
    payload: dict = {
        "ok": True,
        "node_id": node_id,
        "root": str(root) if root is not None else "",
        "available": bool(root is not None and root.is_dir()),
        "items": items,
        "counts": {
            "items": len(items),
            "boundaries": len({int(item["index"]) for item in items}),
            "approved": approved,
            "rejected": rejected,
        },
    }
    if action:
        payload["action"] = action
    if extra:
        payload.update(extra)
    return payload


# --------------------------------------------------------------------------- #
# handlers
# --------------------------------------------------------------------------- #
async def anchors_list(request):
    node_id = str(request.query.get("node_id") or "").strip() or "unknown"
    return web.json_response(_list_payload(node_id))


async def anchors_action(request):
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001 - report, never raise into the UI
        return _json_error(f"Invalid JSON: {exc}")
    if not isinstance(body, dict):
        return _json_error("JSON body must be an object.")

    node_id = str(body.get("node_id") or "").strip() or "unknown"
    action = str(body.get("action") or "").strip().lower()
    if action not in _ACTIONS:
        return _json_error(f"Unknown action {action!r}; expected one of {', '.join(_ACTIONS)}.")

    root = anchor_root(node_id)
    raw_index = body.get("index")
    try:
        index = int(raw_index) if raw_index is not None else None
    except (TypeError, ValueError):
        index = None

    removed = 0
    written = 0
    if action in ("approve", "reject", "pending"):
        if index is None:
            return _json_error("This action needs a boundary index.")
        written = _apply_status(root, index, _status_code_for(action))
        if not written:
            return _json_error(f"No rendered anchor on disk for boundary {index}.", status=404)
    elif action == "approve_all":
        written = sum(_apply_status(root, index, "approved") for index in _indices_on_disk(root))
    elif action == "delete":
        if index is None:
            return _json_error("This action needs a boundary index.")
        for path in _item_files(root, index):
            removed += _unlink_with_sidecar(path)
    elif action == "clear":
        for path in _scan_paths(root):
            removed += _unlink_with_sidecar(path)
    elif action == "prune":
        if root is not None:
            # Sidecars are named '<anchor>.png.json' (SIDECAR_SUFFIX is appended
            # to the full file name), so strip the suffix as text - with_suffix()
            # would turn X.png.json into X.png.png and delete live sidecars.
            try:
                for side in sorted(root.glob("A*.png.json")):
                    png = Path(str(side)[: -len(anchor_ladder.SIDECAR_SUFFIX)])
                    if not png.exists():
                        side.unlink()
                        removed += 1
            except OSError as exc:
                log.debug("Anchor routes: prune failed (%s).", exc)

    return web.json_response(
        _list_payload(
            node_id,
            action=action,
            extra={"removed": removed, "sidecarsWritten": written, "index": index},
        )
    )


def _picture_count(source) -> int:
    if isinstance(source, dict):
        images = source.get("images")
        if isinstance(images, list):
            return sum(1 for item in images if item)
        return 0
    if isinstance(source, list):
        return sum(1 for item in source if item)
    return 0


def _segment_frames(seg: dict) -> int:
    for key in ("length", "frameCount", "frames"):
        try:
            value = int(seg.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
    try:
        return max(0, int(seg.get("end") or 0) - int(seg.get("start") or 0))
    except (TypeError, ValueError):
        return 0


def _as_int(value, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def anchors_plan(node_id: str, timeline: dict, *, width: int, height: int,
                 ref_long_edge: int = DEFAULT_REF_LONG_EDGE,
                 context_frames: int = DEFAULT_CONTEXT_FRAMES,
                 ref_pictures: int | None = None) -> dict:
    """Preflight numbers for the anchor pass + the worst fill segment."""
    segments = [seg for seg in (timeline.get("segments") or []) if isinstance(seg, dict)]
    boundaries = len(segments) + 1
    shims = [
        SimpleNamespace(anchor_prompt=str(seg.get("anchorPrompt") or ""))
        for seg in segments
    ]
    plan = anchor_ladder.parse_anchor_config(timeline, shims)

    pictures = 0
    if ref_pictures is not None:
        pictures = max(0, _as_int(ref_pictures))
    else:
        global_refs = (timeline.get("global") or {}).get("refs")
        pictures = _picture_count(global_refs)
        for seg in segments:
            pictures = max(pictures, _picture_count(seg.get("refs")))
    pictures = min(9, pictures)

    chunk_frames = plan.chunk_frames if plan is not None else anchor_ladder.DEFAULT_CHUNK_FRAMES
    anchor_tokens = (
        video_tokens(chunk_frames, width, height) + picture_tokens(pictures, ref_long_edge)
        if width and height
        else 0
    )

    worst_tokens = 0
    worst_frames = 0
    for seg in segments:
        frames = _segment_frames(seg)
        if seg.get("contextLink") or seg.get("context_link"):
            frames += max(0, _as_int(context_frames, DEFAULT_CONTEXT_FRAMES))
        tokens = (
            video_tokens(frames, width, height) + picture_tokens(pictures, ref_long_edge)
            if width and height
            else 0
        )
        if tokens > worst_tokens:
            worst_tokens = tokens
            worst_frames = frames

    root = anchor_root(node_id)
    items = _scan(root, node_id)
    on_disk = {int(item["index"]) for item in items}
    selected = plan.selected_indices if plan is not None else None
    planned = bool(plan is not None and plan.enabled)
    active = [
        index for index in range(boundaries)
        if planned and (selected is None or index in selected)
    ]
    missing = [index for index in active if index not in on_disk]

    return {
        "ok": True,
        "enabled": planned,
        "mode": plan.mode if plan is not None else anchor_ladder.ANCHOR_MODE_OFF,
        "chunkFrames": int(chunk_frames),
        "boundaries": boundaries,
        "boundariesTotal": boundaries,
        "boundariesActive": len(active),
        "selected": list(active) if (planned and selected is not None) else "all",
        "segmentCount": len(segments),
        "renders": len(active),
        "onDisk": len(items),
        "boundariesOnDisk": len(on_disk),
        "missing": missing,
        "approved": sum(1 for item in items if item.get("approved")),
        "refPictures": pictures,
        "refLongEdge": int(ref_long_edge),
        "width": int(width),
        "height": int(height),
        "anchorTokens": int(anchor_tokens),
        "anchorWorkspaceGb": round(attention_workspace_gb(anchor_tokens), 3) if anchor_tokens else 0.0,
        "worstFillFrames": int(worst_frames),
        "worstFillTokens": int(worst_tokens),
        "worstFillWorkspaceGb": round(attention_workspace_gb(worst_tokens), 3) if worst_tokens else 0.0,
        "beats": [item.beat for item in plan.items] if plan is not None else [],
    }


async def anchors_plan_route(request):
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        return _json_error(f"Invalid JSON: {exc}")
    if not isinstance(body, dict):
        return _json_error("JSON body must be an object.")

    node_id = str(body.get("node_id") or "").strip() or "unknown"
    raw = body.get("timeline_data")
    if isinstance(raw, str):
        try:
            timeline = json.loads(raw) if raw.strip() else {}
        except Exception as exc:  # noqa: BLE001
            return _json_error(f"timeline_data is not valid JSON: {exc}")
    elif isinstance(raw, dict):
        timeline = raw
    else:
        timeline = {}
    if not isinstance(timeline, dict):
        return _json_error("timeline_data must be an object.")

    # A preflight probe must never create or touch the cache; scan read-only.
    payload = anchors_plan(
        node_id,
        timeline,
        width=_as_int(body.get("width")),
        height=_as_int(body.get("height")),
        ref_long_edge=_as_int(body.get("ref_long_edge") or body.get("refLongEdge"), DEFAULT_REF_LONG_EDGE),
        context_frames=_as_int(body.get("context_frames") or body.get("contextFrames"), DEFAULT_CONTEXT_FRAMES),
        ref_pictures=body.get("ref_pictures") if isinstance(body.get("ref_pictures"), int) else None,
    )
    return web.json_response(payload)


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #
def register_anchor_routes(routes) -> None:
    """Register the anchor strip endpoints (idempotent per process)."""
    _route(routes, "GET", BASE, anchors_list)
    _route(routes, "POST", BASE + "/action", anchors_action)
    _route(routes, "POST", BASE + "/plan", anchors_plan_route)


__all__ = ["BASE", "anchor_root", "anchors_plan", "register_anchor_routes"]
