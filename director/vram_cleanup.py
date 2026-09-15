# Portions derived from ComfyUI_MiniMaxH3_Director
# Copyright AIMixer and contributors
# Originally licensed under Apache License 2.0
# Modified for MiniMax H3 Motion Director, 2026-08-09
# This derivative project is distributed under GPL-3.0.
# See NOTICE and LICENSES/Apache-2.0-AIMixer.txt.

"""Release GPU memory between MiniMax H3 Motion Director segment runs."""

from __future__ import annotations

import gc
import logging
import os
import types
import weakref
from typing import Any

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.director.vram")

# Set to 0/false/off/no to silence the anchored-model referrer scan.
LEAK_SCAN_ENV = "MINIMAX_DIRECTOR_LEAK_SCAN"

_REPORTED_ANCHORS: set[str] = set()


def _scan_enabled() -> bool:
    value = str(os.environ.get(LEAK_SCAN_ENV, "1")).strip().lower()
    return value not in {"0", "false", "off", "no"}


def _referrer_line(ref: Any) -> str | None:
    """Describe one referrer, or return None when it carries no information."""
    if isinstance(ref, weakref.ref):
        return None
    if isinstance(ref, types.FrameType):
        if ref.f_code.co_filename.endswith("vram_cleanup.py"):
            return None
        return "frame %s:%d in %s()" % (ref.f_code.co_filename, ref.f_lineno, ref.f_code.co_name)
    if isinstance(ref, types.ModuleType):
        return "module %s" % getattr(ref, "__name__", "?")
    if isinstance(ref, dict):
        return "dict keys=%r" % (list(ref.keys())[:8],)
    if isinstance(ref, (list, tuple, set, frozenset)):
        return "%s len=%d" % (type(ref).__name__, len(ref))
    cls = type(ref)
    module = str(getattr(cls, "__module__", ""))
    name = str(getattr(cls, "__qualname__", cls.__name__))
    hint = " (ComfyUI model wrapper)" if "model_patcher" in module else ""
    return "%s.%s%s" % (module, name, hint)


def _climb_referrer(ref: Any) -> bool:
    """Whether to walk one level past this referrer.

    Torch internals and framework wrappers sit between the model and the object
    that actually roots it (a custom node, a cache dict, a registry); climbing
    them is what makes the report name something actionable.
    """
    if isinstance(ref, (dict, list, tuple, set, frozenset)):
        return True
    module = str(getattr(type(ref), "__module__", ""))
    return module.startswith(("torch.", "comfy."))


def _dump_referrers(real_model: Any, *, max_lines: int = 24, max_targets: int = 8, max_depth: int = 3) -> None:
    """Walk out from ``real_model`` and name what roots it."""
    log.warning(
        "MiniMax H3 Motion Director: %s is still alive after its ComfyUI model "
        "wrapper was released. ComfyUI skips dead entries when unloading "
        "(free_memory ignores them), so VRAM for this model cannot be freed - a "
        "later stage such as Global Refine upscaling then has no room. Something "
        "outside ComfyUI's bookkeeping holds a reference:",
        type(real_model).__name__,
    )
    printed = 0
    targets = 0
    seen = {id(real_model)}
    queue: list[Any] = [real_model]
    depths: dict[int, int] = {id(real_model): 0}
    while queue and printed < max_lines and targets < max_targets:
        target = queue.pop(0)
        depth = depths.pop(id(target), 0)
        targets += 1
        try:
            referrers = gc.get_referrers(target)
        except Exception:  # noqa: BLE001 - diagnostics must never raise
            continue
        for ref in referrers:
            if printed >= max_lines:
                break
            rid = id(ref)
            if rid in seen:
                continue
            seen.add(rid)
            line = _referrer_line(ref)
            if line is not None:
                log.warning("  [depth %d] %s", depth, line)
                printed += 1
            if depth < max_depth and _climb_referrer(ref):
                queue.append(ref)
                depths[rid] = depth + 1
    log.warning(
        "  (end of referrer list - %d line(s); set %s=0 to disable this scan)",
        printed,
        LEAK_SCAN_ENV,
    )


def report_anchored_models(*, max_lines: int = 24) -> int:
    """Name models ComfyUI can no longer unload, and what holds them.

    A loaded-model entry is "dead" when its wrapper (the ModelPatcher that loads
    and unloads weights) has been garbage collected while the raw torch module
    is still alive. ``unload_all_models`` skips dead entries by design, so their
    weights stay resident. The referrer dump names the object (usually a
    third-party custom node) that keeps the module alive. Returns the number of
    anchored models found; never raises.
    """
    if not _scan_enabled():
        return 0
    try:
        import comfy.model_management as mm

        entries = list(getattr(mm, "current_loaded_models", []) or [])
    except Exception:  # noqa: BLE001 - diagnostics must never raise
        return 0
    anchored = 0
    for entry in entries:
        try:
            if not entry.is_dead():
                continue
            real_model = entry.real_model()
        except Exception:  # noqa: BLE001 - unknown entry shapes are skipped
            continue
        if real_model is None:
            continue
        anchored += 1
        key = "%s@%d" % (type(real_model).__name__, id(real_model))
        if key in _REPORTED_ANCHORS:
            continue
        _REPORTED_ANCHORS.add(key)
        _dump_referrers(real_model, max_lines=max_lines)
    return anchored


# Highest device-memory total observed per cleanup call, for the execution report.
_LAST_ANCHORED = 0


def _release_anchored_summary(anchored: int) -> str:
    """One-line report entry for an unload that could not free everything."""
    return (
        f"VRAM: could not free {anchored} model(s) - ComfyUI skips entries whose "
        "wrapper was released. See the referrer scan in the log; a custom node "
        "is holding the model."
    )


def cleanup_segment_vram(*, enabled: bool = True, unload_models: bool = True) -> dict[str, Any]:
    """Release segment GPU memory: gc, optional unload of ComfyUI models, empty CUDA cache.

    Each step runs in its own ``try``. The previous version wrapped the whole
    sequence in one block, so a failure in the *first* step (``cleanup_models_gc``)
    skipped the unload and the cache empty that follow - one raising call silently
    disabled the entire cleanup, which reads to a user exactly like the toggle
    doing nothing.

    Returns a summary dict (``steps``, ``failed``, ``anchored``, ``reports``) so the
    caller can surface a partial failure instead of only logging it.
    """
    summary: dict[str, Any] = {
        "steps": [], "failed": [], "anchored": 0, "reports": [], "unloaded": False,
    }
    if not enabled:
        return summary

    def _step(name: str, fn) -> None:
        try:
            fn()
            summary["steps"].append(name)
        except Exception as exc:  # noqa: BLE001 - one failing step must not cancel the rest
            summary["failed"].append(name)
            log.warning("Segment VRAM cleanup: %s failed: %s", name, exc)

    _step("gc", gc.collect)

    try:
        import comfy.model_management as mm
    except Exception as exc:  # noqa: BLE001 - outside ComfyUI (tests) there is nothing to free
        log.debug("Segment VRAM cleanup: comfy.model_management unavailable: %s", exc)
        if summary["failed"]:
            summary["reports"].append(
                "VRAM: cleanup is partially failing (" + ", ".join(summary["failed"]) + ")."
            )
        return summary

    _step("cleanup_models_gc", mm.cleanup_models_gc)
    if unload_models:
        _step("unload_all_models", mm.unload_all_models)
        _step("cleanup_models", mm.cleanup_models)
        summary["unloaded"] = "unload_all_models" in summary["steps"]
    _step("soft_empty_cache", mm.soft_empty_cache)

    if unload_models:
        # Diagnostic: the unload above cannot free a model whose wrapper is
        # already gone (free_memory skips dead entries), so name the holder.
        try:
            summary["anchored"] = report_anchored_models()
        except Exception as exc:  # noqa: BLE001 - diagnostics must never fail a run
            log.debug("Anchored-model scan failed: %s", exc)

    if summary["failed"]:
        summary["reports"].append(
            "VRAM: cleanup step(s) failed (" + ", ".join(summary["failed"])
            + "); some memory may not have been released."
        )
    if summary["anchored"]:
        summary["reports"].append(_release_anchored_summary(summary["anchored"]))

    global _LAST_ANCHORED
    _LAST_ANCHORED = int(summary["anchored"])

    log.debug(
        "MiniMax H3 Motion Director: segment VRAM cleanup (%s, steps=%s, failed=%s, anchored=%d)",
        "models unloaded" if unload_models else "models kept loaded",
        ",".join(summary["steps"]) or "none",
        ",".join(summary["failed"]) or "none",
        int(summary["anchored"]),
    )
    return summary
