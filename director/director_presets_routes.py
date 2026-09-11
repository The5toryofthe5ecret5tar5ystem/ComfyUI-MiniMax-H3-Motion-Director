# MiniMax H3 Motion Director — named preset HTTP routes.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""HTTP surface for named Director presets.

Deliberately thin: the store owns validation and persistence, these handlers only
translate between JSON and `DirectorPresetError`. Static paths are registered
before the `{preset_id}` catch-all so a future `/presets/<verb>` route cannot be
swallowed by the id pattern.
"""

from __future__ import annotations

import logging

from aiohttp import web

from .director_presets import DirectorPresetError, STORE

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.presets")


def _json_error(message: str, status: int = 400) -> web.Response:
    return web.json_response({"error": str(message)}, status=status)


def _route(routes, method: str, path: str, handler) -> None:
    # Kept local rather than imported from material_library_routes: matching each
    # existing route module is the convention here, and it keeps this module
    # independent of the material library's upload plumbing.
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


def _status_for(exc: DirectorPresetError) -> int:
    return 404 if "not found" in str(exc).lower() else 400


async def _read_json(request) -> dict:
    try:
        body = await request.json()
    except Exception as exc:
        raise DirectorPresetError(f"Invalid JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise DirectorPresetError("JSON body must be an object.")
    return body


async def director_presets_list(request):
    try:
        return web.json_response({"presets": STORE.list_presets()})
    except DirectorPresetError as exc:
        # A corrupt index is the user's to fix; report the path from the message
        # rather than pretending there are no presets.
        return _json_error(str(exc), 500)


async def director_presets_get(request):
    try:
        preset = STORE.get_preset(request.match_info.get("preset_id"))
        return web.json_response({"preset": preset})
    except DirectorPresetError as exc:
        return _json_error(str(exc), _status_for(exc))


async def director_presets_create(request):
    try:
        body = await _read_json(request)
        record = STORE.save_preset(
            name=body.get("name"),
            description=body.get("description", ""),
            payload=body.get("payload"),
        )
        return web.json_response({"preset": record}, status=201)
    except DirectorPresetError as exc:
        return _json_error(str(exc), 400)


async def director_presets_update(request):
    try:
        body = await _read_json(request)
        record = STORE.update_preset(
            request.match_info.get("preset_id"),
            name=body.get("name"),
            # None (key absent) leaves the field alone; "" clears it.
            description=body.get("description"),
            payload=body.get("payload"),
        )
        return web.json_response({"preset": record})
    except DirectorPresetError as exc:
        return _json_error(str(exc), _status_for(exc))


async def director_presets_delete(request):
    try:
        preset_id = STORE.delete_preset(request.match_info.get("preset_id"))
        return web.json_response({"deleted": preset_id})
    except DirectorPresetError as exc:
        return _json_error(str(exc), _status_for(exc))


def register_director_preset_routes(routes) -> None:
    base = "/minimax/motion-director/presets"
    _route(routes, "GET", base, director_presets_list)
    _route(routes, "POST", base, director_presets_create)
    _route(routes, "GET", base + "/{preset_id}", director_presets_get)
    _route(routes, "PATCH", base + "/{preset_id}", director_presets_update)
    _route(routes, "DELETE", base + "/{preset_id}", director_presets_delete)


__all__ = ["register_director_preset_routes"]
