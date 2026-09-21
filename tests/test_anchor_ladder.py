# MiniMax H3 Motion Director - anchor ladder (P1) unit tests.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Unit tests for director/anchor_ladder.py (P1 soft-mode anchor ladder).

Pure logic + filesystem tests: no ComfyUI graph, no GPU. The image helpers use
torch/PIL the same way the runtime does.
"""

from __future__ import annotations

import json
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
    assert (loose.enabled, loose.scale, loose.steps) == (False, 0.5, 0)
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




