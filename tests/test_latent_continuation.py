"""Latent-space continuation builder (pinned latent + nested noise mask)."""

from __future__ import annotations

import pytest
import torch

from mmx_pkg.director import latent_continuation


def _av_latent(video, audio):
    import comfy.nested_tensor

    return {"samples": comfy.nested_tensor.NestedTensor((video, audio))}


def test_video_head_injection_and_mask():
    prev_video = torch.arange(8, dtype=torch.float32).reshape(1, 1, 8, 1, 1)
    template_video = (torch.arange(10, dtype=torch.float32) + 100).reshape(1, 1, 10, 1, 1)
    prev_audio = torch.arange(40, dtype=torch.float32).reshape(1, 1, 2, 20)
    template_audio = (torch.arange(40, dtype=torch.float32) + 100).reshape(1, 1, 2, 20)

    out = latent_continuation.build_pinned_latent(
        _av_latent(template_video, template_audio),
        _av_latent(prev_video, prev_audio),
        span=5,
    )
    streams = list(out["samples"].unbind())
    assert len(streams) == 2
    new_video = streams[0]
    # span=5 -> 2 video tokens (1+4). Previous tail tokens 6,7 land at head 0,1.
    assert float(new_video[0, 0, 0, 0, 0]) == 6.0
    assert float(new_video[0, 0, 1, 0, 0]) == 7.0
    assert float(new_video[0, 0, 2, 0, 0]) == 102.0

    video_mask = list(out["noise_mask"].unbind())[0]
    assert float(video_mask[0, 0, 0, 0, 0]) == 0.0
    assert float(video_mask[0, 0, 1, 0, 0]) == 0.0
    assert float(video_mask[0, 0, 2, 0, 0]) == 1.0
    assert float(video_mask[0, 0, 9, 0, 0]) == 1.0


def test_audio_head_injection_and_mask():
    prev_video = torch.randn(1, 1, 8, 1, 1)
    template_video = torch.randn(1, 1, 10, 1, 1)
    prev_audio = torch.arange(40, dtype=torch.float32).reshape(1, 1, 2, 20)
    template_audio = (torch.arange(40, dtype=torch.float32) + 100).reshape(1, 1, 2, 20)

    out = latent_continuation.build_pinned_latent(
        _av_latent(template_video, template_audio),
        _av_latent(prev_video, prev_audio),
        span=5,
    )
    new_audio = list(out["samples"].unbind())[1]
    # span=5 -> 8 audio steps (5/24 * 40 = 8.33 -> 8). Channel 0 tail 12..19 -> head 0..7.
    assert float(new_audio[0, 0, 0, 0]) == 12.0
    assert float(new_audio[0, 0, 0, 7]) == 19.0
    assert float(new_audio[0, 0, 0, 8]) == 108.0

    audio_mask = list(out["noise_mask"].unbind())[1]
    assert float(audio_mask[0, 0, 0, 0]) == 0.0
    assert float(audio_mask[0, 0, 0, 7]) == 0.0
    assert float(audio_mask[0, 0, 0, 8]) == 1.0


def test_rejects_non_native_fps():
    with pytest.raises(ValueError):
        latent_continuation.build_pinned_latent(
            {"samples": torch.randn(1, 1, 8, 1, 1)},
            {"samples": torch.randn(1, 1, 8, 1, 1)},
            span=5,
            fps=30.0,
        )
