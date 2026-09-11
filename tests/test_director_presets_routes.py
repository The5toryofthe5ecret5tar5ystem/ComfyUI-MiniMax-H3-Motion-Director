"""Preset route registration.

The handlers are thin pass-throughs to the store, which is tested in
`test_director_presets.py`. What is worth pinning here is the wiring: the namespace,
the method/path table, and the fact that `/presets` is registered BEFORE
`/presets/{preset_id}` - aiohttp matches in registration order, so a future
`/presets/<verb>` route would otherwise be swallowed by the id pattern and silently
treated as a preset lookup.

Also covered: the compatibility branch for ComfyUI route tables that only expose
per-method decorators rather than `add_route`.
"""

from __future__ import annotations

from mmx_pkg.director.director_presets_routes import register_director_preset_routes

BASE = "/minimax/motion-director/presets"


class _RouteTable:
    """Modern table: exposes add_route(method, path, handler)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def add_route(self, method, path, handler):
        self.calls.append((method, path))


class _DecoratorTable:
    """Older table: only per-method decorator factories."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def _make(self, method):
        def factory(path):
            def decorate(handler):
                self.calls.append((method, path))
                return handler

            return decorate

        return factory

    def __getattr__(self, name):
        if name in {"get", "post", "patch", "delete"}:
            return self._make(name.upper())
        raise AttributeError(name)


def _registered(table):
    register_director_preset_routes(table)
    return table.calls


def test_all_preset_routes_are_registered():
    calls = _registered(_RouteTable())
    assert len(calls) == 5
    assert ("GET", BASE) in calls
    assert ("POST", BASE) in calls
    assert ("GET", f"{BASE}/{{preset_id}}") in calls
    assert ("PATCH", f"{BASE}/{{preset_id}}") in calls
    assert ("DELETE", f"{BASE}/{{preset_id}}") in calls


def test_routes_live_under_the_motion_director_namespace():
    # Keep every Director route under one prefix so the frontend has a single
    # place to look and nothing collides with the material library or core routes.
    for _method, path in _registered(_RouteTable()):
        assert path.startswith("/minimax/motion-director/")
        assert not path.startswith("/minimax/motion-director/material-library")


def test_static_path_is_registered_before_the_id_path():
    gets = [path for method, path in _registered(_RouteTable()) if method == "GET"]
    assert gets.index(BASE) < gets.index(f"{BASE}/{{preset_id}}")


def test_decorator_style_route_tables_are_supported():
    calls = _registered(_DecoratorTable())
    assert ("GET", BASE) in calls
    assert ("DELETE", f"{BASE}/{{preset_id}}") in calls
    assert len(calls) == 5


def test_unsupported_route_table_raises_rather_than_silently_skipping():
    class _Nothing:
        pass

    try:
        register_director_preset_routes(_Nothing())
    except AttributeError as exc:
        assert "route table" in str(exc).lower()
    else:  # pragma: no cover - a silent no-op would mean no routes at all
        raise AssertionError("an unusable route table must raise")
