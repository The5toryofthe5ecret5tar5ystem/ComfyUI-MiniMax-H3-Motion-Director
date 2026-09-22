# MiniMax H3 Motion Director - r2flv hybrid task unit tests.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Unit tests for the ``r2flv`` ("Ref2va + FL2v Hybrid") task.

``r2flv`` is r2v with the boundary anchors auto-pinned as unmarked H3 first/last
keyframes: references keep steering identity and the sampler interpolates
between the two approved boundary poses. These tests cover the task registry,
set memberships on every family it joins, the conditioning keyframe helper, and
the boundary-anchor resolver. No ComfyUI graph, no GPU.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from mmx_pkg.director import anchor_ladder as al


# --------------------------------------------------------------------------- #
# task registry
# --------------------------------------------------------------------------- #
def test_task_is_registered_and_resolvable():
    from mmx_pkg.lib.task_prompts import (
        TASK_PROMPT_BY_KEY,
        resolve_task_key,
        task_type_combo_options,
    )

    spec = TASK_PROMPT_BY_KEY["r2flv"]
    assert spec.label.startswith("Ref2va + FL2v Hybrid")

    options, meta = task_type_combo_options()
    labels = [o for o in options if o.startswith("r2flv")]
    assert len(labels) == 1
    # The dropdown value round-trips back to the key, and the tooltip advertises it.
    assert resolve_task_key(labels[0]) == "r2flv"
    assert "r2flv" in meta["tooltip"]


def test_task_modes_enum_and_supported_keys_include_r2flv():
    from mmx_pkg.lib.task_modes import MiniMaxH3Task, SUPPORTED_TASK_KEYS

    assert MiniMaxH3Task.R2FLV.value == "r2flv"
    assert "r2flv" in SUPPORTED_TASK_KEYS


def test_r2flv_joins_every_r2v_family_set():
    from mmx_pkg.director.gen_timeline import (
        GEN_BLANK_KEYS,
        PROMPT_BATCH_KEYS,
        VIDEO_BATCH_KEYS,
        MIN_GEN_VIDEO_FRAMES,
        _min_frames_for_task,
    )
    from mmx_pkg.director.audio_drive import AUDIO_ROLE_TASKS
    from mmx_pkg.director.audio_export import task_passes_source_audio
    from mmx_pkg.director.plan import (
        REFERENCE_PICTURE_TASKS,
        segment_ref_audios_for_context,
    )
    from mmx_pkg.lib.generation_source_policy import is_source_free_generation_task
    from mmx_pkg.lib.h3_prompt_rules import H3_DIRECTOR_TASKS
    from mmx_pkg.lib.segment_kind import GENERATED_ROW_TASKS

    assert "r2flv" in GEN_BLANK_KEYS
    assert "r2flv" in PROMPT_BATCH_KEYS
    assert "r2flv" in VIDEO_BATCH_KEYS
    assert "r2flv" in REFERENCE_PICTURE_TASKS
    assert "r2flv" in AUDIO_ROLE_TASKS
    assert "r2flv" in H3_DIRECTOR_TASKS
    assert "r2flv" in GENERATED_ROW_TASKS
    assert _min_frames_for_task("r2flv") == MIN_GEN_VIDEO_FRAMES
    assert task_passes_source_audio("r2flv") is True
    assert is_source_free_generation_task("r2flv") is True
    sentinel = object()
    assert segment_ref_audios_for_context("r2flv", [sentinel]) == [sentinel]


def test_prompt_enhance_treatment_matches_r2v():
    from mmx_pkg.lib.official_pe_templates import ENHANCE_TEMPLATES, JSON_MODE_TASKS, R2V_TEMPLATE
    from mmx_pkg.lib.prompt_enhance_templates import _TASKS_REQUIRE_IMAGE_SLOTS

    assert ENHANCE_TEMPLATES["r2flv"] is R2V_TEMPLATE
    assert "r2flv" in JSON_MODE_TASKS
    assert "r2flv" in _TASKS_REQUIRE_IMAGE_SLOTS


def test_ref2va_recipe_offers_r2flv():
    from mmx_pkg.lib.h3_prompt_recipes import RECIPES

    ref2va = next(r for r in RECIPES if r.key == "ref2va")
    assert "r2flv" in ref2va.tasks


# --------------------------------------------------------------------------- #
# plan wiring
# --------------------------------------------------------------------------- #
def test_plan_builder_accepts_r2flv_and_merges_common_refs():
    from mmx_pkg.director.gen_timeline import build_gen_director_plan

    label = "r2flv — Ref2va + FL2v Hybrid 混合(References + first/last keyframes)"
    timeline = {
        "timelineMode": "prompt_batch",
        "global": {"taskType": label, "prompt": "a scene"},
        "gen": {"defaultFrameCount": 81},
        "segments": [{"prompt": "one", "useCommonAssets": True}],
        "r2vCommon": {"refs": [{"index": 0, "imageFile": "face.png"}]},
        "output": {},
    }
    plan = build_gen_director_plan(
        timeline, global_task_type=label, global_prompt="a scene",
        total_frames=81, frame_rate=24.0, width=512, height=512, ref_max_size=1024,
    )
    assert plan.global_task_key == "r2flv"
    assert plan.segments[0].task_key == "r2flv"
    # The common reference merges into the segment exactly like r2v.
    assert [r.index for r in (plan.segments[0].refs or [])] == [0]


# --------------------------------------------------------------------------- #
# conditioning helper
# --------------------------------------------------------------------------- #
class FakeVAE:
    def encode(self, frame):
        import torch

        assert int(frame.shape[0]) == 1
        # One latent frame whose value follows the picture, so a test can tell
        # the pinned picture from a stale one.
        return torch.full((1, 4, 1, 2, 2), float(frame.mean()))


def _conditioning_with_refs(keyframes=None, frame_count=None):
    import torch

    meta = {"minimax_refs": [{"kind": "image", "latent": torch.zeros(1, 4, 1, 2, 2)}]}
    if keyframes is not None:
        meta["minimax_keyframes"] = keyframes
    if frame_count is not None:
        meta["minimax_frame_count"] = frame_count
    return [["cond", meta, "extra"]]


def test_append_first_last_keyframes_pins_both_ends():
    import torch

    from mmx_pkg.nodes.conditioning import append_first_last_keyframes

    conditioning = _conditioning_with_refs()
    out = append_first_last_keyframes(
        conditioning,
        vae=FakeVAE(),
        frame_count=158,
        width=64,
        height=64,
        first_frame=torch.zeros(1, 8, 8, 3),
        last_frame=torch.ones(1, 8, 8, 3),
    )
    meta = out[0][1]
    # The reference payload the official ReferenceToVideo node built is kept.
    assert len(meta["minimax_refs"]) == 1
    rows = meta["minimax_keyframes"]
    assert [r["resolved_frame_index"] for r in rows] == [0, 157]
    assert all(tuple(r["latent"].shape) == (1, 4, 1, 2, 2) for r in rows)
    assert meta["minimax_frame_count"] == 158
    assert out[0][2] == "extra"  # entry tail is preserved


def test_append_first_last_keyframes_never_drops_marked_guides():
    import torch

    from mmx_pkg.nodes.conditioning import append_first_last_keyframes
    from mmx_pkg.patches.markers import MC_KEY

    head = {"resolved_frame_index": 0, MC_KEY: 0, "latent": torch.zeros(1, 4, 1, 2, 2)}
    body = {"resolved_frame_index": 5, "latent": torch.zeros(1, 4, 1, 2, 2)}
    conditioning = _conditioning_with_refs(keyframes=[head, body], frame_count=277)
    out = append_first_last_keyframes(
        conditioning,
        vae=FakeVAE(),
        frame_count=158,
        width=64,
        height=64,
        last_frame=torch.ones(1, 8, 8, 3),
    )
    rows = out[0][1]["minimax_keyframes"]
    # Marked guide survives, the untouched unmarked row survives, the close end
    # is pinned - and the frame count that was already known is left alone.
    assert rows[0].get(MC_KEY) == 0
    assert rows[1]["resolved_frame_index"] == 5 and MC_KEY not in rows[1]
    assert rows[-1]["resolved_frame_index"] == 157
    assert out[0][1]["minimax_frame_count"] == 277


def test_append_first_last_keyframes_replaces_a_stale_unmarked_pin():
    import torch

    from mmx_pkg.nodes.conditioning import append_first_last_keyframes

    stale = {"resolved_frame_index": 0, "latent": torch.zeros(1, 4, 1, 2, 2)}
    conditioning = _conditioning_with_refs(keyframes=[stale])
    out = append_first_last_keyframes(
        conditioning,
        vae=FakeVAE(),
        frame_count=124,
        width=64,
        height=64,
        first_frame=torch.full((1, 8, 8, 3), 0.5),
    )
    rows = out[0][1]["minimax_keyframes"]
    assert [r["resolved_frame_index"] for r in rows] == [0]
    # The stale row was replaced by the freshly encoded pin, not duplicated.
    assert float(rows[0]["latent"].mean()) == pytest.approx(0.5, abs=0.02)


def test_append_first_last_keyframes_is_a_noop_without_frames():
    from mmx_pkg.nodes.conditioning import append_first_last_keyframes

    conditioning = _conditioning_with_refs()
    assert append_first_last_keyframes(
        conditioning, vae=FakeVAE(), frame_count=124, width=64, height=64,
    ) is conditioning

    with pytest.raises(ValueError):
        append_first_last_keyframes(
            conditioning, vae=FakeVAE(), frame_count=1, width=64, height=64,
            first_frame=object(),
        )


# --------------------------------------------------------------------------- #
# boundary-anchor resolver
# --------------------------------------------------------------------------- #
def _hybrid_plan(tmp_path: Path, n: int = 2, **anchors_block):
    block = {"mode": "soft", "beats": [f"beat {i}" for i in range(n + 1)]}
    block.update(anchors_block)
    segments = []
    for index in range(n):
        segments.append(SimpleNamespace(
            index=index,
            timeline_index=index,
            task_key="r2flv",
            anchor_in=None,
            anchor_out=None,
            refs=[],
            prompt="",
        ))
    plan = SimpleNamespace(segments=segments, anchors_root=str(tmp_path), anchors=None)
    plan.anchors = al.parse_anchor_config({"anchors": block}, segments)
    return plan


def _write_anchor_png(plan, index: int, shade: int) -> Path:
    from PIL import Image

    item = plan.anchors.item(index)
    path = al.resolve_item_path(item, plan.anchors_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), (shade, shade, shade)).save(path)
    return Path(path)


def test_hybrid_boundary_tensors_map_segment_edges(tmp_path):
    torch = pytest.importorskip("torch")

    plan = _hybrid_plan(tmp_path, n=2)
    _write_anchor_png(plan, 0, 10)
    _write_anchor_png(plan, 1, 90)
    _write_anchor_png(plan, 2, 200)

    warnings: list[str] = []
    first, last = al.hybrid_boundary_tensors(plan, plan.segments[0], warnings=warnings)
    # Segment 0 opens on boundary 0 and closes on boundary 1.
    assert first is not None and last is not None
    assert tuple(first.shape) == (1, 8, 8, 3)
    assert float(first.mean()) < float(last.mean())  # shade 10 vs 90
    assert warnings == []

    first, last = al.hybrid_boundary_tensors(plan, plan.segments[1], warnings=warnings)
    assert round(float(first.mean() * 255)) == 90
    assert round(float(last.mean() * 255)) == 200


def test_hybrid_boundary_tensors_skips_missing_and_disabled_sides(tmp_path):
    pytest.importorskip("torch")

    plan = _hybrid_plan(tmp_path, n=2)
    _write_anchor_png(plan, 0, 10)  # boundary 1's PNG is never written

    warnings: list[str] = []
    first, last = al.hybrid_boundary_tensors(plan, plan.segments[0], warnings=warnings)
    assert first is not None and last is None
    assert any("boundary 2" in w for w in warnings)

    off = SimpleNamespace(anchors=None)
    assert al.hybrid_boundary_tensors(off, plan.segments[0]) == (None, None)


def test_hybrid_boundary_tensors_respects_selection(tmp_path):
    pytest.importorskip("torch")

    plan = _hybrid_plan(tmp_path, n=1, boundaries=[0])
    _write_anchor_png(plan, 0, 10)
    _write_anchor_png(plan, 1, 90)

    first, last = al.hybrid_boundary_tensors(plan, plan.segments[0])
    assert first is not None
    assert last is None  # boundary 1 was not selected into the ladder
