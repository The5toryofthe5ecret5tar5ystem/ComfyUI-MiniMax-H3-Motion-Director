"""RefMod diagnostics must be visible from the console.

Two failures used to look identical to the user and to `grep comfyui.log`:

1. `refmod_conditioning` was never wired - the node silently appended nothing.
2. It *was* wired but carried no reference blocks - same silence.

The only signal either way was a conditional line in the node's `report`, which
is delivered to the UI text output and never printed. A user debugging "the mod
had no effect" could not tell a wiring fault from a weak mod.

There was a second, actively misleading signal: `gen_timeline` warned

    "gen segment #N task=r2v has no reference media - will behave like t2v/t2i"

for every segment, because it only counted the Director's own picture/video/audio
slots. It knew nothing about RefMod blocks, which the executor appends to the
segment conditioning later. So a correctly-wired RefMod run still claimed it had
no references at all.

These tests pin the fix for both.
"""

from __future__ import annotations

import logging

import pytest

try:
    from mmx_pkg.director.gen_timeline import build_gen_director_plan
except ImportError as exc:  # pragma: no cover - environment guard
    pytest.skip(f"Director package unavailable: {exc}", allow_module_level=True)


GEN_LOG = "ComfyUI-MiniMax-H3-Motion-Director.director.gen"

# build_gen_director_plan's keyword signature.
_KW = dict(
    global_task_type="r2v",
    global_prompt="a scene",
    total_frames=81,
    frame_rate=24.0,
    width=512,
    height=512,
    ref_max_size=1024,
)


def _r2v_timeline() -> dict:
    """A prompt_batch r2v timeline with no uploaded reference media."""
    return {
        "timelineMode": "prompt_batch",
        "global": {"taskType": "r2v", "prompt": "a scene"},
        "gen": {"defaultFrameCount": 81},
        "segments": [{"prompt": "one"}],
        "output": {},
    }


# ---------------------------------------------------------------------------
# the misleading "no reference media" warning
# ---------------------------------------------------------------------------

def test_without_refmods_the_no_reference_media_warning_still_fires(caplog):
    """The warning is correct when there is genuinely nothing to reference."""
    with caplog.at_level(logging.WARNING, logger=GEN_LOG):
        build_gen_director_plan(_r2v_timeline(), **_KW)
    assert any("has no reference media" in record.message for record in caplog.records), (
        "the warning must still fire for a plain r2v segment with no media"
    )


def test_refmod_blocks_replace_the_warning_with_an_info_line(caplog):
    """A RefMod-conditioned segment must not be told it behaves like t2v/t2i."""
    with caplog.at_level(logging.INFO, logger=GEN_LOG):
        build_gen_director_plan(_r2v_timeline(), **_KW, refmod_block_count=2)

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not [r for r in warnings if "has no reference media" in r.message], (
        "a segment carrying RefMod blocks was still told it has no references"
    )
    infos = [r for r in caplog.records if "RefMod reference block(s)" in r.message]
    assert infos, "expected an info line naming the RefMod block count"
    assert "2" in infos[0].getMessage()


def test_refmod_block_count_defaults_to_zero():
    """Callers that predate the flag (Mixed, resume analysis) keep the old wording."""
    import inspect

    params = inspect.signature(build_gen_director_plan).parameters
    assert params["refmod_block_count"].default == 0


# ---------------------------------------------------------------------------
# The three wiring states and the shared harvest helper are covered by
# tests/test_refmod_registered_class.py, which tests the class that actually runs.
# This file covers the plan-builder warning.
# ---------------------------------------------------------------------------
