"""Every plan builder must carry the Resume intent.

``build_director_plan()`` in ``director/plan.py`` sets ``resume``/``resume_from``
on its ``DirectorPlan``, but the siblings it dispatches to - ``gen_timeline``,
``fl2v_timeline``, ``mixed_plan`` - each own a complete, independent
``DirectorPlan`` construction. A field added to one is silently absent from the
others, and nothing failed loudly enough to notice.

That is what happened to Resume. A ``prompt_batch`` timeline - what the Director
UI actually emits - is routed to ``build_gen_director_plan()``, which never read
the flag. ``plan.resume`` stayed ``False``, ``resume_active`` was ``False``, the
executor reset every done mark and re-sampled from segment 1 - while the Resume
dialog, which only inspects the on-disk caches, reported the prefix as perfectly
reusable. The user saw "Resume from S7" start at group 1/7.

These tests pin the wiring so a builder cannot quietly ignore it again.
"""

import json
import pathlib

import pytest

try:
    from mmx_pkg.director import gen_timeline
    from mmx_pkg.director.gen_timeline import build_gen_director_plan
    from mmx_pkg.director.plan import build_director_plan
except ImportError as exc:  # pragma: no cover - environment guard
    pytest.skip(f"Director package unavailable: {exc}", allow_module_level=True)


# build_gen_director_plan / build_director_plan share this keyword signature.
_KW = dict(
    global_task_type="t2v",
    global_prompt="",
    total_frames=81,
    frame_rate=24.0,
    width=512,
    height=512,
    ref_max_size=1024,
)


def _gen_timeline(**extra):
    """A minimal but valid prompt_batch timeline (the Director's normal mode)."""
    timeline = {
        "timelineMode": "prompt_batch",
        "global": {"taskType": "t2v", "prompt": "a test scene"},
        "gen": {"defaultFrameCount": 81},
        "segments": [{"prompt": "one"}, {"prompt": "two"}, {"prompt": "three"}],
        "output": {},
    }
    timeline.update(extra)
    return timeline


# --------------------------------------------------------------------------
# behaviour: the gen builder (the path the UI actually takes)
# --------------------------------------------------------------------------


def test_gen_builder_propagates_resume_intent():
    plan = build_gen_director_plan(
        _gen_timeline(resumeRun={"enabled": True, "from": 2}), **_KW
    )
    assert plan.resume is True
    assert plan.resume_from == 2


def test_gen_builder_keeps_a_genuine_zero():
    """``from: 0`` means "reuse nothing" - it must not collapse into "unset"."""
    plan = build_gen_director_plan(
        _gen_timeline(resumeRun={"enabled": True, "from": 0}), **_KW
    )
    assert plan.resume is True
    assert plan.resume_from == 0


def test_gen_builder_ignores_a_disabled_intent():
    plan = build_gen_director_plan(
        _gen_timeline(resumeRun={"enabled": False, "from": 2}), **_KW
    )
    assert plan.resume is False


def test_gen_builder_defaults_to_no_resume():
    plan = build_gen_director_plan(_gen_timeline(), **_KW)
    assert plan.resume is False
    assert plan.resume_from is None


def test_snake_case_alias_is_honoured():
    """The route also accepts ``resume_run``."""
    plan = build_gen_director_plan(
        _gen_timeline(resume_run={"enabled": True, "from": 1}), **_KW
    )
    assert plan.resume is True
    assert plan.resume_from == 1


def test_dispatch_carries_resume_to_the_gen_builder():
    """The real entry point: a JSON string through ``build_director_plan``.

    This is the whole route the frontend uses, so it is the one that has to
    agree with what the Resume dialog promised.
    """
    plan = build_director_plan(
        json.dumps(_gen_timeline(resumeRun={"enabled": True, "from": 2})), **_KW
    )
    assert plan.resume is True
    assert plan.resume_from == 2


# --------------------------------------------------------------------------
# structure: stop the next builder from repeating this
# --------------------------------------------------------------------------


def test_every_plan_builder_wires_resume():
    """Any module constructing a DirectorPlan must wire the resume fields.

    The duplicated builders are the root cause, so rather than rely on anyone
    remembering, check the source. ``fl2v``/``mixed`` are covered structurally
    only - building their timelines needs real image inputs.
    """
    director_dir = pathlib.Path(gen_timeline.__file__).parent
    offenders = []
    for path in sorted(director_dir.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "DirectorPlan(" not in text:
            continue
        missing = [
            name
            for name in ("resume=_resume_enabled", "resume_from=_resume_from_index")
            if name not in text
        ]
        if missing:
            offenders.append(f"{path.name} (missing {', '.join(missing)})")

    assert not offenders, (
        "these modules construct a DirectorPlan without wiring resume: "
        f"{offenders}. A Resume run through them silently re-renders from "
        "segment 1 while the dialog reports the prefix as reusable."
    )
