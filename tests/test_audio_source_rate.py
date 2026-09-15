# Regression tests for the source-audio sample-rate label bug.
#
# `_load_full_audio` decodes the source track with ffmpeg at the probed rate.
# The stderr re-parse used to fall back to a hardcoded 44100 whenever ffmpeg
# printed nothing (always, under `-v error`), which overrode the correct probed
# rate: a 48 kHz source was relabelled 44.1 kHz, so the replace-window
# passthrough track played ~9% slow, pitch-dropped and truncated. The parser
# must return (0, 0) when nothing is parseable and only a parsed value may win.

from __future__ import annotations

import types

import torch

import lib.audio_io as aio


class _FakeCompleted:
    def __init__(self, stdout: bytes, stderr: bytes = b""):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = 0


def _fake_run(stdout: bytes, stderr: bytes = b""):
    def run(*args, **kwargs):
        return _FakeCompleted(stdout, stderr)

    return run


def test_parse_ffmpeg_audio_info_empty_returns_zero():
    assert aio._parse_ffmpeg_audio_info("") == (0, 0)


def test_parse_ffmpeg_audio_info_reads_stream_line():
    line = "Stream #0:1[0x2](und): Audio: aac (LC), 48000 Hz, stereo, fltp, 128 kb/s"
    assert aio._parse_ffmpeg_audio_info(line) == (48000, 2)


def test_load_full_audio_keeps_probed_rate_when_stderr_is_empty(tmp_path, monkeypatch):
    aio._FULL_AUDIO_CACHE.clear()
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"stub")
    monkeypatch.setattr(aio, "_probe_audio_stream", lambda p: (48000, 2))
    monkeypatch.setattr(aio, "_ffmpeg_bin", lambda: "ffmpeg")
    samples = 48000  # one second of stereo f32
    stdout = torch.zeros(2 * samples, dtype=torch.float32).numpy().tobytes()
    monkeypatch.setattr(aio, "subprocess", types.SimpleNamespace(run=_fake_run(stdout)))

    out = aio._load_full_audio(str(path))

    assert out is not None
    assert out["sample_rate"] == 48000
    assert out["waveform"].shape == (1, 2, samples)


def test_load_full_audio_accepts_ffmpeg_printed_rate(tmp_path, monkeypatch):
    aio._FULL_AUDIO_CACHE.clear()
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"stub")
    monkeypatch.setattr(aio, "_probe_audio_stream", lambda p: (48000, 2))
    monkeypatch.setattr(aio, "_ffmpeg_bin", lambda: "ffmpeg")
    stdout = torch.zeros(2 * 44100, dtype=torch.float32).numpy().tobytes()
    line = b"Stream #0:1: Audio: aac, 44100 Hz, stereo, fltp, 128 kb/s"
    monkeypatch.setattr(aio, "subprocess", types.SimpleNamespace(run=_fake_run(stdout, line)))

    out = aio._load_full_audio(str(path))

    assert out is not None
    assert out["sample_rate"] == 44100
