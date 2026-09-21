# MiniMax H3 Motion Director - anchor ladder (P1) unit tests.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Unit tests for director/anchor_ladder.py (P1 soft-mode anchor ladder).

Pure logic + filesystem tests: no ComfyUI graph, no GPU. The image helpers use
torch/PIL the same way the runtime does.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from mmx_pkg.director import anchor_ladder as al


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _fake_segment(index: int, refs: int = 2, anchor_prompt: str = ""):
    seg = SimpleNamespace(
        index=index,
        refs=[SimpleNamespace(index=i, tensor=None) for i in range(refs)],
        anchor_prompt=anchor_prompt,
        anchor_in=None,
        anchor_out=None,
        task_key="r2v",
        task_type="r2v — 参考主体生视频(Reference to Video)",
        negative_prompt="",
        prompt=f"segment {index} prompt",
        frame_count=175,
    )
    return seg


def _fake_plan(tmp_path: Path, n: int = 3, **anchors_block):
    block = {"mode": "soft", "beats": [f"beat {i}" for i in range(n + 1)]}
    block.update(anchors_block)
    timeline = {"anchors": block}
    segments = [_fake_segment(i) for i in range(n)]
    plan = SimpleNamespace(
        segments=segments,
        global_prompt="subject_definitions:\n@image1 is <Subject 1>.",
        anchors=None,
        anchors_root=str(tmp_path),
    )
    plan.anchors = al.parse_anchor_config(timeline, segments)
    return plan


# --------------------------------------------------------------------------- #
# grid + naming
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "value,expected",
    [(0, 5), (1, 5), (4, 5), (5, 5), (6, 22), (20, 22), (21, 22), (22, 22),
     (23, 39), (39, 39), (40, 56), (124, 124), (125, 141)],
)
def test_snap_h3_length(value, expected):
    assert al.snap_h3_length(value) == expected


def test_anchor_file_name_is_stable_and_distinct():
    a = al.anchor_file_name(3, 4245)
    assert a == al.anchor_file_name(3, 4245)
    assert a != al.anchor_file_name(4, 4245)
    assert a.endswith(".png")
    assert "_f22" in al.anchor_file_name(1, 2, chunk_frames=22)


def test_resolve_item_path_uses_explicit_path_first(tmp_path):
    item = al.AnchorItem(index=1, seed=7, beat="x", path=str(tmp_path / "explicit.png"))
    assert al.resolve_item_path(item, tmp_path / "root") == tmp_path / "explicit.png"
    item2 = al.AnchorItem(index=1, seed=7, beat="x")
    assert al.resolve_item_path(item2, tmp_path) == tmp_path / al.anchor_file_name(1, 7, chunk_frames=22)
    assert al.resolve_item_path(item2, None) is None


def test_free_anchor_indices_skips_used_and_respects_limit():
    seg = SimpleNamespace(refs=[SimpleNamespace(index=0), SimpleNamespace(index=1)])
    assert al.free_anchor_indices(seg) == [2, 3]
    seg2 = SimpleNamespace(refs=[SimpleNamespace(index=0), SimpleNamespace(index=2)])
    assert al.free_anchor_indices(seg2) == [1, 3]
    seg3 = SimpleNamespace(refs=[SimpleNamespace(index=i) for i in range(8)])
    assert al.free_anchor_indices(seg3, count=2, max_images=9) == [8]


# --------------------------------------------------------------------------- #
# config parsing
# --------------------------------------------------------------------------- #
def test_parse_returns_none_when_absent_or_off():
    segs = [_fake_segment(0)]
    assert al.parse_anchor_config({}, segs) is None
    assert al.parse_anchor_config({"anchors": {"mode": "off"}}, segs) is None
    assert al.parse_anchor_config({"anchors": {"mode": "bogus"}}, segs) is None
    assert al.parse_anchor_config({"anchors": {"mode": "soft"}}, []) is None


def test_mode_off_says_out_loud_that_a_boundary_request_was_dropped(caplog):
    """Mode off erases the whole anchor block - onlyIndices included.

    The strip's render actions pass onlyIndices / preRollOnly. With the mode off the
    engine drops the block entirely, so "render THIS boundary" silently became a
    normal run and rendered the whole timeline - the failure the user saw as "it
    started rendering the entire job". Warn instead of dropping it in silence.
    """
    segs = [_fake_segment(0), _fake_segment(1)]
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert al.parse_anchor_config(
            {"anchors": {"mode": "off", "onlyIndices": [1], "preRollOnly": True}}, segs,
        ) is None
    assert "mode is off" in caplog.text
    assert "onlyIndices" in caplog.text
    # A plain "off" project (no boundary request) stays quiet.
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert al.parse_anchor_config({"anchors": {"mode": "off"}}, segs) is None
    assert "mode is off" not in caplog.text


def test_parse_builds_one_item_per_boundary_with_seeds_and_beats(tmp_path):
    plan = _fake_plan(tmp_path, n=3)
    anchors = plan.anchors
    assert anchors is not None and anchors.enabled
    assert [item.index for item in anchors.items] == [0, 1, 2, 3]
    assert [item.seed for item in anchors.items] == [4242, 4243, 4244, 4245]
    assert [item.beat for item in anchors.items] == ["beat 0", "beat 1", "beat 2", "beat 3"]
    assert anchors.chunk_frames == 22
    # natural boundary mapping: segment i opens on boundary i, closes on i+1
    assert [(s.anchor_in, s.anchor_out) for s in plan.segments] == [(0, 1), (1, 2), (2, 3)]


def test_parse_honours_explicit_seeds_chunk_and_overrides(tmp_path):
    plan = _fake_plan(
        tmp_path,
        n=2,
        seeds=[11, 12, 13],
        chunkFrames=30,
        injectPrompt=False,
        renderPass=False,
    )
    anchors = plan.anchors
    assert [i.seed for i in anchors.items] == [11, 12, 13]
    assert anchors.chunk_frames == 39  # snapped to 17k+5
    assert anchors.inject_prompt is False
    assert anchors.render_pass is False


def test_parse_falls_back_to_segment_anchor_prompt(tmp_path):
    timeline = {"anchors": {"mode": "soft", "open": "the opening pose"}}
    segments = [_fake_segment(0, anchor_prompt="ends seated"), _fake_segment(1, anchor_prompt="ends reaching")]
    anchors = al.parse_anchor_config(timeline, segments)
    assert [i.beat for i in anchors.items] == ["the opening pose", "ends seated", "ends reaching"]


def test_parse_respects_per_segment_boundary_overrides(tmp_path):
    timeline = {"anchors": {"mode": "soft"}}
    segs = [_fake_segment(0), _fake_segment(1)]
    segs[1].anchor_in = 0
    segs[1].anchor_out = 1
    anchors = al.parse_anchor_config(timeline, segs)
    assert anchors is not None
    assert (segs[0].anchor_in, segs[0].anchor_out) == (0, 1)
    assert (segs[1].anchor_in, segs[1].anchor_out) == (0, 1)


# --------------------------------------------------------------------------- #
# prompts
# --------------------------------------------------------------------------- #
def test_anchor_prompt_uses_template_and_beat():
    item = al.AnchorItem(index=2, seed=1, beat="she leans toward the lens")
    text = al.anchor_prompt(item, shared_prompt="SHARED BLOCK")
    assert "SHARED BLOCK" in text
    assert "she leans toward the lens" in text
    custom = al.anchor_prompt(item, shared_prompt="S", template="idx={index} beat={beat} shared={shared}")
    assert custom == "idx=2 beat=she leans toward the lens shared=S"


def test_anchor_prompt_default_beat_when_empty():
    item = al.AnchorItem(index=0, seed=1, beat="   ")
    assert al.DEFAULT_BEAT in al.anchor_prompt(item, shared_prompt="")


def test_expand_segment_prompt_appends_default_lines():
    out = al.expand_segment_prompt("body text", in_tag=3, out_tag=4)
    assert out.startswith("body text")
    assert "<Picture 3> is the FIRST frame of this shot" in out
    assert "<Picture 4> is the pose this shot must END on" in out


def test_expand_segment_prompt_replaces_markers_in_place():
    out = al.expand_segment_prompt("A\n{{anchor_in}}\nB\n{{anchor_out}}", in_tag=1, out_tag=2)
    assert "{{anchor_in}}" not in out and "{{anchor_out}}" not in out
    assert "A\n<Picture 1>" in out
    assert "B\n<Picture 2>" in out
    # no appendix when the user placed the markers themselves
    assert out.count("<Picture 1>") == 1


def test_expand_segment_prompt_disabled_or_no_tags_is_noop():
    assert al.expand_segment_prompt("p", in_tag=1, inject=False) == "p"
    assert al.expand_segment_prompt("p") == "p"


def test_anchor_prompt_supports_the_subject_token():
    item = al.AnchorItem(index=1, seed=5, beat="hands lift to temples")
    text = al.anchor_prompt(
        item, shared_prompt="shared line", template="{shared}\n{subject}\n{beat}",
        subject_text="subject_definitions:\n<Subject 1> is the woman in the references.",
    )
    assert "shared line" in text
    assert "<Subject 1>" in text
    assert "hands lift to temples" in text
    # without the token the subject text is simply unused
    assert al.anchor_prompt(item, shared_prompt="s", template="{beat}") == "hands lift to temples"


def test_subject_block_extracts_only_the_definitions():
    prompt = (
        "pov\nsubject_definitions:\n<Subject 1> is the woman. <Picture 1> is her face.\n"
        "summary:\nA calm room.\ndetailed_description:\n[Shot 1] she enters."
    )
    block = al.subject_block(prompt)
    assert block.startswith("subject_definitions:")
    assert "<Subject 1> is the woman" in block
    assert "summary:" not in block and "[Shot 1]" not in block
    assert al.subject_block("no definitions here") == ""
    assert al.subject_block("") == ""
    assert al.subject_block("subject_definitions:\n<Subject 1> only.") == "subject_definitions:\n<Subject 1> only."


# --------------------------------------------------------------------------- #
# neighbour text: where a boundary's prompt comes from
# --------------------------------------------------------------------------- #
_SHOT_A = (
    "subject_definitions:\n<Subject 1> is the woman.\n"
    "summary:\nShe leans in.\n"
    "detailed_description:\n"
    "[Shot 1] She lifts the cup and takes a slow sip. The camera pushes in slowly. "
    "<Subject 1> (S1) says: <d>[English] Mmm.</d> She sets the cup down and smiles."
)
_SHOT_B = (
    "subject_definitions:\n<Subject 1> is the woman.\n"
    "summary:\nShe reaches out.\n"
    "detailed_description:\n"
    "[Shot 2] She reaches toward the lens with both hands. The camera holds still. "
    "Her fingers curl."
)


def _shot(prompt: str):
    return SimpleNamespace(prompt=prompt)


def test_tail_clause_keeps_the_end_of_a_shot_and_drops_dialogue():
    text = al.tail_clause(_SHOT_A)
    assert "sets the cup down and smiles" in text
    assert "Mmm" not in text  # an anchor is a silent chunk: no dialogue
    assert "subject_definitions" not in text and "summary:" not in text


def test_head_clause_keeps_the_start_of_a_shot():
    text = al.head_clause(_SHOT_B)
    assert text.startswith("She reaches toward the lens")
    assert "camera" not in text.lower()  # framing is carried by {camera}, not here


def test_camera_clause_finds_the_framing_sentence():
    assert "pushes in" in al.camera_clause(_SHOT_A, side="end")
    assert "holds still" in al.camera_clause(_SHOT_B, side="start")
    assert al.camera_clause("she hums softly and smiles") == ""
    assert al.camera_clause("") == ""


def test_boundary_text_reads_the_two_neighbours():
    shots = [_shot(_SHOT_A), _shot(_SHOT_B)]
    middle = al.boundary_text(shots, 1)
    assert middle.from_label == "Shot 1" and middle.to_label == "Shot 2"
    assert "sets the cup down" in middle.from_tail
    assert "reaches toward the lens" in middle.to_head
    assert middle.camera == middle.from_camera  # the arriving shot wins
    opening = al.boundary_text(shots, 0)
    assert opening.from_label == "" and opening.from_tail == ""
    assert opening.to_head
    closing = al.boundary_text(shots, 2)
    assert closing.to_label == "" and closing.to_head == ""
    assert closing.from_tail


def test_prompt_source_follows_the_placement():
    anchors = al.AnchorPlan(mode=al.ANCHOR_MODE_SOFT)
    item = al.AnchorItem(index=1, seed=1, beat="b")
    assert al.effective_prompt_source(anchors, item) == "both"
    anchors.placement = al.ANCHOR_PLACEMENT_LEAD
    assert al.effective_prompt_source(anchors, item) == "from"  # a frame of the ending shot
    anchors.prompt_source = "to"
    assert al.effective_prompt_source(anchors, item) == "to"
    item.prompt_source = "template"
    assert al.effective_prompt_source(anchors, item) == "template"


def test_compose_anchor_prompt_pulls_in_both_neighbours():
    anchors = al.AnchorPlan(mode=al.ANCHOR_MODE_SOFT)
    item = al.AnchorItem(index=1, seed=1, beat="hands still on the cup")
    text = al.compose_anchor_prompt(
        item, anchors=anchors, segments=[_shot(_SHOT_A), _shot(_SHOT_B)],
        global_prompt="GLOBAL STYLE",
    )
    assert "GLOBAL STYLE" in text
    assert "hands still on the cup" in text
    assert "sets the cup down" in text         # {from_tail}
    assert "reaches toward the lens" in text   # {to_head}
    assert "<Subject 1> is the woman" in text  # the owner's own subject block
    assert "Mmm" not in text
    assert "{" not in text  # every token resolved


def test_compose_anchor_prompt_reports_a_missing_source(caplog):
    anchors = al.AnchorPlan(mode=al.ANCHOR_MODE_SOFT)
    item = al.AnchorItem(index=1, seed=1, beat="b")
    warnings: list[str] = []
    # The shot that ends on boundary 2 exists but carries no usable text - that is
    # the case worth reporting.
    al.reset_prompt_note_log()
    with caplog.at_level(logging.WARNING):
        text = al.compose_anchor_prompt(item, anchors=anchors, segments=[_shot("")], warnings=warnings)
    assert "has no source" in caplog.text
    assert any("from_tail" in note for note in warnings)
    assert "{" not in text


def test_opening_boundary_is_not_reported_as_a_missing_source(caplog):
    """Boundary 1 has no shot before it, so {from_tail} is meant to vanish.

    Warning about it on every strip refresh (it cannot be acted on) buried the notes
    that can - and boundary 1 is often deselected for the run entirely.
    """
    anchors = al.AnchorPlan(mode=al.ANCHOR_MODE_SOFT)
    item = al.AnchorItem(index=0, seed=1, beat="b", prompt_override="{from_tail}\n{to_head}")
    warnings: list[str] = []
    al.reset_prompt_note_log()
    with caplog.at_level(logging.WARNING):
        text = al.compose_anchor_prompt(
            item, anchors=anchors, segments=[_shot(_SHOT_A), _shot(_SHOT_B)], warnings=warnings,
        )
    assert warnings == []
    assert "has no source" not in caplog.text
    # {to_head} still resolves - the shot that *starts* on boundary 1 is right there.
    expected = al.head_clause(_SHOT_A)
    assert expected and expected in text
    assert "{" not in text


def test_missing_source_note_is_logged_once(caplog):
    """The strip composes every boundary on every refresh: repeat lines teach nothing."""
    anchors = al.AnchorPlan(mode=al.ANCHOR_MODE_SOFT)
    item = al.AnchorItem(index=1, seed=1, beat="b")
    al.reset_prompt_note_log()
    with caplog.at_level(logging.WARNING):
        first = al.compose_anchor_prompt(item, anchors=anchors, segments=[_shot("")])
        al.compose_anchor_prompt(item, anchors=anchors, segments=[_shot("")])
        al.compose_anchor_prompt(item, anchors=anchors, segments=[_shot("")])
    assert first
    assert caplog.text.count("{from_tail} has no source") == 1
    al.reset_prompt_note_log()


def test_compose_anchor_prompt_lets_a_override_win_and_keeps_tokens():
    anchors = al.AnchorPlan(mode=al.ANCHOR_MODE_SOFT)
    item = al.AnchorItem(index=1, seed=1, beat="b", prompt_override="MINE {from_tail} END")
    text = al.compose_anchor_prompt(
        item, anchors=anchors, segments=[_shot(_SHOT_A), _shot(_SHOT_B)],
    )
    assert text.startswith("MINE")
    assert "sets the cup down" in text
    assert al.anchor_prompt_body(item, anchors=anchors) == "MINE {from_tail} END"


def test_parse_reads_prompt_source_and_per_boundary_overrides(tmp_path):
    plan = _fake_plan(
        tmp_path, n=2, promptSource="From", prompts=["", "OVERRIDE {beat}"],
        promptSources=["", "to"],
    )
    assert plan.anchors.prompt_source == "from"
    assert plan.anchors.item(1).prompt_override == "OVERRIDE {beat}"
    assert plan.anchors.item(1).prompt_source == "to"
    assert plan.anchors.item(0).prompt_override == ""
    # the ladder keeps the shots it parsed with, so previews and the render path
    # compose from exactly the same text
    assert plan.anchors.segments == plan.segments


def test_build_anchor_segment_uses_the_neighbour_prompt(tmp_path):
    from mmx_pkg.director.plan import SegmentPlan

    plan = _fake_plan(tmp_path, n=2, placement="boundary")
    owner = SegmentPlan(
        index=0, start_frame=0, end_frame=175, prompt=_SHOT_A, task_type="t",
        task_key="r2v", use_global=False, refs=[],
    )
    plan.segments = [owner, SimpleNamespace(prompt=_SHOT_B, refs=[], task_key="r2v",
                                           task_type="t", negative_prompt="")]
    plan.anchors = al.parse_anchor_config(
        {"anchors": {"mode": "soft", "promptSource": "both"}}, plan.segments,
    )
    seg = al.build_anchor_segment(plan, plan.anchors.item(1))
    assert "sets the cup down" in seg.prompt
    assert "reaches toward the lens" in seg.prompt


# --------------------------------------------------------------------------- #
# injection
# --------------------------------------------------------------------------- #
def test_apply_injection_adds_refs_and_prompt_lines(tmp_path):
    torch = pytest.importorskip("torch")
    plan = _fake_plan(tmp_path, n=2)
    tensors = {0: torch.zeros(1, 8, 8, 3), 1: torch.ones(1, 8, 8, 3), 2: torch.ones(1, 8, 8, 3) * 0.5}
    touched = al.apply_injection(plan, tensors)
    assert touched == 2
    seg0, seg1 = plan.segments
    assert [ref.index for ref in seg0.refs] == [0, 1, 2, 3]
    assert seg0.refs[2].tensor is tensors[0]
    assert seg0.refs[3].tensor is tensors[1]
    assert "<Picture 3>" in seg0.prompt and "<Picture 4>" in seg0.prompt
    assert "<Picture 3>" in seg1.prompt and "<Picture 4>" in seg1.prompt
    assert seg1.refs[2].tensor is tensors[1]
    assert seg1.refs[3].tensor is tensors[2]


def test_apply_injection_warns_when_out_of_slots(tmp_path):
    torch = pytest.importorskip("torch")
    timeline = {"anchors": {"mode": "soft", "beats": ["a", "b"]}}
    segs = [_fake_segment(0, refs=9)]
    plan = SimpleNamespace(segments=segs, global_prompt="", anchors_root=str(tmp_path), anchors=None)
    plan.anchors = al.parse_anchor_config(timeline, segs)
    warnings: list[str] = []
    touched = al.apply_injection(plan, {0: torch.zeros(1, 4, 4, 3), 1: torch.zeros(1, 4, 4, 3)}, warnings=warnings)
    assert touched == 0
    assert any("no free reference slot" in w for w in warnings)


def test_apply_injection_skips_segments_without_tensors(tmp_path):
    torch = pytest.importorskip("torch")
    plan = _fake_plan(tmp_path, n=2)
    warnings: list[str] = []
    touched = al.apply_injection(plan, {}, warnings=warnings)
    assert touched == 0
    assert warnings == []


# --------------------------------------------------------------------------- #
# lead placement: the pose sits inside the shot that ends on the boundary
# --------------------------------------------------------------------------- #
def test_parse_lead_placement_defaults_and_clamping(tmp_path):
    plan = _fake_plan(tmp_path, n=2)  # no placement keys -> boundary, 24 frames
    assert plan.anchors.placement == "boundary"
    assert plan.anchors.lead_frames == 24
    assert plan.anchors.lead_hard is False
    assert plan.anchors.is_lead is False

    timeline = {
        "anchors": {"mode": "soft", "placement": "lead", "leadFrames": 12, "leadHard": True,
                    "beats": ["a", "b", "c"]},
    }
    segs = [_fake_segment(i) for i in range(2)]
    lead = al.parse_anchor_config(timeline, segs)
    assert lead.placement == "lead" and lead.is_lead is True
    assert lead.lead_frames == 12 and lead.lead_hard is True
    assert abs(lead.lead_seconds() - 0.5) < 1e-9

    # unknown placements fall back, absurd offsets are clamped
    weird = al.parse_anchor_config(
        {"anchors": {"mode": "soft", "placement": "sideways", "leadFrames": 9999}}, segs,
    )
    assert weird.placement == "boundary"
    assert 4 <= weird.lead_frames <= 120


def test_lead_seconds_text_reads_like_english():
    assert al.lead_seconds_text(24) == "one second"
    assert al.lead_seconds_text(48) == "2 seconds"
    assert al.lead_seconds_text(12) == "0.5 seconds"


def test_expand_segment_prompt_supports_the_lead_line():
    text = al.expand_segment_prompt("shot A.", lead_tag=3, lead_seconds="one second")
    assert "<Picture 3>" in text
    assert "about one second before it ends" in text
    assert "do not hold, settle or pose on it" in text
    # the marker wins over appending, and an empty tag injects nothing
    marked = al.expand_segment_prompt("shot {{anchor_lead}} done.", lead_tag=2, lead_seconds="2 seconds")
    assert "<Picture 2>" in marked and "{{anchor_lead}}" not in marked
    assert al.expand_segment_prompt("shot A.", lead_tag=None) == "shot A."


def test_apply_injection_lead_mode_touches_only_the_ending_shot(tmp_path):
    torch = pytest.importorskip("torch")
    timeline = {
        "anchors": {"mode": "soft", "placement": "lead", "leadFrames": 24,
                    "beats": ["opens", "middle", "ends"]},
    }
    segs = [_fake_segment(0, refs=0), _fake_segment(1, refs=0)]
    segs[0].timeline_index = 0
    segs[1].timeline_index = 1
    plan = SimpleNamespace(segments=segs, global_prompt="", anchors_root=str(tmp_path), anchors=None)
    plan.anchors = al.parse_anchor_config(timeline, segs)
    tensors = {i: torch.zeros(1, 4, 4, 3) + i for i in range(3)}
    touched = al.apply_injection(plan, tensors)

    assert touched == 2
    # segment 0: opening pose (boundary 0) + lead pose (boundary 1, inside it)
    assert len(segs[0].refs) == 2
    assert "FIRST frame of this shot" in segs[0].prompt
    assert "about one second before it ends" in segs[0].prompt
    # segment 1: only its own lead pose - nothing at its opening
    assert len(segs[1].refs) == 1
    assert "FIRST frame of this shot" not in segs[1].prompt
    assert "about one second before it ends" in segs[1].prompt
    leads = plan.anchor_leads
    assert set(leads) == {0, 1}
    assert leads[0].boundary == 1 and leads[1].boundary == 2
    assert leads[0].frames == 24 and leads[0].segment == 0
    assert leads[1].tensor is tensors[2]
    assert al.lead_for_segment(plan, 1) is leads[1]
    assert al.lead_for_segment(plan, 7) is None


def test_lead_keyframes_pin_the_pose_inside_the_canvas():
    torch = pytest.importorskip("torch")
    from mmx_pkg.patches.markers import MC_KEY

    class FakeVAE:
        def encode(self, frame):
            assert int(frame.shape[0]) == 1
            return torch.zeros(1, 4, 1, 2, 2)

    lead = al.LeadAnchor(boundary=2, segment=1, frames=24, tensor=torch.zeros(1, 8, 8, 3))
    keyframes = al.lead_keyframes(lead, vae=FakeVAE(), canvas_frames=277, width=64, height=64)
    assert len(keyframes) == 1
    assert keyframes[0][MC_KEY] == 277 - 24
    assert keyframes[0]["resolved_frame_index"] == 0
    assert tuple(keyframes[0]["latent"].shape) == (1, 4, 1, 2, 2)

    with pytest.raises(ValueError):
        al.lead_keyframes(al.LeadAnchor(boundary=0, segment=0, frames=24), vae=FakeVAE(),
                          canvas_frames=12, width=64, height=64)
    with pytest.raises(ValueError):
        al.lead_keyframes(al.LeadAnchor(boundary=0, segment=0, frames=24), vae=FakeVAE(),
                          canvas_frames=243, width=64, height=64)


def test_append_minimax_keyframes_keeps_the_head_and_adds_the_lead():
    torch = pytest.importorskip("torch")
    from mmx_pkg.nodes.conditioning import append_minimax_keyframes
    from mmx_pkg.patches.markers import MC_KEY

    head = [{"resolved_frame_index": 0, MC_KEY: 0, "latent": torch.zeros(1, 4, 1, 2, 2)}]
    conditioning = [["cond", {"minimax_keyframes": head, "minimax_frame_count": 277}, "extra"]]
    lead = [{"resolved_frame_index": 0, MC_KEY: 253, "latent": torch.zeros(1, 4, 1, 2, 2)}]
    out = append_minimax_keyframes(conditioning, keyframes=lead, frame_count=277)
    merged = out[0][1]["minimax_keyframes"]
    assert len(merged) == 2 and merged[0][MC_KEY] == 0 and merged[1][MC_KEY] == 253
    assert out[0][1]["minimax_frame_count"] == 277  # never lowered/overwritten
    assert out[0][2] == "extra"
    # an empty list is a no-op, and a frame count is only filled when missing
    assert append_minimax_keyframes(conditioning, keyframes=[]) is conditioning
    bare = append_minimax_keyframes([["c", {"minimax_keyframes": []}]], keyframes=lead, frame_count=243)
    assert bare[0][1]["minimax_frame_count"] == 243


# --------------------------------------------------------------------------- #
# passes + caching
# --------------------------------------------------------------------------- #
def test_run_anchor_pass_renders_saves_and_reuses(tmp_path):
    torch = pytest.importorskip("torch")
    plan = _fake_plan(tmp_path, n=2)
    calls = {"n": 0}

    def render(seg):
        calls["n"] += 1
        assert seg.anchor_index is not None
        assert seg.seed_override is not None
        return torch.zeros(22, 16, 16, 3)

    reports: list[str] = []
    warnings: list[str] = []
    out = al.run_anchor_pass(plan, render=render, root=tmp_path, reports=reports, warnings=warnings)
    assert calls["n"] == 3  # one per boundary
    assert sorted(out) == [0, 1, 2]
    for index in out:
        png = tmp_path / al.anchor_file_name(index, plan.anchors.item(index).seed, chunk_frames=22)
        assert png.is_file()
        side = json.loads(Path(str(png) + al.SIDECAR_SUFFIX).read_text())
        assert side["status"] == "ready"
        assert side["index"] == index
    assert any("boundary anchor(s) ready" in r for r in reports)
    assert warnings == []

    # second run reuses everything without invoking the renderer
    plan2 = _fake_plan(tmp_path, n=2)
    calls2 = {"n": 0}

    def render2(seg):  # pragma: no cover - must not run
        calls2["n"] += 1
        return torch.zeros(22, 16, 16, 3)

    out2 = al.run_anchor_pass(plan2, render=render2, root=tmp_path)
    assert calls2["n"] == 0
    assert sorted(out2) == [0, 1, 2]


def test_run_anchor_pass_survives_render_failure(tmp_path):
    torch = pytest.importorskip("torch")
    plan = _fake_plan(tmp_path, n=1)

    def render(seg):
        raise RuntimeError("boom")

    warnings: list[str] = []
    out = al.run_anchor_pass(plan, render=render, root=tmp_path, warnings=warnings)
    assert out == {}
    assert any("failed to render" in w for w in warnings)


def test_load_anchor_tensors_warns_on_missing(tmp_path):
    plan = _fake_plan(tmp_path, n=1)
    warnings: list[str] = []
    assert al.load_anchor_tensors(plan, root=tmp_path, warnings=warnings) == {}
    assert len(warnings) == 2


# --------------------------------------------------------------------------- #
# on-disk lookup: seed-exact wins, newest file for the boundary is the fallback
# --------------------------------------------------------------------------- #
def test_resolve_item_file_prefers_the_configured_seed(tmp_path):
    item = al.AnchorItem(index=1, seed=4243, beat="b", chunk_frames=22)
    correct = tmp_path / al.anchor_file_name(1, 4243, chunk_frames=22)
    correct.write_bytes(b"png")
    other = tmp_path / al.anchor_file_name(1, 99, chunk_frames=22)
    other.write_bytes(b"png")
    path, exact = al.resolve_item_file(item, tmp_path)
    assert path == correct and exact is True


def test_resolve_item_file_falls_back_to_the_newest_for_that_boundary(tmp_path):
    item = al.AnchorItem(index=1, seed=4243, beat="b", chunk_frames=22)
    older = tmp_path / al.anchor_file_name(1, 111, chunk_frames=22)
    newer = tmp_path / al.anchor_file_name(1, 222, chunk_frames=22)
    older.write_bytes(b"png")
    newer.write_bytes(b"png")
    newer.touch()  # written (and stamped) last: this is the file the strip shows
    # a file for a DIFFERENT boundary must never be borrowed
    (tmp_path / al.anchor_file_name(2, 333, chunk_frames=22)).write_bytes(b"png")
    path, exact = al.resolve_item_file(item, tmp_path)
    assert path == newer and exact is False
    assert al.scan_anchor_files(1, tmp_path) == [(222, newer), (111, older)]


def test_scan_anchor_files_breaks_a_same_instant_tie_by_seed(tmp_path):
    """Two files stamped in the same instant must still order deterministically.

    A filesystem with a coarse clock (or a fast re-roll) gives equal mtimes; the
    fallback must then pick the file the strip shows - the higher seed - instead
    of whatever ``glob`` happened to return.
    """
    low = tmp_path / al.anchor_file_name(1, 111, chunk_frames=22)
    high = tmp_path / al.anchor_file_name(1, 222, chunk_frames=22)
    low.write_bytes(b"png")
    high.write_bytes(b"png")
    stamp = 1_700_000_000
    for path in (low, high):
        os.utime(path, (stamp, stamp))
    item = al.AnchorItem(index=1, seed=4243, beat="b", chunk_frames=22)
    assert al.scan_anchor_files(1, tmp_path) == [(222, high), (111, low)]
    path, exact = al.resolve_item_file(item, tmp_path)
    assert path == high and exact is False


def test_resolve_item_file_missing_returns_the_configured_path(tmp_path):
    item = al.AnchorItem(index=0, seed=4242, beat="b", chunk_frames=22)
    path, exact = al.resolve_item_file(item, tmp_path)
    assert path == tmp_path / al.anchor_file_name(0, 4242, chunk_frames=22)
    assert exact is True
    assert al.resolve_item_file(item, None) == (None, True)


def test_run_anchor_pass_injects_the_fallback_file_without_rendering(tmp_path, caplog):
    torch = pytest.importorskip("torch")
    plan = _fake_plan(tmp_path, n=2)  # configured seeds 4242, 4243, 4244
    rendered = tmp_path / al.anchor_file_name(1, 987654, chunk_frames=22)
    assert al.save_anchor_image(torch.zeros(1, 8, 8, 3), rendered)

    def render(seg):  # pragma: no cover - the fallback must be reused, not re-rendered
        raise AssertionError("a boundary with a PNG on disk must not re-render")

    with caplog.at_level("INFO"):
        out = al.run_anchor_pass(plan, render=render, root=tmp_path, only=[1])
    assert list(out) == [1]
    assert any(
        "no PNG exists for its configured seed 4243" in r.getMessage() for r in caplog.records
    )


def test_load_anchor_tensors_uses_the_fallback_file(tmp_path, caplog):
    torch = pytest.importorskip("torch")
    plan = _fake_plan(tmp_path, n=1)
    assert al.save_anchor_image(
        torch.zeros(1, 8, 8, 3), tmp_path / al.anchor_file_name(0, 555, chunk_frames=22)
    )
    warnings: list[str] = []
    with caplog.at_level("INFO"):
        out = al.load_anchor_tensors(plan, root=tmp_path, warnings=warnings)
    assert list(out) == [0]
    assert any("injects" in r.getMessage() for r in caplog.records)
    # boundary 1 still has nothing on disk -> warned, not silently dropped
    assert any("is not on disk" in w for w in warnings)


def test_anchor_fingerprint_tracks_files(tmp_path):
    torch = pytest.importorskip("torch")
    plan = _fake_plan(tmp_path, n=1)
    assert al.anchor_fingerprint(plan) == "" or isinstance(al.anchor_fingerprint(plan), str)

    def render(seg):
        return torch.zeros(22, 8, 8, 3)

    al.run_anchor_pass(plan, render=render, root=tmp_path)
    fp1 = al.anchor_fingerprint(plan)
    assert fp1

    # touch one anchor file -> digest must change
    first = plan.anchors.items[0]
    png = tmp_path / al.anchor_file_name(first.index, first.seed, chunk_frames=22)
    png.write_bytes(png.read_bytes() + b"\x00")
    fp2 = al.anchor_fingerprint(plan)
    assert fp2 != fp1


def test_anchor_fingerprint_empty_when_disabled(tmp_path):
    plan = SimpleNamespace(segments=[_fake_segment(0)], anchors=None, anchors_root=str(tmp_path))
    assert al.anchor_fingerprint(plan) == ""
    plan.anchors = al.parse_anchor_config({"anchors": {"mode": "off"}}, plan.segments)
    assert al.anchor_fingerprint(plan) == ""


# --------------------------------------------------------------------------- #
# synthetic anchor segment
# --------------------------------------------------------------------------- #
def test_build_anchor_segment_is_standalone_and_seeded(tmp_path):
    from mmx_pkg.director.plan import SegmentPlan, SEGMENT_KIND_GENERATE

    plan = _fake_plan(tmp_path, n=2)
    # give the owner real SegmentPlan refs so SegmentPlan can copy them
    owner = SegmentPlan(
        index=0, start_frame=0, end_frame=175, prompt="p", task_type="t",
        task_key="r2v", use_global=False, refs=[],
    )
    plan.segments = [owner, _fake_segment(1)]
    item = plan.anchors.item(1)
    seg = al.build_anchor_segment(plan, item)
    assert isinstance(seg, SegmentPlan)
    assert seg.task_key == "r2v"
    assert seg.kind == SEGMENT_KIND_GENERATE
    assert seg.anchor_index == 1
    assert seg.seed_override == item.seed
    assert seg.context_link is None
    assert seg.frame_count == item.chunk_frames
    assert seg.index >= 1000  # never collides with a real segment index


def test_build_anchor_segment_copies_the_owner_references(tmp_path):
    from mmx_pkg.director.plan import SegmentPlan

    plan = _fake_plan(tmp_path, n=1)
    owner = SegmentPlan(
        index=0, start_frame=0, end_frame=175, prompt="p", task_type="t", task_key="r2v",
        use_global=False,
        refs=[SimpleNamespace(index=0), SimpleNamespace(index=1)],
    )
    plan.segments = [owner]
    seg = al.build_anchor_segment(plan, plan.anchors.item(0))
    assert len(seg.refs) == 2


def test_build_anchor_segment_borrows_the_plan_pool_then_warns(tmp_path, caplog):
    """An anchor must never quietly render without the character."""
    from mmx_pkg.director.plan import SegmentPlan

    plan = _fake_plan(tmp_path, n=1)
    owner = SegmentPlan(
        index=0, start_frame=0, end_frame=175, prompt="p", task_type="t", task_key="r2v",
        use_global=False, refs=[],
    )
    plan.segments = [owner]
    plan.global_refs = [SimpleNamespace(index=0)]
    with caplog.at_level("INFO"):
        seg = al.build_anchor_segment(plan, plan.anchors.item(0))
    assert len(seg.refs) == 1
    assert any("borrows 1 picture(s) from plan.global_refs" in r.getMessage() for r in caplog.records)

    caplog.clear()
    plan.global_refs = []
    with caplog.at_level("WARNING"):
        seg = al.build_anchor_segment(plan, plan.anchors.item(0))
    assert seg.refs == []
    assert any("no reference pictures" in r.getMessage() for r in caplog.records)


# --------------------------------------------------------------------------- #
# pre-roll (story skeleton before the fills)
# --------------------------------------------------------------------------- #
def test_parse_pre_roll_only_flag(tmp_path):
    plan = _fake_plan(tmp_path, n=2, preRollOnly=True)
    assert plan.anchors.pre_roll_only is True
    # snake_case alias, and off by default
    timeline = {"anchors": {"mode": "soft", "pre_roll_only": True}}
    aliased = al.parse_anchor_config(timeline, [_fake_segment(0), _fake_segment(1)])
    assert aliased.pre_roll_only is True
    assert _fake_plan(tmp_path, n=2).anchors.pre_roll_only is False


def test_storyboard_frames_holds_each_pose_in_boundary_order():
    import torch

    first = torch.zeros(1, 8, 8, 3)
    first[..., 0] = 0.1
    second = torch.zeros(1, 8, 8, 3)
    second[..., 0] = 0.9
    board = al.storyboard_frames({0: first, 1: second}, hold_frames=5)
    assert board.shape == (10, 8, 8, 3)
    assert torch.allclose(board[0], board[4])  # held pose
    assert board[0][..., 0].mean() < board[-1][..., 0].mean()  # boundary order kept


def test_storyboard_frames_uses_last_frame_and_resizes_mismatch():
    import torch

    tall = torch.zeros(1, 16, 8, 3)
    wide = torch.zeros(1, 8, 16, 3)
    wide[..., 1] = 1.0
    board = al.storyboard_frames({0: tall, 1: wide}, hold_frames=1)
    assert board.shape[0] == 2
    assert int(board.shape[1]) == 16 and int(board.shape[2]) == 8


def test_storyboard_frames_empty_is_none():
    assert al.storyboard_frames({}) is None
    assert al.storyboard_frames({0: None}) is None


def test_write_contact_sheet_writes_labelled_grid(tmp_path):
    import torch

    tensors = {
        0: torch.zeros(1, 32, 48, 3),
        1: torch.ones(1, 32, 48, 3),
    }
    plan = _fake_plan(tmp_path, n=1)
    dest = tmp_path / "sheet.png"
    written = al.write_contact_sheet(
        tensors, items=plan.anchors.items, dest=dest, columns=2, cell=32,
    )
    assert written == dest and dest.is_file()
    from PIL import Image

    with Image.open(dest) as img:
        assert img.width > 0 and img.height > 0


def test_write_contact_sheet_is_best_effort(tmp_path):
    assert al.write_contact_sheet({}, dest=tmp_path / "none.png") is None
    assert al.write_contact_sheet({0: None}, dest=tmp_path / "none.png") is None
    assert al.write_contact_sheet({0: None}, dest=None) is None


# --------------------------------------------------------------------------- #
# per-boundary render (onlyIndices)
# --------------------------------------------------------------------------- #
def test_parse_only_indices_normalises_and_defaults_empty(tmp_path):
    plan = _fake_plan(tmp_path, n=3, onlyIndices=[2, "1", 1, -3, None, "x"])
    assert plan.anchors.only_indices == (1, 2)
    assert _fake_plan(tmp_path, n=3).anchors.only_indices == ()
    timeline = {"anchors": {"mode": "soft", "onlyIndices": 0}}
    parsed = al.parse_anchor_config(timeline, [_fake_segment(0), _fake_segment(1)])
    assert parsed.only_indices == (0,)  # scalar form


def test_run_anchor_pass_only_renders_requested_boundaries(tmp_path):
    import torch

    plan = _fake_plan(tmp_path, n=2)
    calls = []

    def render(seg):
        calls.append(int(seg.anchor_index))
        return torch.zeros(3, 8, 8, 3)

    al.run_anchor_pass(plan, render=render, root=tmp_path, only=[1])
    assert calls == [1]  # boundary 0 was not rendered

    out = al.run_anchor_pass(plan, render=render, root=tmp_path, only=[0])
    assert calls == [1, 0]
    assert set(out) == {0, 1}  # boundary 1 came back from disk, not a render

    al.run_anchor_pass(plan, render=render, root=tmp_path, only=[9])
    assert calls == [1, 0]  # out-of-range request renders nothing


def test_run_anchor_pass_force_overwrites_existing(tmp_path):
    import torch

    plan = _fake_plan(tmp_path, n=1)
    calls = []

    def render(seg):
        calls.append(int(seg.anchor_index))
        return torch.zeros(3, 8, 8, 3)

    al.run_anchor_pass(plan, render=render, root=tmp_path)
    assert calls == [0, 1]
    out = al.run_anchor_pass(plan, render=render, root=tmp_path)   # both reused
    assert calls == [0, 1] and set(out) == {0, 1}
    al.run_anchor_pass(plan, render=render, root=tmp_path, only=[1], force=True)
    assert calls == [0, 1, 1]  # boundary 1 re-rendered, boundary 0 still reused
    assert plan.anchors.force_render is False  # default is off


def test_parse_force_render_flag(tmp_path):
    assert _fake_plan(tmp_path, n=1).anchors.force_render is False
    assert _fake_plan(tmp_path, n=1, forceRender=True).anchors.force_render is True
    timeline = {"anchors": {"mode": "soft", "force_render": True}}
    parsed = al.parse_anchor_config(timeline, [_fake_segment(0), _fake_segment(1)])
    assert parsed.force_render is True



# --------------------------------------------------------------------------- #
# boundary selection (all / bookends / explicit, strict)
# --------------------------------------------------------------------------- #
def test_parse_boundary_selection_presets(tmp_path):
    assert _fake_plan(tmp_path, n=3).anchors.selected_indices is None            # "all" by default
    assert _fake_plan(tmp_path, n=3, boundaries="all").anchors.selected_indices is None
    assert _fake_plan(tmp_path, n=3, boundaries="bookends").anchors.selected_indices == (0, 3)
    assert _fake_plan(tmp_path, n=1, boundaries="bookends").anchors.selected_indices == (0, 1)
    assert _fake_plan(tmp_path, n=3, boundaries=[3, "1", 1, 9, -2]).anchors.selected_indices == (1, 3)
    none = _fake_plan(tmp_path, n=2, boundaries="none")
    assert none.anchors.selected_indices == () and none.anchors.enabled is False


def test_strict_selection_skips_rendering_and_disk_reuse(tmp_path):
    import torch

    plan = _fake_plan(tmp_path, n=3, boundaries=[0, 3])
    calls = []

    def render(seg):
        calls.append(int(seg.anchor_index))
        return torch.zeros(2, 8, 8, 3)

    out = al.run_anchor_pass(plan, render=render, root=tmp_path)
    assert calls == [0, 3]              # boundaries 1 and 2 are not part of the ladder
    assert set(out) == {0, 3}

    # a leftover PNG for an unselected boundary is never loaded either
    al.save_anchor_image(torch.zeros(1, 8, 8, 3), tmp_path / "A01_s4243_v1_f22.png")
    out2 = al.run_anchor_pass(plan, render=render, root=tmp_path)
    assert set(out2) == {0, 3}
    assert set(al.load_anchor_tensors(plan, root=tmp_path)) == {0, 3}


def test_strict_selection_blocks_injection(tmp_path):
    import torch

    plan = _fake_plan(tmp_path, n=2, boundaries=[0])   # boundaries 1 and 2 are off
    seg0, seg1 = plan.segments
    before0, before1 = len(seg0.refs), len(seg1.refs)
    tensors = {0: torch.zeros(1, 8, 8, 3), 1: torch.zeros(1, 8, 8, 3)}  # both supplied
    touched = al.apply_injection(plan, tensors)
    assert touched == 1
    assert len(seg0.refs) == before0 + 1                # open pose only
    assert str(seg0.refs[-1].asset_id) == "anchor:2"    # first free picture slot
    assert len(seg1.refs) == before1                    # both sides off -> untouched


def test_anchor_fingerprint_tracks_selection(tmp_path):
    import torch

    plan = _fake_plan(tmp_path, n=2)
    calls = []

    def render(seg):
        calls.append(int(seg.anchor_index))
        return torch.zeros(2, 8, 8, 3)

    al.run_anchor_pass(plan, render=render, root=tmp_path)
    plan.anchors_root = str(tmp_path)
    every = al.anchor_fingerprint(plan)
    plan.anchors.selected_indices = (0,)
    assert al.anchor_fingerprint(plan) != every


# --------------------------------------------------------------------------- #
# draft pass
# --------------------------------------------------------------------------- #
def test_draft_pass_parsing(tmp_path):
    assert _fake_plan(tmp_path, n=1).anchors.draft is None
    draft = _fake_plan(tmp_path, n=1, draft={"enabled": True, "scale": 0.25, "steps": 6}).anchors.draft
    assert draft.enabled is True and draft.scale == 0.25 and draft.steps == 6
    # defaults + clamping
    loose = al.DraftPass.parse({})
    assert (loose.enabled, loose.scale, loose.steps) == (False, 1.0, 8)
    # an explicit 0 still means "keep the node's current steps"
    assert al.DraftPass.parse({"steps": 0}).steps == 0
    assert al.DraftPass.parse({"scale": 5}).scale == 1.0
    assert al.DraftPass.parse({"scale": 0.001}).scale == 0.1
    assert al.DraftPass.parse({"steps": 999}).steps == 64
    assert al.DraftPass.parse({"steps": -4}).steps == 0
    assert al.DraftPass.parse("nope") is None


def test_draft_variant_keeps_final_cache_separate(tmp_path):
    from mmx_pkg.director.segment_cache import segment_cache_fingerprint
    from mmx_pkg.director.plan import DirectorPlan, SegmentPlan

    seg = SegmentPlan(
        index=0, start_frame=0, end_frame=175, prompt="p", task_type="t",
        task_key="r2v", use_global=False, refs=[],
    )
    director = DirectorPlan(
        frame_rate=24.0, total_frames=175, width=512, height=288, ref_max_size=512,
        output_mode="global", source_width=512, source_height=288,
        global_task_type="r2v", global_task_key="r2v", global_prompt="p",
        global_refs=[], segments=[seg], source_video=None,
        edit_mode="global", raw={},
    )
    final = segment_cache_fingerprint(seg, director)
    director.cache_variant = "draft"
    assert segment_cache_fingerprint(seg, director) != final




