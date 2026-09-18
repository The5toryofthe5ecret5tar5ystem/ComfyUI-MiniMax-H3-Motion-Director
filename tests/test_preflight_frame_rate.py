"""Pre-flight warning when the project rate is not H3's fixed 24 fps.

MiniMax H3 has no fps input - the frame count *is* the duration, and the joint
video+audio latent is defined at 24 fps (ComfyUI's own H3 nodes say so: the grid
is "at 24 fps", and a ref2va reference video is "reference video frames at 24
fps"). A project at any other rate therefore hands N frames of e.g. 30 fps
footage to the model as N frames, which come back as 24 fps content: the picture
plays 25% slow, the segment audio (trimmed at the project rate) is short, and the
merged export is stamped with the project rate while each clip is written at 24.

The validator is the only place that can say this before the GPU bill, so these
tests pin the warning, the quiet case, and the fact that it never blocks a run.
"""

from __future__ import annotations

import pytest

try:
    from mmx_pkg.director.preflight import _static_checks
except ImportError as exc:  # pragma: no cover - environment guard
    pytest.skip(f"Director package unavailable: {exc}", allow_module_level=True)


def _timeline(**extra) -> dict:
    timeline = {
        "replaceMode": True,
        "frameRate": 24,
        "totalFrames": 1137,
        "video": {"videoFile": "source.mp4", "sourceFrameCount": 1137},
        "segments": [
            {"id": "s1", "start": 0, "length": 240, "frameCount": 240, "prompt": "a prompt"},
        ],
    }
    timeline.update(extra)
    return timeline


def _issues(timeline: dict) -> list:
    issues: list = []
    _static_checks(timeline, "rv2v", issues)
    return issues


def _fps_issues(issues: list) -> list:
    return [item for item in issues if item.get("code") == "frame_rate_not_24"]


def test_a_24_fps_project_is_quiet():
    assert _fps_issues(_issues(_timeline(frameRate=24))) == []


@pytest.mark.parametrize("fps", [30, 29.97, 25, 60, 12, 23.976])
def test_any_other_rate_warns(fps):
    found = _fps_issues(_issues(_timeline(frameRate=fps)))
    assert len(found) == 1, fps
    assert found[0]["severity"] == "warning", "a valid render with the wrong speed, not a blocker"


def test_the_warning_states_what_changes():
    """The numbers are the point: they are what the user can check afterwards."""
    message = _fps_issues(_issues(_timeline(frameRate=30)))[0]["message"]

    assert "30 fps" in message
    assert "24 fps" in message
    assert "1.25x slow" in message
    assert "silence" in message, "the segment audio is trimmed at the project rate"
    assert "merged export is stamped" in message


def test_a_faster_project_reads_as_fast():
    message = _fps_issues(_issues(_timeline(frameRate=12)))[0]["message"]
    assert "0.50x fast" in message


def test_the_source_rate_is_read_when_the_timeline_omits_it():
    """Older payloads carry the rate on the video block only."""
    timeline = _timeline(frameRate=None)
    timeline.pop("frameRate")
    timeline["video"] = {"videoFile": "source.mp4", "sourceFrameCount": 1137, "fps": 30}

    assert len(_fps_issues(_issues(timeline))) == 1


def test_a_missing_or_broken_rate_does_not_crash_the_validator():
    for value in (None, "", "auto", 0, -30):
        timeline = _timeline(frameRate=value)
        assert _fps_issues(_issues(timeline)) == [], repr(value)
