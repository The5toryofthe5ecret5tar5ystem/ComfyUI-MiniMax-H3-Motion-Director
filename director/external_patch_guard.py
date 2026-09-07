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


def model_has_external_attention_patch(model: Any) -> bool:
    """True when ``model`` carries an external H3 attention / diffusion patch.

    Detects two signatures left by third-party H3 nodes:
      * any ``diffusion_model`` wrapper installed on the model's wrapper table
        (H3-SLA-Attention registers the ``h3_sla_state`` key; Spectrum-MiniMax-H3
        registers its own key). The Director and ComfyUI core never install a
        ``diffusion_model`` wrapper of their own, so any present one is external.
      * a transformer-level ``optimized_attention_override`` (the mechanism
        attention-backend / sparse-attention nodes use to re-route H3 attention).

    Inspection is best-effort: on any error it returns False so a run is never
    blocked by the check itself.
    """
    try:
        wrappers = getattr(model, "wrappers", None) or {}
        diffusion = wrappers.get(_DIFFUSION_MODEL) or {}
        if diffusion and any(diffusion.values()):
            return True
        model_options = getattr(model, "model_options", None) or {}
        transformer_options = model_options.get("transformer_options") or {}
        if transformer_options.get("optimized_attention_override") is not None:
            return True
    except Exception:  # pragma: no cover - defensive
        return False
    return False
