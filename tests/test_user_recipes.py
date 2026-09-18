# MiniMax H3 Motion Director - user-authored prompt recipes.
# Copyright (C) 2026 WakaSoft. GPL-3.0. See LICENSE.

"""Your own recipes, in a file a pack update cannot overwrite.

The pack's recipes are Python constants: right for the shapes the guide defines,
useless for anything of your own, because an update replaces them and there is nowhere
to put an edit. These tests pin the file that fixes that - what it accepts, what it
refuses, how a user recipe borrows a built-in's assembly in caption mode, and that Auto
still behaves the way it did for everyone who never opens the file.

They also keep ``recipe_templates/`` honest: the starters a user copies must show the
block text the pack actually uses, or the first thing they edit from is already stale.
"""

from __future__ import annotations

import json

import pytest

from mmx_pkg.lib.h3_prompt_recipes import (
    RECIPES,
    RECIPE_BY_KEY,
    RECIPE_KEYS,
    all_recipe_keys,
    assembly_key,
    recipe_block,
    recipe_options,
    resolve_recipe,
    user_recipe_problems,
    user_recipes,
)
from mmx_pkg.lib import h3_user_recipes


def _write(tmp_path, payload) -> str:
    """Write a recipes file where the autouse fixture points the loader."""
    path = tmp_path / "recipes.json"
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    h3_user_recipes.reset_cache()
    return str(path)


def _entry(**overrides) -> dict:
    entry = {
        "key": "my_replace",
        "label": "My replace",
        "based_on": "character_replace",
        "block": "Shape the answer as my own replace window.",
    }
    entry.update(overrides)
    return entry


# --- the file itself ---------------------------------------------------------


def test_no_file_is_not_an_error(tmp_path):
    assert user_recipes() == []
    assert user_recipe_problems() == []
    assert [o["key"] for o in recipe_options()] == list(RECIPE_KEYS)


def test_a_recipe_joins_the_list_the_dropdown_uses(tmp_path, monkeypatch):
    monkeypatch.setenv("MMX_H3_USER_RECIPES", _write(tmp_path, {"version": 1, "recipes": [_entry()]}))
    recipes = user_recipes()
    assert [r.key for r in recipes] == ["my_replace"]
    assert recipes[0].source == "user"
    assert recipes[0].based_on == "character_replace"
    # Inherited from the parent, because the entry does not set them.
    assert recipes[0].tasks == RECIPE_BY_KEY["character_replace"].tasks
    assert recipes[0].needs_source is True
    assert recipes[0].auto is False, "a new recipe must not take over Auto by itself"

    options = recipe_options()
    assert [o["key"] for o in options] == list(RECIPE_KEYS) + ["my_replace"]
    mine = options[-1]
    assert mine["source"] == "user" and mine["label"] == "My replace"


def test_an_edit_is_picked_up_without_a_restart(tmp_path, monkeypatch):
    path = _write(tmp_path, {"version": 1, "recipes": [_entry(block="first")]})
    monkeypatch.setenv("MMX_H3_USER_RECIPES", path)
    assert recipe_block("my_replace") == "first"

    # Same path, new content: the loader caches by file stamp, so the next read sees it.
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"version": 1, "recipes": [_entry(block="second")]}, handle)
    assert recipe_block("my_replace") == "second"


def test_a_block_is_inherited_when_it_is_left_out(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "MMX_H3_USER_RECIPES",
        _write(tmp_path, {"version": 1, "recipes": [_entry(block=None)]}),
    )
    assert recipe_block("my_replace") == RECIPE_BY_KEY["character_replace"].block


def test_an_override_of_tasks_and_auto_is_honoured(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "MMX_H3_USER_RECIPES",
        _write(
            tmp_path,
            {
                "version": 1,
                "recipes": [
                    _entry(key="my_t2v", based_on="text_only", tasks=["t2v"], needs_source=False, auto=True)
                ],
            },
        ),
    )
    mine = user_recipes()[0]
    assert mine.tasks == ("t2v",) and mine.auto is True
    # Opted in, so it beats the built-in for that task.
    assert resolve_recipe("auto", task_key="t2v") == "my_t2v"


def test_a_key_the_pack_uses_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "MMX_H3_USER_RECIPES",
        _write(tmp_path, {"version": 1, "recipes": [_entry(key="character_replace")]}),
    )
    assert user_recipes() == []
    problems = user_recipe_problems()
    assert len(problems) == 1 and "one of the pack's own recipes" in problems[0]


def test_an_unknown_based_on_is_refused_with_the_options(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "MMX_H3_USER_RECIPES",
        _write(tmp_path, {"version": 1, "recipes": [_entry(based_on="my_own_shape")]}),
    )
    assert user_recipes() == []
    problem = user_recipe_problems()[0]
    assert "based_on 'my_own_shape'" in problem
    assert "character_replace" in problem, "say what may be used instead"


def test_broken_json_reports_the_position(tmp_path, monkeypatch):
    monkeypatch.setenv("MMX_H3_USER_RECIPES", _write(tmp_path, '{"recipes": [ {, ]}'))
    problems = user_recipe_problems()
    assert problems and "not valid JSON" in problems[0]
    assert "recipes.json" in problems[0], "name the file"


def test_a_bad_entry_does_not_take_the_good_ones_with_it(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "MMX_H3_USER_RECIPES",
        _write(
            tmp_path,
            {
                "version": 1,
                "recipes": [
                    _entry(key="my_good"),
                    {"label": "no key at all"},
                    _entry(key="my_other", block="second"),
                ],
            },
        ),
    )
    assert [r.key for r in user_recipes()] == ["my_good", "my_other"]
    assert len(user_recipe_problems()) == 1


def test_duplicate_keys_are_reported(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "MMX_H3_USER_RECIPES",
        _write(tmp_path, {"version": 1, "recipes": [_entry(), _entry()]}),
    )
    assert len(user_recipes()) == 1
    assert "appears twice" in user_recipe_problems()[0]


def test_a_bare_list_is_accepted(tmp_path, monkeypatch):
    """Some editors make it easy to end up with just the array."""
    monkeypatch.setenv("MMX_H3_USER_RECIPES", _write(tmp_path, [_entry()]))
    assert [r.key for r in user_recipes()] == ["my_replace"]


# --- how it behaves in a request ---------------------------------------------


def test_choosing_one_by_name_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("MMX_H3_USER_RECIPES", _write(tmp_path, {"version": 1, "recipes": [_entry()]}))
    assert resolve_recipe("my_replace", task_key="t2v") == "my_replace"
    # Case is forgiven, the way the built-in keys forgive it.
    assert resolve_recipe("MY_REPLACE", task_key="t2v") == "my_replace"


def test_auto_ignores_a_recipe_that_did_not_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv("MMX_H3_USER_RECIPES", _write(tmp_path, {"version": 1, "recipes": [_entry()]}))
    # Same tasks as character_replace, but not opted in: Auto keeps choosing the pack's.
    assert resolve_recipe("auto", task_key="rv2v", has_source=True) == "character_replace"
    assert resolve_recipe("auto", task_key="r2v") == "ref2va"


def test_the_assembly_mapping_follows_based_on(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "MMX_H3_USER_RECIPES",
        _write(
            tmp_path,
            {
                "version": 1,
                "recipes": [
                    _entry(key="my_replace"),
                    _entry(key="my_free", based_on="", block="free-standing"),
                ],
            },
        ),
    )
    assert assembly_key("my_replace") == "character_replace"
    # No parent: nothing in the pack knows how to assemble it, so the caller keeps
    # the rewrite path and says so.
    assert assembly_key("my_free") == ""


def test_a_recipe_without_a_parent_still_works_in_rewrite_mode(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "MMX_H3_USER_RECIPES",
        _write(tmp_path, {"version": 1, "recipes": [_entry(key="my_free", based_on="", block="free")]}),
    )
    assert recipe_block("my_free") == "free"
    assert resolve_recipe("my_free") == "my_free"


def test_all_keys_puts_the_packs_first(tmp_path, monkeypatch):
    monkeypatch.setenv("MMX_H3_USER_RECIPES", _write(tmp_path, {"version": 1, "recipes": [_entry()]}))
    keys = all_recipe_keys()
    assert keys[: len(RECIPE_KEYS)] == RECIPE_KEYS
    assert keys[-1] == "my_replace"


# --- the shipped templates ----------------------------------------------------


def test_every_shape_has_a_starter_file():
    from mmx_pkg.lib.h3_user_recipes import template_files

    names = {path.name for path in template_files()}
    expected = {f"{recipe.key}.json" for recipe in RECIPES if recipe.key != "auto"}
    assert names == expected
    assert (h3_user_recipes.templates_dir() / "README.md").is_file()


@pytest.mark.parametrize("recipe", [r for r in RECIPES if r.key != "auto"], ids=lambda r: r.key)
def test_the_starter_shows_the_block_the_pack_uses(recipe):
    """A template with an old block is worse than no template: it is what gets edited."""
    path = h3_user_recipes.templates_dir() / f"{recipe.key}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    entry = payload["recipes"][0]
    assert entry["based_on"] == recipe.key
    assert entry["block"] == recipe.block, "regenerate: python scripts/generate_recipe_templates.py"
    assert entry["key"] != recipe.key, "a starter must not collide with the pack's key"
    assert entry["auto"] is False


def test_a_starter_survives_the_loader_unchanged(tmp_path, monkeypatch):
    """Drop a template in as-is and it is a working recipe, not just valid JSON."""
    template = json.loads(
        (h3_user_recipes.templates_dir() / "character_replace.json").read_text(encoding="utf-8")
    )
    monkeypatch.setenv("MMX_H3_USER_RECIPES", _write(tmp_path, template))
    assert user_recipe_problems() == []
    mine = user_recipes()[0]
    assert mine.key == "my_character_replace"
    assert mine.based_on == "character_replace"
    assert mine.tasks == RECIPE_BY_KEY["character_replace"].tasks
    assert assembly_key(mine.key) == "character_replace"
