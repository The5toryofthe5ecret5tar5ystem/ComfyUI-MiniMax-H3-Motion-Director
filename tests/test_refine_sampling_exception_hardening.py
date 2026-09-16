"""Global Refine exception hardening: OOM surfaces, everything else logs a traceback.

Regressions for the two failure modes that hid behind "Global Refine failed;
keeping first-pass result":

1. A CUDA OOM during refine/upscale must propagate as a hard error (mirroring
   the first-pass OOM handler), not be silently downgraded to the first-pass
   result while a pinned model holds ~20 GB.
2. Any other exception must still fall back to the first-pass result, but the
   outcome and the log must carry enough detail to diagnose it (the ``log``
   NameError bug produced only a bare message with no traceback).
"""

import importlib
import sys
import types

import pytest
import torch


def _install_stubs():
    core = types.ModuleType("director.core_sampling")

    def sample_single_stage(**kwargs):
        return kwargs["latent"]

    core.sample_single_stage = sample_single_stage
    sys.modules["director.core_sampling"] = core

    cfg = types.ModuleType("director.postprocess_config")
    cfg.refine_passes_for = lambda c: int(c.get("passes", 1))
    cfg.refine_pass_settings_for = lambda c, first: [
        (float(c.get("denoise", 0.25)), int(c.get("steps") or 8))
    ] * int(c.get("passes", 1))
    cfg.refine_steps_for = lambda c, first: int(c.get("steps") or 8)
    cfg.refine_seed_for = lambda c, seed, i=0: int(seed) + (
        i if c.get("seed_mode") == "offset" else 0
    )
    cfg.resolve_upscale_target = lambda c, w, h: (
        int(c.get("width", w)),
        int(c.get("height", h)),
    )
    cfg.resolve_vsr_quality_name = lambda c: "HIGHBITRATE_HIGH"
    sys.modules["director.postprocess_config"] = cfg

    rtx = types.ModuleType("director.rtx_deblur")

    class RTXDeblurOutcome:
        pass

    rtx.RTXDeblurOutcome = RTXDeblurOutcome
    rtx.apply_rtx_deblur = lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("deblur should not run")
    )
    sys.modules["director.rtx_deblur"] = rtx

    learned = types.ModuleType("director.h3_learned_latent")

    def upscale(latent, **kwargs):
        out = dict(latent)
        out["samples"] = "upscaled"
        return out

    learned.upscale_h3_av_latent = upscale
    sys.modules["director.h3_learned_latent"] = learned

    mask = types.ModuleType("director.h3_noise_mask")
    mask.remap_h3_noise_mask = lambda value, **kwargs: value

    def with_noise_mask(latent, value):
        out = dict(latent)
        if value is None:
            out.pop("noise_mask", None)
        else:
            out["noise_mask"] = value
        return out

    mask.with_noise_mask = with_noise_mask
    sys.modules["director.h3_noise_mask"] = mask

    sync = types.ModuleType("director.refine_latent_stage")

    def sync_h3_keyframe_conditioning(cond, vae, **kwargs):
        return cond

    sync.sync_h3_keyframe_conditioning = sync_h3_keyframe_conditioning
    sys.modules["director.refine_latent_stage"] = sync


def _load_module():
    sys.modules.pop("director.refine_sampling", None)
    return importlib.import_module("director.refine_sampling")


_CONFIG = {
    "enabled": True,
    "second_sampling_enabled": True,
    "passes": 1,
    "denoise": 0.25,
    "steps": 8,
    "seed_mode": "fixed",
}


def _run(mod):
    return mod.apply_global_refine(
        _CONFIG,
        task_key="t2v",
        samples={"samples": "fake-latent"},
        model=object(),
        vae=object(),
        positive=[],
        negative=[],
        seed=42,
        cfg=1.0,
        first_steps=8,
        sampler_name="euler",
        scheduler="normal",
        shift_video=0.0,
        shift_audio=0.0,
        director_width=64,
        director_height=64,
    )


def test_refine_oom_is_re_raised(monkeypatch):
    _install_stubs()
    mod = _load_module()

    def boom(**kwargs):
        raise torch.OutOfMemoryError("simulated OOM")

    monkeypatch.setattr(mod, "sample_single_stage", boom)
    with pytest.raises(RuntimeError, match="Global Refine"):
        _run(mod)


def test_refine_generic_error_falls_back_with_details(monkeypatch):
    _install_stubs()
    mod = _load_module()

    def boom(**kwargs):
        raise NameError("name 'log' is not defined")

    monkeypatch.setattr(mod, "sample_single_stage", boom)
    source = {"samples": "fake-latent"}
    outcome = _run(mod)
    assert outcome.status == "FAILED"
    assert outcome.fallback == "FIRST_PASS_RESULT"
    assert "NameError" in outcome.error
    assert "log" in outcome.error
    assert outcome.samples == source
