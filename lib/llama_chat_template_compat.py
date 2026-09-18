# MiniMax H3 Motion Director - Jinja helpers for llama.cpp chat templates.
# Copyright (C) 2026 WakaSoft. GPL-3.0. See LICENSE.

"""Give llama.cpp's multimodal chat-template environment what Transformers gives it.

`Jinja2ChatFormatter` (the text-only path) registers `raise_exception`,
`strftime_now` and a non-HTML-escaping `tojson`, and enables `{% break %}` /
`{% continue %}` through the loop-controls extension - it says so in a comment:
"Keep this aligned with Transformers' chat-template Jinja setup".

The multimodal handlers do not. `Qwen25VLChatHandler`, `Qwen3VLChatHandler` and
`Qwen35ChatHandler` all subclass `llama_multimodal.MTMDChatHandler`, whose
`_change_chat_template` builds a bare `ImmutableSandboxedEnvironment`. Any template
that calls one of those helpers therefore dies before a single token is generated:

    Prompt enhance failed: Local inference failed: UndefinedError: 'raise_exception'
    is undefined

Qwen3-VL's own template does exactly that, in its guard branches - so vision caption
mode failed on every request for such a checkpoint while the text path worked fine.

The fix installs the same helpers on the handler's environment the moment the
template is built: no fork edit, no template rewrite, and the model still gets its
own chat template. `ensure_multimodal_template_helpers()` is idempotent and safe to
call before every load.
"""

from __future__ import annotations

import datetime
import json
import logging

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.lib")

# Marks the patched class so a second call does nothing.
_PATCH_MARK = "_minimax_chat_template_helpers"


def _mark(name: str):
    """Decorator: tag an installed helper so a later pass can tell ours from a built-in."""

    def decorate(function):
        setattr(function, "_minimax_template_helper", name)
        return function

    return decorate


def install_template_helpers(environment) -> list[str]:
    """Add the Transformers-compatible globals/filters to a Jinja environment.

    Returns the names that were actually added, so a caller can log what changed
    instead of claiming a fix it did not need to make.
    """
    import jinja2

    added: list[str] = []
    if "raise_exception" not in environment.globals:
        @_mark("raise_exception")
        def raise_exception(message: str):
            """Transformers' template helper: fail loudly from inside a template."""
            raise jinja2.exceptions.TemplateError(message)

        environment.globals["raise_exception"] = raise_exception
        added.append("raise_exception")
    if "strftime_now" not in environment.globals:
        environment.globals["strftime_now"] = _mark("strftime_now")(
            lambda fmt="%Y-%m-%d %H:%M:%S": datetime.datetime.now().strftime(fmt)
        )
        added.append("strftime_now")
    # Jinja ships its own `tojson`, so this is an override rather than a gap: the
    # built-in escapes HTML, which corrupts a plain-text template carrying JSON (a
    # tool payload arrives as `&#34;` soup). Transformers does not escape either.
    existing = environment.filters.get("tojson")
    if getattr(existing, "_minimax_template_helper", "") != "tojson":
        environment.filters["tojson"] = _mark("tojson")(
            lambda value, ensure_ascii=False, **kwargs: json.dumps(
                value, ensure_ascii=ensure_ascii
            )
        )
        added.append("tojson")
    try:
        has_loop_controls = any(
            getattr(extension, "identifier", "") in ("loopcontrols", "jinja2.ext.loopcontrols")
            or type(extension).__name__ == "LoopControlExtension"
            for extension in environment.extensions.values()
        )
        if not has_loop_controls:
            environment.add_extension("jinja2.ext.loopcontrols")
            added.append("loopcontrols")
    except Exception as exc:  # noqa: BLE001 - the extension is a nicety
        log.debug("Chat template: loop controls not added (%s)", exc)
    return added


def _multimodal_module():
    """The module that owns the mtmd handlers, or None.

    It is ``llama_cpp.llama_multimodal`` (imported that way by ``llama.py`` itself);
    a bare ``llama_multimodal`` only resolves on builds that put the package on the
    path, so both spellings are tried and the first that imports wins. Getting this
    wrong is silent - the patch would simply never apply - so it is a name lookup
    with a test that asserts the real class was reached.
    """
    import importlib

    for name in ("llama_cpp.llama_multimodal", "llama_multimodal"):
        try:
            return importlib.import_module(name)
        except Exception:  # noqa: BLE001 - try the next spelling
            continue
    return None


def ensure_multimodal_template_helpers() -> str:
    """Patch mtmd chat handlers once; returns a status string for the log.

    Called before a model load. When the class is missing (a llama.cpp build without
    the multimodal module, or a future version that already registers the helpers)
    nothing is patched and the caller is told which case it was.
    """
    module = _multimodal_module()
    if module is None:
        return "unavailable (no multimodal module)"

    cls = getattr(module, "MTMDChatHandler", None)
    if cls is None:
        return "unavailable (no MTMDChatHandler)"
    if getattr(cls, _PATCH_MARK, False):
        return "already installed"

    original = getattr(cls, "_change_chat_template", None)
    if original is None:
        return "unavailable (no _change_chat_template)"

    def patched(self, new_template):
        original(self, new_template)
        environment = getattr(getattr(self, "chat_template", None), "environment", None)
        if environment is not None:
            added = install_template_helpers(environment)
            if added:
                log.info(
                    "Chat template helpers installed on the multimodal handler: %s",
                    ", ".join(added),
                )

    patched.__name__ = "patched_change_chat_template"
    cls._change_chat_template = patched
    setattr(cls, _PATCH_MARK, True)
    return "installed"
