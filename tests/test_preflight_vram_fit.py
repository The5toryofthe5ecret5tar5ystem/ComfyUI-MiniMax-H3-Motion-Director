"""The VRAM fit check inside Validate.

The validator is the last place that can say "this segment will not fit" before
a render spends minutes learning it the hard way, so these tests pin:

* the shapes it builds from the rebuilt plan (segment length, canvas, reference
  count and size, Motion Context rows),
* that an over-budget plan is a *warning* - a legitimate request that is
  explained, never blocked and never silently changed,
* that a machine it cannot read, or a plan it cannot shape, produces no estimate
  at all rather than a confident one.
"""

from __future__ import annotations

import pytest

try:
    from mmx_pkg.director import preflight
    from mmx_pkg.lib import vram_budget as vb
except ImportError as exc:  # pragma: no cover - environment guard
    pytest.skip(f"Director package unavailable: {exc}", allow_module_level=True)


class _Segment:
    def __init__(self, index, frames, pictures=2, generated=False):
        self.index = index
        self.frame_count = frames
        self.refs = [object()] * pictures
        self.is_generated = lambda: generated  # noqa: E731 - mirrors the property


class _Plan:
    def __init__(self, segments, *, width=1344, height=768, ref_max_size=1024, run_indices=None):
        self.segments = segments
        self.width = width
        self.height = height
        self.ref_max_size = ref_max_size
        self.run_indices = run_indices


def _patch_machine(monkeypatch, *, total=31.43, free=25.0, baselines=None):
    profile = {
        "device": {"total_vram_gb": total, "free_vram_gb": free},
        "baselines": baselines or {
            "segment_frames": 175, "max_segment_frames": 243,
            "width": 1344, "height": 768, "ref_max_size": 1024,
        },
    }
    monkeypatch.setattr(preflight, "_machine_for_budget", lambda: profile)
    return profile


def _check(plan, monkeypatch, **inputs):
    issues: list = []
    report = preflight._check_vram_fit(plan, inputs, issues)
    return report, issues


def test_shapes_come_from_the_plan_not_the_timeline(monkeypatch):
    _patch_machine(monkeypatch)
    plan = _Plan([_Segment(0, 175), _Segment(1, 243), _Segment(2, 362)])
    shapes = preflight._segment_shapes(plan, context_frames=22)
    assert [s.frames for s in shapes] == [175, 243, 362]
    assert shapes[0].context_frames == 0, "the first segment conditions on nothing"
    assert shapes[1].context_frames == 22 and shapes[1].sampled_frames == 265
    assert shapes[2].pictures == 2 and shapes[2].ref_long_edge == 1024
    assert shapes[1].width == 1344 and shapes[1].height == 768


def test_run_selection_is_respected(monkeypatch):
    _patch_machine(monkeypatch)
    plan = _Plan([_Segment(0, 175), _Segment(1, 362)], run_indices=frozenset({0}))
    shapes = preflight._segment_shapes(plan, context_frames=22)
    assert [s.frames for s in shapes] == [175]


def test_a_baseline_plan_reports_ok_as_info(monkeypatch):
    _patch_machine(monkeypatch)
    report, issues = _check(_Plan([_Segment(0, 175), _Segment(1, 175)]), monkeypatch,
                            context_length=22)
    assert report["verdict"] == "ok"
    assert [i["code"] for i in issues] == ["vram_ok"]
    assert issues[0]["severity"] == "info", "a fitting plan must not look like a problem"


def test_the_failing_project_shape_warns_with_numbers(monkeypatch):
    """S4 of the real project: 311 frames at 1376x768, 2 refs at 1376 px."""
    _patch_machine(monkeypatch, free=0.06)
    plan = _Plan([_Segment(0, 175), _Segment(3, 311)], width=1376, ref_max_size=1376)
    report, issues = _check(plan, monkeypatch, context_length=22)
    assert report["verdict"] == "over"
    found = [i for i in issues if i["code"] == "vram_over"]
    assert len(found) == 1
    assert found[0]["severity"] == "warning", "explain, do not block"
    # The message names the segment (S4); the panel does not prefix it again, so
    # the row reads "S4: 311 frames ..." rather than "Segment 4: S4: 311 ...".
    assert "segment" not in found[0]
    assert found[0]["message"].startswith("S4: 311 frames")
    assert "in one piece" in found[0]["message"]
    assert "reference size to 1024 px" in found[0]["message"]
    assert report["segment"]["sampled_frames"] == 333
    assert report["attention_gb"] == pytest.approx(2.8, abs=0.15)


def test_motion_context_can_be_switched_off_for_the_estimate(monkeypatch):
    _patch_machine(monkeypatch)
    plan = _Plan([_Segment(0, 175), _Segment(1, 175)])
    with_context, _ = _check(plan, monkeypatch, context_length=22)
    without, _ = _check(plan, monkeypatch, motion_context_enabled=False)
    assert with_context["segment"]["sampled_frames"] == 197
    assert without["segment"]["sampled_frames"] == 175


def test_model_bytes_are_reported_as_context(monkeypatch):
    _patch_machine(monkeypatch)
    report, _ = _check(_Plan([_Segment(0, 175)]), monkeypatch, model_bytes=35 * 1024 ** 3)
    assert report["resident_gb"] == pytest.approx(35.0, abs=0.1)
    assert any("35.0 GB of weights" in note for note in report["notes"])


def test_an_unreadable_machine_produces_no_estimate(monkeypatch):
    monkeypatch.setattr(preflight, "_machine_for_budget", lambda: {})
    report, issues = _check(_Plan([_Segment(0, 175)]), monkeypatch)
    # No device numbers, but the tier-ratio comparison is still worth making when
    # baselines are missing? No: without baselines there is nothing to compare to.
    assert report is None
    assert issues == []


def test_an_empty_plan_produces_no_estimate(monkeypatch):
    _patch_machine(monkeypatch)
    report, issues = _check(_Plan([]), monkeypatch)
    assert report is None and issues == []


def test_a_failure_inside_the_estimate_never_breaks_validate(monkeypatch):
    def _boom():
        raise RuntimeError("detection exploded")

    monkeypatch.setattr(preflight, "_machine_for_budget", _boom)
    report, issues = _check(_Plan([_Segment(0, 175)]), monkeypatch)
    assert report is None and issues == []


def test_validate_project_attaches_the_estimate(monkeypatch):
    """End to end through validate_project, with the plan rebuild stubbed."""
    _patch_machine(monkeypatch)

    class _RebuiltPlan(_Plan):
        source_total_frames = 0

    def _prepare(**kwargs):
        return _RebuiltPlan([_Segment(0, 175), _Segment(1, 311)],
                            width=1376, ref_max_size=1376)

    monkeypatch.setattr(preflight, "_check_vram_fit", preflight._check_vram_fit)
    import sys
    import types

    stub = types.ModuleType("mmx_pkg.nodes.director_common")
    stub.prepare_director_plan = _prepare
    monkeypatch.setitem(sys.modules, "mmx_pkg.nodes.director_common", stub)
    monkeypatch.setattr(preflight, "_static_checks", lambda *a, **k: None)

    import json

    payload = preflight.validate_project("77", timeline_data=json.dumps({
        "segments": [{"id": "s1", "start": 0, "length": 175, "prompt": "a"},
                     {"id": "s2", "start": 175, "length": 311, "prompt": "b"}],
    }), task_type="r2v")

    assert payload["ok"] is True
    assert payload["vram"]["verdict"] == "over"
    assert payload["vram"]["segment"]["frames"] == 311
    codes = [i["code"] for i in payload["issues"]]
    assert "vram_over" in codes
    assert all(i["severity"] != "error" for i in payload["issues"])


def test_the_estimator_is_the_one_the_settings_panel_uses(monkeypatch):
    """The same coefficients drive the pre-flight and the panel's advice."""
    assert vb.ATTENTION_KB_PER_TOKEN > 0
    assert vb.RATIO_TIGHT < vb.RATIO_OVER
