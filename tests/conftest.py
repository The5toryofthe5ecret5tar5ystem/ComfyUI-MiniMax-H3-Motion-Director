"""Pytest setup for the Resume feature tests (tests/test_resume_*).

The repo's ``director`` package uses ``from ..lib import ...`` relative imports,
which only resolve when ``director`` is a subpackage.  Register the repo root as
an alias top-level package (``mmx_pkg``) so these tests can import
``mmx_pkg.director.segment_cache`` / ``resume_state`` etc. exactly the way the
ComfyUI runtime loads them.
"""

from __future__ import annotations

import pathlib
import sys
import types

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

if "mmx_pkg" not in sys.modules:
    _alias = types.ModuleType("mmx_pkg")
    _alias.__path__ = [str(_REPO_ROOT)]
    sys.modules["mmx_pkg"] = _alias

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
