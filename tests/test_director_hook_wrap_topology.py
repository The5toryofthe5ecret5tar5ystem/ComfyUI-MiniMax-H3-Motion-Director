"""The Director node's six hooks are wrapped by four separate modules.

This file exists because that topology is currently **accidental and invisible**, and
item 5 (folding the `zz_*` layers) cannot proceed safely until it is written down.

What is actually true, verified against the running server:

* The pack's ``WEB_DIRECTORY`` is ``./web/js``, and ComfyUI's ``/extensions`` route builds
  its list with ``glob.glob(..., recursive=True)`` - **unsorted filesystem order**. No
  sort is applied on the server.
* The live ``/extensions`` order does *not* match the filenames: ``minimax_image_batch.js``,
  ``minimax_i18n.js`` and ``minimax_timeline.js`` are all served **after** both ``zz_``
  files. So the ``zz_`` prefix is not achieving "loads last" - whatever order exists today
  comes from directory enumeration, not from the name.
* Four modules wrap the same six prototypes:
  ``minimax_director_inputs.js``, ``minimax_director_sections.js``,
  ``zz_minimax_audio_drive_ui.js``, ``zz_minimax_director_runtime_fix.js``.
  Each captures ``prototype[hook]`` and chains via ``original?.apply(this, arguments)``,
  so the *work* runs in registration order - i.e. in enumeration order.
* The order turns out **not** to be load-bearing, and the reason is worth recording so
  nobody "fixes" it later: ``runtime_fix.js`` wraps ``onDrawBackground`` and calls its own
  ``syncRuntimeFix`` **both before and after** the inner chain, on every draw frame. Its
  own comment states the intent - reassert ownership before LiteGraph paints so stale
  rows and old-language labels never reach a visible frame. Running the correction on both
  sides of the chain makes it the last writer regardless of which module wrapped first.
  ``sections`` additionally polls on an interval, and ``runtime_fix`` re-asserts at
  ``[0, 80, 250, 800]`` ms after each hook plus a microtask and a rAF. So the layers do not
  race for position; they re-assert, and the correction layer wins by construction.

(I initially recorded the opposite conclusion here - that a correction layer running before
 the layer it corrects was "a bug waiting to happen". That was inferred from reading the
 wrap sites and was wrong; the pre/post bracket is what makes ordering irrelevant.)

These tests freeze the topology as it stands and pin the two properties that silently
break if someone edits a wrapper: that each wrapper still chains to the inner handler, and
that no hook is wrapped by a module not listed here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WEB_JS = Path(__file__).resolve().parents[1] / "web" / "js"

# Frozen topology: module -> the node hooks it wraps, and the extension it registers.
# EXTRACTED from the source, not assumed - the first version of this table was guessed
# from partial reads and was wrong for two of the four modules. 19 wrapper installs in
# total across the six hooks; runtime_fix is the only one that wraps all six.
# Changing this table is a deliberate act; changing a wrapper without updating it fails.
WRAP_SITES = {
    "minimax_director_inputs.js": {
        "extension": "MiniMaxH3.MotionDirector.UnifiedInputs",
        "hooks": {"onNodeCreated", "onConfigure", "onConnectionsChange", "onRemoved"},
    },
    "minimax_director_sections.js": {
        "extension": "MiniMaxH3.MotionDirector.MainSections",
        "hooks": {
            "onNodeCreated",
            "onConfigure",
            "onConnectionsChange",
            "onDrawBackground",
            "onRemoved",
        },
    },
    "zz_minimax_audio_drive_ui.js": {
        "extension": "MiniMaxH3.MotionDirector.AudioRoles",
        # onDrawBackground is assigned directly; the other three come from a
        # `for (const hook of [...])` loop with a computed prototype[hook] assignment.
        "hooks": {"onNodeCreated", "onConfigure", "onWidgetChanged", "onDrawBackground"},
    },
    "zz_minimax_director_runtime_fix.js": {
        "extension": "MiniMaxH3.MotionDirector.RuntimeContinuityFix",
        "hooks": {
            "onNodeCreated",
            "onConfigure",
            "onConnectionsChange",
            "onWidgetChanged",
            "onDrawBackground",
            "onRemoved",
        },
    },
}

# The module that corrects the others, and the one whose decisions it corrects. Kept here
# so that if the re-assertion mechanism below is ever removed, the ordering question comes
# back and this pairing has to be re-examined.
CORRECTION_LAYER = "zz_minimax_director_runtime_fix.js"
GENERAL_LAYER = "minimax_director_sections.js"

_ASSIGN_HOOK = re.compile(r"nodeType\.prototype\.(\w+)\s*=\s*function")

# `for (const hook of ["onNodeCreated", ...]) { nodeType.prototype[hook] = ... }`
# The computed assignment itself is not statically enumerable, but its literal list is,
# and that is what the wrapper actually installs.
_HOOK_LIST = re.compile(r"for\s*\(\s*const\s+(\w+)\s+of\s*\[([^\]]+)\]\s*\)")

# `const X = nodeType.prototype.hook;` or `const X = nodeType.prototype[hook];` - the
# previous handler a wrapper must chain to.
_CAPTURE = re.compile(r"const\s+(\w+)\s*=\s*nodeType\.prototype(?:\.\w+|\[[^\]]+\])\s*;")


def _source(name: str) -> str:
    path = WEB_JS / name
    assert path.is_file(), f"wrap site is missing: {name}"
    return path.read_text(encoding="utf-8")


def _wrapped_hooks(source: str) -> set[str]:
    """Hooks this module installs a wrapper on, by either assignment style."""
    hooks = set(_ASSIGN_HOOK.findall(source))
    for variable, literals in _HOOK_LIST.findall(source):
        if not re.search(rf"nodeType\.prototype\[{re.escape(variable)}\]\s*=", source):
            continue
        hooks |= set(re.findall(r'"(\w+)"', literals))
    return hooks


@pytest.mark.parametrize("module", sorted(WRAP_SITES))
def test_wrap_topology_is_unchanged(module: str):
    expected = WRAP_SITES[module]["hooks"]
    actual = _wrapped_hooks(_source(module))
    assert actual == expected, (
        f"{module} wraps {sorted(actual)} but {sorted(expected)} is pinned. "
        "The Director node's hooks are wrapped by four modules whose relative order is "
        "not guaranteed (ComfyUI enumerates extensions unsorted), so adding or removing a "
        "wrapper changes behaviour in a way nothing else would catch. Update the table "
        "deliberately, and check the correction layer still runs after the general layer."
    )


@pytest.mark.parametrize("module", sorted(WRAP_SITES))
def test_wrap_sites_register_the_pinned_extension(module: str):
    source = _source(module)
    name = WRAP_SITES[module]["extension"]
    assert f'name: "{name}"' in source, (
        f"{module} no longer registers {name}. Two modules registering one name, or a "
        "module losing its name, both break the frontend's extension bookkeeping."
    )


@pytest.mark.parametrize("module", sorted(WRAP_SITES))
def test_every_captured_handler_is_chained(module: str):
    """A wrapper that captures the previous handler but never calls it silently disables it.

    Checked by variable identity, not by proximity: every
    ``const X = nodeType.prototype.<hook>;`` capture must be invoked as
    ``X?.apply(this, arguments)`` somewhere in the file. An earlier version of this test
    scanned a window of text after each assignment instead and did **not** notice
    ``const result = onRemoved?.apply(this, arguments);`` being replaced with
    ``const result = undefined;`` - verified by probe, so the weaker form was discarded.
    """
    source = _source(module)
    captures = list(_CAPTURE.finditer(source))
    assert captures, f"no prototype captures found in {module} - the scan is probably broken"

    # Scoped per capture SITE, not per variable name: a module may capture the same hook
    # twice (director_inputs captures onRemoved twice behind two wrap functions), so a
    # file-wide search would keep passing after one of the two invocations was removed.
    # The pattern is always `const X = prototype.hook;` immediately followed by the
    # replacement wrapper whose body calls `X?.apply(...)`, so the segment up to the next
    # capture is exactly the wrapper body.
    breaks: list[str] = []
    for index, match in enumerate(captures):
        end = captures[index + 1].start() if index + 1 < len(captures) else len(source)
        window = source[match.start():end]
        variable = match.group(1)
        if not re.search(rf"\b{re.escape(variable)}\?\s*\.\s*apply\(this,\s*arguments\)", window):
            breaks.append(f"{variable} (capture #{index + 1})")

    assert not breaks, (
        f"{module} captures {breaks} from the prototype chain but never calls them. "
        "Every other wrapper in the pack chains to the handler it replaced; a missing "
        "call disables whichever module was wrapped before this one, with no error "
        "anywhere."
    )


def test_order_independence_is_achieved_by_reassertion_not_load_order():
    """The correction layer wins by re-asserting, not by loading last.

    Its ``onDrawBackground`` wrapper calls ``syncRuntimeFix`` on BOTH sides of the inner
    chain, every draw frame, so it is the last writer no matter which module wrapped
    first. That is precisely why the load order needs no defending - and why the remaining
    `zz_*` consolidation has no correctness motivation.

    If this ever becomes a single call, ordering starts to matter again.
    """
    source = _source(CORRECTION_LAYER)
    start = source.index("const onDrawBackground = nodeType.prototype.onDrawBackground;")
    body = source[start:source.index("const onRemoved = nodeType.prototype.onRemoved;", start)]

    calls = [m.start() for m in re.finditer(r"syncRuntimeFix\(this\);", body)]
    chain = body.index("const result = onDrawBackground?.apply(this, arguments);")

    assert len(calls) >= 2, (
        "the correction layer must re-assert on both sides of the inner chain; with a "
        "single call it becomes load-order dependent again"
    )
    assert calls[0] < chain < calls[-1], (
        "syncRuntimeFix must bracket the inner onDrawBackground chain, not run only after it"
    )


def test_the_correction_layer_is_still_the_post_fix_layer():
    """runtime_fix must keep overriding the general pass, not replace it.

    It should reference the shared core predicates rather than reimplementing visibility
    rules, so the two layers agree about *what* a widget's state should be.
    """
    source = _source(CORRECTION_LAYER)
    assert "minimax_director_runtime_fix_core.mjs" in source, (
        "the correction layer must keep using its shared core predicates"
    )
    for predicate in (
        "keepSamplingSourceHidden",
        "restoreContinuityWidgetRenderer",
        "generatedAudioContinuationShouldBeInteractive",
    ):
        assert predicate in source, f"correction layer lost its {predicate} handling"

    # And the general layer must stay a pure "apply my section layout" pass - if it starts
    # calling the correction predicates too, the two layers have merged and the ordering
    # question changes shape.
    general = _source(GENERAL_LAYER)
    for predicate in ("keepSamplingSourceHidden", "restoreContinuityWidgetRenderer"):
        assert predicate not in general, (
            f"{GENERAL_LAYER} now calls {predicate}; the layering has merged and "
            "CORRECTION_LAYER's role needs rethinking rather than assuming."
        )
