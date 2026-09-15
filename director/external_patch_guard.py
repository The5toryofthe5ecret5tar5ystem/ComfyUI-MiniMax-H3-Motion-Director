# Guard rails for running the Director's Global Refine stage over externally
# patched H3 models.
#
# Global Refine re-samples the result through the same model that produced it.
# When that model carries a third-party attention / diffusion patch (e.g.
# ComfyUI-H3-SLA-Attention's ``h3_sla_state`` diffusion wrapper, or
# ComfyUI-Spectrum-MiniMax-H3's diffusion wrapper), that re-sampling has
# aborted at the CUDA level (SLA / Comfy-Kitchen ``sol_attn``) instead of
# failing cleanly. The Director therefore skips Global Refine for such a model
# and keeps the first-pass result, unless the post-process config explicitly
# opts out via the key below.
#
# Distributed under GPL-3.0; see NOTICE and LICENSES.

from __future__ import annotations

from typing import Any

# comfy.patcher_extension.WrappersMP.DIFFUSION_MODEL. Kept as a literal so this
# module stays dependency-free and unit-testable without a ComfyUI import.
_DIFFUSION_MODEL = "diffusion_model"

# Post-process config key that, when truthy, lets Global Refine run anyway over
# an externally patched model (advanced / A/B only).
ALLOW_REFINE_ON_EXTERNAL_PATCH = "allow_refine_on_external_patch"


def _module_of(obj: Any) -> str:
    """Best-effort ``module.qualname`` for a wrapper or override callable.

    This is the whole point of the report: the module names the pack that
    installed the patch, which is what someone reading the log actually needs.
    A bound method reports its owner class (``state.make_attention_override``),
    and a ``functools.partial`` is unwrapped so it reports the wrapped function
    rather than ``functools``.
    """
    if obj is None:
        return ""
    wrapped = getattr(obj, "func", None)
    if wrapped is not None and callable(wrapped):
        obj = wrapped
    qual = (
        getattr(obj, "__qualname__", None)
        or getattr(obj, "__name__", None)
        or type(obj).__qualname__
    )
    owner = getattr(obj, "__self__", None)
    if owner is not None:
        return f"{type(owner).__module__}.{type(owner).__qualname__}.{qual}"
    module = getattr(obj, "__module__", None) or type(obj).__module__
    return f"{module}.{qual}" if module else str(qual)


def _describe_installed(value: Any) -> str:
    """Describe an installed wrapper value.

    ComfyUI stores wrappers as a list of callables per key, so a bare
    ``type(value)`` would report ``builtins.list`` and tell you nothing. Walk
    the list and describe the first callable instead.
    """
    candidates = value if isinstance(value, (list, tuple)) else [value]
    for item in candidates:
        if callable(item):
            return _module_of(item)
    return ""


def external_attention_patch_findings(model: Any) -> list[str]:
    """Name every external patch signature found on ``model``.

    Returns one human-readable finding per signature, for example::

        ['diffusion_model wrapper "h3_sla_state" (sla.patch._make_wrapper.<locals>.wrapper)',
         'optimized_attention_override = comfyui_kjnodes.nodes.model_optimization_nodes._PreparedAttention']

    An empty list means the model is clean. Inspection is best-effort and never
    raises, so a run is never blocked by the check itself.
    """
    findings: list[str] = []

    try:
        wrappers = getattr(model, "wrappers", None) or {}
        diffusion = wrappers.get(_DIFFUSION_MODEL) or {}
        if isinstance(diffusion, dict):
            for key, value in sorted(diffusion.items(), key=lambda pair: str(pair[0])):
                if not value:
                    continue
                source = _describe_installed(value)
                findings.append(
                    f'diffusion_model wrapper "{key}"'
                    + (f" ({source})" if source else "")
                )
    except Exception:  # pragma: no cover - defensive
        pass

    try:
        model_options = getattr(model, "model_options", None) or {}
        transformer_options = model_options.get("transformer_options") or {}
        override = transformer_options.get("optimized_attention_override")
        if override is not None:
            source = _module_of(override)
            findings.append(
                "optimized_attention_override"
                + (f" = {source}" if source else "")
            )
    except Exception:  # pragma: no cover - defensive
        pass

    return findings


def model_has_external_attention_patch(model: Any) -> bool:
    """True when ``model`` carries an external H3 attention / diffusion patch.

    Detects two signatures left by third-party H3 nodes:
      * any ``diffusion_model`` wrapper installed on the model's wrapper table
        (H3-SLA-Attention registers the ``h3_sla_state`` key; Spectrum-MiniMax-H3
        registers its own key). The Director and ComfyUI core never install a
        ``diffusion_model`` wrapper of their own - the Director's live-preview
        hook is an ``OUTER_SAMPLE`` wrapper - so any present one is external.
      * a transformer-level ``optimized_attention_override`` (the mechanism
        attention-backend / sparse-attention nodes use to re-route H3 attention).

    Inspection is best-effort: on any error it returns False so a run is never
    blocked by the check itself. Use :func:`external_attention_patch_findings`
    when you need to know *which* patch was found.
    """
    return bool(external_attention_patch_findings(model))
