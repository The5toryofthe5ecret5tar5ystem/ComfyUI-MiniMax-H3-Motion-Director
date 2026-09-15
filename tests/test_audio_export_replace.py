"""Export-all source audio for Character Replace windows (director.audio_export, CPU).

The combined "Export all" clip of replace windows is a back-to-back
concatenation of independent source ranges, so its source audio must be the
per-window tracks stitched in window order - not source[0:end].
"""

from __future__ import annotations

from types import SimpleNamespace

import torch

import mmx_pkg.director.audio_export as audio_export
from mmx_pkg.director.audio_export import build_director_audio_outputs

FPS = 30.0


def _fake_plan(replace: bool, segments: list):
    return SimpleNamespace(
        frame_rate=FPS,
        total_frames=81201,
        raw={"replaceMode": True} if replace else {},
        segments=segments,
        run_indices=None,
    )


def _fake_seg(start, end, replace_enabled=True):
    return SimpleNamespace(
        start_frame=start,
        end_frame=end,
        frame_count=end - start,
        replace=SimpleNamespace(enabled=replace_enabled) if replace_enabled is not None else None,
        index=0,
    )


def _wave_for(frames: int):
    samples = int(round(frames * 44100 / FPS))
    return {"waveform": torch.zeros(1, 2, samples), "sample_rate": 44100}


def test_replace_export_all_extracts_each_window_track(monkeypatch):
    segs = [_fake_seg(100, 200), _fake_seg(500, 600)]
    plan = _fake_plan(replace=True, segments=segs)
    combined = torch.zeros(200, 8, 8, 3)  # 100 + 100 frames

    calls: list[tuple[int, int]] = []

    def fake_extract(timeline, start, end, fps):
        calls.append((int(start), int(end)))
        return _wave_for(int(end) - int(start))

    monkeypatch.setattr(audio_export, "extract_timeline_audio", fake_extract)
    out, fallback = build_director_audio_outputs(
        plan,
        [combined],
        export_segments=False,
        output_frame_end=int(combined.shape[0]),
        segment_audios=None,
        audio_mode="source",
        mute_audio=False,
    )
    # Each window's own source range is requested; never source[0:combined_len].
    assert calls == [(100, 200), (500, 600)]
    assert fallback is None
    assert len(out) == 1
    assert int(out[0]["waveform"].shape[-1]) == int(round(200 * 44100 / FPS))


def test_non_replace_export_all_keeps_source_from_zero(monkeypatch):
    # Normal contiguous timelines (single source from 0) must keep [0, end].
    segs = [_fake_seg(0, 100, replace_enabled=None), _fake_seg(100, 200, replace_enabled=None)]
    plan = _fake_plan(replace=False, segments=segs)
    combined = torch.zeros(200, 8, 8, 3)

    calls: list[tuple[int, int]] = []

    def fake_extract(timeline, start, end, fps):
        calls.append((int(start), int(end)))
        return _wave_for(int(end) - int(start))

    monkeypatch.setattr(audio_export, "extract_timeline_audio", fake_extract)
    build_director_audio_outputs(
        plan,
        [combined],
        export_segments=False,
        output_frame_end=int(combined.shape[0]),
        segment_audios=None,
        audio_mode="source",
        mute_audio=False,
    )
    assert calls == [(0, 200)]


def test_replace_export_all_silent_when_no_window_track(monkeypatch):
    segs = [_fake_seg(100, 200)]
    plan = _fake_plan(replace=True, segments=segs)
    combined = torch.zeros(100, 8, 8, 3)

    def fake_extract(timeline, start, end, fps):
        return None

    monkeypatch.setattr(audio_export, "extract_timeline_audio", fake_extract)
    out, fallback = build_director_audio_outputs(
        plan,
        [combined],
        export_segments=False,
        output_frame_end=int(combined.shape[0]),
        segment_audios=None,
        audio_mode="source",
        mute_audio=False,
    )
    assert fallback == "silent"
    assert len(out) == 1
    # Digital-silence buffer, but still exactly the combined window length.
    wave = out[0]["waveform"]
    assert int(wave.shape[-1]) == int(round(100 * 44100 / FPS))
    assert float(wave.abs().max()) == 0.0


# ---------------------------------------------------------------------------
# Seam fades.
#
# Each window's audio is trimmed to a frame boundary, so it normally stops
# mid-waveform. Concatenating those raw steps straight from one sample into an
# unrelated one, which is audible as a click - and the finished clip's own tail
# has the same problem against the silence that follows it.
# ---------------------------------------------------------------------------


def _ones_for(frames: int):
    samples = int(round(frames * 44100 / FPS))
    return {"waveform": torch.ones(1, 2, samples), "sample_rate": 44100}


def test_merged_replace_audio_fades_window_joins_and_edges(monkeypatch):
    segs = [_fake_seg(100, 200), _fake_seg(500, 600)]
    plan = _fake_plan(replace=True, segments=segs)
    combined = torch.zeros(200, 8, 8, 3)

    monkeypatch.setattr(
        audio_export, "extract_timeline_audio",
        lambda timeline, start, end, fps: _ones_for(int(end) - int(start)),
    )
    out, _ = build_director_audio_outputs(
        plan,
        [combined],
        export_segments=False,
        output_frame_end=int(combined.shape[0]),
        segment_audios=None,
        audio_mode="source",
        mute_audio=False,
    )
    wave = out[0]["waveform"]
    total = int(wave.shape[-1])
    assert total == int(round(200 * 44100 / FPS))

    join = int(round(100 * 44100 / FPS))  # window 1 ends where window 2 begins
    # Head, window join and tail all ramp to zero; nothing steps into silence.
    assert abs(float(wave[0, 0, 0])) < 1e-6
    assert abs(float(wave[0, 0, join - 1])) < 1e-6
    assert abs(float(wave[0, 0, join])) < 1e-6
    assert abs(float(wave[0, 0, -1])) < 1e-6
    # The body of each window is untouched, so the fade does not duck the audio.
    for frame in (50, 150):
        idx = int(round(frame * 44100 / FPS))
        assert abs(float(wave[0, 0, idx]) - 1.0) < 1e-6


def test_non_replace_source_export_fades_its_tail(monkeypatch):
    segs = [_fake_seg(0, 100, replace_enabled=None)]
    plan = _fake_plan(replace=False, segments=segs)
    combined = torch.zeros(100, 8, 8, 3)

    monkeypatch.setattr(
        audio_export, "extract_timeline_audio",
        lambda timeline, start, end, fps: _ones_for(int(end) - int(start)),
    )
    out, _ = build_director_audio_outputs(
        plan,
        [combined],
        export_segments=False,
        output_frame_end=int(combined.shape[0]),
        segment_audios=None,
        audio_mode="source",
        mute_audio=False,
    )
    wave = out[0]["waveform"]
    assert abs(float(wave[0, 0, 0])) < 1e-6
    assert abs(float(wave[0, 0, -1])) < 1e-6
    assert abs(float(wave[0, 0, int(wave.shape[-1]) // 2]) - 1.0) < 1e-6


def test_per_segment_source_export_is_faded(monkeypatch):
    segs = [_fake_seg(0, 100, replace_enabled=None)]
    plan = _fake_plan(replace=False, segments=segs)
    combined = torch.zeros(100, 8, 8, 3)

    monkeypatch.setattr(
        audio_export, "extract_timeline_audio",
        lambda timeline, start, end, fps: _ones_for(int(end) - int(start)),
    )
    out, _ = build_director_audio_outputs(
        plan,
        [combined],
        export_segments=True,
        output_frame_end=int(combined.shape[0]),
        segment_audios=None,
        audio_mode="source",
        mute_audio=False,
    )
    wave = out[0]["waveform"]
    assert abs(float(wave[0, 0, 0])) < 1e-6
    assert abs(float(wave[0, 0, -1])) < 1e-6
