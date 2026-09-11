"""What a stopped run's partial result must survive on the way to the output.

The executor assembles the finished prefix and hands it to the node's
``finalize_director_outputs``. Two things there could resize that prefix, so both
are pinned here against the real functions rather than assumed:

* ``pad_or_trim_frames`` clips to at most ``plan.total_frames`` and never pads, so a
  partial prefix cannot be blown back out to the full requested length.
* The split (segment-export) path passes ``output_frame_end=None`` to the audio
  builder, which falls back to ``plan.total_frames`` - so the executor rewriting
  ``plan.total_frames`` on Stop is what keeps generated audio the same length as
  the video that actually shipped.

Audio plumbing itself is stubbed; the length contract is what is under test.
"""

from __future__ import annotations

from types import SimpleNamespace

import torch

import mmx_pkg.nodes.director_common as director_common
from mmx_pkg.director.frame_align import pad_or_trim_frames

SEG = 124  # 5s @ 24fps, a valid H3 length


def _plan(*, total_frames: int, run_indices, export_mode: str = "all"):
    return SimpleNamespace(
        frame_rate=24.0,
        total_frames=total_frames,
        run_indices=run_indices,
        export_mode=export_mode,
        raw={},
        global_task_key="r2v",
        segments=[],
        width=8,
        height=8,
        mixed_mode=False,
    )


def _stub_audio(monkeypatch) -> list[dict]:
    """Capture the audio-builder call so the length contract can be asserted."""
    calls: list[dict] = []

    def _builder(*args, **kwargs):
        calls.append(kwargs)
        return torch.zeros(1, 2, 64), None

    monkeypatch.setattr(director_common, "build_director_audio_outputs", _builder)
    return calls


def _finalize(plan, combined, segment_outputs):
    return director_common.finalize_director_outputs(
        plan, combined, segment_outputs, "[Final]\nStatus: SUCCESS",
    )


# ---------------------------------------------------------------------------
# Padding is impossible by design
# ---------------------------------------------------------------------------


def test_pad_or_trim_frames_only_ever_trims():
    frames = torch.zeros(SEG, 8, 8, 3)
    # A target far larger than the data must not invent frames.
    assert pad_or_trim_frames(frames, SEG * 3).shape[0] == SEG
    assert pad_or_trim_frames(frames, SEG).shape[0] == SEG
    assert pad_or_trim_frames(frames, SEG - 1).shape[0] == SEG - 1


def test_stale_total_frames_cannot_inflate_a_partial_result(monkeypatch):
    # Even if the plan still asked for 3x the frames, the prefix is what ships.
    _stub_audio(monkeypatch)
    prefix = torch.zeros(SEG, 8, 8, 3)
    plan = _plan(total_frames=SEG * 3, run_indices=frozenset({0}))
    images, _audio, _fps, frame_count, _src, _report = _finalize(plan, prefix, [prefix])
    assert images[0].shape[0] == SEG
    assert frame_count == SEG


def test_partial_plan_keeps_the_produced_length(monkeypatch):
    # What the executor sets plan.total_frames to when stopped at 1 of 3.
    _stub_audio(monkeypatch)
    prefix = torch.zeros(SEG, 8, 8, 3)
    plan = _plan(total_frames=SEG, run_indices=frozenset({0}))
    images, _audio, _fps, frame_count, _src, _report = _finalize(plan, prefix, [prefix])
    assert images[0].shape[0] == SEG
    assert frame_count == SEG


# ---------------------------------------------------------------------------
# Uninterrupted runs are untouched
# ---------------------------------------------------------------------------


def test_complete_run_length_is_unchanged(monkeypatch):
    _stub_audio(monkeypatch)
    full = torch.zeros(SEG * 3, 8, 8, 3)
    plan = _plan(total_frames=SEG * 3, run_indices=frozenset({0, 1, 2}))
    images, _audio, _fps, frame_count, _src, _report = _finalize(plan, full, [full])
    assert images[0].shape[0] == SEG * 3
    assert frame_count == SEG * 3


def test_unselected_run_is_not_resized(monkeypatch):
    # A run-selection ("选择运行") is already its own length; Stop must not alter it.
    _stub_audio(monkeypatch)
    chunk = torch.zeros(SEG, 8, 8, 3)
    plan = _plan(total_frames=SEG, run_indices=frozenset({2}))
    images, _audio, _fps, frame_count, _src, _report = _finalize(plan, chunk, [chunk])
    assert images[0].shape[0] == SEG
    assert frame_count == SEG


# ---------------------------------------------------------------------------
# Segment export returns exactly the produced clips
# ---------------------------------------------------------------------------


def test_segment_export_returns_exactly_the_produced_clips(monkeypatch):
    _stub_audio(monkeypatch)
    chunks = [torch.zeros(SEG, 8, 8, 3), torch.zeros(SEG, 8, 8, 3)]
    plan = _plan(total_frames=SEG * 3, run_indices=frozenset({0, 1}), export_mode="segments")
    images, _audio, _fps, frame_count, _src, _report = _finalize(plan, torch.cat(chunks), chunks)
    assert len(images) == 2
    assert frame_count == SEG * 2


def test_segment_export_audio_falls_back_to_plan_total_frames(monkeypatch):
    # This is why the executor must rewrite plan.total_frames on Stop: on the
    # split path the audio builder gets no explicit end and uses the plan's.
    calls = _stub_audio(monkeypatch)
    chunks = [torch.zeros(SEG, 8, 8, 3)]
    plan = _plan(total_frames=SEG, run_indices=frozenset({0}), export_mode="segments")
    _finalize(plan, torch.cat(chunks), chunks)
    assert calls, "audio builder was not called"
    assert calls[-1]["output_frame_end"] is None
    assert plan.total_frames == SEG


def test_merged_path_pins_audio_to_the_produced_length(monkeypatch):
    # The merged path passes an explicit end, so a stale total cannot stretch audio.
    calls = _stub_audio(monkeypatch)
    prefix = torch.zeros(SEG, 8, 8, 3)
    plan = _plan(total_frames=SEG * 3, run_indices=frozenset({0}))
    _finalize(plan, prefix, [prefix])
    assert calls[-1]["output_frame_end"] == SEG
