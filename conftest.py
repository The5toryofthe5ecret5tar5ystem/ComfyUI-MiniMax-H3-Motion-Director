"""Make the Motion Director Python test suite runnable from any CWD without ComfyUI.

Three hazards are neutralised here so ``python -m pytest`` works out of the box
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

3. **CPU-only torch vs. ComfyUI's import-time CUDA probe.** ``comfy.model_management``
   resolves the device at *import* time via ``get_torch_device()``, which calls
   ``torch.cuda.current_device()`` whenever ``cpu_state`` is left at its GPU
   default. On a CPU-only torch build (which is what CI installs, and the only
   thing that runs on a GPU-less box) that raises ``AssertionError: Torch not
   compiled with CUDA enabled`` before any test is collected - and it does so
   from inside ``patches/h3_layout.py``, so it takes down every test file that
   imports the executor. Setting ComfyUI's own ``args.cpu`` flag before
   ``comfy.model_management`` is first imported drives ``cpu_state`` to CPU and
   skips the probe.

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

# 3) Ask ComfyUI for a CPU device before it is imported for the first time.
#    Importing comfy.cli_args is safe (it only parses argv); the GPU probe lives
#    in comfy.model_management, which this prevents from ever choosing CUDA.
#    Skipped when a GPU is actually present, so a local run still exercises the
#    real device path.
def _force_cpu_for_comfy() -> None:
    if "comfy.model_management" in sys.modules:
        # Already imported (e.g. by an earlier conftest import) - nothing to do,
        # and mutating cpu_state now would not help.
        return
    try:
        import comfy.cli_args as cli_args
    except Exception:  # noqa: BLE001 - ComfyUI absent; tests that need it will skip
        return
    try:
        import torch

        if torch.cuda.is_available():
            return
    except Exception:  # noqa: BLE001 - no torch at all; nothing to steer
        pass
    try:
        cli_args.args.cpu = True
    except Exception:  # noqa: BLE001 - unexpected cli_args shape; never fail collection
        pass


_force_cpu_for_comfy()

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
