# MiniMax H3 Motion Director - user-authored prompt recipes.
# Copyright (C) 2026 WakaSoft. GPL-3.0. See LICENSE.

"""Prompt recipes you can edit, kept where a pack update cannot overwrite them.

The recipes that ship with the pack are Python constants (`h3_prompt_recipes`), which
is right for the shapes the guide defines and wrong for anything of your own: an
update replaces them, and there is nowhere to put an edit. This module reads a JSON
file from the ComfyUI user directory instead - the one directory a pack update never
touches - and merges those recipes into the same list the panel's dropdown is built
from. Editing the file is enough; the list is re-read when it changes, so the panel
picks a change up on its next open.

File: ``<ComfyUI user dir>/minimax_h3_motion_director/recipes.json``

    {
      "version": 1,
      "recipes": [
        {
          "key": "my_pov_replace",
          "label": "My POV replace",
          "summary": "Shown as the dropdown tooltip.",
          "based_on": "character_replace",
          "block": "Shape the answer as ...",
          "tasks": ["rv2v", "v2v"],
          "needs_source": true,
          "auto": false
        }
      ]
    }

A user recipe is a *variant of a built-in*: `based_on` names one of the pack's
recipes, which supplies the assembly used by ``Build from images`` (that part is
code, not text) and the inherited `tasks` / `needs_source` / `block`. Everything is
optional except `key` and `label`; `block` is what you override to change the shape
instruction the enhancer sends in rewrite mode.

Templates for every type live in ``recipe_templates/`` at the pack root - copy one
into the file above and edit it. A broken file never breaks the pack: the problems
are collected and shown in the panel next to the dropdown.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.lib")

_USER_DIRNAME = "minimax_h3_motion_director"
_RECIPES_FILENAME = "recipes.json"
_TEMPLATES_DIRNAME = "recipe_templates"

# Keys are chosen by the user and travel in requests, so they stay in the shape the
# built-ins use; `key` can never be a path component here, but a boring alphabet
# keeps a typo from producing a key nothing else can match.
_SAFE_KEY = re.compile(r"^[A-Za-z0-9_-]{2,64}$")

_LABEL_MAX = 120
_SUMMARY_MAX = 600
# A shape instruction is a page of prose. This is generous for one and small enough
# that a stray paste of a whole prompt cannot fill the user directory.
_BLOCK_MAX = 40_000
_MAX_RECIPES = 50


@dataclass(frozen=True)
class UserRecipe:
    """One recipe from the user's file, with its problems already resolved away."""

    key: str
    label: str
    based_on: str
    summary: str = ""
    block: str = ""
    tasks: tuple[str, ...] = ()
    needs_source: bool = False
    auto: bool = False
    overrides: tuple[str, ...] = field(default_factory=tuple)


# (path, mtime, size) of the last read, plus what it produced. The panel asks for the
# list every time it opens, and re-parsing a file that has not changed is pointless.
_cache: dict = {"stamp": None, "recipes": [], "errors": []}


def user_directory() -> Path:
    """ComfyUI's user directory, resolved the way the pack's other stores do."""
    try:
        import folder_paths  # type: ignore
    except Exception:  # pragma: no cover - importable outside ComfyUI
        folder_paths = None

    getter = getattr(folder_paths, "get_user_directory", None)
    if callable(getter):
        try:
            value = getter()
            if value:
                return Path(value)
        except Exception:
            pass
    value = getattr(folder_paths, "user_directory", None)
    if value:
        return Path(value)
    base = getattr(folder_paths, "base_path", None)
    return Path(base or os.getcwd()) / "user"


def recipes_path() -> Path:
    """The file the panel tells the user to edit."""
    override = str(os.environ.get("MMX_H3_USER_RECIPES") or "").strip()
    if override:
        return Path(override).expanduser()
    return user_directory() / _USER_DIRNAME / _RECIPES_FILENAME


def templates_dir() -> Path:
    """The shipped per-type templates, at the pack root."""
    return Path(__file__).resolve().parent.parent / _TEMPLATES_DIRNAME


def template_files() -> list[Path]:
    try:
        return sorted(path for path in templates_dir().glob("*.json") if path.is_file())
    except OSError:
        return []


def _clean_text(value, limit: int) -> str:
    text = " ".join(str(value or "").replace("\x00", "").split())
    return text[:limit]


def _clean_block(value) -> str:
    """A shape instruction keeps its own line breaks; only the size is bounded."""
    text = str(value or "").replace("\x00", "").strip()
    return text[:_BLOCK_MAX]


def _parse_entry(raw, builtin_keys: frozenset[str], errors: list[str], index: int) -> UserRecipe | None:
    where = f"recipes[{index}]"
    if not isinstance(raw, dict):
        errors.append(f"{where}: expected an object")
        return None

    key = str(raw.get("key") or "").strip()
    if not key:
        errors.append(f"{where}: 'key' is missing")
        return None
    if not _SAFE_KEY.match(key):
        errors.append(f"{where}: key '{key}' must be 2-64 characters of A-Z a-z 0-9 _ -")
        return None
    if key in builtin_keys:
        errors.append(
            f"{where}: key '{key}' is one of the pack's own recipes - pick another name"
        )
        return None

    label = _clean_text(raw.get("label"), _LABEL_MAX) or key
    based_on = str(raw.get("based_on") or "").strip()
    if based_on and based_on not in builtin_keys:
        errors.append(
            f"{where}: based_on '{based_on}' is not a recipe of this pack - leave it "
            "out for a free-standing recipe, or use one of: "
            + ", ".join(sorted(builtin_keys))
        )
        return None

    overrides: list[str] = []
    tasks: tuple[str, ...] = ()
    if raw.get("tasks") is not None:
        value = raw.get("tasks")
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            errors.append(f"{where}: 'tasks' must be a list of task keys")
            return None
        tasks = tuple(str(item).strip().lower() for item in value if str(item).strip())
        overrides.append("tasks")

    needs_source = False
    if raw.get("needs_source") is not None:
        needs_source = bool(raw.get("needs_source"))
        overrides.append("needs_source")

    if raw.get("block") is not None:
        overrides.append("block")

    return UserRecipe(
        key=key,
        label=label,
        based_on=based_on,
        summary=_clean_text(raw.get("summary"), _SUMMARY_MAX),
        block=_clean_block(raw.get("block")),
        tasks=tasks,
        needs_source=needs_source,
        auto=bool(raw.get("auto")),
        overrides=tuple(overrides),
    )


def _read(path: Path, builtin_keys: frozenset[str]) -> tuple[list[UserRecipe], list[str]]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], []
    except OSError as exc:
        return [], [f"{path}: {exc}"]

    if not raw.strip():
        return [], []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [], [f"{path.name}: not valid JSON ({exc.lineno}:{exc.colno} {exc.msg})"]

    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        entries = data.get("recipes")
    else:
        entries = None
    if not isinstance(entries, list):
        return [], [f"{path.name}: expected a 'recipes' list"]

    errors: list[str] = []
    recipes: list[UserRecipe] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries[:_MAX_RECIPES]):
        recipe = _parse_entry(entry, builtin_keys, errors, index)
        if recipe is None:
            continue
        if recipe.key in seen:
            errors.append(f"recipes[{index}]: key '{recipe.key}' appears twice")
            continue
        seen.add(recipe.key)
        recipes.append(recipe)
    if len(entries) > _MAX_RECIPES:
        errors.append(f"only the first {_MAX_RECIPES} recipes are read")
    return recipes, errors


def load_user_recipes(builtin_keys: frozenset[str], *, refresh: bool = False) -> tuple[list[UserRecipe], list[str]]:
    """The user's recipes and any problems in their file.

    Re-reads only when the file changed, so a running ComfyUI picks up an edit on the
    next panel open without a restart.
    """
    path = recipes_path()
    try:
        stat = path.stat()
        stamp = (str(path), stat.st_mtime_ns, stat.st_size)
    except OSError:
        stamp = (str(path), None, None)

    if not refresh and _cache["stamp"] == stamp:
        return list(_cache["recipes"]), list(_cache["errors"])

    recipes, errors = _read(path, builtin_keys)
    if recipes or errors:
        log.info("User recipes: %d loaded from %s", len(recipes), path)
    for problem in errors:
        log.warning("User recipes: %s", problem)

    _cache.update({"stamp": stamp, "recipes": recipes, "errors": errors})
    return recipes, errors


def reset_cache() -> None:
    """Test hook: forget the last read."""
    _cache.update({"stamp": None, "recipes": [], "errors": []})
