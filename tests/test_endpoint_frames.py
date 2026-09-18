# MiniMax H3 Motion Director - endpoint frames for the caption path.
# Copyright (C) 2026 WakaSoft. GPL-3.0. See LICENSE.

"""i2v and fl2v supply fixed frames, not reference slots, and the panel now sends
them. Two things have to hold: the caption must see exactly those frames (never the
source window, never a reference image), and the assembled prompt must not try to
carry a `<Picture N>` tag that the task has no slot for.
"""

from __future__ import annotations

import sys
import types

# Prefer ComfyUI's real module: this suite imports it through PYTHONPATH, and
# installing a stub here would hand a fake to every test collected afterwards.
try:
    import folder_paths  # noqa: F401
except ImportError:  # pragma: no cover - only on a box without ComfyUI
    _stub = types.ModuleType("folder_paths")
    _stub.get_input_directory = lambda: "/tmp"
    _stub.get_output_directory = lambda: "/tmp"
    _stub.get_temp_directory = lambda: "/tmp"
    _stub.models_dir = "/tmp/models"
    _stub.base_path = "/tmp"
    _stub.folder_names_and_paths = {}
    _stub.get_folder_paths = lambda kind: []
    _stub.get_filename_list = lambda kind: []
    _stub.get_full_path = lambda kind, name: None
    sys.modules["folder_paths"] = _stub

import pytest  # noqa: E402

from mmx_pkg.lib.h3_prompt_caption import (  # noqa: E402 - after the stub
    CAPTION_RECIPES,
    build_first_last_prompt,
    build_from_images,
    build_start_image_prompt,
    plan_captions,
)

FRAME = "She stands in a hallway in a grey hoodie, weight on her right leg."
SPAN = "Both frames share the same bathroom; she faces the mirror at the start and has turned away by the end."


def test_both_frame_recipes_can_caption():
    assert "start_image" in CAPTION_RECIPES
    assert "first_last" in CAPTION_RECIPES


def test_plan_needs_the_frames_the_recipe_actually_uses():
    assert plan_captions("start_image", frame_images=1) == ["start_frame"]
    assert plan_captions("start_image", frame_images=0) == []
    assert plan_captions("first_last", frame_images=2) == ["frame_span"]
    # One frame cannot describe a change, which is the whole point of fl2v.
    assert plan_captions("first_last", frame_images=1) == []
    # And the frame list must not leak into the other recipes' plans.
    assert plan_captions("character_replace", reference_images=1, frame_images=2) == ["identity"]
    assert plan_captions("source_edit", source_frames=3, frame_images=2) == ["action"]


def test_start_image_prompt_uses_the_frame_and_keeps_the_users_words():
    result = build_start_image_prompt(
        frame_caption=FRAME, action_text="She walks to the door and opens it."
    )
    text = " ".join(result.text.split())
    assert FRAME in text, "the frame's own description must appear"
    assert "She walks to the door and opens it." in text, "the action stays verbatim"
    assert "Begin from the supplied first frame" in text
    assert "<Picture" not in text, "i2v has no reference slots to name"
    assert result.character == FRAME and result.action == "She walks to the door and opens it."


def test_start_image_prompt_without_a_caption_says_so():
    result = build_start_image_prompt(frame_caption="", action_text="She waves.")
    assert result.skipped == ["frame"]
    assert "come from the supplied first frame" in result.text
    assert "She waves." in result.text


def test_first_last_prompt_describes_the_change_and_bans_restating_the_frames():
    result = build_first_last_prompt(span_caption=SPAN, motion_text="She lowers the hood.")
    text = " ".join(result.text.split())
    assert SPAN in text
    assert "She lowers the hood." in text
    assert "arrive exactly at the supplied last frame" in text
    assert "never re-describe either one as an event that happens again" in text
    assert "<Picture" not in text


def test_the_frames_reach_only_their_own_caption(monkeypatch):
    """The frame caption gets the frames; the action caption gets the source frames."""
    calls: list[tuple[str, int]] = []

    def fake_enhance(**kwargs):
        calls.append((kwargs["user_prompt"][:30], len(kwargs.get("images_b64") or [])))
        return "She stands in a hallway.", None

    import mmx_pkg.lib.prompt_enhancer as prompt_enhancer

    monkeypatch.setattr(prompt_enhancer, "enhance_prompt_sync", fake_enhance)
    result, error = build_from_images(
        recipe="first_last",
        url="", model="m", api_format="local",
        user_prompt="She turns around.",
        frame_images=["start-frame", "end-frame"],
        source_images=["a-source-frame"],
    )
    assert error is None
    assert len(calls) == 1, "fl2v needs one caption over the pair, not more"
    assert calls[0][1] == 2, "and it must see both frames"
    assert "She turns around." in result.text


def test_a_segment_without_its_frames_is_told_what_is_missing():
    result, error = build_from_images(
        recipe="start_image", url="", model="m", api_format="local",
        user_prompt="She waves.", reference_images=["ref"],
    )
    assert result is None
    assert "its first frame" in error

    result, error = build_from_images(
        recipe="first_last", url="", model="m", api_format="local",
        user_prompt="She waves.", reference_images=["ref"],
    )
    assert result is None
    assert "both of its frames" in error


@pytest.mark.parametrize("recipe", ["start_image", "first_last"])
def test_frame_recipes_are_never_given_a_source_frame_caption(recipe):
    """A source video is not part of these tasks, so the action caption must not run."""
    assert "action" not in plan_captions(recipe, source_frames=3, frame_images=2)
