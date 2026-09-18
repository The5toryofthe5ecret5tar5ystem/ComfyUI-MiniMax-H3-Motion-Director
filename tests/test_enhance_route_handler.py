# MiniMax H3 Motion Director - the enhance route handler itself.
# Copyright (C) 2026 WakaSoft. GPL-3.0. See LICENSE.

"""Call `director_enhance_prompt` the way the panel does.

This exists because of a real 500: the route called `is_replace_task_prompt` without
importing it, so every Enhance click returned `NameError: name 'is_replace_task_prompt'
is not defined` while the whole test suite stayed green. Nothing exercised the handler
- the rule tests call `enhance_prompt_sync`, the panel harness stubs the HTTP layer,
and QA only walks GET routes. A handler is exactly the kind of code where a missing
import is invisible until a user clicks a button, so this file drives both paths
(rewrite and captions) through the real function and fails on any unbound name.

The LLM and the caption builder are stubbed; what is under test is the handler's own
wiring: request fields in, response fields out.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types

try:  # the suite imports ComfyUI core through PYTHONPATH; never stub over it
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

from mmx_pkg.director import prompt_enhance_routes as routes  # noqa: E402
from mmx_pkg.lib.h3_prompt_caption import CaptionResult  # noqa: E402


class _Request:
    """The only thing the handler uses from aiohttp's Request is `.json()`."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    async def json(self) -> dict:
        return self._payload


def _call(payload: dict):
    response = asyncio.run(routes.director_enhance_prompt(_Request(payload)))
    body = json.loads(response.body.decode("utf-8")) if response.body else {}
    return response.status, body


def _base(**overrides) -> dict:
    payload = {
        "task_type": "rv2v",
        "llm_url": "http://127.0.0.1:9/does-not-matter",
        "api_format": "OpenAI Compatible",
        "model": "test-model",
        "prompt": "<Video 1> window. <Subject 1> smiles.",
        "h3_rules": True,
        "h3_recipe": "auto",
    }
    payload.update(overrides)
    return payload


def test_rewrite_path_reaches_the_llm_and_reports_its_state(monkeypatch):
    seen: dict = {}

    def fake_enhance(**kwargs):
        seen.update(kwargs)
        return "enhanced window text", None

    monkeypatch.setattr(routes, "enhance_prompt_sync", fake_enhance)
    status, body = _call(_base(h3_rules_compact=True, vision_source_count=2))

    assert status == 200, body
    assert body["response"] == "enhanced window text"
    assert body["h3_rules"] is True
    assert body["h3_rules_compact"] is True, "the compact flag is echoed back"
    assert body["prompt_mode"] == "rewrite"
    assert seen["h3_rules_compact"] is True, "and it reaches the enhancer"


def test_rewrite_path_without_rules_reports_them_off(monkeypatch):
    monkeypatch.setattr(routes, "enhance_prompt_sync", lambda **kw: ("text", None))
    status, body = _call(_base(h3_rules=False, h3_rules_compact=True))
    assert status == 200
    assert body["h3_rules"] is False
    # Compact is meaningless with the rules off, so it must not be reported as on.
    assert body["h3_rules_compact"] is False


def test_rewrite_failure_is_reported_as_a_bad_gateway(monkeypatch):
    monkeypatch.setattr(routes, "enhance_prompt_sync", lambda **kw: (None, "boom"))
    status, body = _call(_base())
    assert status == 502
    assert "boom" in body["error"]


def test_caption_path_returns_the_assembled_block(monkeypatch):
    seen: dict = {}

    def fake_build_from_images(**kwargs):
        seen.update(kwargs)
        return CaptionResult(text="subject_definitions:\n<Subject 1> is her."), None

    import mmx_pkg.lib.h3_prompt_caption as caption_module

    monkeypatch.setattr(caption_module, "build_from_images", fake_build_from_images)
    status, body = _call(_base(
        prompt_mode="captions",
        images=["frame-one", "frame-two"],
        source_count=1,
        ref_slots=[0],
        audio_policy="source",
    ))

    assert status == 200, body
    assert body["prompt_mode"] == "captions"
    assert body["response"].startswith("subject_definitions:")
    assert seen["source_images"] == ["frame-one"], "source frames are split off"
    assert seen["reference_images"] == ["frame-two"]
    assert seen["audio_policy"] == "source"


def test_caption_path_carries_the_new_options_to_the_builder(monkeypatch):
    """Hide-performer and endpoint frames are the newest request fields."""
    seen: dict = {}

    def fake_build_from_images(**kwargs):
        seen.update(kwargs)
        return CaptionResult(text="block"), None

    import mmx_pkg.lib.h3_prompt_caption as caption_module

    monkeypatch.setattr(caption_module, "build_from_images", fake_build_from_images)
    status, body = _call(_base(
        prompt_mode="captions",
        hide_performer=True,
        frame_images=["start-frame", "end-frame"],
        h3_recipe="first_last",
        reference_images_note="unused",
    ))

    assert status == 200, body
    assert seen["hide_performer"] is True
    assert seen["frame_images"] == ["start-frame", "end-frame"]
    assert body["hide_performer"] is True
    assert body["h3_recipe"] == "first_last"


def test_caption_mode_declines_a_recipe_it_cannot_caption(monkeypatch):
    """t2v has nothing to look at, so the handler rewrites and says why."""
    monkeypatch.setattr(routes, "enhance_prompt_sync", lambda **kw: ("rewritten", None))
    status, body = _call(_base(
        task_type="t2v", prompt_mode="captions", h3_recipe="text_only", images=[],
    ))
    assert status == 200, body
    assert body["prompt_mode"] == "rewrite"
    assert "source-edit" in body["note"] or "recipes" in body["note"]


def test_a_caption_failure_is_a_bad_gateway_with_the_reason(monkeypatch):
    def fake_build_from_images(**kwargs):
        return None, "Action caption failed: HTTP 500"

    import mmx_pkg.lib.h3_prompt_caption as caption_module

    monkeypatch.setattr(caption_module, "build_from_images", fake_build_from_images)
    status, body = _call(_base(
        prompt_mode="captions", images=["frame-one"], source_count=1,
    ))
    assert status == 502
    assert "Action caption failed" in body["error"]


def test_the_refmod_recipe_reads_the_character_before_captioning(monkeypatch):
    """The character decode is part of the caption path, so it must be reachable."""
    seen: dict = {}
    decoded: dict = {}

    def fake_character_images(spec, **kwargs):
        decoded["spec"] = spec
        return ["char-frame"], {"source": "mod", "name": "elf_girl", "mode": "encode"}, ""

    def fake_build_from_images(**kwargs):
        seen.update(kwargs)
        return CaptionResult(text="block with wardrobe", skipped=[]), None

    import mmx_pkg.lib.h3_prompt_caption as caption_module
    import mmx_pkg.lib.refmod_character as refmod_module

    monkeypatch.setattr(refmod_module, "character_images_b64", fake_character_images)
    monkeypatch.setattr(caption_module, "build_from_images", fake_build_from_images)
    status, body = _call(_base(
        prompt_mode="captions",
        h3_recipe="character_replace_refmod",
        refmod_character="people/elf_girl",
        images=["frame-one"],
        source_count=1,
    ))

    assert status == 200, body
    assert decoded["spec"] == "people/elf_girl"
    assert seen["character_images"] == ["char-frame"]
    assert body["refmod"]["name"] == "elf_girl"


def test_a_refmod_decode_failure_is_reported_not_swallowed(monkeypatch):
    def fake_character_images(spec, **kwargs):
        return [], {}, "the H3 video VAE is not installed"

    import mmx_pkg.lib.h3_prompt_caption as caption_module
    import mmx_pkg.lib.refmod_character as refmod_module

    monkeypatch.setattr(refmod_module, "character_images_b64", fake_character_images)
    monkeypatch.setattr(
        caption_module, "build_from_images", lambda **kw: (None, "should not run")
    )
    status, body = _call(_base(
        prompt_mode="captions",
        h3_recipe="character_replace_refmod",
        refmod_character="people/elf_girl",
        images=["frame-one"],
        source_count=1,
    ))

    assert status == 502
    assert "H3 video VAE" in body["error"], "the real reason must reach the panel"


def test_empty_prompt_and_missing_model_are_rejected(monkeypatch):
    status, body = _call(_base(prompt=""))
    assert status == 400 and "Empty prompt" in body["error"]
    # Each backend substitutes its own default model name, so an empty request field
    # rarely stays empty; the guard is what matters, and it is pinned by making the
    # resolver answer with nothing.
    monkeypatch.setattr(routes, "coerce_llm_model", lambda value, default="": "")
    status, body = _call(_base(task_type="t2v"))
    assert status == 400 and "No model selected" in body["error"]


def test_invalid_json_is_a_bad_request():
    class _Broken:
        async def json(self):
            raise ValueError("not json")

    response = asyncio.run(routes.director_enhance_prompt(_Broken()))
    assert response.status == 400
    assert "Invalid JSON" in json.loads(response.body.decode())["error"]


def _call_unload(payload: dict):
    response = asyncio.run(routes.director_unload_model(_Request(payload)))
    body = json.loads(response.body.decode("utf-8")) if response.body else {}
    return response.status, body


def test_local_unload_frees_the_resident_model(monkeypatch):
    """Local (ComfyUI) is the default backend, and its Unload button used to 400.

    The panel showed the button because the model is resident in ComfyUI's own
    process - the one backend where unloading hands VRAM straight back to the
    render - but the route only knew the two remote formats and answered
    "Current API format does not support model unload". It now calls the runtime
    that owns the model.
    """
    import mmx_pkg.lib.prompt_local_runtime as local_runtime

    monkeypatch.setattr(
        local_runtime,
        "resident_info",
        lambda: {"model_path": "/models/LLM/Qwen3-VL-8B-Instruct-Q4_K_M.gguf"},
    )
    monkeypatch.setattr(local_runtime, "unload_local_models", lambda: 1)

    status, body = _call_unload({"api_format": "Local (ComfyUI)", "model": "qwen3-vl-8b"})

    assert status == 200, body
    assert body["status"] == "unloaded"
    assert body["provider"] == "Local (ComfyUI)"
    assert body["released"] == 1
    # Report what was actually holding memory, not what the panel guessed.
    assert body["model"] == "Qwen3-VL-8B-Instruct-Q4_K_M.gguf"


def test_local_unload_needs_no_model_name_and_reports_an_empty_runtime(monkeypatch):
    """Freeing VRAM must not depend on the panel still naming a model."""
    import mmx_pkg.lib.prompt_local_runtime as local_runtime

    monkeypatch.setattr(local_runtime, "resident_info", lambda: {})
    monkeypatch.setattr(local_runtime, "unload_local_models", lambda: 0)

    status, body = _call_unload({"api_format": "Local (ComfyUI)"})

    assert status == 200, body
    # The panel branches on this: "unloaded" when nothing was loaded would claim
    # a free that never happened.
    assert body["released"] == 0


def test_a_plain_openai_server_still_reports_that_it_cannot_unload(monkeypatch):
    """Only Ollama and llama-swap expose a remote unload; faking success would
    leave the user believing VRAM was freed."""
    status, body = _call_unload(
        {"api_format": "OpenAI Compatible", "model": "some-model", "openai_compat_mode": "standard"}
    )
    assert status == 400
    assert "does not support" in body["error"]
