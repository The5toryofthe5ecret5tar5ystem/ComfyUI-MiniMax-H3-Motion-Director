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

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _alias_repo_as_mmx_pkg() -> None:
    if "mmx_pkg" not in sys.modules:
        _alias = types.ModuleType("mmx_pkg")
        _alias.__path__ = [str(_REPO_ROOT)]
        sys.modules["mmx_pkg"] = _alias

    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))


_alias_repo_as_mmx_pkg()


@pytest.fixture(autouse=True)
def _isolate_sam3_memory():
    """Keep the SAM3 auto-mask module state from leaking between tests.

    ``sam3_auto`` remembers text-seed misses under a (checkpoint, prompt) key so
    a long chain does not repeat a doomed 5-attempt plan on every window. That
    memory is process-global by design, which means one test recording a miss
    silently changes how many attempts a later test observes - and the attempts
    are exactly what several of these tests assert on.
    """
    try:
        from mmx_pkg.director import sam3_auto
    except Exception:  # pragma: no cover - ComfyUI deps absent
        yield
        return
    sam3_auto.reset_auto_mask_memory()
    yield
    sam3_auto.reset_auto_mask_memory()
