"""Character Replace per-segment spec parsing (director.replace_spec)."""

from __future__ import annotations

from mmx_pkg.director.replace_spec import (
    AUDIO_POLICIES,
    DEFAULT_REPLACE_LEAD_FRAMES,
    ReplaceMaskSpec,
    ReplaceSpec,
    parse_replace_spec,
)


def test_empty_segment_has_no_replace():
    spec = parse_replace_spec({"prompt": "hello"})
    assert spec.enabled is False


def test_replace_block_parses_full():
    block = {
        "enabled": True,
        "audio_policy": "generate",
        "mask": {"kind": "frames", "dir": "/tmp/masks", "offset": 100, "grow": 2, "feather": 1.5},
        "sam_prompts": ["the woman"],
    }
    spec = parse_replace_spec({"replace": block})
    assert spec.enabled is True
    assert spec.audio_policy == "generate"
    assert spec.mask.kind == "frames"
    assert spec.mask.dir == "/tmp/masks"
    assert spec.mask.offset == 100
    assert spec.mask.grow == 2
    assert spec.mask.feather == 1.5
    assert spec.sam_prompts == ["the woman"]


def test_character_replace_alias_and_roundtrip():
    block = {"enabled": True, "audio_policy": "source", "mask": {"kind": "frames", "dir": "x"}}
    spec = parse_replace_spec({"characterReplace": block})
    assert spec.enabled is True
    again = ReplaceSpec.from_json(spec.to_json())
    assert again.enabled is True
    assert again.audio_policy == "source"
    assert again.mask.kind == "frames"
    assert again.mask.dir == "x"


def test_invalid_policy_and_mask_kind_normalize():
    spec = parse_replace_spec({"replace": {"enabled": True, "audio_policy": "banana"}})
    assert spec.audio_policy == "source"
    spec2 = parse_replace_spec({"replace": {"enabled": True, "mask": {"kind": "nope", "dir": "d"}}})
    assert spec2.mask.kind == "none"


def test_disabled_block_returns_disabled():
    spec = parse_replace_spec({"replace": {"enabled": False, "audio_policy": "generate"}})
    assert spec.enabled is False


def test_audio_policies_contract():
    assert AUDIO_POLICIES == ("source", "generate", "none")


def test_replace_lead_default_and_tuning():
    # A sensible default is locked in when the window does not say otherwise.
    spec = parse_replace_spec({"replace": {"enabled": True}})
    assert spec.lead == DEFAULT_REPLACE_LEAD_FRAMES == 12
    # Explicit 0 turns the runway off; explicit values tune the lead frames.
    assert parse_replace_spec({"replace": {"enabled": True, "lead": 0}}).lead == 0
    assert parse_replace_spec({"replace": {"enabled": True, "lead": 24}}).lead == 24
    assert parse_replace_spec({"replace": {"enabled": True, "lead": -5}}).lead == 0
    assert parse_replace_spec({"replace": {"enabled": True, "lead": "bogus"}}).lead == DEFAULT_REPLACE_LEAD_FRAMES


def test_replace_lead_aliases_and_roundtrip():
    for key in ("pre_roll", "preRoll", "lead_frames", "leadFrames"):
        spec = parse_replace_spec({"replace": {"enabled": True, key: 18}})
        assert spec.lead == 18
    block = {"enabled": True, "lead": 16, "mask": {"kind": "frames", "dir": "x"}}
    spec = parse_replace_spec({"replace": block})
    assert spec.lead == 16
    again = ReplaceSpec.from_json(spec.to_json())
    assert again.lead == 16
    assert again.to_json()["lead"] == 16
    assert ReplaceSpec.from_json(spec.to_json()).mask.kind == "frames"


def test_mask_kind_sam3_and_obj_id():
    block = {"enabled": True, "mask": {"kind": "sam3"}}
    spec = parse_replace_spec({"replace": block})
    assert spec.enabled is True
    assert spec.mask.kind == "sam3"
    assert spec.mask.obj_id == 1  # default tracked object id
    spec2 = parse_replace_spec(
        {"replace": {"enabled": True, "mask": {"kind": "sam3", "obj_id": 3}}}
    )
    assert spec2.mask.obj_id == 3
    assert spec2.to_json()["mask"]["kind"] == "sam3"
    assert spec2.to_json()["mask"]["obj_id"] == 3
    assert ReplaceSpec.from_json(spec2.to_json()).mask.kind == "sam3"
    assert ReplaceMaskSpec.from_json({"kind": "banana"}).kind == "none"


def test_mask_render_mode_default_and_parse():
    # Default render mode is the proven negative-anchor full re-render.
    spec = parse_replace_spec({"replace": {"enabled": True, "mask": {"kind": "sam3"}}})
    assert spec.mask.render == "anchor"
    spec2 = parse_replace_spec(
        {"replace": {"enabled": True, "mask": {"kind": "frames", "render": "inpaint"}}}
    )
    assert spec2.mask.render == "inpaint"
    assert spec2.to_json()["mask"]["render"] == "inpaint"
    assert ReplaceSpec.from_json(spec2.to_json()).mask.render == "inpaint"
    # Unknown render falls back to the default.
    assert (
        parse_replace_spec(
            {"replace": {"enabled": True, "mask": {"kind": "sam3", "render": "bogus"}}}
        ).mask.render
        == "anchor"
    )


def test_pick_box_parse_clamps_and_roundtrips():
    block = {
        "enabled": True,
        "mask": {"kind": "sam3"},
        "pick": {"box": [0.2, 0.3, 0.4, 0.5], "frame": 12},
    }
    spec = parse_replace_spec({"replace": block})
    assert spec.pick_box == [0.2, 0.3, 0.4, 0.5]
    assert spec.pick_frame == 12
    again = ReplaceSpec.from_json(spec.to_json())
    assert again.pick_box == [0.2, 0.3, 0.4, 0.5]
    assert again.pick_frame == 12
    # Boxes that would run past the edge get width/height clipped.
    clipped = parse_replace_spec(
        {"replace": {"enabled": True, "mask": {"kind": "sam3"}, "pick": {"box": [0.9, 0.9, 0.5, 0.5]}}}
    )
    assert clipped.pick_box is not None
    assert clipped.pick_box[2] <= 0.1 and clipped.pick_box[3] <= 0.1
    # Malformed boxes are dropped.
    for bad in ([1.5, 0.2, 0.3, 0.4], [0.2, 0.3, 0.4], "x", None):
        s = parse_replace_spec(
            {"replace": {"enabled": True, "mask": {"kind": "sam3"}, "pick": {"box": bad, "frame": 0}}}
        )
        assert s.pick_box is None
    # No pick block -> None.
    assert parse_replace_spec({"replace": {"enabled": True, "mask": {"kind": "sam3"}}}).pick_box is None
