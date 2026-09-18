# MiniMax H3 Motion Director - frontend module cache headers.
# Copyright (C) 2026 WakaSoft. GPL-3.0. See LICENSE.

"""A `.mjs` module must not be left to the browser's own caching rules.

ComfyUI's cache middleware only matches paths ending in `.js` (and `.css`), so a
`.mjs` module could be answered from the browser cache long after the file on
disk changed. That is exactly the trap this pack fell into: the prompt enhancer
gained an import of a name that had just been added to a shared `.mjs`, the
freshly served `.js` entry could not *link* against the cached copy ("does not
provide an export named ..."), the lazy import rejected, and the `.catch` around
it only wrote to the console - so the Enable/Settings buttons stayed on screen
and did nothing at all when clicked.

Two layers are pinned here:

1. the header hook, so a response for one of this pack's own module files always
   says ``no-store``;
2. a version token on the import specifier of every importer of the shared
   module, so a browser that already holds the old URL asks for a new one
   (headers alone cannot help a client that never re-requests the file).
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

try:
    from mmx_pkg.director import web_cache
except ImportError as exc:  # pragma: no cover - environment guard
    pytest.skip(f"Director package unavailable: {exc}", allow_module_level=True)


REPO_ROOT = Path(__file__).resolve().parents[1]
JS_DIR = REPO_ROOT / "web" / "js"
PREFIX = web_cache.extension_prefix()


class _Request:
    def __init__(self, path: str) -> None:
        self.path = path


class _Response:
    def __init__(self, headers=None) -> None:
        self.headers = dict(headers or {})


def _prepare(path: str, headers=None) -> _Response:
    """Run the hook the way aiohttp would, and hand back the response."""
    response = _Response(headers)
    asyncio.run(web_cache.no_store_for_modules(_Request(path), response))
    return response


# --- which paths are ours ---------------------------------------------------


def test_the_pack_serves_its_modules_under_its_own_directory():
    assert re.fullmatch(r"/extensions/[^/]+/", PREFIX), PREFIX
    assert PREFIX.endswith("/ComfyUI-MiniMax-H3-Motion-Director/"), (
        "the prefix is derived from the folder on disk and must match the served URL"
    )


@pytest.mark.parametrize(
    "name",
    [
        "minimax_prompt_enhancer.js",
        "minimax_timeline.js",
        "minimax_reference_assets.mjs",
        "minimax_prompt_enhance_batch.mjs",
    ],
)
def test_the_packs_module_files_are_marked_no_store(name):
    assert web_cache.wants_no_store(PREFIX + name) is True


@pytest.mark.parametrize(
    "path",
    [
        "/extensions/ComfyUI-Some-Other-Pack/minimax_reference_assets.mjs",
        PREFIX + "logo.png",
        PREFIX + "index.json",
        "/scripts/api.js",
        "/api/object_info",
        PREFIX,
    ],
)
def test_everything_else_is_left_alone(path):
    """Only this pack's own browser modules are ours to decide about."""
    assert web_cache.wants_no_store(path) is False
    assert "Cache-Control" not in _prepare(path).headers


# --- the header itself ------------------------------------------------------


def test_a_module_response_gets_no_store():
    response = _prepare(PREFIX + "minimax_reference_assets.mjs")
    assert response.headers["Cache-Control"] == "no-store"


def test_an_explicit_cache_header_is_not_overwritten():
    """A route that deliberately set a policy keeps it (setdefault semantics)."""
    response = _prepare(
        PREFIX + "minimax_timeline.js", {"Cache-Control": "public, max-age=60"}
    )
    assert response.headers["Cache-Control"] == "public, max-age=60"


def test_the_hook_never_raises():
    """A missing attribute must not turn into a 500 on a static file."""
    asyncio.run(web_cache.no_store_for_modules(object(), _Response()))


def test_installing_returns_false_without_a_server():
    """No PromptServer (or none started yet) is a deferred install, not an error."""
    assert web_cache.install_module_cache_headers() is False


# --- the wiring -------------------------------------------------------------


def test_the_package_installs_the_hook_at_import_time():
    source = (REPO_ROOT / "__init__.py").read_text(encoding="utf-8")
    assert "from .director.web_cache import install_module_cache_headers" in source
    assert "install_module_cache_headers()" in source
    assert "Frontend module cache headers failed to load" in source, (
        "a broken install must be reported, not crash the pack import"
    )


# --- the import specifiers --------------------------------------------------


def test_importers_agree_on_a_version_token():
    """Headers cannot help a browser that already cached the old URL.

    The enhancer's entry file is re-fetched on every load (`.js` is covered), so
    a token on the *dependency* specifier is what forces the browser to ask for
    the module again instead of linking against the copy it holds.
    """
    specifier = re.compile(
        r"from\s*[\"'](\./minimax_reference_assets\.mjs)(\?[^\"']*)?[\"']"
    )
    tokens: dict[str, set[str]] = {}
    importers: list[str] = []
    for path in sorted(list(JS_DIR.glob("*.js")) + list(JS_DIR.glob("*.mjs"))):
        if ".bak" in path.name:
            continue
        for match in specifier.finditer(path.read_text(encoding="utf-8")):
            importers.append(path.name)
            tokens.setdefault(match.group(2) or "", set()).add(path.name)

    assert len(importers) >= 5, f"the shared module is imported from {importers}"
    assert "" not in tokens, (
        "an unversioned import can be answered from a stale browser cache: "
        f"{sorted(tokens[''])}"
    )
    assert len(tokens) == 1, (
        "one token for every importer, or the browser instantiates the module "
        f"twice: {sorted(tokens)}"
    )


def test_the_module_that_broke_still_exports_what_the_panel_needs():
    """The panel imports this by name; an unversioned importer is the bug."""
    shared = (JS_DIR / "minimax_reference_assets.mjs").read_text(encoding="utf-8")
    assert re.search(
        r"export\s+(?:async\s+)?function\s+effectivePictureRefs\b", shared
    ), "the panel imports effectivePictureRefs from this module"

    enhancer = (JS_DIR / "minimax_prompt_enhancer.js").read_text(encoding="utf-8")
    assert re.search(
        r"from\s*[\"']\./minimax_reference_assets\.mjs\?boot=[A-Za-z0-9_]+[\"']",
        enhancer,
    ), "the enhancer must import the shared module under a version token"
