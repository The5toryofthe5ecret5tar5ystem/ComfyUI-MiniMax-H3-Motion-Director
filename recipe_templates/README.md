# Your own prompt recipes

The prompt enhancer has a **Recipe** dropdown that decides the *shape* of the answer it
asks for. The pack ships nine of them; this folder gives you one starter file per shape
so you can write your own.

## Where your recipes live

```
<ComfyUI>/user/minimax_h3_motion_director/recipes.json
```

That is ComfyUI's user directory, so a pack update never touches it (the built-in
recipes are code and *are* replaced by an update — yours are not). The enhancer panel
shows the exact path for your machine above the dropdown. Override it with the
`MMX_H3_USER_RECIPES` environment variable if you keep your ComfyUI user files
somewhere else.

Create the file if it is not there yet:

```json
{ "version": 1, "recipes": [] }
```

## Making one

1. Open the starter file for the shape you want (see the list below).
2. Copy its single entry into the `recipes` list in your `recipes.json`.
3. Give it a new `key` and a `label` you will recognise, then edit `block`.

```json
{
  "version": 1,
  "recipes": [
    {
      "key": "my_pov_replace",
      "label": "My POV replace",
      "summary": "Shown as the dropdown tooltip.",
      "based_on": "character_replace",
      "auto": false,
      "block": "Shape the answer as ..."
    }
  ]
}
```

| Field | Required | What it does |
|---|---|---|
| `key` | yes | The name the panel sends. 2–64 characters of `A-Z a-z 0-9 _ -`, and it must not be one of the pack's own keys. |
| `label` | yes | What the dropdown shows. |
| `summary` | no | The tooltip under the dropdown. Inherited from `based_on` when omitted. |
| `based_on` | no | A built-in recipe this one is a variant of. It supplies everything you leave out — including the block itself — and, in `Build from images` mode, the assembly (see below). |
| `block` | no | The shape instruction the enhancer sends to the model in rewrite mode. Omit it to inherit the built-in's, which makes the entry a relabelled copy to edit later. |
| `tasks` | no | Task keys this recipe is the automatic choice for (`r2v`, `i2v`, `fl2v`, `v2v`, `rv2v`, `t2v`). Inherited when omitted. |
| `needs_source` | no | Require a source video before this recipe may be picked automatically. Inherited when omitted. |
| `auto` | no | `true` lets **Auto** pick this recipe for its `tasks`. Default `false`: a recipe you are still writing must not take over Auto. |

## Starters in this folder

| File | Based on | The shape |
|---|---|---|
| `ref2va.json` | `ref2va` | Reference segment: `subject_definitions` with slot roles, Camera, Scene, Audio, summary, `detailed_description`. |
| `character_replace.json` | `character_replace` | Replace window with `<Picture N>` references: discard sentence, role lines, wardrobe, window opener. |
| `character_replace_refmod.json` | `character_replace_refmod` | Replace window whose identity arrives from a RefMod: no appearance prose, no `<Picture N>` tag. |
| `source_edit.json` | `source_edit` | One change to the source window, everything else stated as unchanged. |
| `start_image.json` | `start_image` | Begin from the supplied first frame, describe the action forward. |
| `first_last.json` | `first_last` | Both frames fixed; describe only the motion between them. |
| `text_only.json` | `text_only` | Nothing supplied, so the prose carries the whole scene. |
| `official.json` | `official` | Leave the shape to MiniMax's own task template. |

These files are generated from the pack's recipes (`scripts/generate_recipe_templates.py`),
so the block text in them is the block text the pack actually uses today. A test fails
if the two drift apart.

## Rewrite mode and `Build from images` are not the same

- **Rewrite mode** sends your `block` to the model as the target shape. This is where a
  custom block has full effect.
- **`Build from images`** (`captions`) assembles the block in *code* from vision
  captions: the section order, the role lines, the discard sentence and the audio
  policy are written by the pack, not by a model. A user recipe there borrows the
  assembly of its `based_on` — so a variant of `character_replace` builds exactly like
  `character_replace`, with your captions. A recipe with no `based_on` has no assembly,
  so the panel falls back to rewrite mode and tells you.

## When something is wrong

A broken `recipes.json` never breaks the pack: the problems are collected and shown in
the panel next to the dropdown (a bad key, a duplicate, invalid JSON, a `based_on` that
is not a recipe). Fix the file and reopen the panel — it is re-read whenever the file's
timestamp changes, so no ComfyUI restart is needed for a recipe edit.
