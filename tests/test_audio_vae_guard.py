"""Offline tests for the H3 reference-audio encode guard (no GPU / no ComfyUI).

The module under test only imports ``torch`` at import time; ComfyUI/``comfy``
and ``comfy_extras`` are imported lazily, so the pure chunk math and the OOM
fallback can be exercised with fakes in a plain test environment.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest
import torch

PATH = Path(__file__).parents[1] / "director" / "audio_vae_guard.py"
spec = importlib.util.spec_from_file_location("audio_vae_guard_under_test", PATH)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def _loud_oom():
    return RuntimeError("CUDA out of memory. Tried to allocate 512.00 MiB (GPU 0)")


class FakeFirstStage:
    """Mimics comfy.ldm.minimax.audio_vae.MiniMaxH3AudioVAE.encode():

    input ``[1, 2, L]`` channels-first -> normalized latents ``[1, 32, 2, L/800]``.
    ``oom_samples`` raises a CUDA OOM when the segment is longer than the limit.
    """

    def __init__(self, oom_samples=None):
        self.oom_samples = oom_samples
        self.calls = []

    def encode(self, x):
        length = int(x.shape[-1])
        if self.oom_samples is not None and length > self.oom_samples:
            raise _loud_oom()
        self.calls.append(length)
        t = -(-length // mod._HOP)  # real first stage right-pads to the hop (ceil)
        out = torch.zeros(1, 32, 2, t)
        out[..., 0, 0, :] = float(x[:, 0, 0].sum().item())  # weak identity marker
        return out


def _fake_vae(first_stage, sample_rate=32000):
    return types.SimpleNamespace(
        first_stage_model=first_stage,
        audio_sample_rate=sample_rate,
        device=None,
        output_device=None,
    )


def _audio(wave, sample_rate=32000):
    return {"waveform": wave, "sample_rate": sample_rate}


def test_pad_to_hop():
    wave = torch.zeros(1, 2, 800 * 3 + 17)
    padded = mod.pad_to_hop(wave)
    assert padded.shape[-1] == 800 * 4
    wave2 = torch.zeros(1, 2, 800 * 4)
    assert mod.pad_to_hop(wave2) is wave2


def test_chunked_encode_latents_total_length_with_warmup():
    total_lat = 130
    wave = torch.zeros(1, 2, total_lat * mod._HOP)
    fs = FakeFirstStage()

    def encode_one(seg):
        return fs.encode(seg)

    z = mod.chunked_encode_latents(encode_one, wave, chunk_lat=60, warmup_lat=10)
    assert z.shape[-1] == total_lat
    # first chunk full 60; every later chunk (including the final 10-latent
    # remainder) carries 10 warm-up latents that are dropped before joining
    assert fs.calls == [60 * mod._HOP, (60 + 10) * mod._HOP, (10 + 10) * mod._HOP]


def test_encode_reference_audio_happy_path_untiled():
    fs = FakeFirstStage(oom_samples=None)
    av = _fake_vae(fs)
    length = 800 * 37 + 123  # not hop-aligned -> pads to 38 latents
    wave = torch.zeros(1, 2, length)
    z, t = mod.encode_reference_audio(av, _audio(wave))
    assert t == 38
    assert z.shape == (1, 32, 2, t)
    # exactly one untiled attempt when it fits
    assert fs.calls == [length]


def test_encode_reference_audio_oom_falls_back_chunked():
    # Anything over ~1 s OOMs untiled, so the full 82-latent file must chunk.
    oom_limit = 60 * mod._HOP
    fs = FakeFirstStage(oom_samples=oom_limit)
    av = _fake_vae(fs)
    total_lat = 82
    wave = torch.zeros(1, 2, total_lat * mod._HOP)
    z, t = mod.encode_reference_audio(av, _audio(wave))
    assert t == total_lat
    assert z.shape == (1, 32, 2, t)
    # every attempted segment stayed within the OOM limit
    assert all(c <= oom_limit for c in fs.calls)
    assert len(fs.calls) > 1


def test_encode_reference_audio_resamples_when_sr_mismatch():
    torchaudio = pytest.importorskip("torchaudio")
    fs = FakeFirstStage(oom_samples=None)
    av = _fake_vae(fs, sample_rate=32000)
    # 48000 Hz source, ~1 s -> resampled to 32000 Hz
    wave = torch.zeros(1, 2, 48000)
    z, t = mod.encode_reference_audio(av, _audio(wave, sample_rate=48000))
    assert t == 40  # 32000 samples / 800 per latent
    assert z.shape == (1, 32, 2, t)


def test_install_replaces_stock_encode_ref_audio(monkeypatch):
    h3 = types.ModuleType("nodes_minimax_h3_stub")
    h3._encode_ref_audio = lambda av, audio: ("stock", 0)

    def fake_import(name):
        assert name == "comfy_extras"
        pkg = types.ModuleType("comfy_extras")
        pkg.nodes_minimax_h3 = h3
        sys.modules["comfy_extras"] = pkg
        sys.modules["comfy_extras.nodes_minimax_h3"] = h3
        return pkg

    monkeypatch.setattr(mod, "_INSTALLED", False)
    original_import = __import__

    def patched_import(name, *args, **kwargs):
        if name == "comfy_extras":
            return fake_import(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", patched_import)
    mod.install_audio_vae_guard()
    assert mod._INSTALLED is True
    assert h3._encode_ref_audio is not None
    fs = FakeFirstStage(oom_samples=None)
    av = _fake_vae(fs)
    wave = torch.zeros(1, 2, 800 * 10)
    z, t = h3._encode_ref_audio(av, _audio(wave))
    assert t == 10
