"""The Resume dialog's authoritative cache analysis must not explode.

`analyze_resume_cache` stamps `plan.color_reanchor_enabled` AFTER building the
plan, but it used to forward the whole caller dict into `prepare_director_plan()`
— which does not accept that key. Every call from the frontend sends it, so the
authoritative analysis raised TypeError on *every* Resume, the route returned a
generic error, and the dialog quietly fell back to its heuristic. That is how a
Resume that was doomed to re-render from S1 still displayed as healthy.

These tests pin the contract: the toggle is consumed, not forwarded.
"""

import inspect

import pytest

try:
    from mmx_pkg.nodes.director_common import (
        analyze_resume_cache,
        prepare_director_plan,
    )
except Exception as exc:  # pragma: no cover - depends on the local install
    pytest.skip(f"cannot import the node package: {exc}", allow_module_level=True)


# Every key the resume_preview route is able to forward, plus the toggle.
ROUTE_KEYS = (
    "timeline_data",
    "task_type",
    "global_prompt",
    "total_frames",
    "frame_rate",
    "width",
    "height",
    "ref_max_size",
    "motion_context_enabled",
    "color_reanchor_enabled",
    "i2v_groups",
    "r2v_groups",
)


def test_color_reanchor_is_not_a_prepare_director_plan_parameter():
    """If this ever becomes a real parameter the forwarding bug is re-armed."""
    params = set(inspect.signature(prepare_director_plan).parameters)
    assert "color_reanchor_enabled" not in params, (
        "prepare_director_plan now accepts color_reanchor_enabled; re-check that "
        "analyze_resume_cache still wants to pop it"
    )


def test_route_keys_are_accepted_or_consumed():
    """No key the route can send may be able to reach prepare_director_plan."""
    params = set(inspect.signature(prepare_director_plan).parameters)
    params.discard("unique_id")
    unconsumed = set(ROUTE_KEYS) - params - {"color_reanchor_enabled"}
    assert not unconsumed, f"route keys with nowhere to go: {sorted(unconsumed)}"


def test_analyze_resume_cache_accepts_color_reanchor_enabled():
    """The reported crash: an empty timeline must report 'empty plan', not a TypeError."""
    result = analyze_resume_cache(
        "__mmx_resume_contract_probe__",
        timeline_data="",
        task_type="",
        global_prompt="",
        total_frames=0,
        frame_rate=24,
        width=0,
        height=0,
        ref_max_size=0,
        motion_context_enabled=True,
        color_reanchor_enabled=True,
    )
    assert isinstance(result, dict), "must always report a dict"
    text = repr(result)
    assert "unexpected keyword argument" not in text, (
        "the toggle must be consumed, not forwarded into prepare_director_plan(): "
        f"{result}"
    )
    assert "color_reanchor_enabled" not in text, (
        f"the toggle leaked into the plan build: {result}"
    )
    # It must have reached the planner and reported a real plan error.
    assert result.get("error"), f"expected a plan error, got: {result}"


def test_analyze_resume_cache_handles_every_route_key():
    """Passing the full route payload must not raise."""
    payload = {key: None for key in ROUTE_KEYS}
    payload.update(
        {
            "timeline_data": "",
            "task_type": "",
            "global_prompt": "",
            "total_frames": 0,
            "frame_rate": 24,
            "width": 0,
            "height": 0,
            "ref_max_size": 0,
            "motion_context_enabled": True,
            "color_reanchor_enabled": False,
        }
    )
    result = analyze_resume_cache("__mmx_resume_contract_probe__", **payload)
    assert isinstance(result, dict)
    assert "unexpected keyword argument" not in str(result), result
