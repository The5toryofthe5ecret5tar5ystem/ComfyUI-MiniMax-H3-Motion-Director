"""Keep the frontend widget-tail table in step with the declaration it mirrors.

repairDirectorWidgetTailWorkflow writes defaults into the Director's declaration
tail on load. If that table drifts from the real declaration, the repair silently
paints values into the wrong widget slots - which is worse than the null it was
fixing. Three things have to agree:

  * ``nodes/director.py``          - the declaration and its defaults (the truth)
  * ``tests/test_example_workflow_widgets.py`` - what the shipped files must satisfy
  * ``web/js/minimax_sampling_ui.js``          - the table the repair uses

This test reads the first and the third and fails when they disagree.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SAMPLING_UI = REPO / "web" / "js" / "minimax_sampling_ui.js"
DIRECTOR_PY = REPO / "nodes" / "director.py"
SPEC_MODULE = Path(__file__).resolve().parent / "test_example_workflow_widgets.py"


def _load_spec_module():
    """Load the sibling spec module by path.

    ``tests/`` is not a package, so a plain import would depend on pytest's
    import mode. Reading the file directly keeps this working either way.
    """
    spec = importlib.util.spec_from_file_location("_lts_example_workflow_spec", SPEC_MODULE)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        pytest.fail(f"could not load {SPEC_MODULE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_spec = _load_spec_module()
TAIL_AFTER_POSTPROCESS = _spec.TAIL_AFTER_POSTPROCESS
LEGACY_TAIL_AFTER_POSTPROCESS = _spec.LEGACY_TAIL_AFTER_POSTPROCESS

# The JS kind string that corresponds to each declared Python type.
KIND_FOR_TYPE = {str: "str", bool: "bool", int: "int", float: "float"}

# Tail slots the frontend creates itself, so there is no declaration to compare
# against. minimax_motion_director_ui is added by an addDOMWidget() call in
# minimax_timeline.js and carries the serialized UI state.
FRONTEND_ONLY = {"minimax_motion_director_ui"}


def js_tail_table() -> list[tuple[str, str, object]]:
    """Parse [name, kind, default] rows out of DIRECTOR_WIDGET_TAIL."""
    source = SAMPLING_UI.read_text(encoding="utf-8")
    match = re.search(
        r"const DIRECTOR_WIDGET_TAIL = \[(.*?)\n\];",
        source,
        re.DOTALL,
    )
    if not match:
        pytest.fail("DIRECTOR_WIDGET_TAIL not found in minimax_sampling_ui.js")
    rows: list[tuple[str, str, object]] = []
    for line in match.group(1).splitlines():
        row = re.match(
            r'\s*\[\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*(.+?)\s*\],?\s*$',
            line,
        )
        if not row:
            continue
        name, kind, raw = row.group(1), row.group(2), row.group(3)
        if raw == "false":
            default: object = False
        elif raw == "true":
            default = True
        elif raw.startswith('"'):
            default = raw.strip('"')
        else:
            default = float(raw) if "." in raw else int(raw)
        rows.append((name, kind, default))
    if not rows:
        pytest.fail("DIRECTOR_WIDGET_TAIL is empty or unparsable")
    return rows


def declared_default(widget: str) -> object | None:
    """Read the default the node declares for `widget`, or None if absent."""
    source = DIRECTOR_PY.read_text(encoding="utf-8")
    at = source.find(f'"{widget}": (')
    if at < 0:
        return None
    window = source[at : at + 400]
    hit = re.search(r'"default":\s*(False|True|"[^"]*"|-?[\d.]+)', window)
    if not hit:
        return None
    raw = hit.group(1)
    if raw == "False":
        return False
    if raw == "True":
        return True
    if raw.startswith('"'):
        return raw.strip('"')
    return float(raw) if "." in raw else int(raw)


def test_js_table_matches_the_declaration_order() -> None:
    """Names, in order, or the repair writes into the wrong slots."""
    js_names = [name for name, _, _ in js_tail_table()]
    py_names = [name for name, _ in TAIL_AFTER_POSTPROCESS]
    assert js_names == py_names, (
        "DIRECTOR_WIDGET_TAIL and TAIL_AFTER_POSTPROCESS disagree.\n"
        f"  js: {js_names}\n  py: {py_names}"
    )


def test_js_kinds_match_the_declared_types() -> None:
    """A kind mismatch turns a benign slot into one the repair will overwrite."""
    js = js_tail_table()
    for (js_name, js_kind, _), (py_name, py_type) in zip(js, TAIL_AFTER_POSTPROCESS):
        assert js_name == py_name
        assert js_kind == KIND_FOR_TYPE[py_type], (
            f"{js_name}: JS treats it as {js_kind!r}, the declaration says "
            f"{py_type.__name__}"
        )


def test_js_defaults_match_the_node_declaration() -> None:
    """A stale default would be written into every repaired workflow."""
    for name, _kind, js_default in js_tail_table():
        if name in FRONTEND_ONLY:
            assert js_default == "", (
                f"{name} is frontend-created, so its default must be an empty "
                f"string, not {js_default!r}"
            )
            continue
        declared = declared_default(name)
        assert declared is not None, f"{name} is not declared in nodes/director.py"
        assert js_default == declared, (
            f"{name}: JS default is {js_default!r}, the node declares {declared!r}"
        )


def test_frontend_only_slots_really_are_frontend_created() -> None:
    """If one of these grows a declaration, it stops being exempt above."""
    timeline = (REPO / "web" / "js" / "minimax_timeline.js").read_text(encoding="utf-8")
    for name in FRONTEND_ONLY:
        assert declared_default(name) is None, (
            f"{name} is now declared in nodes/director.py - drop it from FRONTEND_ONLY"
        )
        assert f'addDOMWidget("{name}"' in timeline, (
            f"{name} is exempt from the declaration check but nothing creates it"
        )


def test_legacy_table_drops_only_verbose_logging() -> None:
    """The legacy shape is the same tail minus the one widget added later."""
    legacy_js = [name for name, _, _ in js_tail_table() if name != "verbose_logging"]
    legacy_py = [name for name, _ in LEGACY_TAIL_AFTER_POSTPROCESS]
    assert legacy_js == legacy_py


def test_the_repair_is_wired_into_the_load_hook() -> None:
    """An exported repair nothing calls would pass every test above."""
    timeline = (REPO / "web" / "js" / "minimax_timeline.js").read_text(encoding="utf-8")
    assert "repairDirectorWidgetTailWorkflow" in timeline, "not imported/called"
    hook = re.search(r"beforeConfigureGraph\(graphData\)\s*\{(.*?)\n    \},", timeline, re.DOTALL)
    assert hook, "beforeConfigureGraph not found in minimax_timeline.js"
    assert "repairDirectorWidgetTailWorkflow(graphData)" in hook.group(1), (
        "the repair is imported but not called in beforeConfigureGraph"
    )
