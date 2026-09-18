# MiniMax H3 Motion Director - compact engine rules for the prompt enhancer.
# Copyright (C) 2026 WakaSoft. GPL-3.0. See LICENSE.

"""The short form of the H3 contract, and why it is a trade rather than an upgrade.

The full rules are ~10k characters and a recipe block adds ~4k more. A local model
on partial offload pays for all of it before the first token and re-reads it on every
retry pass, so compact mode ships the same invariants with the explanations removed.
The invariants pinned here are the ones a live failure actually produced: an invented
event, a property that contradicted itself two sentences later, unplayable mood
prose, beats that never changed state, a `<d>` marker sitting in prose, and a
missing silence rule for a segment with no line.
"""

from __future__ import annotations

import json
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

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

from mmx_pkg.lib.h3_prompt_rules import (  # noqa: E402 - after the stub
    H3_DIRECTOR_TASKS,
    build_h3_enhance_rules,
    build_h3_enhance_rules as _rules,
)
from mmx_pkg.lib.prompt_enhancer import (  # noqa: E402 - after the stub
    API_FORMAT_OPENAI_COMPAT,
    enhance_prompt_sync,
)

# Every sentence here is a rule that a real enhancement broke.
_INVARIANTS = (
    "never invent a section",          # structure survives
    "Add no event",                    # no invented content
    "Do not contradict yourself",      # self-contradiction ban
    "cannot play",                     # unplayable mood prose
    "changes state",                   # beats that move
    "[English]",                       # the dialogue marker
    "completely silent",               # the silence rule
    "never leave the voice rule",      # ... and that it is unconditional
    "there is no negative prompt",
    "imageN",                          # the caller's own numbering
    "never renumber",                  # slot bindings
    "repeat with every segment",       # repeated lines carry no events
)


def _capture_server() -> tuple[HTTPServer, list[dict], str]:
    seen: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - http.server naming
            length = int(self.headers.get("Content-Length") or 0)
            seen.append(json.loads(self.rfile.read(length) or b"{}"))
            payload = json.dumps({
                "choices": [{"message": {"role": "assistant", "content": "enhanced"}}],
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, seen, f"http://127.0.0.1:{server.server_port}"


def _system(body: dict) -> str:
    return "\n".join(
        m.get("content") or "" for m in (body.get("messages") or [])
        if m.get("role") == "system"
    )


def test_compact_keeps_every_invariant_and_cuts_the_length():
    # The recipe block (~3.7k) is carried by both, so the saving is a constant ~4.5k
    # characters whatever the shape: 49% of a t2v segment, 68% of a replace window.
    for task, has_source in (("t2v", False), ("r2v", False), ("rv2v", True)):
        full = _rules(task, has_source=has_source)
        compact = _rules(task, has_source=has_source, compact=True)
        saved = len(full) - len(compact)
        assert saved >= 4000, f"{task}: compact saved only {saved}"
        assert len(compact) < len(full) * 0.7, f"{task}: compact is not shorter enough"
        flat = " ".join(compact.split())
        for phrase in _INVARIANTS:
            assert phrase.lower() in flat.lower(), f"{task} compact dropped: {phrase}"


def test_compact_applies_to_every_director_task_and_nothing_else():
    for key in sorted(H3_DIRECTOR_TASKS):
        assert build_h3_enhance_rules(key, compact=True), key
    assert build_h3_enhance_rules("t2i", compact=True) == ""


def test_compact_still_carries_the_recipe_and_the_replace_contract():
    compact = _rules(
        "rv2v", has_source=True, compact=True, recipe="character_replace_refmod"
    )
    assert "character reference" in compact
    # The discard sentence is a replace requirement at any rules length.
    assert "discard" in compact.lower()
    assert "RefMod" in compact or "mod" in compact
    assert "Write the enhanced prompt in English" in compact


def test_compact_and_full_agree_on_the_audio_policy_line():
    for compact in (False, True):
        block = _rules(
            "rv2v", has_source=True, compact=compact, audio_policy="generate"
        )
        assert "Audio policy for this window (authoritative" in block


def test_compact_is_what_the_request_carries(caplog):
    import logging

    server, seen, url = _capture_server()
    try:
        with caplog.at_level(logging.INFO):
            caplog.clear()
            enhance_prompt_sync(
                task_type="r2v",
                user_prompt="<Subject 1> walks in.",
                url=url,
                model="test-model",
                api_format=API_FORMAT_OPENAI_COMPAT,
                h3_rules=True,
                h3_rules_compact=True,
                timeout=10,
            )
        system = _system(seen[0])
        assert "Do not contradict yourself" in system
        # The long form's explanatory prose must not be there.
        assert "Work in one segment" not in system
        assert "compact" in caplog.text
    finally:
        server.shutdown()


def test_full_rules_are_unchanged_when_compact_is_not_asked_for():
    server, seen, url = _capture_server()
    try:
        enhance_prompt_sync(
            task_type="r2v",
            user_prompt="<Subject 1> walks in.",
            url=url,
            model="test-model",
            api_format=API_FORMAT_OPENAI_COMPAT,
            h3_rules=True,
            timeout=10,
        )
    finally:
        server.shutdown()

    system = _system(seen[0])
    assert "State each property once, and never contradict yourself" in system
    assert "compact" not in system.lower()
