"""Upscaler + Global Refine matrix: every method × every setting, offline.

This is the regression net for the upscale/postprocess path. It sweeps:

* all five ``upscale_method`` values (lanczos, upscale_model/Real-ESRGAN,
  nvidia_rtx_vsr, seedvr2, h3_learned_latent),
* second-sampling on/off,
* tiled refine and temporal split,
* the external-patch guard (skip + override), skip_fl2v, force_skip, disabled.

It runs entirely on CPU: the heavy upscalers and samplers are faked so the
test exercises the *routing and outcome*, not the model weights. This is what
would have caught the ``log`` NameError (h3_learned_latent path) and the
SeedVR2 lazy-import bug (seedvr2 path) at dispatch time.
"""

import importlib
import sys
import types

import pytest
import torch

PIXEL_METHODS = ["lanczos", "upscale_model", "nvidia_rtx_vsr", "seedvr2"]
LATENT_METHODS = ["h3_learned_latent"]
ALL_METHODS = PIXEL_METHODS + LATENT_METHODS


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
    learned.upscale_h3_av_latent = lambda latent, **kw: dict(latent)
    sys.modules["director.h3_learned_latent"] = learned

    mask = types.ModuleType("director.h3_noise_mask")
    mask.remap_h3_noise_mask = lambda value, **kw: value
    mask.with_noise_mask = lambda latent, value: latent
    sys.modules["director.h3_noise_mask"] = mask

    sync = types.ModuleType("director.refine_latent_stage")
    sync.sync_h3_keyframe_conditioning = lambda cond, vae, **kw: cond
    sys.modules["director.refine_latent_stage"] = sync


def _load_module():
    sys.modules.pop("director.refine_sampling", None)
    return importlib.import_module("director.refine_sampling")


def _fake_chain(mod, monkeypatch, records):
    """Fake the pixel decode/upscale/encode chain and the three samplers."""
    monkeypatch.setattr(
        mod, "_split_av", lambda latent: ({"samples": "video"}, {"samples": "audio"})
    )
    monkeypatch.setattr(mod, "_video_latent_canvas", lambda latent: (64, 64))
    monkeypatch.setattr(mod, "_decode_video", lambda vae, latent: torch.zeros(4, 64, 64, 3))
    monkeypatch.setattr(mod, "_encode_video", lambda vae, images: {"samples": "encoded"})
    monkeypatch.setattr(
        mod, "_join_av", lambda video, audio, template: {"samples": "joined"}
    )

    def fake_upscale(images, *, width, height, method, **kw):
        records["upscale_method"] = method
        return torch.zeros(images.shape[0], height, width, 3)

    monkeypatch.setattr(mod, "upscale_image_batch_strict", fake_upscale)
    monkeypatch.setattr(
        mod, "sample_tiled_refine_pass", lambda **kw: kw["latent"]
    )
    monkeypatch.setattr(
        mod, "sample_temporal_chunked_refine", lambda **kw: kw["latent"]
    )


def _call(mod, config, task_key="t2v", model=None):
    return mod.apply_global_refine(
        config,
        task_key=task_key,
        samples={"samples": "fake-latent"},
        model=object() if model is None else model,
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


# ---------------------------------------------------------------------------
# 1. Pixel-space dispatch covers every upscale_method branch.
# ---------------------------------------------------------------------------
def test_upscale_image_batch_strict_dispatches_every_pixel_method(monkeypatch):
    _install_stubs()
    mod = _load_module()
    ran = []

    def fake(images, w, h, name):
        ran.append(name)
        return torch.zeros(images.shape[0], h, w, 3)

    monkeypatch.setattr(
        mod, "_resize_lanczos", lambda images, w, h: fake(images, w, h, "lanczos")
    )
    monkeypatch.setattr(
        mod,
        "_upscale_model_exact",
        lambda images, model_name, *, width, height, **k: fake(
            images, width, height, "upscale_model"
        ),
    )
    monkeypatch.setattr(
        mod,
        "_upscale_rtx_vsr_exact",
        lambda images, width, height, **k: fake(images, width, height, "nvidia_rtx_vsr"),
    )
    monkeypatch.setattr(
        mod,
        "_upscale_seedvr2_exact",
        lambda images, width, height, **k: fake(images, width, height, "seedvr2"),
    )
    img = torch.zeros(2, 32, 32, 3)
    for method in PIXEL_METHODS:
        mod.upscale_image_batch_strict(img, width=32, height=32, method=method)
    assert ran == ["lanczos", "upscale_model", "nvidia_rtx_vsr", "seedvr2"]

    with pytest.raises(ValueError):
        mod.upscale_image_batch_strict(img, width=32, height=32, method="h3_learned_latent")


# ---------------------------------------------------------------------------
# 2. Every method: upscale + second sampling succeeds end-to-end (no fallback).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("method", ALL_METHODS)
def test_every_upscale_method_succeeds(monkeypatch, method):
    _install_stubs()
    mod = _load_module()
    records = {}
    _fake_chain(mod, monkeypatch, records)
    outcome = _call(
        mod,
        {
            "enabled": True,
            "mode": "upscale",
            "upscale_method": method,
            "second_sampling_enabled": True,
            "passes": 1,
            "denoise": 0.25,
            "steps": 8,
            "seed_mode": "fixed",
        },
    )
    assert outcome.succeeded, f"{method}: {outcome.status}"
    if method in PIXEL_METHODS:
        assert records.get("upscale_method") == method


@pytest.mark.parametrize("method", ALL_METHODS)
def test_every_upscale_method_succeeds_upscale_only(monkeypatch, method):
    _install_stubs()
    mod = _load_module()
    records = {}
    _fake_chain(mod, monkeypatch, records)
    outcome = _call(
        mod,
        {
            "enabled": True,
            "mode": "upscale",
            "upscale_method": method,
            "second_sampling_enabled": False,
        },
    )
    assert outcome.succeeded, f"{method}: {outcome.status}"
    assert outcome.steps == 0


@pytest.mark.parametrize("method", ALL_METHODS)
def test_every_method_with_tiled_refine(monkeypatch, method):
    _install_stubs()
    mod = _load_module()
    _fake_chain(mod, monkeypatch, {})
    outcome = _call(
        mod,
        {
            "enabled": True,
            "mode": "upscale",
            "upscale_method": method,
            "second_sampling_enabled": True,
            "tiled_refine": True,
            "tile_size": 32,
            "tile_overlap": 8,
            "passes": 1,
            "denoise": 0.25,
            "steps": 8,
            "seed_mode": "fixed",
        },
    )
    assert outcome.succeeded, f"{method}: {outcome.status}"


@pytest.mark.parametrize("method", ALL_METHODS)
def test_every_method_with_temporal_split(monkeypatch, method):
    _install_stubs()
    mod = _load_module()
    _fake_chain(mod, monkeypatch, {})
    outcome = _call(
        mod,
        {
            "enabled": True,
            "mode": "upscale",
            "upscale_method": method,
            "second_sampling_enabled": True,
            "temporal_split": True,
            "temporal_chunk_frames": 136,
            "temporal_overlap_frames": 17,
            "passes": 1,
            "denoise": 0.25,
            "steps": 8,
            "seed_mode": "fixed",
        },
    )
    assert outcome.succeeded, f"{method}: {outcome.status}"


# ---------------------------------------------------------------------------
# 3. The skip / guard matrix ("postprocessing not working" cases).
# ---------------------------------------------------------------------------
def test_external_patch_skips_unless_allowed(monkeypatch):
    _install_stubs()
    mod = _load_module()
    monkeypatch.setattr(
        mod, "external_attention_patch_findings", lambda model: ["h3_sla_state (fake)"]
    )
    _fake_chain(mod, monkeypatch, {})
    skipped = _call(
        mod,
        {
            "enabled": True,
            "mode": "upscale",
            "upscale_method": "lanczos",
            "second_sampling_enabled": True,
            "passes": 1,
            "denoise": 0.25,
            "steps": 8,
        },
    )
    assert skipped.status.startswith("SKIPPED"), skipped.status
    assert "external" in skipped.status

    allowed = _call(
        mod,
        {
            "enabled": True,
            "mode": "upscale",
            "upscale_method": "lanczos",
            "second_sampling_enabled": True,
            "allow_refine_on_external_patch": True,
            "passes": 1,
            "denoise": 0.25,
            "steps": 8,
        },
    )
    assert allowed.succeeded, allowed.status


def test_skip_fl2v_only_gates_fl2v(monkeypatch):
    _install_stubs()
    mod = _load_module()
    _fake_chain(mod, monkeypatch, {})
    config = {
        "enabled": True,
        "mode": "upscale",
        "upscale_method": "lanczos",
        "second_sampling_enabled": True,
        "skip_fl2v": True,
        "passes": 1,
        "denoise": 0.25,
        "steps": 8,
    }
    assert _call(mod, config, task_key="fl2v").status.startswith("SKIPPED")
    assert _call(mod, config, task_key="t2v").succeeded


def test_force_skip_reason_short_circuits(monkeypatch):
    _install_stubs()
    mod = _load_module()
    outcome = _call(
        mod,
        {"enabled": True, "second_sampling_enabled": True, "passes": 1},
    )
    # force_skip_reason is a kwarg, not a config key; test via direct call.
    forced = mod.apply_global_refine(
        {"enabled": True, "second_sampling_enabled": True, "passes": 1},
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
        force_skip_reason="masked Character Replace window",
    )
    assert forced.status.startswith("SKIPPED")


def test_disabled_short_circuits(monkeypatch):
    _install_stubs()
    mod = _load_module()
    outcome = _call(mod, {"enabled": False})
    assert outcome.status == "DISABLED"
