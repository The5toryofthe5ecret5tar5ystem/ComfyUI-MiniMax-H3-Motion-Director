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
    external_attention_patch_findings,
    model_has_external_attention_patch,
)


def _fake_sla_wrapper(*_args, **_kwargs):
    """Stands in for a third-party wrapper; its ``__module__`` is the payload."""
    return None


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


# --------------------------------------------------------------------------- #
# The report: a skip has to name the patch, not list the candidates it might be.
# --------------------------------------------------------------------------- #


def test_findings_name_the_wrapper_key_and_source():
    model = _model(wrappers={"diffusion_model": {"h3_sla_state": [_fake_sla_wrapper]}})
    findings = external_attention_patch_findings(model)
    assert len(findings) == 1
    assert 'diffusion_model wrapper "h3_sla_state"' in findings[0]
    # The module is the whole point: it names the pack that installed it.
    assert _fake_sla_wrapper.__module__ in findings[0]


def test_findings_describe_the_callable_not_the_list():
    # ComfyUI stores wrappers as a list per key; describing the list would
    # report "builtins.list" and tell you nothing.
    model = _model(wrappers={"diffusion_model": {"spectrum_forecast": [_fake_sla_wrapper]}})
    finding = external_attention_patch_findings(model)[0]
    assert "builtins.list" not in finding
    assert _fake_sla_wrapper.__module__ in finding


def test_findings_name_the_attention_override_source():
    model = _model(transformer_options={"optimized_attention_override": _fake_sla_wrapper})
    findings = external_attention_patch_findings(model)
    assert len(findings) == 1
    assert findings[0].startswith("optimized_attention_override")
    assert _fake_sla_wrapper.__module__ in findings[0]


def test_findings_unwrap_partial():
    import functools

    model = _model(
        transformer_options={"optimized_attention_override": functools.partial(_fake_sla_wrapper)}
    )
    finding = external_attention_patch_findings(model)[0]
    assert _fake_sla_wrapper.__module__ in finding
    assert "functools" not in finding


def test_findings_report_both_signatures():
    model = _model(
        wrappers={"diffusion_model": {"h3_sla_state": [_fake_sla_wrapper]}},
        transformer_options={"optimized_attention_override": _fake_sla_wrapper},
    )
    assert len(external_attention_patch_findings(model)) == 2


def test_findings_agree_with_the_boolean():
    for model in (
        _model(),
        _model(wrappers={"diffusion_model": {"h3_sla_state": [_fake_sla_wrapper]}}),
        _model(transformer_options={"optimized_attention_override": _fake_sla_wrapper}),
        _model(wrappers={"outer_sample": {"minimax_motion_director_preview": [_fake_sla_wrapper]}}),
    ):
        assert bool(external_attention_patch_findings(model)) is model_has_external_attention_patch(model)


def test_findings_empty_for_a_clean_model():
    assert external_attention_patch_findings(_model()) == []
    assert external_attention_patch_findings(_model(wrappers={"diffusion_model": {}})) == []


def test_findings_ignore_the_directors_own_wrapper():
    model = _model(
        wrappers={"outer_sample": {"minimax_motion_director_preview": [_fake_sla_wrapper]}}
    )
    assert external_attention_patch_findings(model) == []


def test_findings_never_raise_on_junk():
    class Boom:
        @property
        def wrappers(self):
            raise RuntimeError("nope")

        @property
        def model_options(self):
            raise RuntimeError("nope")

    assert external_attention_patch_findings(Boom()) == []
    assert external_attention_patch_findings(None) == []
    assert external_attention_patch_findings("not a model") == []
