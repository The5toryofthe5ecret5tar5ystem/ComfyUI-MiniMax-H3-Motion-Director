"""Prompt recipes: the target shape the enhancer must produce for each job.

The enhancer used to wrap every task in MiniMax's official template, whose only
output contract is "editing instruction + detailed description, one paragraph".
A live character-replace run came back with no discard sentence, no role lines and
no window opener - correct for that template, useless for the node.

These tests pin the resolution rules (Auto must never surprise existing users) and
that every recipe says the replace-critical things where they matter.
"""

from __future__ import annotations

import pytest

from mmx_pkg.lib.h3_prompt_recipes import (
    RECIPES,
    RECIPE_KEYS,
    normalize_recipe,
    recipe_block,
    recipe_options,
    resolve_recipe,
)
from mmx_pkg.lib.h3_prompt_rules import build_h3_enhance_rules


def test_recipe_keys_are_unique_and_options_match():
    assert len(RECIPE_KEYS) == len(set(RECIPE_KEYS))
    options = recipe_options()
    assert [o["key"] for o in options] == list(RECIPE_KEYS)
    assert all(o["label"] for o in options)


def test_every_named_recipe_has_a_block():
    for recipe in RECIPES:
        if recipe.key == "auto":
            assert recipe.block == "", "auto is a selector, not a shape"
            continue
        assert recipe.block, f"{recipe.key} has no instructions"
        assert len(recipe.block) > 200, f"{recipe.key} block is too thin to guide a model"


def test_auto_picks_by_task():
    assert resolve_recipe("auto", task_key="r2v") == "ref2va"
    assert resolve_recipe("", task_key="i2v") == "start_image"
    assert resolve_recipe("", task_key="fl2v") == "first_last"
    assert resolve_recipe("", task_key="t2v") == "text_only"
    # rv2v is both the reference-segment task and the replace task; the shape
    # differs, so a source video (or an explicit replace call) decides. Without a
    # source it is not a replace window, and rv2v has no non-replace recipe - the
    # official template is the safe answer.
    assert resolve_recipe("auto", task_key="rv2v", has_source=False) == "official"
    assert resolve_recipe("auto", task_key="rv2v", has_source=True) == "character_replace"
    assert resolve_recipe("auto", task_key="v2v", has_source=True, replace=True) == "character_replace"
    # mv2v is this pack's alias of v2v (prompt_enhance_templates._TEMPLATE_ALIASES,
    # and the timeline shows both with the same prompt-only style), so it must resolve
    # exactly like v2v - otherwise the same timeline renders under the wrong shape.
    assert resolve_recipe("auto", task_key="mv2v", has_source=True) == "character_replace"
    assert resolve_recipe("auto", task_key="mv2v", has_source=True, replace=True) == "character_replace"
    assert resolve_recipe("auto", task_key="mv2v", has_source=False) == "official"


def test_unknown_task_and_unknown_recipe_fall_back_to_official():
    assert resolve_recipe("auto", task_key="mixed") == "official"
    assert resolve_recipe("nonsense", task_key="r2v") == "ref2va", "a bad value behaves like auto"
    assert normalize_recipe("NONSENSE") == ""
    assert normalize_recipe("character_replace") == "character_replace"


def test_an_explicit_recipe_always_wins():
    """The dropdown is the user's override, including against the task's default."""
    assert resolve_recipe("character_replace_refmod", task_key="r2v") == "character_replace_refmod"
    assert resolve_recipe("text_only", task_key="rv2v", has_source=True) == "text_only"
    assert resolve_recipe("official", task_key="r2v") == "official"


def test_replace_recipe_block_joins_the_contract():
    rules = build_h3_enhance_rules("rv2v", has_source=True, recipe="character_replace")
    flat = " ".join(rules.split())
    assert "DIFFERENT, unrelated woman" in flat
    # Shape from the recipe...
    assert "Shape the answer as this pack's character-replace window" in flat
    # ...and the universal replace contract is still present beside it.
    assert "This is a replace window: source footage is being edited" in flat
    assert "write it if the input does not" in flat


def test_refmod_recipe_forbids_appearance_prose():
    rules = build_h3_enhance_rules("rv2v", has_source=True, recipe="character_replace_refmod")
    flat = " ".join(rules.split())
    assert "carried by the attached character reference" in flat
    assert "Never describe her face, hair or body in prose" in flat
    assert "Do not invent a `<Picture N>` tag for the mod" in flat


def test_recipe_choice_changes_the_requested_shape():
    ref = " ".join(build_h3_enhance_rules("rv2v", has_source=True, recipe="ref2va").split())
    rep = " ".join(build_h3_enhance_rules("rv2v", has_source=True, recipe="character_replace").split())
    assert "Shape the answer as this pack's r2v / ref2va segment block" in ref
    assert "Shape the answer as this pack's character-replace window" in rep
    assert ref != rep


def test_official_recipe_leaves_the_shape_alone_but_keeps_the_contract():
    rules = build_h3_enhance_rules("r2v", recipe="official")
    flat = " ".join(rules.split())
    assert "Shape the answer as the calling task's own MiniMax template" in flat
    # The engine contract is still attached: recipes are shape, not safety.
    assert "Reference slots are bindings" in flat
    assert "Beats" in flat


@pytest.mark.parametrize("key", [k for k in RECIPE_KEYS if k not in ("auto", "official")])
def test_recipe_blocks_never_use_em_dashes(key):
    block = recipe_block(key)
    assert "\u2014" not in block, key
    assert "\u2013" not in block, key
