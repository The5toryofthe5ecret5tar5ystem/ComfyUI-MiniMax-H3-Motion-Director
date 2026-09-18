"""H3 engine rules for the prompt enhancer.

The panel hands a segment prompt to a general-purpose model. Nothing in the
request used to tell that model what the Director does with the text, so a
"helpful" rewrite could invert a slot role, put a spoken quote outside a `<d>`
block (the video model then reads the whole prompt aloud), or carry a beat in a
line that repeats in every segment. These tests pin the rule block and, more
importantly, that it actually reaches the request the LLM receives.
"""

from __future__ import annotations

import json
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

# `lib.prompt_enhancer` reaches `director.prompt_enhance_media`, which imports
# ComfyUI's `folder_paths` at module level. The prompt-enhance path only ever calls
# `get_input_directory()` inside functions, so a stand-in is enough to import it on
# a box without ComfyUI core on sys.path. Installed only when nothing else provided
# one (other test modules in this suite leak their own stub, which is fine too).
if "folder_paths" not in sys.modules:
    _stub = types.ModuleType("folder_paths")
    _stub.get_input_directory = lambda: "/tmp"
    _stub.get_output_directory = lambda: "/tmp"
    _stub.get_temp_directory = lambda: "/tmp"
    _stub.models_dir = "/tmp/models"
    sys.modules["folder_paths"] = _stub

from mmx_pkg.lib.h3_prompt_rules import (  # noqa: E402 - after the stub
    H3_DIRECTOR_TASKS,
    build_h3_enhance_rules,
    h3_rules_enabled,
)
from mmx_pkg.lib.prompt_enhancer import (  # noqa: E402 - after the stub
    API_FORMAT_OPENAI_COMPAT,
    enhance_prompt_sync,
)


@pytest.mark.parametrize("value,expected", [
    (True, True),
    (False, False),
    (None, False),
    (1, True),
    (0, False),
    ("true", True),
    ("on", True),
    ("yes", True),
    ("0", False),
    ("off", False),
    ("", False),
    ("random", False),
])
def test_toggle_coercion(value, expected):
    assert h3_rules_enabled(value) is expected


def test_every_director_task_gets_rules_and_unknown_tasks_do_not():
    for key in H3_DIRECTOR_TASKS:
        assert build_h3_enhance_rules(key), f"{key} produced no rules"
    assert build_h3_enhance_rules("t2i") == ""
    assert build_h3_enhance_rules("") == ""


def test_replace_block_only_when_a_source_video_exists():
    """The discard sentence is a replace contract: it is meaningless for t2v."""
    no_source = build_h3_enhance_rules("rv2v", has_source=False)
    with_source = build_h3_enhance_rules("rv2v", has_source=True)
    assert "DIFFERENT, unrelated woman" not in no_source
    assert "DIFFERENT, unrelated woman" in with_source
    assert "Wardrobe ownership" in with_source


def test_structured_caller_keeps_its_json_contract():
    plain = build_h3_enhance_rules("rv2v", has_source=True)
    structured = build_h3_enhance_rules("rv2v", has_source=True, structured=True)
    assert "structured JSON" not in plain
    assert "structured JSON" in structured


def test_rules_language_follows_the_output_language():
    assert "Write the enhanced prompt in English." in build_h3_enhance_rules("r2v")
    zh = build_h3_enhance_rules("r2v", output_language="中文")
    assert "Simplified Chinese" in zh
    # Slot labels stay untranslated whatever the output language is.
    assert "`<Picture 1>`" in zh and "`[English]`" in zh


def test_rules_use_plain_hyphens_only():
    """The pack's own style: no em/en dashes anywhere in generated prompt text."""
    for key in sorted(H3_DIRECTOR_TASKS):
        rules = build_h3_enhance_rules(key, has_source=True, structured=True)
        assert "\u2014" not in rules, key
        assert "\u2013" not in rules, key


def test_contradictions_and_unplayable_prose_are_banned():
    """Real failure from a live enhancement (2026-09-17).

    The model turned one segment into prose that described loose waving hair and,
    two sentences later, a neat ponytail - and spent three sentences on mood
    ("she exudes a cheerful and lively character", "adding a touch of playful
    energy") instead of beats. Both classes are now named in the rules.
    """
    for key in sorted(H3_DIRECTOR_TASKS):
        rules = build_h3_enhance_rules(key)
        assert "State each property once, and never contradict yourself" in rules, key
        assert "Cut anything the model cannot play" in rules, key
        assert "lively vibe" in rules, key


def test_discard_sentence_must_be_added_when_the_input_lacks_it():
    """Live failure (2026-09-17): the input had no discard sentence, the enhanced
    text kept that gap, and the rule only said "keep it intact"."""
    rules = build_h3_enhance_rules("rv2v", has_source=True)
    assert "ADD it if it does not" in rules
    assert "structural requirement" in rules


def test_attachment_vocabulary_matches_the_pack_convention():
    """Source frames are frameN and reference images are imageN - not <Picture N>.

    The pack's own vision preamble teaches this numbering and the engine adds
    `<Picture N>` / `<Video 1>` itself when a prompt needs them, so the rules must
    not tell the model to rewrite imageN into a tag (an earlier version did).
    """
    rules = build_h3_enhance_rules("rv2v", has_source=True)
    assert "`image0`, `image1`, ..." in rules and "`frame0`, `frame1`" in rules
    assert "Do not add" in rules and "<Picture N>" in rules
    assert "Never write `@tag` aliases" in rules


def test_replace_mapping_is_pinned():
    rules = build_h3_enhance_rules("rv2v", has_source=True)
    # A replace sentence must keep saying who replaces whom.
    assert "replacement mapping intact" in rules


def test_replace_window_keeps_its_shape_and_identity_ownership():
    """Live failure (2026-09-17): the enhanced replace window came back as one
    prose paragraph with no opener, and it described the new woman's face and
    wardrobe in prose even though identity is carried by a character reference."""
    rules = build_h3_enhance_rules("rv2v", has_source=True)
    # Collapse wrapping: phrase checks must not depend on where the text breaks.
    flat = " ".join(rules.split())
    assert "never flatten a structured window into one paragraph" in flat
    assert "an attached character reference" in flat
    assert "do NOT describe her face, hair or body in prose" in flat
    assert "Begin from the opening frame of this window" in flat
    assert "Keep an audio-policy line if the input has one" in flat
    # Non-replace tasks must not receive replace-only instructions.
    assert "discard" not in build_h3_enhance_rules("t2v").lower()


def _capture_server() -> tuple[HTTPServer, list[dict], str]:
    """A one-endpoint OpenAI-compatible server that records the request body."""
    seen: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - http.server naming
            length = int(self.headers.get("Content-Length") or 0)
            seen.append({
                "path": self.path,
                "body": json.loads(self.rfile.read(length) or b"{}"),
            })
            payload = json.dumps({
                "choices": [{"message": {"role": "assistant", "content": "enhanced text"}}],
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):  # keep the test output clean
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, seen, f"http://127.0.0.1:{server.server_port}"


def _system_message(request_body: dict) -> str:
    messages = request_body.get("messages") or []
    systems = [m.get("content") or "" for m in messages if m.get("role") == "system"]
    return "\n".join(systems)


def test_rules_reach_the_llm_request():
    server, seen, url = _capture_server()
    try:
        text, err = enhance_prompt_sync(
            task_type="rv2v",
            user_prompt="<Video 1> window. <Subject 1> smiles.",
            url=url,
            model="test-model",
            api_format=API_FORMAT_OPENAI_COMPAT,
            h3_rules=True,
            timeout=10,
        )
    finally:
        server.shutdown()

    assert err is None and text == "enhanced text"
    assert len(seen) == 1
    system = _system_message(seen[0]["body"])
    assert "Reference slots are bindings" in system
    assert "<d>" in system and "DIFFERENT, unrelated woman" not in system  # no source count sent
    # The user's own text still reaches the model as the user message.
    user = [m for m in seen[0]["body"]["messages"] if m.get("role") == "user"]
    assert user and "Subject 1" in (user[0].get("content") or "")


def test_rules_are_absent_when_the_toggle_is_off():
    """A caller that does not ask for the rules must see no change at all."""
    server, seen, url = _capture_server()
    try:
        enhance_prompt_sync(
            task_type="rv2v",
            user_prompt="<Video 1> window. <Subject 1> smiles.",
            url=url,
            model="test-model",
            api_format=API_FORMAT_OPENAI_COMPAT,
            timeout=10,
        )
    finally:
        server.shutdown()

    system = _system_message(seen[0]["body"])
    assert "Reference slots are bindings" not in system
    assert "Beats" not in system


def test_replace_source_count_adds_the_discard_rule_to_the_request():
    server, seen, url = _capture_server()
    try:
        enhance_prompt_sync(
            task_type="rv2v",
            user_prompt="<Video 1> window. <Subject 1> smiles.",
            url=url,
            model="test-model",
            api_format=API_FORMAT_OPENAI_COMPAT,
            vision_source_count=2,
            h3_rules=True,
            timeout=10,
        )
    finally:
        server.shutdown()

    assert "DIFFERENT, unrelated woman" in _system_message(seen[0]["body"])


def test_character_detail_is_skipped_for_refmod_identity(caplog):
    """"Character feature enhance" and the RefMod recipe ask for opposite things.

    The toggle demands a long appearance description built from the reference image,
    while the recipe says not to describe her face or hair in prose at all (the mod
    is appended after text encoding, so prose about her cannot be grounded in it).
    Obeying both is impossible, and the detail path also costs a 4096-token budget
    and up to three passes - so it stands down for that recipe.
    """
    import logging

    def _run(recipe):
        server, seen, url = _capture_server()
        try:
            with caplog.at_level(logging.INFO):
                caplog.clear()
                enhance_prompt_sync(
                    task_type="rv2v",
                    user_prompt="<Video 1> window. <Subject 1> smiles.",
                    url=url,
                    model="test-model",
                    api_format=API_FORMAT_OPENAI_COMPAT,
                    vision_source_count=2,
                    character_feature_enhance=True,
                    h3_rules=True,
                    h3_recipe=recipe,
                    timeout=10,
                )
            return seen[0]["body"], caplog.text
        finally:
            server.shutdown()

    _, refmod_log = _run("character_replace_refmod")
    assert "character feature enhance skipped" in refmod_log

    _, pictures_log = _run("character_replace")
    assert "character feature enhance skipped" not in pictures_log
