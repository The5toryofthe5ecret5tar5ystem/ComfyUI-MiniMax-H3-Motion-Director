"""Temporal chunking for the Global Refine second-sampling pass."""

from __future__ import annotations

import torch

from mmx_pkg.director import temporal_refine


def _make_latent(tokens: int = 40, h: int = 8, w: int = 8, audio_tokens: int = 240) -> dict:
    import comfy.nested_tensor

    video = torch.randn(1, 24, tokens, h, w)
    audio = torch.randn(1, 32, 2, audio_tokens)
    return {"samples": comfy.nested_tensor.NestedTensor((video, audio))}


def _video(latent: dict) -> torch.Tensor:
    samples = latent["samples"]
    if hasattr(samples, "unbind"):
        return list(samples.unbind())[0]
    return samples


def test_snap_group_rounds_to_17():
    assert temporal_refine._snap_group(136) == 136
    assert temporal_refine._snap_group(140) == 136
    assert temporal_refine._snap_group(17) == 17
    assert temporal_refine._snap_group(0) == 0


def test_edge_ramp():
    flat = temporal_refine._edge_ramp(10, 5, left=False, right=False)
    assert torch.allclose(flat, torch.ones(10))
    left = temporal_refine._edge_ramp(10, 5, left=True, right=False)
    assert float(left[0]) < 1.0
    assert float(left[-1]) == 1.0
    right = temporal_refine._edge_ramp(10, 5, left=False, right=True)
    assert float(right[0]) == 1.0
    assert float(right[-1]) < 1.0


def test_identity_chunked_refine_reconstructs(monkeypatch):
    """With an identity sampler, the cross-faded stitch must reproduce the input.

    The weights over every overlapping token sum to 1, so chunking + stitching
    is lossless when the sampler returns its input unchanged.
    """
    from mmx_pkg.director import core_sampling

    def identity(**kwargs):
        return kwargs["latent"]

    monkeypatch.setattr(core_sampling, "sample_single_stage", identity)

    latent = _make_latent(tokens=40, h=8, w=8)
    out = temporal_refine.sample_temporal_chunked_refine(
        model=None,
        positive=None,
        negative=None,
        latent=latent,
        seed=0,
        cfg=1.0,
        steps=2,
        sampler_name="res_multistep",
        scheduler="simple",
        shift_video=12.0,
        shift_audio=3.0,
        denoise=0.25,
        chunk_frames=34,
        overlap_frames=17,
    )
    out_video = _video(out)
    orig_video = _video(latent)
    assert tuple(out_video.shape) == tuple(orig_video.shape)
    assert torch.allclose(out_video, orig_video, atol=1e-5)

    # Audio is carried through unchanged, never re-sampled.
    out_audio = list(out["samples"].unbind())[1]
    orig_audio = list(latent["samples"].unbind())[1]
    assert torch.equal(out_audio, orig_audio)
