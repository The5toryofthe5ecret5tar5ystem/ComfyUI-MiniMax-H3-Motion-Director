"""Everything under ``web/js`` is served to the browser, recursively.

ComfyUI's ``WEB_DIRECTORY`` for this pack is ``./web/js`` and the frontend imports
every ``.js`` file the ``/extensions`` route reports - including files inside
subdirectories. A stray directory there is therefore **not inert**: it is loaded as
extension code.

This guard exists because that bit us for real. The installed pack had accumulated a
``web/js/_perf_backup_20260909-210305/`` directory holding two-day-old copies of
``minimax_timeline.js``, ``minimax_director_inputs.js`` and
``minimax_director_sections.js``. Those copies registered the **same extension names**
as the live modules (``ComfyUI.MiniMaxH3MotionDirectorPlugin``,
``MiniMaxH3.MotionDirector.UnifiedInputs``, ``MiniMaxH3.MotionDirector.MainSections``),
so a stale 615 KB timeline module was being imported on top of the current one - which
is exactly the "base module and override drift apart" failure the fork review warned
about, only worse, because the drifting copy was invisible in the repo.

Two rules, both cheap:

1. Only expected directories live under ``web/js`` (currently just ``tests``).
2. No extension name is registered twice anywhere in the served tree.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WEB_JS = Path(__file__).resolve().parents[1] / "web" / "js"

# Directories that are allowed directly under web/js. `tests` holds Node test files,
# which are never imported by the frontend. Anything else must be reviewed: if it
# contains .js modules it will be served and executed.
ALLOWED_SUBDIRS = {"tests"}

_MODULE_SUFFIXES = (".js", ".mjs")

# Bounded window rather than [^}]*: a registration body may contain braces
# (e.g. a beforeRegisterNodeDef() method) before `name` appears.
_REGISTER_NAME = re.compile(
    r"registerExtension\(\s*\{.{0,600}?\bname\s*:\s*[\"']([^\"']+)[\"']",
    re.DOTALL,
)


def _served_dirs() -> list[Path]:
    if not WEB_JS.is_dir():
        pytest.skip(f"web/js not found at {WEB_JS}")
    return sorted(p for p in WEB_JS.iterdir() if p.is_dir())


def _modules() -> list[Path]:
    return sorted(p for p in WEB_JS.rglob("*") if p.is_file() and p.suffix in _MODULE_SUFFIXES)


def test_only_expected_directories_are_served():
    unexpected = sorted(p.name for p in _served_dirs() if p.name not in ALLOWED_SUBDIRS)
    assert not unexpected, (
        "Unexpected director(ies) under web/js: "
        f"{unexpected}. ComfyUI serves web/js recursively, so any .js inside them is "
        "imported as extension code. A backup or scratch directory here will load a "
        "stale duplicate of whatever it contains. Move it outside web/."
    )


def test_no_backup_or_editor_leftovers_are_served():
    # A `.bak`/`~`/`.orig` file is inert (not .js), but a renamed *.js copy is not.
    leftovers = sorted(
        p.name
        for p in WEB_JS.rglob("*")
        if p.is_file()
        and p.suffix in _MODULE_SUFFIXES
        and (p.name.startswith(("_", ".")) or ".bak" in p.name or p.name.endswith("~"))
    )
    assert not leftovers, (
        f"Backup-looking modules are being served and executed: {leftovers}. "
        "They register the same extension names as the live files and will run twice."
    )


def test_no_extension_name_is_registered_twice():
    seen: dict[str, list[str]] = {}
    for module in _modules():
        try:
            source = module.read_text(encoding="utf-8", errors="replace")
        except OSError:  # pragma: no cover - unreadable file is its own problem
            continue
        for name in _REGISTER_NAME.findall(source):
            seen.setdefault(name, []).append(str(module.relative_to(WEB_JS)))

    duplicates = {name: paths for name, paths in seen.items() if len(paths) > 1}
    assert not duplicates, (
        "The same extension name is registered from more than one served module: "
        f"{duplicates}. Both copies will be imported and both will run, so hooks get "
        "double-wrapped and DOM widgets get mounted twice. Remove the stale copy."
    )


def test_the_guard_actually_finds_registrations():
    # If the regex stopped matching (formatting change), the duplicate check above
    # would silently pass forever. Pin that it still sees the real registrations.
    names = {
        name
        for module in _modules()
        for name in _REGISTER_NAME.findall(module.read_text(encoding="utf-8", errors="replace"))
    }
    assert "ComfyUI.MiniMaxH3MotionDirectorPlugin" in names
    assert len(names) >= 5, f"only found {sorted(names)} - the scan is probably broken"
