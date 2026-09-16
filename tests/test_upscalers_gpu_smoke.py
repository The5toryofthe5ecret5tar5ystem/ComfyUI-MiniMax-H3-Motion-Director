"""GPU smoke for the real upscalers (auto-skipped when deps/models are absent).

Each test runs ONE real upscaler on a small input and asserts the output shape.
Every case skips cleanly when CUDA or that upscaler's model/dependency is
missing, so this file is safe to leave in the normal suite — CI (CPU-only) will
skip every GPU case while still running the lanczos case.

Run on the GPU box:

    PYTHONPATH=<ComfyUI> <embedded_python> -m pytest tests/test_upscalers_gpu_smoke.py -v

A PASS means the upscaler produced frames of the target shape; it does not
assert visual quality. This is the "does it actually run end-to-end" layer on
top of the offline routing matrix in test_refine_sampling_upscaler_matrix.py.
"""

import pytest
import torch

FRAMES = 17  # one H3 keyframe group; enough for SeedVR2's temporal window


def _require_cuda():
    if not torch.cuda.is_available():
        pytest.skip("CUDA not available")


def _images(t=FRAMES, h=64, w=96, c=3):
    return torch.rand(t, h, w, c, dtype=torch.float32)


def _assert_pixel_shape(out, width, height, frames=FRAMES):
    assert tuple(out.shape[:3]) == (frames, height, width), tuple(out.shape)
    assert out.shape[-1] == 3, out.shape


# ---------------------------------------------------------------------------
def test_lanczos_smoke():
    """CPU-safe; also runs in CI. Real resize must produce the target canvas."""
    from director.refine_sampling import _resize_lanczos

    out = _resize_lanczos(_images(), 192, 128)
    _assert_pixel_shape(out, 192, 128)


def test_realesrgan_smoke():
    _require_cuda()
    import folder_paths

    models = folder_paths.get_filename_list("upscale_models")
    if not models:
        pytest.skip("no files in models/upscale_models")
    from director.refine_sampling import _upscale_model_exact

    out = _upscale_model_exact(
        _images(h=32, w=32), models[0], width=128, height=128,
    )
    assert out.shape[1] == 128 and out.shape[2] == 128, tuple(out.shape)


def test_seedvr2_smoke():
    _require_cuda()
    import os

    import folder_paths
    from director.refine_sampling import _ensure_custom_nodes_importable

    _ensure_custom_nodes_importable()
    try:
        import seedvr2_videoupscaler  # noqa: F401
    except ImportError:
        pytest.skip("SeedVR2 pack not installed")
    models_dir = os.path.join(str(folder_paths.base_path), "models", "SEEDVR2")
    if not os.path.isdir(models_dir) or not os.listdir(models_dir):
        pytest.skip("SeedVR2 checkpoints not downloaded (run one render first)")

    from director.refine_sampling import _upscale_seedvr2_exact

    out = _upscale_seedvr2_exact(_images(h=96, w=160), width=320, height=192)
    _assert_pixel_shape(out, 320, 192)


def test_rtx_vsr_smoke():
    _require_cuda()
    try:
        import nvvfx  # noqa: F401
    except ImportError:
        pytest.skip("nvidia-vfx (nvvfx) not installed")

    from director.refine_sampling import _upscale_rtx_vsr_exact

    out = _upscale_rtx_vsr_exact(_images(h=96, w=160), 320, 192, quality_name="high")
    # RTX VSR rounds output to a multiple of 8.
    assert out.shape[0] == FRAMES and out.shape[-1] == 3, tuple(out.shape)
    assert abs(out.shape[2] - 320) <= 7 and abs(out.shape[1] - 192) <= 7, tuple(out.shape)


def test_h3_learned_latent_smoke():
    _require_cuda()
    from director.h3_learned_latent import list_h3_latent_models

    models = list_h3_latent_models()
    if not models:
        pytest.skip("no H3 learned-latent checkpoints installed")

    try:
        from comfy.nested_tensor import NestedTensor
    except ImportError:
        pytest.skip("comfy.nested_tensor unavailable")

    # Minimal AV latent: 17-frame video at 32x48 latent grid (512x768 px),
    # plus a paired audio stream. Target upscales the grid to 40x64 (640x1024).
    video = torch.randn(1, 24, FRAMES, 32, 48, dtype=torch.float32)
    audio = torch.randn(1, 32, 2, 40, dtype=torch.float32)
    latent = {"samples": NestedTensor((video, audio))}

    from director.h3_learned_latent import upscale_h3_av_latent

    out = upscale_h3_av_latent(
        latent,
        width=1024,
        height=640,
        model_name=models[0],
        precision="fp16",
        device="cuda",
    )
    video_out, _ = out["samples"].unbind()
    assert tuple(video_out.shape[-2:]) == (40, 64), tuple(video_out.shape)
    assert video_out.shape[-3] == FRAMES, tuple(video_out.shape)
