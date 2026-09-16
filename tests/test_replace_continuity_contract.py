"""Character Replace continuity-anchor wiring (source contract).

The executor is a monolithic function, so its continuity wiring is pinned by
asserting the source call sites exist and sit in the right place: each replace
window records its last rendered frame, and the next window re-injects that
frame as an extra <Picture> reference so adjacent windows open from the prior
output's pose instead of a fresh guess.
"""

from pathlib import Path


def _source() -> str:
    return Path("director/executor_core_legacy.py").read_text(encoding="utf-8")


def test_replace_output_tails_state_is_declared():
    assert "replace_output_tails: dict[int, torch.Tensor] = {}" in _source()


def test_previous_window_tail_is_looked_up():
    source = _source()
    assert "prev_slots = [slot for slot in replace_output_tails if slot < timeline_slot]" in source
    assert "replace_continuity_frame = replace_output_tails[max(prev_slots)]" in source


def test_continuity_anchor_is_injected_after_inputs():
    source = _source()
    inputs_at = source.index("_build_minimax_inputs(")
    inject_at = source.index("continuity anchor injected as <Picture")
    assert inputs_at < inject_at
    # The anchor must be added to the ref dict before conditioning runs.
    cond_at = source.index("run_minimax_conditioning(")
    assert inject_at < cond_at


def test_tails_are_recorded_after_each_replace_window():
    source = _source()
    assert "replace_output_tails[int(seg.timeline_index)] = chunk[-1:].clone()" in source
    # Cache-reused windows still provide continuity for the next window.
    assert "replace_output_tails[int(seg.timeline_index)] = cached[-1:].clone()" in source
