"""Character Replace per-segment spec parsing (director.replace_spec)."""

from __future__ import annotations

from mmx_pkg.director.replace_spec import (
    AUDIO_POLICIES,
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
