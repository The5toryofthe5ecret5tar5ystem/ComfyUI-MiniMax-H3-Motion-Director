"""Make the Motion Director Python test suite runnable from any CWD without ComfyUI.

Two hazards are neutralised here so ``python -m pytest`` works out of the box
(whether launched from the repository root or anywhere else):

1. **CWD-relative source loads.** Several tests resolve source files with
   CWD-relative paths such as ``Path("director/segment_boundary.py")`` or
   ``Path("web/js/minimax_timeline.js")``. Pinning the process CWD to the
   repository root keeps those loads correct no matter where pytest is started.

2. **Top-level ``nodes/`` package shadowing.** This repository ships its own
   ``nodes/`` package, which shadows ComfyUI's ``nodes`` module whenever the
   repo root is on ``sys.path`` (pytest inserts it during collection). ComfyUI's
   real ``nodes`` module exposes node classes such as ``VAEDecode``/``VAEEncode``
   that ``director/refine_latent_stage.py`` lazily imports. When a genuine
   ComfyUI ``nodes`` module is already loaded it is left untouched; otherwise a
   minimal stand-in is installed in ``sys.modules`` so the refine tests can
   monkeypatch the same object the code under test imports.

This is test-only configuration; it has no effect on ComfyUI runtime loading.
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent

# 1) Keep CWD-relative Path("...") loads in the tests pinned to the repo root.
os.chdir(_REPO_ROOT)

# 2) Install a `nodes` stand-in only when ComfyUI's real module is absent.
_NODE_CLASS_PROBES = ("VAEDecode", "VAEEncode")
_existing_nodes = sys.modules.get("nodes")
if _existing_nodes is None or not any(
    hasattr(_existing_nodes, name) for name in _NODE_CLASS_PROBES
):
    _stub = types.ModuleType("nodes")
    _stub.VAEDecode = object  # replaced per-test by monkeypatch
    _stub.VAEEncode = object
    sys.modules["nodes"] = _stub
