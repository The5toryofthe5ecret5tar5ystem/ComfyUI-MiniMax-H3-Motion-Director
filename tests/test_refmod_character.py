# MiniMax H3 Motion Director - RefMod character captions.
# Copyright (C) 2026 WakaSoft. GPL-3.0. See LICENSE.

"""A RefMod window may not describe her face, but it must fill the wardrobe line.

Guide 6.4: the mod is a full visual reference appended after text encoding, so prose
about identity cannot be grounded in it; the wardrobe line must MATCH what the mod
shows, and at most one 2-4 word clue is allowed. These tests pin the three pieces
that make that possible: reading a mod, resolving what the panel typed, and turning
the answer into a block that still obeys the guide.
"""

from __future__ import annotations

import json
import os
import struct
import sys
import types

import pytest

if "folder_paths" not in sys.modules:
    _stub = types.ModuleType("folder_paths")
    _stub.get_input_directory = lambda: "/tmp"
    _stub.get_output_directory = lambda: "/tmp"
    _stub.get_temp_directory = lambda: "/tmp"
    _stub.models_dir = "/tmp/models"
    _stub.get_folder_paths = lambda kind: []
    _stub.get_filename_list = lambda kind: []
    _stub.get_full_path = lambda kind, name: None
    sys.modules["folder_paths"] = _stub

from mmx_pkg.lib.h3_prompt_caption import (  # noqa: E402
    MAX_CLUE_WORDS,
    build_from_images,
    build_replace_window_prompt,
    parse_character_caption,
    plan_captions,
)
from mmx_pkg.lib.refmod_character import (  # noqa: E402
    _member_tensor_keys,
    character_images_b64,
    describe_mod,
    list_refmods,
    mod_search_dirs,
    read_mod_metadata,
    resolve_mod,
    resolve_source,
)


def _write_mod(path: str, *, name: str = "elf_girl", mode: str = "encode",
               kind: str = "video", description: str = "", tags=None) -> str:
    """A minimal but real mod file: safetensors header + a dummy latent."""
    meta = {
        "name": name, "kind": kind, "mode": mode, "concept_type": "identity",
        "description": description, "tags": tags or ["2 img, 0 vid"],
        "pool": "full-res 864x1536px", "latent_h": 96, "latent_w": 54,
        "latent_t": 2, "_format_version": 4,
    }
    header = {
        "latent": {"dtype": "F16", "shape": [1, 24, 2, 96, 54],
                   "data_offsets": [0, 24 * 2 * 96 * 54 * 2]},
        "__metadata__": {"refmod_meta": json.dumps(meta)},
    }
    payload = b"\x00" * (24 * 2 * 96 * 54 * 2)
    blob = json.dumps(header).encode("utf-8")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(struct.pack("<Q", len(blob)))
        handle.write(blob)
        handle.write(payload)
    return path


@pytest.fixture()
def fake_comfy(tmp_path, monkeypatch):
    """A stub folder_paths so the module runs without ComfyUI on the path."""
    models = tmp_path / "models"
    (models / "refmods" / "people").mkdir(parents=True)
    (models / "vae").mkdir(parents=True)
    inputs = tmp_path / "input"
    inputs.mkdir()
    stub = types.ModuleType("folder_paths")
    stub.models_dir = str(models)
    stub.get_input_directory = lambda: str(inputs)
    stub.get_folder_paths = lambda kind: [str(models / "refmods")] if kind == "refmods" else []
    stub.get_filename_list = lambda kind: ["minimax_h3_video_vae_fp16.safetensors"] if kind == "vae" else []
    stub.get_full_path = (
        lambda kind, name: str(models / "vae" / name) if kind == "vae" else None
    )
    monkeypatch.setitem(sys.modules, "folder_paths", stub)
    return types.SimpleNamespace(models=models, inputs=inputs, stub=stub)


# ── reading a mod ────────────────────────────────────────────────────────────


def test_metadata_is_read_without_loading_tensors(fake_comfy):
    path = _write_mod(str(fake_comfy.models / "refmods" / "people" / "elf_girl.safetensors"))
    meta = read_mod_metadata(path)
    assert meta["name"] == "elf_girl"
    assert meta["mode"] == "encode"
    assert meta["latent_t"] == 2
    assert _member_tensor_keys(meta)[0][0] == "latent"


def test_mod_search_dirs_and_listing_skip_audio_and_other_formats(fake_comfy):
    root = fake_comfy.models / "refmods"
    _write_mod(str(root / "people" / "elf_girl.safetensors"), description="auburn hair")
    _write_mod(str(root / "people" / "voice.safetensors"), name="voice", kind="audio")
    (root / "people" / "not_a_mod.safetensors").write_bytes(b"garbage")
    assert str(root) in mod_search_dirs()
    ids = [entry["id"] for entry in list_refmods()]
    assert "people/elf_girl" in ids
    assert "people/voice" not in ids, "an audio mod has no character to describe"
    assert "people/not_a_mod" not in ids, "a foreign safetensors is not a mod"


def test_describe_reports_what_the_author_wrote(fake_comfy):
    path = _write_mod(
        str(fake_comfy.models / "refmods" / "people" / "mira.safetensors"),
        name="mira", description="green-skinned elf", tags=["4 img, 0 vid"],
    )
    info = describe_mod(path)
    assert info["description"] == "green-skinned elf"
    assert info["mode"] == "encode"
    assert "4 img" in info["summary"]


# ── resolving what the panel typed ───────────────────────────────────────────


def test_resolve_accepts_mod_name_path_and_images(fake_comfy):
    mod = _write_mod(str(fake_comfy.models / "refmods" / "people" / "elf_girl.safetensors"))
    assert resolve_mod("people/elf_girl") == mod
    assert resolve_mod("people/elf_girl.safetensors") == mod
    kind, payload, error = resolve_source("people/elf_girl")
    assert (kind, payload, error) == ("mod", mod, "")

    image = fake_comfy.inputs / "chars" / "face.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    assert resolve_source("chars/face.png")[0] == "images"
    assert resolve_source(str(image.parent))[0] == "images"


def test_resolve_explains_itself_when_nothing_matches(fake_comfy):
    kind, payload, error = resolve_source("people/does_not_exist")
    assert kind == "" and payload is None
    assert "models/refmods" in error and "people/elf_girl" in error


def test_missing_character_is_reported_not_guessed(fake_comfy):
    images, info, error = character_images_b64("")
    assert images == [] and info == {}
    assert "No RefMod character" in error


def test_training_mode_mods_are_refused_with_a_reason(fake_comfy):
    path = _write_mod(
        str(fake_comfy.models / "refmods" / "people" / "pooled.safetensors"),
        name="pooled", mode="training",
    )
    images, info, error = character_images_b64("people/pooled")
    assert images == []
    assert "training mode" in error
    assert "blurry blob" in error, "the reason must be actionable, not just a refusal"
    assert info["mode"] == "training"


# ── the caption itself ───────────────────────────────────────────────────────


def test_character_caption_splits_outfit_and_clue():
    outfit, clue = parse_character_caption(
        "OUTFIT: a forest-green tunic with a leather belt and brown boots. "
        "CLUE: the green-skinned elf"
    )
    assert outfit.startswith("a forest-green tunic")
    assert clue == "the green-skinned elf"


def test_character_caption_accepts_prose_and_drops_sentinel_values():
    outfit, clue = parse_character_caption("She wears a red silk dress and gold earrings.")
    assert outfit == "She wears a red silk dress and gold earrings"
    assert clue == "", "a clue is only taken from an explicit CLUE: line"
    assert parse_character_caption("OUTFIT: none CLUE: none") == ("", "")


def test_a_clue_longer_than_the_guide_allows_is_dropped():
    long_clue = "the tall auburn haired woman with the green eyes and the scar"
    assert len(long_clue.split()) > MAX_CLUE_WORDS
    outfit, clue = parse_character_caption(f"OUTFIT: a blue dress CLUE: {long_clue}")
    assert outfit == "a blue dress"
    assert clue == ""


def test_refmod_block_fills_wardrobe_and_clue_without_describing_her():
    result = build_replace_window_prompt(
        recipe="character_replace_refmod",
        character_caption="OUTFIT: a forest-green tunic over a white shirt CLUE: the green-skinned elf",
        action_caption="She crosses the room and sits down.",
    )
    assert "wardrobe: she wears a forest-green tunic over a white shirt" in result.text
    assert "never a different outfit than the character reference shows" in result.text
    assert "<Subject 1> is the green-skinned elf carried by the attached character reference" in result.text
    assert "not a description" in result.text
    assert "identity" not in result.skipped, "refmod never wants an identity caption"
    assert "outfit is the wardrobe line exactly" in result.text
    # The whole point: no appearance paragraph.
    assert "forest-green tunic" in result.text
    assert "high cheekbones" not in result.text


def test_refmod_block_without_a_character_keeps_the_old_shape():
    result = build_replace_window_prompt(
        recipe="character_replace_refmod", action_caption="She sits."
    )
    assert "wardrobe:" not in result.text, "no wardrobe line beats an invented one"
    assert "<Subject 1> is the woman carried by the attached character reference" in result.text
    assert "her outfit is the wardrobe line" not in result.text
    assert result.skipped == ["wardrobe", "clue"]


def test_non_refmod_recipes_ignore_the_character_caption():
    result = build_replace_window_prompt(
        recipe="character_replace",
        identity_caption="She has long dark hair.",
        character_caption="OUTFIT: a green tunic CLUE: the elf",
        picture_count=1,
    )
    assert "Identity: She has long dark hair." in result.text
    assert "green tunic" not in result.text
    assert result.skipped == []


# ── the caption plan ─────────────────────────────────────────────────────────


def test_plan_needs_the_character_shots_for_a_refmod_window():
    assert plan_captions("character_replace_refmod", character_images=2, source_frames=6) == [
        "character", "action",
    ]
    assert plan_captions("character_replace_refmod", source_frames=6) == ["action"]
    assert plan_captions("character_replace_refmod", character_images=2) == ["character"]
    # Without either, there is nothing to look at and the caller gets a message.
    assert plan_captions("character_replace_refmod") == []


def test_plan_leaves_the_other_recipes_alone():
    assert plan_captions("character_replace", reference_images=2, source_frames=6) == [
        "identity", "action",
    ]
    assert plan_captions("ref2va", reference_images=2) == ["identity", "scene"]
    assert plan_captions("source_edit", source_frames=6) == ["action"]


def test_refmod_without_a_character_asks_for_one():
    """No source frames and no character: say what is missing, do not call the LLM."""
    result, error = build_from_images(
        recipe="character_replace_refmod", url="", model="m", api_format="local",
        audio_policy="source",
    )
    assert result is None
    assert "RefMod character" in error and "wardrobe" in error


def test_refmod_with_source_frames_still_assembles_without_a_character(monkeypatch):
    """A RefMod window with source frames keeps working; only the wardrobe is skipped."""
    def fake_enhance(**kwargs):
        return "She crosses the room.", None

    import mmx_pkg.lib.prompt_enhancer as prompt_enhancer

    monkeypatch.setattr(prompt_enhancer, "enhance_prompt_sync", fake_enhance)
    result, error = build_from_images(
        recipe="character_replace_refmod", url="", model="m", api_format="local",
        source_images=["frame"], audio_policy="source",
    )
    assert error is None
    assert "wardrobe:" not in result.text
    assert result.skipped == ["wardrobe", "clue"]


def test_character_images_reach_only_the_character_caption(fake_comfy, monkeypatch):
    """The caption must see the mod's frames - and the action caption must not."""
    calls: list[tuple[str, int]] = []

    def fake_enhance(**kwargs):
        images = kwargs.get("images_b64") or []
        calls.append((kwargs["user_prompt"][:40], len(images)))
        return "OUTFIT: a leather jerkin CLUE: the elf", None

    import mmx_pkg.lib.prompt_enhancer as prompt_enhancer

    monkeypatch.setattr(prompt_enhancer, "enhance_prompt_sync", fake_enhance)
    result, error = build_from_images(
        recipe="character_replace_refmod",
        url="", model="m", api_format="local",
        user_prompt="",
        source_images=["source-frame"],
        character_images=["character-frame-1", "character-frame-2"],
        audio_policy="source",
    )
    assert error is None
    assert len(calls) == 2, "one caption for the character, one for the action"
    assert calls[0][1] == 2, "the character caption gets the mod's frames"
    assert calls[1][1] == 1, "the action caption gets the source frames"
    assert "wardrobe: she wears a leather jerkin" in result.text
    assert "<Subject 1> is the elf carried by" in result.text
