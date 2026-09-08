"""Replace windows preserve user (drag) order through the plan builder."""

from __future__ import annotations

from mmx_pkg.director.plan import _segment_ranges_from_timeline


def _ids(ranges):
    return [r[2].get("id") for r in ranges]


def test_replace_mode_preserves_user_order():
    timeline = {
        "replaceMode": True,
        "segments": [
            {"start": 500, "length": 100, "id": "b"},
            {"start": 10, "length": 60, "id": "a"},
            {"start": 300, "length": 175, "id": "c"},
        ],
    }
    # User order (list order) is kept - NOT re-sorted by start.
    assert _ids(_segment_ranges_from_timeline(timeline, 1000)) == ["b", "a", "c"]


def test_tiled_mode_still_sorts_by_start():
    timeline = {
        "segments": [
            {"start": 500, "length": 100, "id": "b"},
            {"start": 10, "length": 60, "id": "a"},
            {"start": 300, "length": 175, "id": "c"},
        ],
    }
    # Normal (tiled) timelines keep the old frame-sorted behavior.
    assert _ids(_segment_ranges_from_timeline(timeline, 1000)) == ["a", "c", "b"]
