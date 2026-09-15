# Tests for the anchored-model referrer scan in director.vram_cleanup.
#
# Background: when a loaded-model entry is "dead" (its ModelPatcher wrapper was
# collected while the raw torch module is still alive), ComfyUI cannot unload
# it - free_memory skips dead entries - so the weights stay on the GPU and a
# later stage such as Global Refine upscaling starves. The scan names the object
# that holds the model, which is what a bug report actually needs.

from __future__ import annotations

import logging
import sys
import types

import director.vram_cleanup as vram_cleanup

_LOG = vram_cleanup.log.name


class _Entry:
    """Stand-in for comfy.model_management.LoadedModel."""

    def __init__(self, real_model, dead=True):
        self._real_model = real_model
        self._dead = dead

    def is_dead(self):
        return self._dead

    def real_model(self):
        return self._real_model


class _Anchored:
    """Stand-in for the raw MiniMaxH3 torch module."""


def _install_comfy(entries):
    comfy = types.ModuleType("comfy")
    mm = types.ModuleType("comfy.model_management")
    mm.current_loaded_models = list(entries)
    mm.cleanup_models_gc = lambda: None
    mm.unload_all_models = lambda: None
    mm.cleanup_models = lambda: None
    mm.soft_empty_cache = lambda: None
    comfy.model_management = mm
    sys.modules["comfy"] = comfy
    sys.modules["comfy.model_management"] = mm
    return mm


def test_scan_names_the_holder(caplog):
    vram_cleanup._REPORTED_ANCHORS.clear()
    anchored = _Anchored()
    holder = {"third_party_node_cache": anchored}
    _install_comfy([_Entry(anchored)])
    with caplog.at_level(logging.WARNING, logger=_LOG):
        found = vram_cleanup.report_anchored_models()
    assert found == 1
    assert "is still alive" in caplog.text
    assert "third_party_node_cache" in caplog.text
    assert "end of referrer list" in caplog.text
    assert holder is not None


def test_scan_ignores_live_entries(caplog):
    vram_cleanup._REPORTED_ANCHORS.clear()
    _install_comfy([_Entry(_Anchored(), dead=False)])
    with caplog.at_level(logging.WARNING, logger=_LOG):
        assert vram_cleanup.report_anchored_models() == 0
    assert "is still alive" not in caplog.text


def test_scan_deduplicates_repeats(caplog):
    vram_cleanup._REPORTED_ANCHORS.clear()
    anchored = _Anchored()
    holder = {"node_cache": anchored}
    _install_comfy([_Entry(anchored)])
    with caplog.at_level(logging.WARNING, logger=_LOG):
        assert vram_cleanup.report_anchored_models() == 1
        assert vram_cleanup.report_anchored_models() == 1
    assert caplog.text.count("is still alive") == 1
    assert holder is not None


def test_scan_can_be_disabled(monkeypatch, caplog):
    vram_cleanup._REPORTED_ANCHORS.clear()
    monkeypatch.setenv(vram_cleanup.LEAK_SCAN_ENV, "0")
    _install_comfy([_Entry(_Anchored())])
    with caplog.at_level(logging.WARNING, logger=_LOG):
        assert vram_cleanup.report_anchored_models() == 0
    assert "is still alive" not in caplog.text


def test_scan_tolerates_broken_entries(caplog):
    vram_cleanup._REPORTED_ANCHORS.clear()

    class Broken:
        def is_dead(self):
            raise RuntimeError("boom")

        def real_model(self):
            raise RuntimeError("boom")

    class NoneReal:
        def is_dead(self):
            return True

        def real_model(self):
            return None

    _install_comfy([Broken(), NoneReal()])
    with caplog.at_level(logging.WARNING, logger=_LOG):
        assert vram_cleanup.report_anchored_models() == 0
    assert "is still alive" not in caplog.text


def test_cleanup_reports_anchored_model(caplog):
    vram_cleanup._REPORTED_ANCHORS.clear()
    anchored = _Anchored()
    holder = {"some_pack_registry": anchored}
    _install_comfy([_Entry(anchored)])
    with caplog.at_level(logging.WARNING, logger=_LOG):
        vram_cleanup.cleanup_segment_vram(enabled=True, unload_models=True)
    assert "is still alive" in caplog.text
    assert "some_pack_registry" in caplog.text
    assert holder is not None


# ---------------------------------------------------------------------------
# Partial failure isolation.
#
# The cleanup used to run every step inside a single try/except, so a failure in
# the FIRST step skipped the unload and the cache empty that follow - one raising
# call silently disabled the whole cleanup, which looks to a user exactly like
# the toggle doing nothing.
# ---------------------------------------------------------------------------


def _install_comfy_failing(failing):
    """Install a comfy stand-in where ``failing`` step names raise."""
    called = []

    def make(name):
        if name in failing:
            def boom():
                called.append(name)
                raise RuntimeError(f"{name} exploded")
            return boom

        def ok():
            called.append(name)
        return ok

    comfy = types.ModuleType("comfy")
    mm = types.ModuleType("comfy.model_management")
    mm.current_loaded_models = []
    for name in ("cleanup_models_gc", "unload_all_models", "cleanup_models", "soft_empty_cache"):
        setattr(mm, name, make(name))
    comfy.model_management = mm
    sys.modules["comfy"] = comfy
    sys.modules["comfy.model_management"] = mm
    return called


def test_cleanup_runs_every_step_when_the_first_fails(caplog):
    """A failing cleanup_models_gc must not cancel the unload or cache empty."""
    vram_cleanup._REPORTED_ANCHORS.clear()
    called = _install_comfy_failing({"cleanup_models_gc"})
    with caplog.at_level(logging.WARNING, logger=_LOG):
        summary = vram_cleanup.cleanup_segment_vram(enabled=True, unload_models=True)
    assert "unload_all_models" in called, "unload was skipped by an earlier failure"
    assert "cleanup_models" in called, "cleanup_models was skipped by an earlier failure"
    assert "soft_empty_cache" in called, "cache empty was skipped by an earlier failure"
    assert summary["failed"] == ["cleanup_models_gc"]
    assert "unload_all_models" in summary["steps"]


def test_cleanup_surfaces_partial_failure_in_reports(caplog):
    """A partial failure must reach the execution report, not just the log."""
    vram_cleanup._REPORTED_ANCHORS.clear()
    _install_comfy_failing({"soft_empty_cache"})
    with caplog.at_level(logging.WARNING, logger=_LOG):
        summary = vram_cleanup.cleanup_segment_vram(enabled=True, unload_models=True)
    assert summary["failed"] == ["soft_empty_cache"]
    assert any("cleanup step(s) failed" in line for line in summary["reports"])
    assert any("soft_empty_cache" in line for line in summary["reports"])


def test_cleanup_surfaces_anchored_models_in_reports(caplog):
    """An un-freeable model must be named in the report, not only the log."""
    vram_cleanup._REPORTED_ANCHORS.clear()
    anchored = _Anchored()
    _install_comfy([_Entry(anchored)])
    with caplog.at_level(logging.WARNING, logger=_LOG):
        summary = vram_cleanup.cleanup_segment_vram(enabled=True, unload_models=True)
    assert summary["anchored"] == 1
    assert any("could not free 1 model(s)" in line for line in summary["reports"])


def test_cleanup_reports_are_empty_when_nothing_is_wrong(caplog):
    vram_cleanup._REPORTED_ANCHORS.clear()
    _install_comfy([])
    with caplog.at_level(logging.WARNING, logger=_LOG):
        summary = vram_cleanup.cleanup_segment_vram(enabled=True, unload_models=True)
    assert summary["reports"] == []
    assert summary["failed"] == []
    assert summary["unloaded"] is True


def test_cleanup_keeps_models_when_not_unloading(caplog):
    """unload_models=False must still gc and empty the cache, never unload."""
    vram_cleanup._REPORTED_ANCHORS.clear()
    called = _install_comfy_failing(set())
    with caplog.at_level(logging.WARNING, logger=_LOG):
        summary = vram_cleanup.cleanup_segment_vram(enabled=True, unload_models=False)
    assert "unload_all_models" not in called
    assert "unload_all_models" not in summary["steps"]
    assert "soft_empty_cache" in called
    assert summary["unloaded"] is False


def test_cleanup_is_a_noop_when_disabled():
    _install_comfy_failing(set())
    summary = vram_cleanup.cleanup_segment_vram(enabled=False)
    assert summary["steps"] == [] and summary["reports"] == []


def test_cleanup_tolerates_missing_comfy():
    """Outside ComfyUI (bare test runs) the cleanup must not raise."""
    sys.modules.pop("comfy", None)
    sys.modules.pop("comfy.model_management", None)
    summary = vram_cleanup.cleanup_segment_vram(enabled=True, unload_models=True)
    assert summary["reports"] == []
