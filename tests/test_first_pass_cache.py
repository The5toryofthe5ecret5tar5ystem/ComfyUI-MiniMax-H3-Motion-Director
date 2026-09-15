"""First-pass AV latent cache: identity building, restore, and disk round-trip."""

from __future__ import annotations

import uuid

import pytest
import torch

import folder_paths
from mmx_pkg.director import first_pass_cache
from mmx_pkg.director.plan import DirectorPlan, SegmentPlan


@pytest.fixture
def out_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(folder_paths, "get_output_directory", lambda: str(tmp_path))
    return tmp_path


def _seg(index: int, prompt: str) -> SegmentPlan:
    return SegmentPlan(
        index=index, start_frame=index * 4, end_frame=index * 4 + 4,
        prompt=prompt, task_type="t2v", task_key="t2v", use_global=True,
    )


def _plan(*segs: SegmentPlan) -> DirectorPlan:
    return DirectorPlan(
        frame_rate=24.0, total_frames=len(segs) * 4, width=64, height=64,
        ref_max_size=64, output_mode="fixed", source_width=64, source_height=64,
        global_task_type="t2v", global_task_key="t2v", global_prompt="",
        global_refs=[], segments=list(segs),
        source_video=torch.zeros((1, 3, 8, 8)), edit_mode="segment", raw={},
    )


def _node() -> str:
    return f"firstpass_test_{uuid.uuid4().hex[:10]}"


def test_build_first_pass_settings_strips_postprocess():
    settings = first_pass_cache.build_first_pass_settings(
        {
            "seed": 7,
            "context_length": 22,
            "cfg": 1.0,
            "global_refine": {"enabled": True, "denoise": 0.4},
            "face_refine": {"enabled": False},
            "audio_refine": {"enabled": True},
        },
        seed=7,
        context_length=22,
    )
    assert "global_refine" not in settings
    assert "face_refine" not in settings
    assert "audio_refine" not in settings
    assert settings["cfg"] == 1.0
    assert settings["first_pass_seed"] == 7
    assert settings["first_pass_context_length"] == 22


def test_build_first_pass_settings_folds_seed_and_context():
    settings = first_pass_cache.build_first_pass_settings(
        {"seed": 1234, "context_length": 39},
        seed=1234,
        context_length=39,
    )
    # The raw keys survive plus distinct folded keys so the producer fingerprint
    # (which drops "seed"/"context_length") still sees them.
    assert settings["seed"] == 1234
    assert settings["context_length"] == 39
    assert settings["first_pass_seed"] == 1234
    assert settings["first_pass_context_length"] == 39


def test_restore_av_latent_round_trip():
    import comfy.nested_tensor

    video = torch.randn(1, 16, 4, 8, 8)
    audio = torch.randn(1, 16, 2, 4)
    latent = {
        "samples": comfy.nested_tensor.NestedTensor((video, audio)),
        "batch_index": 0,
    }
    cpu = first_pass_cache.av_latent_to_cpu(latent)
    restored = first_pass_cache.restore_av_latent(cpu, device=torch.device("cpu"))
    assert isinstance(restored["samples"], comfy.nested_tensor.NestedTensor)
    streams = list(restored["samples"].unbind())
    assert len(streams) == 2
    assert torch.allclose(streams[0], video)
    assert torch.allclose(streams[1], audio)
    assert restored["batch_index"] == 0


def test_first_pass_save_load_round_trip(out_dir):
    import comfy.nested_tensor

    node = _node()
    seg = _seg(0, "alpha")
    plan = _plan(seg)
    latent = {
        "samples": comfy.nested_tensor.NestedTensor(
            (torch.randn(1, 16, 4, 8, 8), torch.randn(1, 16, 2, 4))
        ),
    }
    settings = first_pass_cache.build_first_pass_settings(
        {"seed": 5, "cfg": 1.0}, seed=5, context_length=0,
    )
    assert first_pass_cache.save_first_pass_latent(node, seg, plan, latent=latent, settings=settings)
    loaded = first_pass_cache.load_first_pass_latent(node, seg, plan, settings=settings)
    assert loaded is not None
    assert "samples" in loaded


def test_first_pass_rejects_stale_settings(out_dir):
    import comfy.nested_tensor

    node = _node()
    seg = _seg(0, "alpha")
    plan = _plan(seg)
    latent = {
        "samples": comfy.nested_tensor.NestedTensor(
            (torch.randn(1, 16, 4, 8, 8), torch.randn(1, 16, 2, 4))
        ),
    }
    settings = first_pass_cache.build_first_pass_settings(
        {"seed": 5, "cfg": 1.0}, seed=5, context_length=0,
    )
    first_pass_cache.save_first_pass_latent(node, seg, plan, latent=latent, settings=settings)
    stale = first_pass_cache.build_first_pass_settings(
        {"seed": 6, "cfg": 1.0}, seed=6, context_length=0,
    )
    assert first_pass_cache.load_first_pass_latent(node, seg, plan, settings=stale) is None


def test_replace_first_pass_identity_captures_spec_and_tensors():
    class Spec:
        def to_json(self):
            return {"enabled": True, "mask": {"dir": "/masks/x", "grow": 1}}

    mask = torch.randn(4, 8, 8)
    source = torch.randn(4, 16, 16, 3)
    identity = first_pass_cache.replace_first_pass_identity(
        Spec(), mask_vis=mask, source_frames=source, mode="inpaint",
    )
    assert identity["mode"] == "inpaint"
    assert identity["spec"]["mask"]["grow"] == 1
    assert torch.equal(identity["mask_vis"], mask)
    assert torch.equal(identity["source"], source)


def test_save_first_pass_strips_noise_mask(out_dir):
    import comfy.nested_tensor

    node = _node()
    seg = _seg(0, "alpha")
    plan = _plan(seg)
    video = torch.randn(1, 16, 4, 8, 8)
    audio = torch.randn(1, 16, 2, 4)
    noise_mask = comfy.nested_tensor.NestedTensor(
        (torch.zeros(1, 1, 4, 8, 8), torch.zeros(1, 1, 2, 4))
    )
    latent = {
        "samples": comfy.nested_tensor.NestedTensor((video, audio)),
        "noise_mask": noise_mask,
    }
    settings = first_pass_cache.build_first_pass_settings(
        {"seed": 1}, seed=1, context_length=0,
    )
    assert first_pass_cache.save_first_pass_latent(node, seg, plan, latent=latent, settings=settings)
    loaded = first_pass_cache.load_first_pass_latent(node, seg, plan, settings=settings)
    assert loaded is not None
    assert "noise_mask" not in loaded

