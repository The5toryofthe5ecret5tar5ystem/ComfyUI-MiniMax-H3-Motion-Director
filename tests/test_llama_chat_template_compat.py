# MiniMax H3 Motion Director - chat template compatibility for vision handlers.
# Copyright (C) 2026 WakaSoft. GPL-3.0. See LICENSE.

"""The vision path renders the checkpoint's chat template; it must be renderable.

Live failure (2026-09-18): caption mode on a Qwen3-VL checkpoint died with

    Local inference failed: UndefinedError: 'raise_exception' is undefined

before generating a token. `Jinja2ChatFormatter` (the text-only path) registers
`raise_exception`, `strftime_now` and a non-escaping `tojson`; the multimodal handlers
subclass `MTMDChatHandler`, whose environment registers none of them. Qwen3-VL's own
template calls `raise_exception` in its guard branches, so every vision request failed
while text-only enhancement kept working - which is exactly the split the user saw.

The last test here loads the real GGUF metadata from the user's models/LLM tree and
renders that checkpoint's actual template through the patched environment, so the fix
is proven against the template that failed rather than against a stand-in.
"""

from __future__ import annotations

import datetime
import sys
import types

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

import jinja2  # noqa: E402
import pytest  # noqa: E402
from jinja2.sandbox import ImmutableSandboxedEnvironment  # noqa: E402

from mmx_pkg.lib.llama_chat_template_compat import (  # noqa: E402
    ensure_multimodal_template_helpers,
    install_template_helpers,
)

# The shape of the guard branch that broke: a template that refuses to render when it
# is called wrongly, which is how Qwen3-VL protects its required variables.
GUARD_TEMPLATE = (
    "{% if messages is not defined %}{{ raise_exception('messages is required') }}{% endif %}"
    "{% for message in messages %}{{ message['role'] }}:{{ message['content'] }}\n{% endfor %}"
)


def _fresh_env(template: str = ""):
    env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
    if template:
        return env, env.from_string(template)
    return env, None


def test_raise_exception_is_undefined_before_the_fix():
    """Pin the bug itself, so the helpers below are the only thing that changed."""
    _, template = _fresh_env(GUARD_TEMPLATE)
    with pytest.raises(jinja2.exceptions.UndefinedError):
        template.render()


def test_helpers_make_the_guard_template_render():
    env, template = _fresh_env(GUARD_TEMPLATE)
    added = install_template_helpers(env)
    assert "raise_exception" in added
    out = template.render(messages=[{"role": "user", "content": "hi"}])
    assert "user:hi" in out
    # The guard still fires when it should: the helper raises, rather than being a
    # no-op that would let a broken render through silently.
    with pytest.raises(jinja2.exceptions.TemplateError):
        template.render()


def test_helpers_cover_the_rest_of_the_transformers_set():
    env, _ = _fresh_env()
    installed = install_template_helpers(env)
    assert set(installed) >= {"raise_exception", "strftime_now", "tojson"}
    # strftime_now is what date-aware templates call.
    assert env.globals["strftime_now"]("%Y") == str(datetime.datetime.now().year)
    # tojson must not HTML-escape, or a JSON tool payload arrives as &#34; soup.
    assert env.filters["tojson"]({"a": "<b>"}) == '{"a": "<b>"}'
    # {% break %} needs the loop-controls extension.
    template = env.from_string("{% for i in range(5) %}{{ i }}{% if i == 2 %}{% break %}{% endif %}{% endfor %}")
    assert template.render() == "012"


def test_installing_twice_changes_nothing():
    env, _ = _fresh_env()
    install_template_helpers(env)
    assert install_template_helpers(env) == [], "a second pass must be a no-op"


def test_the_patch_is_idempotent_and_reports_its_state():
    first = ensure_multimodal_template_helpers()
    second = ensure_multimodal_template_helpers()
    assert first in {"installed", "already installed", "unavailable"} or first.startswith(
        "unavailable"
    )
    if first == "installed":
        assert second == "already installed"


def test_the_patch_targets_the_environment_the_handler_renders_with():
    """Drive the real method on whichever spelling this build exposes.

    The spelling is the point: `llama.py` reaches the module as
    ``llama_cpp.llama_multimodal``, and a bare ``llama_multimodal`` does not
    resolve on that build. Asking only for the bare name makes this test skip on
    the very build it exists to check - it did, reporting "build without the
    multimodal module" for a wheel that ships one.
    """
    import importlib

    module = None
    failures: list[str] = []
    for name in ("llama_cpp.llama_multimodal", "llama_multimodal"):
        try:
            module = importlib.import_module(name)
            break
        except Exception as exc:  # noqa: BLE001 - report which spelling failed and why
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
    if module is None:
        pytest.skip("multimodal module not importable (" + "; ".join(failures) + ")")
    cls = getattr(module, "MTMDChatHandler", None)
    if cls is None:
        pytest.skip("no MTMDChatHandler in this build")
    ensure_multimodal_template_helpers()

    handler = cls.__new__(cls)          # no model, no clip: just the template plumbing
    handler.chat_template = None
    handler._change_chat_template(GUARD_TEMPLATE)

    env = handler.chat_template.environment
    assert "raise_exception" in env.globals, "the helper reached the handler's env"
    rendered = handler.chat_template.render(messages=[{"role": "user", "content": "hi"}])
    assert "user:hi" in rendered


def _real_chat_template() -> tuple[str, str]:
    """(path, template) for a real checkpoint whose template calls the helper."""
    from mmx_pkg.lib.prompt_local_models import scan_gguf_files

    try:
        from llama_cpp import Llama
    except Exception:  # pragma: no cover - no llama_cpp on this box
        return "", ""
    for path, _mmproj in scan_gguf_files():
        try:
            probe = Llama(model_path=str(path), vocab_only=True, verbose=False)
            template = str((probe.metadata or {}).get("tokenizer.chat_template") or "")
            del probe
        except Exception:
            continue
        if "raise_exception" in template:
            return str(path), template
    return "", ""


def test_a_real_checkpoint_template_renders_after_the_fix():
    """The load-bearing check: the template that failed must now render."""
    path, template = _real_chat_template()
    if not template:
        pytest.skip("no installed GGUF uses raise_exception in its chat template")

    # What the multimodal handler builds, before and after the helpers.
    plain = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
    with pytest.raises(jinja2.exceptions.UndefinedError):
        plain.from_string(template).render(messages=[], add_generation_prompt=True)

    ensure_multimodal_template_helpers()
    env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
    install_template_helpers(env)
    rendered = env.from_string(template).render(
        messages=[{"role": "user", "content": "describe this frame"}],
        add_generation_prompt=True,
        bos_token="",
        eos_token="",
    )
    assert "describe this frame" in rendered, f"{path} rendered nothing"
