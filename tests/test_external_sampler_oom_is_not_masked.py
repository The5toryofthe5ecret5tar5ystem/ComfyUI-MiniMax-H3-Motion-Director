"""A CUDA OOM inside the external sampler must not be relabelled.

``sample_single_stage`` wrapped *every* exception from
``comfy.sample.sample_custom`` in "Confirm the sampler supports standard ComfyUI
SAMPLER objects and MiniMax H3 NestedTensor inputs". That is the right hint for a
genuine API mismatch and the wrong one for an out-of-memory error - and it did
real damage, because the executor already handles ``torch.OutOfMemoryError``
with an accurate message ("ran out of VRAM during H3 sampling", naming
resolution, reference count and ``clear_vram_between_segments``). The blanket
wrapper converted the OOM into a plain ``RuntimeError`` first, so that handler
could never match and the user was sent chasing a sampler-compatibility problem.

The real fault was arithmetic: 1376x768 at 362 frames puts ~81,780 attention
tokens through a sampler (``[H3Utils] SLA: ... S=81780``) alongside a ~20 GB
model on a 24 GB card.

Both halves are pinned here: OOM propagates as itself, and genuine sampler
errors still get the compatibility hint.
"""

import sys
import types

import pytest

torch = pytest.importorskip("torch")

try:
    from mmx_pkg.director import core_sampling
except ImportError as exc:  # pragma: no cover - environment guard
    pytest.skip(f"Director package unavailable: {exc}", allow_module_level=True)


class _Boom(Exception):
    """Stands in for a sampler that genuinely cannot handle the inputs."""


def _install_comfy_stubs(monkeypatch, sample_custom):
    """Minimal comfy surface for the external-sampler branch."""
    tensor = torch.zeros((1, 4, 2, 2), dtype=torch.float32)

    sample_mod = types.ModuleType("comfy.sample")
    sample_mod.fix_empty_latent_channels = lambda model, x, *a: x
    sample_mod.prepare_noise = lambda x, seed, batch_index=None: tensor
    sample_mod.sample_custom = sample_custom
    sample_mod.sample = lambda *a, **k: tensor

    utils_mod = types.ModuleType("comfy.utils")
    utils_mod.PROGRESS_BAR_ENABLED = False

    comfy_mod = types.ModuleType("comfy")
    comfy_mod.sample = sample_mod
    comfy_mod.utils = utils_mod

    extras = types.ModuleType("comfy_extras.nodes_minimax_h3")
    extras.MiniMaxH3SigmaShift = object

    for name, mod in (
        ("comfy", comfy_mod),
        ("comfy.sample", sample_mod),
        ("comfy.utils", utils_mod),
        ("comfy_extras", types.ModuleType("comfy_extras")),
        ("comfy_extras.nodes_minimax_h3", extras),
    ):
        monkeypatch.setitem(sys.modules, name, mod)

    # The external branch is what the Director uses; skip sigma validation.
    monkeypatch.setattr(
        core_sampling,
        "validate_external_sampling",
        lambda model, sampler, sigmas: (["sigma"], 8),
        raising=False,
    )
    return tensor


def _call(tensor):
    return core_sampling.sample_single_stage(
        model=object(),
        positive=[],
        negative=[],
        latent={"samples": tensor},
        seed=1,
        cfg=1.0,
        steps=8,
        sampler_name="res_multistep",
        scheduler="simple",
        external_sampler=object(),
        external_sigmas=[1.0, 0.0],
    )


def test_oom_propagates_without_being_relabelled(monkeypatch):
    def sample_custom(*a, **k):
        raise torch.OutOfMemoryError(
            "Allocation on device 0 would exceed allowed memory. (out of memory)"
        )

    tensor = _install_comfy_stubs(monkeypatch, sample_custom)

    with pytest.raises(torch.OutOfMemoryError):
        _call(tensor)


def test_oom_is_not_wrapped_in_a_runtime_error(monkeypatch):
    """The executor matches on torch.OutOfMemoryError, so the type must survive."""

    def sample_custom(*a, **k):
        raise torch.OutOfMemoryError("out of memory")

    tensor = _install_comfy_stubs(monkeypatch, sample_custom)

    try:
        _call(tensor)
    except torch.OutOfMemoryError:
        pass
    except BaseException as exc:  # anything else is a regression
        raise AssertionError(
            f"OOM was converted to {type(exc).__name__}: {exc}"
        ) from exc
    else:
        raise AssertionError("expected the OOM to propagate")


def test_genuine_sampler_errors_still_get_the_compatibility_hint(monkeypatch):
    """The diagnostic is valuable - only OOM should bypass it."""

    def sample_custom(*a, **k):
        raise _Boom("sampler does not understand NestedTensor")

    tensor = _install_comfy_stubs(monkeypatch, sample_custom)

    with pytest.raises(RuntimeError) as info:
        _call(tensor)

    message = str(info.value)
    assert "external SAMPLER failed" in message
    assert "NestedTensor" in message
    assert "sampler does not understand NestedTensor" in message


def test_successful_sampling_is_unchanged(monkeypatch):
    holder = {}

    def sample_custom(*a, **k):
        return holder["tensor"]

    tensor = _install_comfy_stubs(monkeypatch, sample_custom)
    holder["tensor"] = tensor

    out = _call(tensor)

    assert torch.equal(out["samples"], tensor)


# --- every OOM handler reports the same way -------------------------------------
#
# Four code paths can hit a CUDA OOM (H3 sampling, the Source Bridge sample,
# Motion Context encoding, Global Refine/upscale) and each used to raise its own
# hand-written sentence. They all go through lib.vram_budget.oom_message now, so
# the message carries the segment shape, the tokens, the attention workspace, the
# free memory and the concrete settings to change - the same numbers the
# pre-flight check reports, which is what makes the two agree.

import pathlib  # noqa: E402

_REPO = pathlib.Path(__file__).resolve().parent.parent


def _source(relative: str) -> str:
    return (_REPO / relative).read_text(encoding="utf-8")


def test_every_oom_handler_uses_the_shared_message():
    expected = {
        "director/executor_core_legacy.py": 2,   # H3 sampling + Source Bridge
        "director/motion_context.py": 2,         # visual + audio context encode
        "director/refine_sampling.py": 1,        # Global Refine / upscale
    }
    for relative, count in expected.items():
        source = _source(relative)
        assert source.count("vram_budget.oom_message(") == count, relative


def test_the_unattributed_sentences_are_gone():
    for relative in ("director/executor_core_legacy.py", "director/motion_context.py"):
        source = _source(relative)
        assert "Motion Director ran out of VRAM" not in source, relative

    # Global Refine keeps the plain sentence, but only as the fallback taken when
    # the budget module cannot be imported at all (the stub harnesses load this
    # module from a tree where a relative `lib` import is unreachable). The message
    # that actually ships carries the numbers.
    refine = _source("director/refine_sampling.py")
    assert refine.count("Motion Director ran out of VRAM") == 1
    assert "return vram_budget.oom_message(" in refine
    assert "_refine_oom_message" in refine
    assert "raise RuntimeError(_refine_oom_message())" in refine


def test_the_preflight_estimate_and_the_oom_message_share_one_model():
    """Both must describe a segment the same way, or the warning misleads."""
    executor = _source("director/executor_core_legacy.py")
    assert "vram_budget.shape_from(" in executor, "the sampler OOM names its segment shape"
    assert "vram_budget.device_free_gb()" in executor, "and how much was free at the time"
    assert "vram_budget.suggestions_for(" in executor, "and what to change"

    preflight = _source("director/preflight.py")
    assert "vram_budget.evaluate(" in preflight
    assert "_segment_shapes(plan" in preflight, "the estimate is built from the rebuilt plan"
