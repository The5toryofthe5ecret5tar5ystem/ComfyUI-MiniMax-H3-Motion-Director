"""Plan-aware audio room application (director.audio_refine).

Pins the two properties that make this stage worth having:

* a scene's own ``room`` wins over the global one, so a bathroom scene and a
  bedroom scene in one render do not share a space, and
* a track that cannot be processed is kept dry and *reported*, never silently
  passed through as if it had worked.
"""

from __future__ import annotations

from types import SimpleNamespace

import torch

import mmx_pkg.nodes.director_common as director_common
from mmx_pkg.director.audio_refine import (
    apply_plan_audio_refine,
    scene_room_for,
    segment_order_for,
)
from mmx_pkg.director.audio_refine_config import normalize_audio_refine

HAVE_SOX = __import__("shutil").which("sox") is not None
import pytest

needs_sox = pytest.mark.skipif(not HAVE_SOX, reason="SoX is not installed")

SAMPLE_RATE = 32000


def _plan(raw_segments=None, *, segments=None, run_indices=None):
    raw_segments = list(raw_segments if raw_segments is not None else [])
    if segments is None:
        # plan.segments is the source of truth for how many outputs there are and
        # which scene each one belongs to, so keep it consistent with the raw
        # timeline the way a real build does.
        segments = [_segment(i) for i in range(len(raw_segments))]
    return SimpleNamespace(
        raw={"segments": raw_segments},
        global_task_key="t2v",
        export_mode="all",
        total_frames=24,
        frame_rate=24.0,
        segments=list(segments),
        run_indices=run_indices,
        mixed_mode=False,
    )


def _segment(index=0):
    return SimpleNamespace(index=index, start_frame=0, end_frame=24, frame_count=24)


def _audio(samples=4000):
    t = torch.arange(samples, dtype=torch.float32) / SAMPLE_RATE
    return {
        "waveform": torch.stack([torch.sin(2 * torch.pi * 440 * t), torch.sin(2 * torch.pi * 660 * t)]).unsqueeze(0),
        "sample_rate": SAMPLE_RATE,
    }


def _active(**overrides):
    return normalize_audio_refine({"enabled": True, "room": "hall", **overrides})


# --------------------------------------------------------------------------
# Reading the per-scene field
# --------------------------------------------------------------------------


def test_scene_room_reads_snake_and_camel_forms():
    plan = _plan([{"room": "bathroom"}, {"roomPreset": "bedroom"}, {"room_preset": "car"}])
    assert scene_room_for(plan, 0) == "bathroom"
    assert scene_room_for(plan, 1) == "bedroom"
    assert scene_room_for(plan, 2) == "car"


@pytest.mark.parametrize("index", [None, "x", -1, 99])
def test_scene_room_is_blank_for_unusable_indices(index):
    plan = _plan([{"room": "bathroom"}])
    assert scene_room_for(plan, index) == ""


def test_scene_room_tolerates_a_non_dict_segment():
    assert scene_room_for(_plan(["not a dict"]), 0) == ""


def test_scene_room_is_blank_when_the_timeline_has_no_segments_key():
    plan = SimpleNamespace(raw={"somethingElse": True})
    assert scene_room_for(plan, 0) == ""


def test_segment_order_follows_a_partial_run():
    """A resume run must attribute each track to its real scene, not slot 0..n."""
    plan = _plan([{}] * 6, segments=[_segment(i) for i in range(6)], run_indices=[4, 5])
    assert segment_order_for(plan, 2) == [4, 5]


def test_segment_order_is_identity_without_a_partial_run():
    plan = _plan([{}] * 3, segments=[_segment(i) for i in range(3)])
    assert segment_order_for(plan, 3) == [0, 1, 2]


def test_segment_order_pads_with_none_beyond_the_plan():
    plan = _plan([{}] * 2, segments=[_segment(0), _segment(1)])
    assert segment_order_for(plan, 4) == [0, 1, None, None]


# --------------------------------------------------------------------------
# Inactive paths
# --------------------------------------------------------------------------


def test_disabled_config_returns_tracks_untouched():
    audios = [_audio()]
    out, note = apply_plan_audio_refine(_plan(), audios, config={"enabled": False})
    assert out == audios
    assert note == ""


def test_empty_audio_list_is_a_noop():
    out, note = apply_plan_audio_refine(_plan(), [], config=_active())
    assert out == [] and note == ""


def test_non_list_audio_slot_passes_straight_through():
    """A tensor slot must not be iterated, and must not raise on truthiness."""
    tensor = torch.zeros(1, 2, 16)
    out, note = apply_plan_audio_refine(_plan(), tensor, config=_active())
    assert out is tensor and note == ""


def test_none_audio_slot_passes_straight_through():
    out, note = apply_plan_audio_refine(_plan(), None, config=_active())
    assert out is None and note == ""


def test_dry_room_reports_nothing():
    out, note = apply_plan_audio_refine(
        _plan([{}]), [_audio()], config=_active(room="dry", reverb_enabled=False)
    )
    assert note == ""


# --------------------------------------------------------------------------
# Per-scene application
# --------------------------------------------------------------------------


@needs_sox
def test_each_scene_gets_its_own_room():
    """Two scenes, two different spaces, in one call."""
    plan = _plan([{"room": "bathroom"}, {"room": "cathedral"}])
    dry = _audio()
    out, note = apply_plan_audio_refine(plan, [dry, dry], config=_active())

    assert len(out) == 2
    assert not torch.allclose(out[0]["waveform"], dry["waveform"])
    assert not torch.allclose(out[1]["waveform"], dry["waveform"])
    # A cathedral tail is a different space from a tiled bathroom.
    assert not torch.allclose(out[0]["waveform"], out[1]["waveform"])
    assert "bathroom" in note and "cathedral" in note


@needs_sox
def test_scene_without_a_room_falls_back_to_the_global_choice():
    plan = _plan([{"room": "bathroom"}, {}])
    dry = _audio()
    out, _ = apply_plan_audio_refine(plan, [dry, dry], config=_active(room="hall"))
    # Slot 1 uses the global hall, so both tracks are processed and differ.
    assert not torch.allclose(out[0]["waveform"], out[1]["waveform"])


@needs_sox
def test_channels_and_length_survive_the_plan_level_application():
    plan = _plan([{"room": "bar"}])
    out, _ = apply_plan_audio_refine(plan, [_audio(samples=5000)], config=_active())
    assert tuple(out[0]["waveform"].shape) == (1, 2, 5000)


# --------------------------------------------------------------------------
# Failure handling
# --------------------------------------------------------------------------


def test_a_failing_track_is_kept_dry_and_reported():
    """Never the third-party node's silent `return original`."""
    plan = _plan([{"room": "bathroom"}])
    dry = _audio()
    out, note = apply_plan_audio_refine(
        plan, [dry], config=_active(sox_path="/bin/false")
    )

    assert out[0] is dry, "a failed track must be left untouched, not half-written"
    assert "DRY" in note
    assert "0 track(s)" not in note


def test_partial_failure_still_reports_the_tracks_that_worked():
    # A nonexistent path fails for every track; the report names the reason.
    _, note = apply_plan_audio_refine(
        _plan([{"room": "bathroom"}, {"room": "hall"}]),
        [_audio(), _audio()],
        config=_active(sox_path="/nonexistent/sox"),
    )
    assert "2 track(s) left DRY" in note


def test_missing_scene_attribution_falls_back_to_the_global_room():
    """When the output slot cannot be tied to a scene, the global room applies."""
    plan = _plan()  # no raw segments, so no per-scene room is available
    _, note = apply_plan_audio_refine(plan, [], config=_active(room="bathroom"))
    assert note == ""


# --------------------------------------------------------------------------
# Director wiring
# --------------------------------------------------------------------------


@needs_sox
def test_finalize_processor_precedes_the_merge(monkeypatch):
    """Model audio must be processed before the merge, or a merged export can
    only ever carry one room for the whole clip."""
    seen: list = []

    def spy(plan, audios, *, config, indices=None):
        seen.append(list(audios))
        return audios, "\n\nAudio room: spied."

    monkeypatch.setattr(director_common, "apply_plan_audio_refine", spy)
    monkeypatch.setattr(
        director_common,
        "build_director_audio_outputs",
        lambda *a, **k: ([_audio()], None),
    )

    segment_audio = _audio()
    _, _, _, _, _, report = director_common.finalize_director_outputs(
        _plan([{}], segments=[_segment(0)]),
        torch.zeros(24, 8, 8, 3),
        [torch.zeros(24, 8, 8, 3)],
        "",
        segment_audios=[segment_audio],
        postprocess={"audio_refine": _active(room="bathroom")},
    )

    assert seen and seen[0][0] is segment_audio
    assert "Audio room: spied." in report


def test_finalize_without_postprocess_is_unchanged(monkeypatch):
    """Existing callers that pass no postprocess must behave exactly as before."""
    monkeypatch.setattr(
        director_common,
        "build_director_audio_outputs",
        lambda *a, **k: ([_audio()], None),
    )
    _, audio_out, _, _, _, report = director_common.finalize_director_outputs(
        _plan([{}], segments=[_segment(0)]),
        torch.zeros(24, 8, 8, 3),
        [torch.zeros(24, 8, 8, 3)],
        "",
        segment_audios=[_audio()],
    )
    assert len(audio_out) == 1
    assert "Audio room" not in report
