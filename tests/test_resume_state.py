"""Resume / stop engine bookkeeping (director.resume_state).

Covers the run manifest lifecycle, the graceful-stop request flag, the clean
ComfyUI interrupt it raises, and "start over" cache clearing — all keyed by
node id and stored on disk under the (monkeypatched) output directory.
"""

from __future__ import annotations

import sys
import types

import pytest

import folder_paths
from mmx_pkg.director import resume_state


@pytest.fixture
def out_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(folder_paths, "get_output_directory", lambda: str(tmp_path))
    return tmp_path


def _node_id(prefix: str = "resume_test") -> str:
    import uuid

    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@pytest.fixture
def comfy_interrupt(monkeypatch):
    """Install a minimal comfy.model_management so raise_graceful_stop can raise
    its clean interrupt without a live ComfyUI."""
    import importlib

    comfy_mod = types.ModuleType("comfy")
    mm = types.ModuleType("comfy.model_management")

    class InterruptProcessingException(BaseException):
        pass

    state = {"interrupted": False, "raised": False}

    def interrupt_current_processing(value=True):
        state["interrupted"] = bool(value)

    def throw_exception_if_processing_interrupted():
        if state["interrupted"]:
            state["raised"] = True
            raise InterruptProcessingException()

    mm.InterruptProcessingException = InterruptProcessingException
    mm.interrupt_current_processing = interrupt_current_processing
    mm.throw_exception_if_processing_interrupted = throw_exception_if_processing_interrupted
    monkeypatch.setitem(sys.modules, "comfy", comfy_mod)
    monkeypatch.setitem(sys.modules, "comfy.model_management", mm)
    return state, InterruptProcessingException


def test_manifest_fresh_run_marks_segments(out_dir) -> None:
    node = _node_id()
    resume_state.begin_run(node, 3, reset_done=True)
    resume_state.mark_segment_done(node, 0, 0)
    resume_state.mark_segment_done(node, 1, 1)

    status = resume_state.resume_status(node)
    assert status["state"] == "running"
    assert status["segment_total"] == 3
    assert status["done"] == [0, 1]
    assert status["next"] == 2


def test_manifest_all_done_next_equals_total(out_dir) -> None:
    node = _node_id()
    resume_state.begin_run(node, 2, reset_done=True)
    resume_state.mark_segment_done(node, 0, 0)
    resume_state.mark_segment_done(node, 1, 1)
    resume_state.mark_run_state(node, "done")

    status = resume_state.resume_status(node)
    assert status["state"] == "done"
    assert status["done"] == [0, 1]
    assert status["next"] == 2


def test_resume_run_keeps_done_prefix(out_dir) -> None:
    node = _node_id()
    resume_state.begin_run(node, 3, reset_done=True)
    resume_state.mark_segment_done(node, 0, 0)
    resume_state.mark_segment_done(node, 1, 1)

    # A Resume run (reset_done=False) keeps the finished prefix.
    resume_state.begin_run(node, 3, reset_done=False)
    assert resume_state.resume_status(node)["done"] == [0, 1]


def test_idle_node_has_empty_manifest(out_dir) -> None:
    node = _node_id()
    status = resume_state.resume_status(node)
    assert status["state"] == "idle"
    assert status["done"] == []
    assert status["next"] == 0


def test_graceful_stop_requests_and_raises_clean(out_dir, comfy_interrupt) -> None:
    state, interrupt_type = comfy_interrupt
    node = _node_id()
    resume_state.begin_run(node, 4, reset_done=True)
    resume_state.mark_segment_done(node, 0, 0)
    resume_state.mark_segment_done(node, 1, 1)

    assert resume_state.stop_requested(node) is False
    resume_state.request_graceful_stop(node)
    assert resume_state.stop_requested(node) is True

    with pytest.raises(interrupt_type):
        resume_state.raise_graceful_stop(node)

    assert state["raised"] is True
    # Flag consumed and the manifest records a stopped (resumable) run.
    assert resume_state.stop_requested(node) is False
    status = resume_state.resume_status(node)
    assert status["state"] == "stopped"
    assert status["done"] == [0, 1]
    assert status["next"] == 2


def test_clear_run_removes_caches_and_manifest(out_dir) -> None:
    import torch

    from mmx_pkg.director import segment_cache
    from mmx_pkg.director.plan import DirectorPlan, SegmentPlan

    node = _node_id()
    seg = SegmentPlan(
        index=0, start_frame=0, end_frame=4, prompt="p", task_type="t2v",
        task_key="t2v", use_global=True,
    )
    plan = DirectorPlan(
        frame_rate=24.0, total_frames=4, width=64, height=64, ref_max_size=64,
        output_mode="fixed", source_width=64, source_height=64,
        global_task_type="t2v", global_task_key="t2v", global_prompt="",
        global_refs=[], segments=[seg], source_video=torch.zeros((1, 3, 8, 8)),
        edit_mode="segment", raw={},
    )
    segment_cache.save_segment_cache(node, seg, plan, torch.zeros((4, 64, 64, 3)))
    resume_state.begin_run(node, 1, reset_done=True)
    resume_state.mark_segment_done(node, 0, 0)

    assert segment_cache.segment_cache_status(node, seg, plan) == "hit"
    assert resume_state.resume_status(node)["done"] == [0]

    existed = resume_state.clear_run(node)
    assert existed is True
    assert resume_state.resume_status(node)["done"] == []
    assert segment_cache.segment_cache_status(node, seg, plan) == "missing"


def test_clear_stop_request_noop_without_node(out_dir) -> None:
    resume_state.request_graceful_stop(None)
    assert resume_state.stop_requested(None) is False
