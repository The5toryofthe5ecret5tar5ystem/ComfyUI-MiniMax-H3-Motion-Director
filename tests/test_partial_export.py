"""Cooperative Stop must export the finished prefix instead of discarding it.

Stopping a Motion Director run used to raise ComfyUI's interrupt the moment the
request was read, so a 10-segment render stopped at 3 produced nothing at all and
the finished work was only reachable through Resume. The executor now leaves the
segment loop and assembles what completed.

These tests pin the decision function that narrows the run. The invariant that
matters most is that an uninterrupted run is returned untouched -- Stop is the
only thing that may shrink a run.
"""

from __future__ import annotations

import pytest

from mmx_pkg.director.partial_export import (
    PartialExport,
    narrow_to_completed_prefix,
)


class _Seg:
    """Minimal stand-in for a SegmentPlan in a Source Bridge pair."""

    def __init__(self, index: int) -> None:
        self.index = index


def _pair(left: int, right: int) -> tuple[_Seg, _Seg]:
    return (_Seg(left), _Seg(right))


def _pair_indices(pairs) -> list[tuple[int, int]]:
    return [(int(left.index), int(right.index)) for left, right in pairs]


# ---------------------------------------------------------------------------
# Uninterrupted runs must be untouched
# ---------------------------------------------------------------------------


def test_complete_run_keeps_every_segment_and_bridge():
    pairs = [_pair(0, 1), _pair(1, 2), _pair(2, 3)]
    result = narrow_to_completed_prefix(
        run_list=[0, 1, 2, 3],
        completed={0, 1, 2, 3},
        bridge_pairs=pairs,
        segment_total=4,
    )
    assert result.run_list == [0, 1, 2, 3]
    assert result.run_indices == frozenset({0, 1, 2, 3})
    assert _pair_indices(result.bridge_pairs) == [(0, 1), (1, 2), (2, 3)]
    assert result.unsampled == []
    assert result.usable is True


def test_complete_run_is_byte_identical_to_the_request():
    # Nothing about a normal run may change because Stop exists.
    run_list = list(range(7))
    result = narrow_to_completed_prefix(
        run_list=run_list, completed=set(run_list), segment_total=7,
    )
    assert result.run_list == run_list
    assert result.run_indices == frozenset(run_list)


# ---------------------------------------------------------------------------
# A stopped run exports the finished prefix only
# ---------------------------------------------------------------------------


def test_stopped_run_keeps_only_the_finished_prefix():
    result = narrow_to_completed_prefix(
        run_list=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
        completed={0, 1, 2},
        segment_total=10,
    )
    assert result.run_list == [0, 1, 2]
    assert result.run_indices == frozenset({0, 1, 2})
    assert result.unsampled == [3, 4, 5, 6, 7, 8, 9]
    assert result.usable is True


def test_nothing_completed_is_not_usable():
    # The executor falls back to the original hard cancel in this case.
    result = narrow_to_completed_prefix(
        run_list=[0, 1, 2], completed=set(), segment_total=3,
    )
    assert result.run_list == []
    assert result.usable is False
    assert result.unsampled == [0, 1, 2]


def test_resume_manifest_cannot_be_widened():
    # Only already-completed segments may be exported, whatever is requested.
    result = narrow_to_completed_prefix(
        run_list=[1, 3],
        completed={0, 1, 2, 3},
        segment_total=4,
    )
    assert result.run_indices <= frozenset({1, 3})
    assert result.run_list == [1, 3]


def test_offset_run_selection_narrows_in_run_order():
    result = narrow_to_completed_prefix(
        run_list=[4, 5, 6, 7],
        completed={5, 4, 9},
        segment_total=10,
    )
    assert result.run_list == [4, 5]
    assert result.unsampled == [6, 7]


def test_out_of_order_completion_is_reported_in_run_order():
    result = narrow_to_completed_prefix(
        run_list=[0, 1, 2, 3],
        completed={2, 0},
        segment_total=4,
    )
    assert result.run_list == [0, 2]


# ---------------------------------------------------------------------------
# Source Bridges need both sides
# ---------------------------------------------------------------------------


def test_bridges_crossing_the_stop_point_are_dropped():
    pairs = [_pair(0, 1), _pair(1, 2), _pair(2, 3)]
    result = narrow_to_completed_prefix(
        run_list=[0, 1, 2, 3],
        completed={0, 1},
        bridge_pairs=pairs,
        segment_total=4,
    )
    # 1->2 and 2->3 reference a segment that never ran.
    assert _pair_indices(result.bridge_pairs) == [(0, 1)]


def test_bridge_list_defaults_to_empty():
    result = narrow_to_completed_prefix(run_list=[0], completed={0}, segment_total=1)
    assert result.bridge_pairs == []


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def test_report_uses_one_based_numbers_and_the_plan_total():
    result = narrow_to_completed_prefix(
        run_list=list(range(10)), completed={0, 1, 2}, segment_total=10,
    )
    report = "\n".join(result.report_lines())
    assert "STOPPED (partial export)" in report
    assert "1, 2, 3" in report
    assert "(3 of 10)" in report
    assert "Resume" in report


def test_warning_names_the_kept_segments():
    result = narrow_to_completed_prefix(
        run_list=[0, 1, 2], completed={0, 1, 2}, segment_total=3,
    )
    assert "1, 2, 3" in result.warning()
    assert "completed prefix" in result.warning()


def test_summary_is_machine_readable():
    result = narrow_to_completed_prefix(
        run_list=list(range(5)), completed={0, 1}, segment_total=5,
    )
    assert result.summary() == {
        "completed": [1, 2],
        "completed_count": 2,
        "segment_total": 5,
        "unsampled": [3, 4, 5],
    }


def test_segment_total_is_preserved_for_reporting():
    # The plan total must survive narrowing, or the UI would claim 3 of 3.
    result = narrow_to_completed_prefix(
        run_list=[0, 1, 2], completed={0}, segment_total=3,
    )
    assert result.segment_total == 3


def test_partial_export_is_immutable():
    result: PartialExport = narrow_to_completed_prefix(
        run_list=[0, 1], completed={0}, segment_total=2,
    )
    with pytest.raises(Exception):
        result.run_list = [9]  # type: ignore[misc]
