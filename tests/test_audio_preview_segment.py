"""Per-segment audio preview payloads (director.progress.report_director_audio_preview)."""

from __future__ import annotations

import sys
import types

import pytest
import torch


@pytest.fixture
def fake_prompt_server(monkeypatch):
    """Stub ComfyUI's ``server`` module so send_sync is captured, not broadcast."""

    class _Instance:
        client_id = "client-1"

        def send_sync(self, event, payload, sid):
            sent.append((event, dict(payload), sid))

    sent: list = []
    instance = _Instance()
    module = types.ModuleType("server")
    module.PromptServer = type("PromptServer", (), {"instance": instance})
    monkeypatch.setitem(sys.modules, "server", module)
    return sent


def _waveform(seconds: float = 0.2, rate: int = 32000) -> torch.Tensor:
    # One batch, stereo, N samples (matches decoded segment audio layout).
    return torch.zeros(1, 2, int(rate * seconds))


def test_segment_audio_payload_carries_segment_index(fake_prompt_server):
    from mmx_pkg.director.progress import report_director_audio_preview

    sent = fake_prompt_server
    report_director_audio_preview(
        "node-7",
        [{"waveform": _waveform(), "sample_rate": 32000}],
        segment_index=3,
    )
    assert sent, "expected one audio preview message"
    event, payload, _sid = sent[-1]
    assert event == "minimax_motion_director_audio"
    assert payload["node_id"] == "node-7"
    assert payload["segment_index"] == 3
    assert payload["media_type"] == "audio/wav"
    assert payload["sample_rate"] == 32000
    assert payload["audio_b64"]


def test_combined_audio_payload_omits_segment_index(fake_prompt_server):
    from mmx_pkg.director.progress import report_director_audio_preview

    sent = fake_prompt_server
    report_director_audio_preview(
        "node-7",
        [{"waveform": _waveform(), "sample_rate": 32000}],
    )
    assert sent
    _event, payload, _sid = sent[-1]
    assert "segment_index" not in payload


def test_audio_preview_ignores_empty_or_muted_waveform(fake_prompt_server):
    from mmx_pkg.director.progress import report_director_audio_preview

    sent = fake_prompt_server
    report_director_audio_preview(
        "node-7",
        [{"waveform": torch.zeros(0), "sample_rate": 32000}],
    )
    report_director_audio_preview(
        "node-7",
        [{"waveform": torch.zeros(1, 2, 32), "sample_rate": 0}],
    )
    assert not sent


def test_executor_emits_per_segment_audio_preview():
    """The segment tail must push audio right after the video preview."""
    source = (
        "director/executor_core_legacy.py"
    )
    text = open(source, encoding="utf-8").read()
    assert "report_director_audio_preview(" in text
    assert "segment_index=ui_idx" in text
    assert 'log.debug("Segment audio preview skipped: %s", exc)' in text
