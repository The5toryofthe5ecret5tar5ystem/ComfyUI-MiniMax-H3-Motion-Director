"""Every input the Director declares must actually be bound by the code that runs.

This is the generalisation of two real bugs found the same way:

* ``refmod_conditioning`` was declared in ``INPUT_TYPES`` (so the socket appeared,
  the wire connected, and ComfyUI's history showed the link) but the effective
  ``execute`` had no such parameter. ComfyUI passed the incoming conditioning into
  ``**kwargs`` where it was discarded, so a correctly wired RefMod did nothing.
* ``audio_refine_enabled / audio_refine_steps / audio_refine_denoise`` had the same
  problem - the Audio Refine widgets were always silently ignored.

Both were invisible because a declared-but-unbound input looks identical to an
unused one from the outside. The registered class is the third in an inheritance
chain (``director_output`` -> ``director_inputs`` -> ``director``), so patching
``nodes/director.py`` changed nothing at runtime.

The rule these tests enforce: **an input is only real if the running ``execute``
names it.**
"""

from __future__ import annotations

import inspect

import pytest

try:
    from mmx_pkg.nodes.director_inputs import MiniMaxH3MotionDirector as _InputsDirector
    from mmx_pkg.nodes.director_output import MiniMaxH3MotionDirector as RegisteredDirector
except ImportError as exc:  # pragma: no cover - environment guard
    pytest.skip(f"Director package unavailable: {exc}", allow_module_level=True)


# Frontend-only section-header widgets. They hold a widgets_values slot so the
# custom UI can find its sections, and ComfyUI sends them as named inputs, but the
# node never reads a value from them - they are headings.
UI_ONLY_INPUTS = frozenset({
    "bd_grp_sample",
    "bd_grp_motion",
    "bd_grp_advanced",
    "bd_grp_perf",
    "bd_grp_experimental",
    "bd_grp_audio_refine",
})

# Inputs ComfyUI injects that the signature does not need to name.
INJECTED_INPUTS = frozenset({"unique_id", "prompt", "extra_pnginfo"})


def _declared_inputs() -> set[str]:
    schema = RegisteredDirector.INPUT_TYPES()
    names: set[str] = set()
    for group in ("required", "optional"):
        names.update(schema.get(group) or {})
    return names


def _effective_execute():
    """The ``execute`` that actually receives the inputs.

    The registered class inherits a chain of three, and the outermost is a pure
    ``(self, *args, **kwargs)`` forwarder. The one that names inputs is the first
    class up the MRO whose ``execute`` declares parameters - that is the signature
    ComfyUI's kwargs have to match.
    """
    for klass in RegisteredDirector.__mro__:
        fn = klass.__dict__.get("execute")
        if fn is None:
            continue
        params = inspect.signature(fn).parameters
        named = [
            name for name, p in params.items()
            if name != "self"
            and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD,
                           inspect.Parameter.KEYWORD_ONLY)
        ]
        if named:
            return klass, fn
    raise AssertionError("no execute with named parameters found in the MRO")


def _bound_parameters() -> set[str]:
    """Parameters the effective execute accepts by name (not via **kwargs)."""
    _, fn = _effective_execute()
    params = inspect.signature(fn).parameters
    return {
        name for name, p in params.items()
        if name != "self"
        and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD,
                       inspect.Parameter.KEYWORD_ONLY)
    }


def test_the_effective_execute_is_the_director_inputs_override():
    """Pin which class has to carry the input wiring.

    This is the knowledge whose absence caused the bug: the wiring belongs in
    ``director_inputs.MiniMaxH3MotionDirector``, NOT in ``director.py``, because
    that is the implementation the registered class resolves to.
    """
    klass, _ = _effective_execute()
    assert klass is _InputsDirector, (
        f"the effective execute now lives on {klass.__name__}; move the input "
        "wiring to whichever class actually receives the inputs"
    )


def test_the_schema_is_readable():
    declared = _declared_inputs()
    assert len(declared) > 20, f"suspiciously few declared inputs: {sorted(declared)}"


def test_every_declared_input_is_bound_or_explicitly_ui_only():
    """The core contract. A failure here means an input is silently ignored."""
    unbound = sorted(
        name for name in _declared_inputs()
        if name not in _bound_parameters()
        and name not in UI_ONLY_INPUTS
    )
    assert not unbound, (
        "these inputs are declared in INPUT_TYPES but the registered Director's "
        "execute() has no parameter for them, so ComfyUI will drop them into "
        f"**kwargs and ignore the user's setting: {unbound}"
    )


@pytest.mark.parametrize("name", ["refmod_conditioning", "audio_refine_enabled",
                                  "audio_refine_steps", "audio_refine_denoise"])
def test_the_inputs_that_were_silently_dropped_are_bound(name):
    """Named individually so a refactor cannot quietly re-break one of them."""
    assert name in _declared_inputs(), f"{name} is no longer declared at all"
    assert name in _bound_parameters(), f"{name} is declared but not bound"


def test_ui_only_inputs_are_genuinely_not_parameters():
    """The allowlist must not hide a real input by accident."""
    bound = _bound_parameters()
    overlap = sorted(UI_ONLY_INPUTS & bound)
    assert not overlap, (
        f"{overlap} are allowlisted as UI-only but are also bound parameters; "
        "remove them from UI_ONLY_INPUTS"
    )
