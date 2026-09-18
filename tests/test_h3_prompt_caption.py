"""Build a replace prompt from images (the Character Remake + QwenVL port).

That workflow was reliable because a model never wrote the structure: two narrow
vision captions answered "what does she look like" and "what happens here", and a
template glued them together. These tests pin the properties that made it work:

* each caption sees only its own images (identity gets the references, action gets
  the source frames), so neither can describe the other;
* the block, its role lines and the discard sentence come from code;
* the RefMod variant drops the identity caption entirely, because prose about her
  face cannot be grounded in a reference the text encoder never sees.
"""

from __future__ import annotations

import json
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

if "folder_paths" not in sys.modules:
    _stub = types.ModuleType("folder_paths")
    _stub.get_input_directory = lambda: "/tmp"
    _stub.get_output_directory = lambda: "/tmp"
    _stub.get_temp_directory = lambda: "/tmp"
    _stub.models_dir = "/tmp/models"
    sys.modules["folder_paths"] = _stub

from mmx_pkg.lib.h3_prompt_caption import (  # noqa: E402
    ACTION_CAPTION_TOKENS,
    AUDIO_LINES,
    MAX_MOTION_NOTE_CHARS,
    build_from_images,
    build_ref2va_prompt,
    build_replace_window_prompt,
    build_source_edit_prompt,
    normalize_audio_policy,
    plan_captions,
)
from mmx_pkg.lib.prompt_enhancer import API_FORMAT_OPENAI_COMPAT  # noqa: E402


# --- which captions a request needs -----------------------------------------

def test_plan_captions_needs_matching_images():
    # Identity first, action last: the action call is the one that may unload.
    assert plan_captions("character_replace", source_frames=3, reference_images=2) == ["identity", "action"]
    assert plan_captions("character_replace", source_frames=3, reference_images=0) == ["action"]
    assert plan_captions("character_replace", source_frames=0, reference_images=2) == ["identity"]
    assert plan_captions("character_replace", source_frames=0, reference_images=0) == []


def test_plan_captions_for_reference_segments_and_source_edits():
    """r2v has no source video: her look and the room both come from references."""
    assert plan_captions("ref2va", source_frames=0, reference_images=3) == ["identity", "scene"]
    # A source edit is the opposite: the source frames describe it, the user's own
    # prompt supplies the change.
    assert plan_captions("source_edit", source_frames=3, reference_images=0) == ["action"]
    assert plan_captions("source_edit", source_frames=0, reference_images=0) == []


def test_plan_captions_for_a_refmod_window():
    """A mod carries the identity, so there is nothing to caption from text alone.

    A window can carry numbered reference pictures *as well* - the shared Common
    pool plus its own - and those are text-visible, so they are captioned and the
    assembled block names them as the same woman.
    """
    assert plan_captions("character_replace_refmod", source_frames=3) == ["action"]
    assert plan_captions(
        "character_replace_refmod", source_frames=3, reference_images=2
    ) == ["identity", "action"]


def test_plan_captions_ignores_recipes_it_cannot_assemble():
    # t2v has no images at all, and i2v/fl2v frames are not sent to the enhancer.
    assert plan_captions("text_only", source_frames=3, reference_images=2) == []
    assert plan_captions("official", source_frames=3, reference_images=2) == []
    assert plan_captions("start_image", source_frames=2, reference_images=2) == []


# --- assembly ----------------------------------------------------------------

IDENTITY = "An East Asian woman in her thirties, long dark hair, plaid shirt."
ACTION = "A bright bedroom; the camera sits at face level; she kneels on the bed."


def test_assembled_block_carries_the_code_owned_lines():
    result = build_replace_window_prompt(
        recipe="character_replace",
        identity_caption=IDENTITY,
        action_caption=ACTION,
        audio_policy="source",
        picture_count=2,
    )
    flat = " ".join(result.text.split())
    assert "DIFFERENT, unrelated woman and is fully discarded" in flat
    assert "Begin from the opening frame of this window" in flat
    assert f"Identity: {IDENTITY}" in flat
    assert ACTION in flat
    assert "Camera: exactly as <Video 1>" in flat
    assert result.skipped == []


def test_picture_lines_only_for_attached_references():
    one = build_replace_window_prompt(
        recipe="character_replace", identity_caption=IDENTITY,
        action_caption=ACTION, picture_count=1,
    ).text
    two = build_replace_window_prompt(
        recipe="character_replace", identity_caption=IDENTITY,
        action_caption=ACTION, picture_count=2,
    ).text
    assert "<Picture 1>" in one and "<Picture 2>" not in one
    assert "<Picture 1>" in two and "<Picture 2>" in two


def test_a_replace_window_carries_the_users_own_motion_note():
    """The action prose used to be the caption's alone, and a caption of stills
    cannot see motion that leaves no visible difference between them."""
    result = build_replace_window_prompt(
        recipe="character_replace",
        identity_caption=IDENTITY,
        action_caption=ACTION,
        motion_note="She lies face down and keeps gyrating her hips.",
        picture_count=2,
    )
    flat = " ".join(result.text.split())
    assert "keeps gyrating her hips" in flat
    assert "own note on the motion" in flat
    assert "never replace what <Video 1> does" in flat
    assert "never invent a different action" in flat
    assert ACTION in flat, "the caption still describes what the frames show"
    assert result.action == ACTION, "the note does not become the action caption"


def test_a_replace_window_without_a_note_has_no_note_sentence():
    result = build_replace_window_prompt(
        recipe="character_replace",
        identity_caption=IDENTITY,
        action_caption=ACTION,
        picture_count=1,
    )
    assert "own note on the motion" not in result.text


def test_the_motion_note_is_one_line_and_bounded():
    result = build_replace_window_prompt(
        recipe="character_replace",
        action_caption=ACTION,
        motion_note='She rolls her hips.\n\n# marked "up" ' + ("and again " * 200),
        picture_count=1,
    )
    note = result.text.split("which still frames cannot show: ", 1)[1].split(". Follow it;", 1)[0]
    assert "\n" not in note
    assert "marked up" in note, "markdown and quotes are stripped"
    assert len(note) <= MAX_MOTION_NOTE_CHARS, "bounded, so it cannot crowd the block"


def test_a_refmod_window_keeps_the_note_too():
    result = build_replace_window_prompt(
        recipe="character_replace_refmod",
        action_caption=ACTION,
        character_caption="OUTFIT: a tunic CLUE: the elf",
        motion_note="Her hips never stop moving.",
    )
    flat = " ".join(result.text.split())
    assert "Her hips never stop moving." in flat
    assert "wardrobe: she wears a tunic" in flat


def test_refmod_block_never_includes_appearance_prose():
    # No numbered pictures attached: the mod is her only identity source, so there is
    # nothing text-visible to ground appearance prose in and it is left out. With
    # pictures attached it is included instead - see
    # test_refmod_character.py::test_refmod_window_with_reference_pictures_names_and_describes_them.
    result = build_replace_window_prompt(
        recipe="character_replace_refmod",
        identity_caption=IDENTITY,
        action_caption=ACTION,
        audio_policy="source",
    )
    flat = " ".join(result.text.split())
    assert IDENTITY not in flat, "the mod's identity must not be described in prose"
    assert "Identity:" not in flat
    assert "carried by the attached character reference" in flat
    assert "not described in this text" in flat
    # The plan asks for an identity caption on a mod window only when the window
    # carries pictures of its own (pinned in test_refmod_character.py). What
    # `skipped` reports here is what the window could not be given: with no RefMod
    # character supplied, the wardrobe line and the clue are both absent - and the
    # wardrobe line is the one the guide says must match the reference, so it is
    # reported rather than quietly dropped.
    assert result.skipped == ["wardrobe", "clue"]
    assert "wardrobe:" not in flat
    assert ACTION in flat, "the action caption is still used"
    assert "<Picture 1>" not in flat, "no pictures, no picture lines"


def test_audio_policy_is_stated_not_guessed():
    for policy, expected in AUDIO_LINES.items():
        text = build_replace_window_prompt(
            recipe="character_replace", identity_caption=IDENTITY,
            action_caption=ACTION, audio_policy=policy,
        ).text
        assert expected in " ".join(text.split()), policy
    assert normalize_audio_policy("nonsense") == "source"
    assert normalize_audio_policy("GENERATE") == "generate"


def test_captions_are_flattened_and_quotes_stripped():
    result = build_replace_window_prompt(
        recipe="character_replace", identity_caption='A woman\nwith "quotes".',
        action_caption="Line one.\nLine two.", picture_count=2,
    )
    assert 'Identity: A woman with quotes.' in result.text
    assert "Line one. Line two." in result.text


def test_no_em_or_en_dashes():
    for recipe in ("character_replace", "character_replace_refmod"):
        text = build_replace_window_prompt(
            recipe=recipe, identity_caption=IDENTITY, action_caption=ACTION,
        ).text
        assert "\u2014" not in text and "\u2013" not in text, recipe


# --- the two calls themselves ------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    seen: list[dict] = []

    def do_POST(self):  # noqa: N802 - http.server naming
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        _Handler.seen.append(body)
        # Label by the instruction, not by call order: the RefMod variant runs only
        # the action caption, and an order-based fake would mislabel it.
        user_text = ""
        for message in body.get("messages") or []:
            if message.get("role") == "user":
                content = message.get("content")
                user_text = content if isinstance(content, str) else " ".join(
                    part.get("text", "") for part in content if isinstance(part, dict)
                )
                break
        caption = "ACTION-CAPTION"
        if "identity-preserving video generation" in user_text:
            caption = "IDENTITY-CAPTION"
        elif "scene continuity" in user_text:
            caption = "SCENE-CAPTION"
        payload = json.dumps({"choices": [{"message": {"content": caption}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        return


@pytest.fixture
def _server():
    _Handler.seen = []
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def _image_urls(body: dict) -> list[str]:
    content = (body.get("messages") or [{}])[1].get("content")
    if not isinstance(content, list):
        return []
    return [part["image_url"]["url"] for part in content if part.get("type") == "image_url"]


def test_each_caption_receives_only_its_own_images(_server):
    result, err = build_from_images(
        recipe="character_replace",
        url=_server,
        model="test-model",
        api_format=API_FORMAT_OPENAI_COMPAT,
        source_images=["SRC1", "SRC2", "SRC3"],
        reference_images=["REF1", "REF2"],
        audio_policy="generate",
        timeout=10,
    )
    assert err is None, err
    assert len(_Handler.seen) == 2, "one call per caption"

    identity_body, action_body = _Handler.seen
    identity_urls = _image_urls(identity_body)
    action_urls = _image_urls(action_body)
    assert all("REF" in url for url in identity_urls) and len(identity_urls) == 2
    assert all("SRC" in url for url in action_urls) and len(action_urls) == 3

    # The captions land in the assembled block, which is code-owned structure.
    assert "Identity: IDENTITY-CAPTION" in result.text
    assert "ACTION-CAPTION" in result.text
    assert AUDIO_LINES["generate"] in " ".join(result.text.split())


def test_caption_calls_are_capped_so_the_run_stays_short(_server):
    build_from_images(
        recipe="character_replace",
        url=_server,
        model="test-model",
        api_format=API_FORMAT_OPENAI_COMPAT,
        source_images=["SRC1"],
        reference_images=["REF1"],
        timeout=10,
    )
    for body in _Handler.seen:
        assert body.get("max_tokens") == ACTION_CAPTION_TOKENS


def test_build_from_images_keeps_the_users_motion_note_for_a_replace_window(_server):
    """End to end: the text in the prompt box reaches the assembled block."""
    result, err = build_from_images(
        recipe="character_replace",
        url=_server,
        model="test-model",
        api_format=API_FORMAT_OPENAI_COMPAT,
        user_prompt="She lies face down and keeps gyrating her hips.",
        source_images=["SRC1"],
        reference_images=["REF1", "REF2"],
        timeout=10,
    )
    assert err is None, err
    assert "keeps gyrating her hips" in result.text
    assert "IDENTITY-CAPTION" in result.text, "the reference caption is still there"


def test_refmod_only_runs_one_call(_server):
    result, err = build_from_images(
        recipe="character_replace_refmod",
        url=_server,
        model="test-model",
        api_format=API_FORMAT_OPENAI_COMPAT,
        source_images=["SRC1", "SRC2"],
        timeout=10,
    )
    assert err is None, err
    assert len(_Handler.seen) == 1, "no identity caption for a mod-carried identity"
    assert all("SRC" in url for url in _image_urls(_Handler.seen[0]))
    assert "ACTION-CAPTION" in result.text
    assert "IDENTITY-CAPTION" not in result.text


def test_refmod_with_reference_pictures_captions_them_too(_server):
    """Mod + pictures: the pictures are text-visible, so they are described as well."""
    result, err = build_from_images(
        recipe="character_replace_refmod",
        url=_server,
        model="test-model",
        api_format=API_FORMAT_OPENAI_COMPAT,
        source_images=["SRC1"],
        reference_images=["REF1", "REF2"],
        timeout=10,
    )
    assert err is None, err
    assert len(_Handler.seen) == 2, "identity from the attached pictures, then action"
    identity_call, action_call = _Handler.seen
    assert all("REF" in url for url in _image_urls(identity_call)), (
        "the identity caption sees the references, never the source frames"
    )
    assert all("SRC" in url for url in _image_urls(action_call))
    assert "IDENTITY-CAPTION" in result.text
    assert "ACTION-CAPTION" in result.text


def test_missing_images_is_reported_not_guessed(_server):
    result, err = build_from_images(
        recipe="character_replace",
        url=_server,
        model="test-model",
        api_format=API_FORMAT_OPENAI_COMPAT,
        source_images=[],
        reference_images=[],
        timeout=10,
    )
    assert result is None
    assert "nothing to caption" in err and "text-to-video segment has none" in err
    assert _Handler.seen == [], "no model call is made without images"


def test_unsupported_recipe_is_refused(_server):
    result, err = build_from_images(
        recipe="text_only",
        url=_server,
        model="test-model",
        api_format=API_FORMAT_OPENAI_COMPAT,
        source_images=["SRC1"],
        reference_images=["REF1"],
        timeout=10,
    )
    assert result is None and "nothing to caption" in err
    assert _Handler.seen == []


# --- reference segments keep the user's own action text ----------------------

USER_PROMPT = (
    "She kneels down, then reaches for the drawer. She opens it slowly and looks back "
    "at the viewer."
)


def test_ref2va_uses_captions_for_look_and_room_and_the_user_prompt_for_action():
    result = build_ref2va_prompt(
        identity_caption=IDENTITY,
        scene_caption="A wood-panelled bedroom, warm lamp light from the left, a low bed.",
        action_text=USER_PROMPT,
        picture_count=2,
    )
    flat = " ".join(result.text.split())
    assert "subject_definitions:" in flat
    assert f"Identity: {IDENTITY}" in flat
    assert "warm lamp light from the left" in flat
    # The user's own words survive verbatim - they are the one part no image can supply.
    assert USER_PROMPT in flat
    assert "the camera IS the viewer's eyes" in flat
    assert "NO MALE AUDIO" in flat
    assert result.skipped == []


def test_ref2va_without_a_scene_caption_says_so():
    result = build_ref2va_prompt(identity_caption=IDENTITY, action_text=USER_PROMPT, picture_count=1)
    flat = " ".join(result.text.split())
    assert result.skipped == ["scene"]
    assert "Scene:" not in flat, "no invented location when the image gave none"
    assert "Identity:" in flat


def test_source_edit_keeps_the_change_in_the_users_words():
    result = build_source_edit_prompt(
        action_caption="A dim room; the camera is a static wide shot; she is seated.",
        change_text="replace the lamp's bulb with a warm one",
        audio_policy="source",
    )
    flat = " ".join(result.text.split())
    assert "replace the lamp's bulb with a warm one" in flat
    assert "A dim room; the camera is a static wide shot; she is seated." in flat
    assert "Everything else stays exactly as <Video 1>" in flat
    assert AUDIO_LINES["source"] in flat


def test_ref2va_captions_share_the_reference_images(_server):
    """Identity and scene are two narrow questions about the same pictures."""
    result, err = build_from_images(
        recipe="ref2va",
        url=_server,
        model="test-model",
        api_format=API_FORMAT_OPENAI_COMPAT,
        user_prompt=USER_PROMPT,
        source_images=[],
        reference_images=["REF1", "REF2"],
        timeout=10,
    )
    assert err is None, err
    assert len(_Handler.seen) == 2
    identity, scene = _Handler.seen
    assert all("REF" in url for url in _image_urls(identity))
    assert all("REF" in url for url in _image_urls(scene))
    # Both answers land in the block, and the user's prompt is untouched.
    assert "IDENTITY-CAPTION" in result.text
    assert "SCENE-CAPTION" in result.text
    assert USER_PROMPT in " ".join(result.text.split())
