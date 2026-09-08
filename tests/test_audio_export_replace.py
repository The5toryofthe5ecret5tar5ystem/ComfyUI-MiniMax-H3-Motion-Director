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
