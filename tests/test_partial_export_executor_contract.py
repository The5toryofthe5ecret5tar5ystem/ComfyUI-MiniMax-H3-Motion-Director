"""Wiring contract for partial export on Stop.

``director/partial_export.py`` holds the decision and is unit-tested on its own.
These tests guard the executor wiring, which cannot be exercised without a GPU and
a full model load, so they read the source the way the other handoff contracts in
this repo do.

The two things that must not silently regress:

* Stop must leave the segment loop instead of aborting, or partial export never
  happens.
* A stopped run must present itself as partial to the node's finalize step, or the
  merged video is padded back out to the full requested length.
"""

from __future__ import annotations

from pathlib import Path

import pytest

EXECUTOR = "director/executor_core_legacy.py"


def _source() -> str:
    return Path(EXECUTOR).read_text(encoding="utf-8")


def _stop_block() -> str:
    source = _source()
    start = source.index("if resume_state.stop_requested(node_id):")
    end = source.index("if seg.index in run_indices:")
    return source[start:end]


# ---------------------------------------------------------------------------
# Stop leaves the loop
# ---------------------------------------------------------------------------


def test_stop_breaks_out_of_the_segment_loop_instead_of_aborting():
    block = _stop_block()
    assert "stopped_early = True" in block
    assert "break" in block
    # The old behaviour threw the finished prefix away.
    assert "raise_graceful_stop" not in block


def test_stop_still_records_the_run_state_and_clears_the_request():
    block = _stop_block()
    assert 'resume_state.mark_run_state(node_id, "stopped")' in block
    assert "resume_state.clear_stop_request(node_id)" in block


def test_comfyui_cancel_is_not_swallowed():
    # ComfyUI's own Cancel must still hard-abort: we never catch its interrupt.
    source = _source()
    assert "except InterruptProcessingException" not in source
    assert "except model_management.InterruptProcessingException" not in source


def test_nothing_completed_falls_back_to_the_original_cancel():
    source = _source()
    guard = source[source.index("if stopped_early and not ["):]
    guard = guard[:guard.index("partial_export = None")]
    assert "resume_state.raise_graceful_stop(node_id)" in guard


# ---------------------------------------------------------------------------
# The run narrows to the finished prefix
# ---------------------------------------------------------------------------


def test_run_is_narrowed_through_the_pure_decision_function():
    source = _source()
    block = source[source.index("if stopped_early:"):source.index("def _report_resolved_preview")]
    assert "from .partial_export import narrow_to_completed_prefix" in block
    assert "run_list = partial_export.run_list" in block
    assert "run_indices = partial_export.run_indices" in block
    assert "source_bridge_pairs = partial_export.bridge_pairs" in block


def test_reports_surface_the_partial_result():
    source = _source()
    block = source[source.index("if stopped_early:"):source.index("def _report_resolved_preview")]
    assert "reports.extend(partial_export.report_lines())" in block
    assert "warning_messages.append(partial_export.warning())" in block


# ---------------------------------------------------------------------------
# Assembly tolerates a partial prefix
# ---------------------------------------------------------------------------


def _assembly_block() -> str:
    """The full-export branch of the assembly step, not the earlier mode checks."""
    source = _source()
    block = source[source.index("missing_all = "):]
    return block[:block.index("        export_chunks = segment_outputs")]


def test_full_export_check_spares_a_stopped_run():
    assert "if missing_all and not stopped_early:" in _assembly_block()


def test_export_lists_are_built_from_what_was_produced():
    block = _assembly_block()
    assert "export_segments = [seg for seg in all_segments if int(seg.index) in all_export_results]" in block
    # The old form assumed every segment existed.
    assert "export_chunks = [all_export_results[int(seg.index)][0] for seg in all_segments]" not in block


# ---------------------------------------------------------------------------
# The plan must describe the partial run, and resume must stay intact
# ---------------------------------------------------------------------------


def test_stopped_run_reports_the_plan_as_partial():
    source = _source()
    tail = source[source.index("if stopped_early:\n        # Present the plan as a partial run"):]
    tail = tail[:tail.index("return combined, segment_outputs")]
    # finalize_director_outputs pads the merged video to plan.total_frames and
    # labels the saved file from plan.run_indices.
    assert "plan.run_indices = partial_export.run_indices" in tail
    assert "plan.total_frames = sum(" in tail


def test_run_is_not_marked_done_when_stopped():
    source = _source()
    assert 'resume_state.mark_run_state(node_id, "stopped" if stopped_early else "done")' in source


def test_stop_never_clears_the_resume_manifest():
    # Resume must still start at the first unfinished segment after a Stop.
    source = _source()
    assert "resume_state.clear_run(" not in source
    stop_start = source.index("if resume_state.stop_requested(node_id):")
    block = source[stop_start:source.index("def _report_resolved_preview")]
    assert "mark_segment_done" not in block


@pytest.mark.parametrize("forbidden", ["resume_state.clear_run", "reset_done=True"])
def test_partial_export_does_not_reset_progress(forbidden: str):
    source = _source()
    block = source[source.index("if stopped_early:"):source.index("def _report_resolved_preview")]
    assert forbidden not in block
