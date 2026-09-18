#!/usr/bin/env python3
"""Write one starter file per recipe type into ``recipe_templates/``.

The templates exist so a user can copy a working recipe into their own
``recipes.json`` and edit it, instead of writing a shape instruction from nothing.
They are generated from ``lib/h3_prompt_recipes.py`` rather than kept by hand: a
template that still shows an old block after the guide changed is worse than none.
``tests/test_user_recipes.py`` fails when the files and the code disagree, so run
this after editing a built-in recipe:

    python scripts/generate_recipe_templates.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib.h3_prompt_recipes import RECIPES  # noqa: E402

TEMPLATES_DIR = REPO_ROOT / "recipe_templates"

# Only the recipes that ask the model for a shape. "auto" is a selector, not a
# shape, so it has nothing to copy.
SKIP_KEYS = {"auto"}

_README = (
    "Starter file for the '{label}' recipe. Copy the entry into your own "
    "recipes.json - the prompt-enhancer panel shows the exact path on every "
    "machine - then edit it. 'key' must be a name the pack does not already use, "
    "'label' is what the dropdown shows, and 'block' is the shape instruction the "
    "enhancer sends. Anything you delete is inherited from 'based_on'."
)


def template_entries() -> list[tuple[str, dict]]:
    files: list[tuple[str, dict]] = []
    for recipe in RECIPES:
        if recipe.key in SKIP_KEYS:
            continue
        payload = {
            "version": 1,
            "_readme": _README.format(label=recipe.label),
            "recipes": [
                {
                    "key": f"my_{recipe.key}",
                    "label": f"My {recipe.label}",
                    "summary": recipe.summary,
                    "based_on": recipe.key,
                    # Off by default: a recipe being written should not take over
                    # Auto until its author says so.
                    "auto": False,
                    "block": recipe.block,
                }
            ],
        }
        files.append((f"{recipe.key}.json", payload))
    return files


def main() -> int:
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in template_entries():
        path = TEMPLATES_DIR / name
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
