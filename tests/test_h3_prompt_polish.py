# MiniMax H3 Motion Director - the wording-only polish mode.
# Copyright (C) 2026 WakaSoft. GPL-3.0. See LICENSE.

"""Polish mode must edit the prompt, not rebuild it.

Every other enhancer path decides the *shape* of the answer - MiniMax's official
template, a recipe, or the caption block this pack assembles from images. Polish
mode promises the opposite, and that promise is the whole product: the user has a
prompt that already works, wants better wording, and cannot afford a rename, a
dropped role line or an invented section costing a render.

Two halves are testable without a model, and both are pinned here:

* the instructions that go out (the prompt verbatim, no template, no rules, no
  images), and
* the mechanical structure comparison that decides whether the answer is
  acceptable - including the retry that names what moved, and the note that warns
  when it moved anyway.
"""

from __future__ import annotations

import json
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

if "folder_paths" not in sys.modules:  # the enhancer imports ComfyUI's paths
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

from mmx_pkg.lib.h3_prompt_polish import (  # noqa: E402
    build_polish_retry_message,
    build_polish_system_prompt,
    build_polish_user_message,
    inventory,
    is_polish_mode,
    polish_note,
    verify_polish,
)
from mmx_pkg.lib.prompt_enhancer import (  # noqa: E402
    API_FORMAT_OPENAI_COMPAT,
    enhance_prompt_sync,
)

# A small prompt in the shape the guide asks for: two sections, tags that are
# bindings, a beat marker, and a prohibition that must survive the edit.
SOURCE_PROMPT = """\
subject_definitions:
<Subject 1> is the woman in the attached references.
<Picture 1> is the sole source of her face.
<Video 1> is this window's source footage; its performer is discarded.

summary:
<Subject 1> replaces the source performer inside this window.

detailed_description:
[Shot 1] Begin from the opening frame. <Subject 1> lies face-down, never looking
at the camera. No second person. No on-screen text.
"""

# The enhancer trims the answer, so the scripted replies are built from the same
# text without its trailing newline.
PROMPT = SOURCE_PROMPT.strip()


def _flat(text: str) -> str:
    """Compare instructions without caring where the literal wrapped."""
    return " ".join(str(text or "").split())


# --- the mode name ------------------------------------------------------------


def test_only_the_polish_aliases_select_polish_mode():
    for value in ("polish", "POLISH", " polish_only ", "Polish-Only", "wording", "wording_only"):
        assert is_polish_mode(value), value
    # Everything else keeps its own path: a typo must not silently turn a rewrite
    # into a "kept your structure" answer that quietly reshapes the prompt.
    for value in ("", None, "rewrite", "captions", "polish_", "polisher"):
        assert not is_polish_mode(value), value


# --- the instructions ---------------------------------------------------------


def test_the_instructions_keep_the_structure_and_only_touch_wording():
    system = _flat(build_polish_system_prompt("English"))
    # What must not move.
    for phrase in (
        "header line",
        "the same headers, in the same order",
        "Never rename, renumber, reorder, add or remove",
        "beat marker",
        "prohibition",
        "Do not translate",
    ):
        assert phrase in system, phrase
    # What may change, and what must not be invented.
    for phrase in (
        "Grammar, spelling, punctuation",
        "Word choice",
        "Do not add sections, sentences, subjects, actions, props or details",
        "no preamble, no commentary",
    ):
        assert phrase in system, phrase
    # A polish pass is an edit, not an expansion.
    assert "10%" in system


def test_the_user_message_carries_the_prompt_verbatim():
    message = build_polish_user_message(PROMPT)
    assert PROMPT in message, "the model edits the user's text, not a copy of it"
    assert "=== PROMPT START ===" in message and "=== PROMPT END ===" in message
    # The prompt's own tags must not be confused with the message's delimiters.
    assert "<Subject 1>" in message


def test_chinese_output_gets_chinese_instructions():
    for language in ("中文", "zh"):
        system = _flat(build_polish_system_prompt(language))
        message = _flat(build_polish_user_message(SOURCE_PROMPT, language))
        assert "校对编辑" in system and "不得新增" in system, language
        assert "PROMPT START" in message and "请改进" in message, language
        assert "line editor" not in system, "the English instruction is replaced, not appended"


# --- the structure check ------------------------------------------------------


def test_rewording_alone_passes_the_check():
    polished = SOURCE_PROMPT.replace("lies face-down", "rests face-down")
    report = verify_polish(SOURCE_PROMPT, polished)
    assert report.ok, report.summary()
    assert report.summary() == "structure and tags unchanged"


def test_a_dropped_tag_or_heading_is_reported():
    polished = SOURCE_PROMPT.replace("<Picture 1> is the sole source of her face.\n", "")
    report = verify_polish(SOURCE_PROMPT, polished)
    assert not report.ok
    assert "<picture 1>" in report.missing_tags
    assert any("tags that disappeared" in line for line in report.problems())


def test_an_invented_tag_or_heading_is_reported():
    polished = SOURCE_PROMPT + "\n<Picture 3> is a second reference.\nretention_analysis:\nkept.\n"
    report = verify_polish(SOURCE_PROMPT, polished)
    assert not report.ok
    assert "<picture 3>" in report.added_tags
    assert "retention_analysis" in report.added_headers


def test_a_repeated_tag_must_stay_repeated():
    """Presence is not enough: a prompt that referenced a slot twice and comes
    back referencing it once lost a line."""
    once = SOURCE_PROMPT
    twice = SOURCE_PROMPT.replace("<Video 1> is this", "<Video 1> is this")
    assert verify_polish(once + "\n<Video 1> again.\n", once).ok is False
    assert verify_polish(twice, twice.replace("face-down", "face down")).ok


def test_case_and_spacing_differences_do_not_trip_the_check():
    """A capitalisation-only difference points at the same slot; spending another
    slow pass on it would cost more than it fixes."""
    polished = SOURCE_PROMPT.replace("<Subject 1>", "<subject  1>")
    assert verify_polish(SOURCE_PROMPT, polished).ok


def test_the_inventory_sees_the_tags_headers_and_markers():
    found = inventory(SOURCE_PROMPT)
    assert found.tags["<subject 1>"] == 3, "counted, not just present"
    assert found.tags["<video 1>"] == 1
    assert found.headers == ["subject_definitions", "summary", "detailed_description"]
    assert found.markers == ["[shot 1]"]


def test_the_retry_names_what_moved_and_carries_the_original():
    polished = SOURCE_PROMPT.replace("<Picture 1> is the sole source of her face.\n", "")
    report = verify_polish(SOURCE_PROMPT, polished)
    retry = build_polish_retry_message(SOURCE_PROMPT, report)
    assert "<picture 1>" in retry, "a generic 'keep the tags' is what already failed"
    assert SOURCE_PROMPT.strip() in retry
    assert "ORIGINAL prompt" in retry


# --- what the panel is told ---------------------------------------------------


def test_a_clean_pass_says_nothing():
    report = verify_polish(SOURCE_PROMPT, SOURCE_PROMPT.replace("lies", "rests"))
    assert polish_note(report, chars_before=300, chars_after=300) == ""


def test_a_retry_is_reported_but_not_alarming():
    report = verify_polish(SOURCE_PROMPT, SOURCE_PROMPT)
    report.retried = True
    note = polish_note(report, chars_before=300, chars_after=310)
    assert "retry" in note and "300 -> 310" in note


def test_a_structure_that_changed_anyway_warns_before_rendering():
    polished = SOURCE_PROMPT.replace("<Picture 1> is the sole source of her face.\n", "")
    report = verify_polish(SOURCE_PROMPT, polished)
    report.retried = True
    note = polish_note(report, chars_before=300, chars_after=280)
    assert "Review the prompt before rendering" in note
    assert "<picture 1>" in note


# --- through the enhancer -----------------------------------------------------


def _server(responses: list[str]) -> tuple[HTTPServer, list[dict], str]:
    """An OpenAI-compatible endpoint that answers with each scripted reply in turn."""
    seen: list[dict] = []
    queue = list(responses)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - http.server naming
            length = int(self.headers.get("Content-Length") or 0)
            seen.append(json.loads(self.rfile.read(length) or b"{}"))
            content = queue.pop(0) if queue else "polished"
            payload = json.dumps(
                {"choices": [{"message": {"role": "assistant", "content": content}}]}
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):  # keep the test output clean
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, seen, f"http://127.0.0.1:{server.server_port}"


def _polish(url: str, report: dict | None = None, **overrides):
    kwargs = dict(
        task_type="rv2v",
        user_prompt=SOURCE_PROMPT,
        url=url,
        model="test-model",
        api_format=API_FORMAT_OPENAI_COMPAT,
        prompt_mode="polish",
        timeout=10,
    )
    kwargs.update(overrides)
    return enhance_prompt_sync(**kwargs, polish_report=report)


def _messages(body: dict) -> tuple[str, object]:
    messages = body.get("messages") or []
    system = "\n".join(m.get("content") or "" for m in messages if m.get("role") == "system")
    user = next((m.get("content") for m in messages if m.get("role") == "user"), None)
    return system, user


def test_polish_sends_the_prompt_verbatim_with_no_template_rules_or_images():
    clean = PROMPT.replace("lies", "rests")
    server, seen, url = _server([clean])
    try:
        text, err = _polish(
            url,
            images_b64=["fake-image-bytes"],
            image_num=1,
            vision_source_count=1,
            ref_slots=[1],
            h3_rules=True,
            h3_recipe="character_replace",
        )
    finally:
        server.shutdown()

    assert err is None, err
    assert text == clean
    assert len(seen) == 1, "a clean pass needs no retry"
    system, user = _messages(seen[0])
    # The prompt is the thing being edited: it is present in full, not summarised
    # into a template's slot.
    assert PROMPT in str(user)
    assert "line editor" in system, "the polish instruction is the system prompt"
    # The engine contract invites a restructure, and images invite new appearance
    # prose; neither belongs in a wording pass.
    assert "engine" not in system.lower() or "line editor" in system
    assert "<Video 1> window" not in system
    assert isinstance(user, str), "no multimodal parts are attached in polish mode"


def test_a_dropped_tag_costs_one_retry_that_names_it():
    polished = PROMPT.replace(
        "<Picture 1> is the sole source of her face.\n", ""
    ).replace("lies", "rests")
    fixed = PROMPT.replace("lies face-down", "rests face-down")
    server, seen, url = _server([polished, fixed])
    report: dict = {}
    try:
        text, err = _polish(url, report)
    finally:
        server.shutdown()

    assert err is None, err
    assert text == fixed, "the retry's answer is what the user gets"
    assert len(seen) == 2, "exactly one retry"
    _, retry_user = _messages(seen[1])
    assert "<picture 1>" in str(retry_user), "the retry names the tag that went missing"
    assert report["ok"] is True and report["retried"] is True
    assert report["chars_after"] == len(fixed)

def test_a_structure_that_keeps_changing_is_still_returned_with_a_warning():
    """Better to hand back a usable polish with a note than to fail the click -
    but the note has to say what to check."""
    broken = PROMPT.replace("<Picture 1> is the sole source of her face.\n", "")
    server, seen, url = _server([broken, broken])
    report: dict = {}
    try:
        text, err = _polish(url, report)
    finally:
        server.shutdown()

    assert err is None, err
    assert text == broken
    assert len(seen) == 2, "one retry, not three"
    assert report["ok"] is False
    assert "<picture 1>" in report["problems"][0]
    assert "Review the prompt" in polish_note(
        verify_polish(SOURCE_PROMPT, broken),
        chars_before=len(SOURCE_PROMPT),
        chars_after=len(broken),
    )

def test_polish_still_reports_an_unreachable_backend(monkeypatch):
    """A polish pass must not swallow a connection error into "nothing to do"."""
    text, err = _polish("http://127.0.0.1:9", timeout=2)
    assert text is None and err, "an unreachable server is an error, not a no-op"


@pytest.mark.parametrize("mode", ["rewrite", "captions"])
def test_other_modes_keep_their_own_shape(mode):
    """Guard against polish leaking into the modes that *should* reshape: their
    user message is the template, not the raw prompt between markers."""
    server, seen, url = _server(["some text"])
    try:
        enhance_prompt_sync(
            task_type="rv2v",
            user_prompt=SOURCE_PROMPT,
            url=url,
            model="test-model",
            api_format=API_FORMAT_OPENAI_COMPAT,
            prompt_mode=mode,
            timeout=10,
        )
    finally:
        server.shutdown()

    system, user = _messages(seen[0])
    assert "line editor" not in system
    assert "=== PROMPT START ===" not in str(user)
