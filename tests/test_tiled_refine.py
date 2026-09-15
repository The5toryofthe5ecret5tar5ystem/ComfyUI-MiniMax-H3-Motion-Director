"""Spatial tiling helpers for the Global Refine second-sampling pass."""

from __future__ import annotations

import torch

from mmx_pkg.director import tiled_refine


def _covers(size: int, starts: list[int], tile: int) -> bool:
    covered = [False] * size
    for start in starts:
        for index in range(start, min(start + tile, size)):
            covered[index] = True
    return all(covered)


def test_tile_starts_cover_and_flush():
    starts = tiled_refine._tile_starts(100, 40, 8)
    assert starts[0] == 0
    assert starts[-1] == 100 - 40
    assert all(b > a for a, b in zip(starts, starts[1:]))
    assert _covers(100, starts, 40)


def test_tile_starts_single_when_tile_covers_size():
    assert tiled_refine._tile_starts(20, 32, 8) == [0]


def test_tile_weight_edge_vs_interior():
    # Edge (top-left) tile keeps full weight at the canvas corner.
    edge = tiled_refine._tile_weight(0, 32, 0, 32, 64, 64, 8)
    assert float(edge[0, 0]) == 1.0
    # Interior tile ramps down on all four sides.
    interior = tiled_refine._tile_weight(24, 56, 24, 56, 64, 64, 8)
    assert float(interior[0, 0]) < 1.0
    assert float(interior[0, 0]) > 0.0


def test_brightness_match_aligns_mean_and_std():
    tile_in = torch.randn(1, 4, 2, 16, 16) * 0.3 + 0.5
    tile_out = torch.randn(1, 4, 2, 16, 16) * 0.8 + 2.0
    matched = tiled_refine._brightness_match(tile_out, tile_in)
    assert matched.shape == tile_in.shape
    assert abs(float(matched.float().mean()) - float(tile_in.float().mean())) < 1e-3
    assert abs(float(matched.float().std(unbiased=False)) - float(tile_in.float().std(unbiased=False))) < 1e-2


def test_crop_keyframes_slices_spatial_dims():
    latent = torch.randn(1, 16, 2, 8, 8)
    conditioning = [
        ["cond", {"minimax_keyframes": [{"latent": latent, "resolved_frame_index": 0}]}]
    ]
    cropped = tiled_refine._crop_keyframes(conditioning, 2, 6, 1, 5)
    keyframe = cropped[0][1]["minimax_keyframes"][0]
    assert tuple(keyframe["latent"].shape) == (1, 16, 2, 4, 4)
    assert torch.equal(keyframe["latent"], latent[..., 1:5, 2:6])


def test_crop_keyframes_ignores_non_tensor():
    conditioning = [
        ["cond", {"minimax_keyframes": [{"resolved_frame_index": 0}]}],
        "plain_entry",
    ]
    cropped = tiled_refine._crop_keyframes(conditioning, 0, 4, 0, 4)
    assert cropped[1] == "plain_entry"
    assert cropped[0][1]["minimax_keyframes"][0] == {"resolved_frame_index": 0}


def test_split_streams_video_and_audio():
    import comfy.nested_tensor

    video = torch.randn(1, 16, 4, 8, 8)
    audio = torch.randn(1, 16, 2, 4)
    latent = {"samples": comfy.nested_tensor.NestedTensor((video, audio))}
    out_video, out_audio, extra = tiled_refine._split_streams(latent)
    assert out_video is not None and out_video.ndim == 5
    assert out_audio is not None and out_audio.ndim == 4
    assert extra == {}
