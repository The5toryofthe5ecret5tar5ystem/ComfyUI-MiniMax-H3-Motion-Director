"""External attention/diffusion patch detection (director.external_patch_guard).

Global Refine re-samples through the same model the segment was generated
with. Third-party H3 nodes (H3-SLA-Attention, Spectrum) install a
``diffusion_model`` wrapper (or an ``optimized_attention_override``) on that
model; refining through those has aborted at the CUDA level, so the Director
skips Global Refine for them. These tests pin what the detector considers an
"external patch" so it neither misses SLA/Spectrum nor false-positives on the
Director's own OUTER_SAMPLE preview wrapper or a stock model.
"""

from __future__ import annotations

from types import SimpleNamespace

from mmx_pkg.director.external_patch_guard import (
    ALLOW_REFINE_ON_EXTERNAL_PATCH,
    model_has_external_attention_patch,
)


def _model(wrappers=None, transformer_options=None):
    return SimpleNamespace(
        wrappers=wrappers or {},
        model_options={"transformer_options": transformer_options or {}},
    )


def test_sla_diffusion_wrapper_detected():
    model = _model(wrappers={"diffusion_model": {"h3_sla_state": [object()]}})
    assert model_has_external_attention_patch(model) is True


def test_spectrum_diffusion_wrapper_detected():
    model = _model(wrappers={"diffusion_model": {"spectrum_forecast": [object()]}})
    assert model_has_external_attention_patch(model) is True


def test_optimized_attention_override_detected():
    model = _model(transformer_options={"optimized_attention_override": object()})
    assert model_has_external_attention_patch(model) is True


def test_stock_model_not_detected():
    model = _model()
    assert model_has_external_attention_patch(model) is False


def test_director_outer_sample_wrapper_not_detected():
    # The Director's own live-preview hook is OUTER_SAMPLE, never diffusion_model.
    model = _model(wrappers={"outer_sample": {"minimax_motion_director_preview": [object()]}})
    assert model_has_external_attention_patch(model) is False


def test_empty_diffusion_wrapper_ignored():
    model = _model(wrappers={"diffusion_model": {}})
    assert model_has_external_attention_patch(model) is False


def test_non_dict_model_safe():
    assert model_has_external_attention_patch(None) is False
    assert model_has_external_attention_patch("not a model") is False


def test_opt_out_key_name_stable():
    # The post-process config key used to bypass the guard.
    assert ALLOW_REFINE_ON_EXTERNAL_PATCH == "allow_refine_on_external_patch"
