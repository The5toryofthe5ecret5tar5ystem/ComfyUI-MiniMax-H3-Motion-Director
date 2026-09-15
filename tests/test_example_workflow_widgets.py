"""Keep the shipped example workflows queueable.

Regression guard for a real failure: re-saving the ref2va example in ComfyUI appended
the audio-refine widget slots and filled them with ``None`` (the frontend had no saved
value to restore). The backend then refused the prompt with

    Failed to convert an input value to a FLOAT value: audio_refine_denoise, None
    Failed to convert an input value to a INT value: audio_refine_steps, None

ComfyUI coerces widget values by declaration type, so ``int(None)`` / ``float(None)``
raise while ``str(None)`` / ``bool(None)`` do not -- which is why only the two numeric
slots broke. A ``None`` in a *numeric* slot is always a bug; a ``None`` in a group-header
or boolean slot is normal in these files and is left alone.
"""

from __future__ import annotations

import json

import pytest
from pathlib import Path

WORKFLOW_DIR = Path(__file__).resolve().parents[1] / "example_workflows"

# Declaration order tail of MiniMaxH3MotionDirector (see nodes/director.py). These are
# the slots ComfyUI appends after `postprocess_config`, and the types it coerces them to.
TAIL_AFTER_POSTPROCESS: list[tuple[str, type]] = [
    ("bd_grp_audio_refine", str),
    ("audio_refine_enabled", bool),
    ("audio_refine_steps", int),
    ("audio_refine_denoise", float),
    ("latent_continuation_enabled", bool),
    ("verbose_logging", bool),
    ("minimax_motion_director_ui", str),
]

# Files saved before verbose_logging was declared end one slot earlier. Both
# shapes must stay loadable, so every check below accepts either tail.
LEGACY_TAIL_AFTER_POSTPROCESS: list[tuple[str, type]] = [
    ("bd_grp_audio_refine", str),
    ("audio_refine_enabled", bool),
    ("audio_refine_steps", int),
    ("audio_refine_denoise", float),
    ("latent_continuation_enabled", bool),
    ("minimax_motion_director_ui", str),
]

VALID_TAILS = (TAIL_AFTER_POSTPROCESS, LEGACY_TAIL_AFTER_POSTPROCESS)

NUMERIC = (int, float)


def director_nodes(path: Path):
    try:
        workflow = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [n for n in workflow.get("nodes", []) if n.get("type") == "MiniMaxH3MotionDirector"]


def workflow_files() -> list[Path]:
    return sorted(WORKFLOW_DIR.glob("*.json"))


def test_there_are_examples_to_check():
    """Guard against the glob silently matching nothing."""
    assert workflow_files(), f"no workflows found under {WORKFLOW_DIR}"


@pytest.mark.parametrize("path", workflow_files(), ids=lambda p: p.name)
def test_numeric_widget_slots_are_never_none(path: Path):
    """A None in an INT/FLOAT widget slot makes the workflow unqueueable."""
    for node in director_nodes(path):
        values = node.get("widgets_values") or []
        for index, value in enumerate(values):
            if value is not None:
                continue
            # Only the tail is type-mapped reliably enough to assert on; mid-array None
            # slots are section headers / booleans and are tolerated by ComfyUI.
            for tail_spec in VALID_TAILS:
                if index < len(values) - len(tail_spec):
                    continue
                name, expected = tail_spec[index - (len(values) - len(tail_spec))]
                if expected in NUMERIC:
                    pytest.fail(
                        f"{path.name}: widgets_values[{index}] ({name}) is None; "
                        f"ComfyUI will fail with 'Failed to convert an input value to a "
                        f"{expected.__name__.upper()} value'"
                    )


@pytest.mark.parametrize("path", workflow_files(), ids=lambda p: p.name)
def test_audio_refine_tail_has_real_values(path: Path):
    """The five slots after `postprocess_config` must carry concrete values."""
    for node in director_nodes(path):
        values = node.get("widgets_values") or []
        # `timeline_data` is also a JSON string starting with {"version":, so match on a
        # key only the postprocess config carries.
        config_index = next(
            (i for i, v in enumerate(values)
             if isinstance(v, str) and v.startswith('{"version":')
             and '"global_refine"' in v), None)
        if config_index is None:
            continue
        available = values[config_index + 1:]
        if not available:
            continue                                    # older file: widgets fall back to defaults
        for tail_spec in VALID_TAILS:
            if len(available) < len(tail_spec):
                continue
            tail = available[: len(tail_spec)]
            for (name, expected), value in zip(tail_spec, tail):
                assert value is not None, f"{path.name}: {name} is None"
                assert isinstance(value, expected), (
                    f"{path.name}: {name} should be {expected.__name__}, got {type(value).__name__}"
                )
            break
        else:
            pytest.fail(
                f"{path.name}: unexpected widget tail after postprocess_config: "
                f"{available!r}"
            )


@pytest.mark.parametrize("path", workflow_files(), ids=lambda p: p.name)
def test_widget_state_mirror_has_no_none_for_audio_refine(path: Path):
    """The state mirror is what re-injects the Nones on load."""
    for node in director_nodes(path):
        state = (node.get("properties") or {}).get("mmx_director_widget_state") or {}
        for name, _ in TAIL_AFTER_POSTPROCESS:
            if name in state:
                assert state[name] is not None, (
                    f"{path.name}: mmx_director_widget_state['{name}'] is None, which the "
                    "frontend will restore into widgets_values"
                )
