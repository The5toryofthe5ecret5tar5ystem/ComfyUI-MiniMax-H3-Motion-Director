# Portions derived from ComfyUI_MiniMaxH3_Director
# Copyright AIMixer and contributors
# Originally licensed under Apache License 2.0
# Modified for MiniMax H3 Motion Director, 2026-08-09
# This derivative project is distributed under GPL-3.0.
# See NOTICE and LICENSES/Apache-2.0-AIMixer.txt.

"""Cache headers for the pack's own ES modules.

ComfyUI's cache middleware sends ``Cache-Control: no-store`` for ``.js`` and
``.css`` paths only - the rule is ``request.path.endswith(".js")`` - so a
``.mjs`` module is left to the browser's heuristic freshness rules and can be
served from the disk cache long after the file changed on disk.

That is not a theoretical problem for this pack, which ships its editors as
``.mjs`` modules. The failure it produces is quiet and confusing:

* the entry ``.js`` file is always re-fetched (the core does cover ``.js``), so
  the browser has the new code;
* one of its ``.mjs`` dependencies is answered from the cache with an older
  copy, and if that copy lacks an export the new code needs, the module graph
  fails to *link* with "does not provide an export named ...";
* a lazily imported panel - the prompt enhancer - then never mounts, and
  because the import is wrapped in a ``.catch`` that only logs, the buttons
  that open it look alive but do nothing at all.

Installing this hook restores the intended behaviour for ``.mjs`` as well, so a
reload always sees the file that is on disk. It is registered through
``Application.on_response_prepare`` (the same mechanism the core's rule uses),
never raises, and only ever adds a header to this pack's own extension files.
"""

from __future__ import annotations

import logging
import os

_log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director")

# The folder name is read from disk rather than hardcoded, so a renamed install
# still matches the URLs ComfyUI serves it under.
_PACK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EXTENSION_PREFIX = "/extensions/" + os.path.basename(_PACK_ROOT) + "/"

# `.js` is listed for completeness: the core covers it, but `setdefault` means
# this only ever fills a gap.
_MODULE_SUFFIXES = (".js", ".mjs")


def extension_prefix() -> str:
    """The URL prefix ComfyUI serves this pack's frontend under."""
    return _EXTENSION_PREFIX


def wants_no_store(path: str) -> bool:
    """True when ``path`` is one of this pack's browser modules."""
    return path.startswith(_EXTENSION_PREFIX) and path.endswith(_MODULE_SUFFIXES)


async def no_store_for_modules(request, response) -> None:
    """aiohttp ``on_response_prepare`` handler; never raises."""
    try:
        if wants_no_store(request.path):
            response.headers.setdefault("Cache-Control", "no-store")
    except Exception:  # pragma: no cover - a header is never worth a 500
        pass


def install_module_cache_headers() -> bool:
    """Attach :func:`no_store_for_modules` to the running ComfyUI app.

    Returns True when the hook is installed. False means PromptServer is not up
    yet (a caller may retry) or the hook was already present - both harmless.
    """
    try:
        from server import PromptServer  # type: ignore
    except Exception:
        return False

    app = getattr(PromptServer, "instance", None)
    app = getattr(app, "app", None)
    if app is None:
        return False

    prepare = getattr(app, "on_response_prepare", None)
    if prepare is None:
        return False

    try:
        # Signal.append is connect(); the explicit fallback keeps older aiohttp
        # builds working.
        add = getattr(prepare, "append", None) or prepare.connect
        add(no_store_for_modules)
    except Exception as exc:  # pragma: no cover - ComfyUI startup only
        _log.warning("Frontend module cache headers could not be installed: %s", exc)
        return False

    _log.debug("Frontend module cache headers installed for %s", _EXTENSION_PREFIX)
    return True
