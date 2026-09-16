# Example Workflows — MiniMax H3 Motion Director

## The RefMod chain ships in every example

Every workflow here carries the same three-node RefMod group, so an example can be
switched to a mod-carried character without rebuilding it:

```
CLIP Text Encode ──conditioning──┐
                                 ├─ Apply H3 RefMod ──conditioning──▶ Director.refmod_conditioning
Load H3 RefMods ─────mods────────┘
```

`Apply H3 RefMod` appends each mod's stored reference latent to that
conditioning's `minimax_refs`. The Director harvests the payload and appends it to
**every** segment's conditioning. The `CLIP Text Encode` is a stub — the Director
builds its own conditioning per segment, so that node's text is discarded; it
exists only to satisfy a required input on `Apply H3 RefMod`.

| Example | RefMod |
|---|---|
| `ref2va + RefMod 1x4s` | **enabled** — `people/elf_girl` |
| `character replace (RefMod + SAM3) 2x5s` | **enabled** — `people/elf_girl` |
| `character replace (Faceswap Test without masking)` | **enabled** — `people/flaffy02` drives a **full-character** replace, not a face-only swap |
| `ref2va 3x7s` | bypassed — picture references carry the character |
| `t2v 5x7s - elf vs giant orc` | bypassed — the example is defined as pure prompt |
| `character replace 3x7s - elf vs giant orc` | bypassed — uploaded references carry the character |

**Enable a bypassed group with `Ctrl+B`** across its three nodes. The group is
titled `RefMod (BYPASSED - Ctrl+B to enable)` so the state of a file is obvious at
a glance, and the enabled groups keep the original
`RefMod (optional - delete to disable)` title. While bypassed the chain
contributes nothing: the run report may print

```
RefMod: refmod_conditioning is connected but supplied no reference blocks
```

That line means it harvested no payload, which is the intent — the render matches
the example as written. Delete the group to remove the input from the graph
entirely.

### Where the mods live

RefMod reads from a `refmods` model folder, **not** from this directory:

```
ComfyUI/models/refmods/people/elf_girl.safetensors
```

`example_workflows/refmods/people/elf_girl.safetensors` is a convenience copy —
place it under `models/refmods/` so the relative name `people/elf_girl` resolves,
or point `Load H3 RefMods → mod_1` at a mod of your own. The Faceswap example
points at `people/flaffy02`, which is **not** bundled here: it needs that mod on
disk or a re-point before it will run.

---

## `Minimax h3 Director - ref2va example workflow 3x7s.json`

A ready-to-run **ref2va (Reference to Video)** example: one continuous golden-hour
forest run, 3 segments × 7 s (21 s @ 24 fps). Subject 1 is an athletic elf woman
sprinting through dense forest — clearing a creek and a log, vaulting onto a high
branch, then stopping at a cliff edge to look out over the vast forest. Dynamic
cinematic camera (orbit / side-tracking / low-angle pan). No dialogue, no music —
only exertion breaths, movement grunts, clothes rustle, footfalls, and forest
ambience.

### Run it

1. Open the workflow in ComfyUI.
2. Provide the two references in the Director's **Common References** panel:
   - **Picture 1 = headshot** (`ref2va_example_assets/headshot.png`)
   - **Picture 2 = character sheet** (`ref2va_example_assets/charsheet.png`)
   The bundled images under `ref2va_example_assets/` are AI-generated placeholder
   characters (not real people) — swap in your own character if you prefer. Copy
   them into your ComfyUI `input/` folder, or upload them directly in the UI.
3. Confirm the **ImpactSwitch `select` = 2** (this routes `MODEL_2`, the H3
   **REF2VA** model path — the workflow opens with this already set).
4. **Generate** (Export mode: *Export all* → a single 21 s clip).

Requires the node pack plus the MiniMax H3 models/VAEs and the H3 REF2VA model
referenced by the workflow's model subgraph (swap the loader files to the paths
on your machine if needed).

**The RefMod group ships bypassed here.** This example's character comes from the
two picture references above, so the mod chain is present but inactive. `Ctrl+B`
on its three nodes switches identity from the pictures to
`people/elf_girl` — see
[The RefMod chain ships in every example](#the-refmod-chain-ships-in-every-example).

### Default models & downloads

Place files under your ComfyUI `models/` folder (subfolders as shown):

| Role | Place in `ComfyUI/models/…` | Download |
|---|---|---|
| REF2VA diffusion model | `diffusion_models/Minimax/10Eros_Max_h3_TURBO-hybrid_beta4_int8_convrot.safetensors` | [10Eros-Max (TenStrip)](https://huggingface.co/TenStrip/10Eros-Max/blob/main/10Eros_Max_h3_TURBO-hybrid_beta4_int8_convrot.safetensors) |
| Text encoder (uncensored) | `text_encoders/qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors` | [Qwen3-VL-32B-Heretic (sakamakismile)](https://huggingface.co/sakamakismile/Qwen3-VL-32B-Heretic-MiniMax-H3-NVFP4/blob/main/qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors) |
| Video VAE | `vae/minimax_h3_video_vae_int8_convrot.safetensors` | [Kijai / MiniMax-H3-experimental](https://huggingface.co/Kijai/MiniMax-H3-experimental/blob/main/minimax_h3_video_vae_int8_convrot.safetensors) |

Also referenced by the model subgraph: the **audio VAE** (`vae/minimax_h3_audio_vae_fp32.safetensors`, same Kijai repo) and the **REF2V turbo LoRA** applied on the ref2va path (`loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors`). The workflow also contains a top-level **Power Lora Loader**, but it is intentionally left **empty** — add your own LoRA there if you want one.

---

## `Minimax h3 Director - ref2va + RefMod example workflow 1x4s.json`

The **quick RefMod test**: a single 4 s shot (107 frames), carried entirely by a RefMod —
no headshot and no character sheet. One sprint beat through golden-hour forest, with the
same node graph, model path and settings as the full examples. Short enough to iterate on
identity in a couple of minutes instead of twenty.

The extra group of three nodes below the canvas is:

```
CLIP Text Encode ────conditioning────┐
                                     ├── Apply H3 RefMod ──conditioning──▶ Director.refmod_conditioning
Load H3 RefMods ───────mods──────────┘
```

`Apply H3 RefMod` appends each RefMod's stored reference latent to the conditioning's
`minimax_refs` — the same key the official H3 ReferenceToVideo node fills. The Director
harvests that payload and appends it to every segment's conditioning, so the mod acts as
the subject reference for the whole chain.

The workflow also ships a **MarkdownNote that is the full usage guide** — identity,
wardrobe, every setting and its reason, the failure modes, and a bisect order. This
section is the summary. For a longer story on the same setup, apply the same prompt
blocks to the other examples.

### How the reference actually reaches the model

Everything below follows from this.

- `Apply H3 RefMod` runs **after** text encoding. It writes
  `conditioning[i][1]["minimax_refs"]` and nothing else.
- **The text encoder never sees the mod.** There is no `<Picture n>` tag for it, no name
  and no label — `ref_block()` returns only `{kind, latent_h, latent_w, latent, latent_t,
  ref_audio_t, audio_latent}`.
- So the mod is an **unnamed latent blob in the DiT sequence**. It influences every frame
  of the segment, and nothing binds it to `<Subject 1>` in your text.

Two consequences: you cannot address a mod by number, and **any reference image will beat
it in an argument** (see Wardrobe below).

### Identity

The prompt names the subject, describes what she *does*, and avoids what she *looks like* —
with one deliberate exception, the identity anchor:

```
subject_definitions:
<Subject 1> is the woman in the attached character reference - a swift, athletic forest runner.
Her face, hair and build come from that reference and are not described here.
Identity lock: her face, hair and build are locked to the attached character reference and stay
identical in every frame and every shot - never a different woman.
Reference rule: the attached character reference is a static identity reference only. It never
shows her in motion, and its background, framing, panel layout and any standing pose must never
appear in the video. Every shot uses the running, leaping or balancing action described for that
shot, and all motion, camera moves and cuts are created fresh by each shot's description.
```

Why so little appearance: with no feature words anywhere in the text, the reference latent
is the only identity signal, so writing her out would hand the *text* channel an opinion to
argue with the reference about. RefMod's own guidance is to prompt subject and action rather
than appearance, and it states outright that it has **no `<Name>` trigger parser** —
`<Subject 1>` is a narrative handle for the action sentences, not a tag that resolves to
your mod.

**If the face still drifts, add 2-3 concrete words to the `Identity lock:` line** — hair
colour, ear shape, build. Feature words are what actually fight the model's own default
face; a pure "stay identical" instruction is much weaker.

The knobs, in order of effect:

| Knob | Where | Notes |
|---|---|---|
| `strength_1` | Load H3 RefMods | `1.0` = full reference (official behaviour). Lower values *blur* the reference toward a softened copy of itself and identity fades smoothly — a fade dial, not a free win. |
| `copies_1` | Load H3 RefMods | `2-3` is the documented sweet spot. Each copy costs its full token count in every DiT block. |
| `retention` | Apply H3 RefMod | Master multiplier over every `strength_N`. MiniMax levels: `1.0` fully preserved, `0.7` partial, `0.4` attribute transfer (style, not identity), `0.15` weak. |
| `curve_direction` | RefMod Step Curve | Envelope over the **denoise steps**. `concept_at_end` holds the reference at full strength in the late steps, where facial detail is set. |
| SLA `enabled` | H3SLA Attention | **Off** in this example. SLA drops ~90% of attention blocks after the first step, and a latent-only reference is the first thing to lose. |

Do not confuse the two curves: `Apply H3 RefMod`'s `curve_direction` selects **which
reference frames** dominate, while `MiniMaxH3RefModStepCurve`'s selects **which denoise
steps** receive the reference. They are different axes.

### Wardrobe: the mod carries face and body, not clothing

An empty wardrobe is expected, not a failure. The saved latent is roughly a **96 x 54
thumbnail per frame**. That is plenty to hold face structure (low frequency) and nothing
like enough to hold a garment's cut, seams or trim. The mod gives you only what it has.

**Text channel** — the `wardrobe:` section in each segment prompt:

```
wardrobe:
Her outfit is set by this description and not by the character reference: a fitted dark-teal
trail-running tank top, black compression shorts with a thin reflective stripe, and a worn
olive utility belt.
```

The mod will not fight you over this, because it is not carrying clothing at all.

**Image channel** — a clothing photograph, which arrives at full resolution through H3's
native reference path. Tag numbering is 1-based and yours to count: the first reference
image in a segment is `<Picture 1>`. **Your RefMod does not take a tag slot**, so a lone
clothing picture is always `<Picture 1>`.

```
wardrobe:
Her clothing comes from <Picture 1>. Reproduce the garment only - the same colour, fabric, cut
and length. <Picture 1> must not supply a face, hair, body shape, skin tone, background or
framing, and must not supply any other character visible in that image. The character reference
supplies her face, hair and build and must not supply clothing.
```

**A character sheet is the worst possible input**, because a character sheet *is* an identity
reference — and one with several characters on it is worse still. Expect the face, body and
pose to be taken from it. Text cannot out-argue a full-resolution identity reference. Ranked
fixes:

1. **Crop the reference to the garment alone.** No face in the picture means no face to copy.
   The only option that removes the failure instead of negotiating with it.
2. **Deliver the outfit as a second RefMod** on loader slot 2 at `strength_2` around `0.4` —
   MiniMax's documented *attribute transfer (keep style/attributes, not identity)* level —
   with identity at `strength_1 = 1.0`. Both sources are then the same kind of signal and each
   has its own weight. `MiniMaxH3RefModExtract` has a `mask` input, so the head can be masked
   out during extraction rather than cropped by hand.
3. `MiniMaxH3RefModStepCurve` at `concept_at_end` holds identity late. That tips the balance
   toward the mod but does not stop the picture's face being copied.

Refs are not bound to subjects, so an outfit mod bleeds into the face unless its `strength`
is low.

### Run it

1. Install [ComfyUI-MiniMaxH3Mod](https://github.com/Luisacaotica/ComfyUI-MiniMaxH3Mod) and
   restart ComfyUI.
2. Pick your mod in **Load H3 RefMods → `mod_1`**. The workflow ships pointing at
   `people/elf_girl`, the copy bundled here — see
   [Where the mods live](#where-the-mods-live). Swap it for your own.
3. Rewrite `Scene:` / `Style:` / `Audio:` and the shot description for your own scene, and
   keep the `subject_definitions:` block, `Identity lock:` included.
4. **Generate** — one 4 s shot, no chaining, so a full identity check is quick.

To compare against no-RefMod at all, bypass the `Apply H3 RefMod` node (`Ctrl+B`) or delete
the whole group — the Director treats a disconnected `refmod_conditioning` as a no-op.

### What to know before you judge the output

- **The connected prompt is discarded.** The Director builds its own conditioning per
  segment, so `CLIP Text Encode` exists only to satisfy `Apply H3 RefMod`'s required
  `conditioning` input. Its text, and the frame size of the conditioning it produces, are
  ignored. Put your scene prompt in the Director's segments.
- **Watch the run report.** It prints `RefMod: N reference block(s) appended to every
  segment.` If that line is missing, nothing was harvested and the output is not a RefMod
  result.
- **The bundled sample mod is a poor identity test.** `vanellope_example` is built in
  RefMod's *pooled / compressed* mode at 16 x 16, and RefMod's own docs say that mode "may
  retain colors and large structures while losing face detail, texture or useful motion." A
  run with it proves the wiring end to end; it does not prove RefMod can carry a face. Build
  your own mod in `encode` (**Full Reference**) mode for a real identity test.
- **Fast motion is RefMod's hard case.** Its README notes that a rapid sequence "gets smeared
  into something slower and softer" because the reference is only a handful of latent frames.
  This example is a sprint, so expect the mod to have the least influence on the fastest beat.
- **Single segment, so no cross-segment drift is possible here.** Once this shot holds
  identity, move to the 3 x 7 s examples — where only the first `context_length` frames of a
  segment are pinned to the previous segment's real output and the rest is free generation.
  This example carries **44**, roughly double the default, specifically to hold identity
  longer down a chain.

### Not required

`H3 RefMod Text Encode` is an alternative that outputs a plain `CONDITIONING` and reports
`<Picture n> = <mod>` labels. It decodes every visual RefMod latent through the VAE to
present it to the text encoder — work the Director then discards, since `harvest_refmod_refs()`
keeps only `minimax_refs`. That labelling therefore cannot reach the Director. `Apply H3
RefMod` does the same job here without the VAE decode; use *picture* references when you want
tags.

---

## `Minimax h3 Director - t2v example workflow 5x7s - elf vs giant orc.json`

A ready-to-run **t2v (Text to Video)** example — pure prompt, no references — in
the **updated v2 layout/config** (8-step hybrid model path, Audio Refine ON, all
cross-segment context links ON). One continuous story, 5 segments × 7 s (35 s @
24 fps, 875 frames):

> An elf woman fights a hostile giant orc the size of a ten-story building by
> climbing up his body in graceful swift motion — hopping around his legs,
> clothes and arms — as the camera cinematically follows her and changes angles.
> She reaches his head and slashes the back of his neck with her dagger; the
> giant orc falls in a huge rumbling earthshaking crash, she leaps clear at the
> last moment and lands unharmed with the dead giant orc sprawled in the shot
> behind her.

Shots: (1) establishing + dodge between his legs, (2) climb the leg to his belt,
(3) up the chest/arm to his shoulder, (4) the neck slash + the giant starts to
fall, (5) the crash, her leap clear and the aftermath. Cue-by-cue audio per beat,
no dialogue, no music.

### Run it

1. Open the workflow in ComfyUI. **No references required** — everything is
   defined in text.
2. Confirm the **ImpactSwitch `select` = 1** (this routes `MODEL_1`, the H3
   **FL2VA / T2V-I2V** model path — already set). `select = 2` switches to the
   REF2VA path, `select = 3` to the Fast-Video path (same model subgraph as the
   other examples).
3. **Generate** (Export mode: *Export all* → a single 35 s clip).

Uses the same model subgraph/VAEs as the other examples (see the default-models
table below; this file references the `beta5` hybrid build of the REF2VA path and
the FL2VA turbo 4-step path for T2V). Top-level **Power Lora Loader** is empty —
add your own LoRA if you want one.

**The RefMod group ships bypassed here**, below the graph and inactive, so this
example stays what it says it is: pure prompt, no references. Press `Ctrl+B` on
its three nodes to turn it on — worth doing if the elf's face drifts across the
five segments, which is what a chain of free generations does with a character
described only in text. See
[The RefMod chain ships in every example](#the-refmod-chain-ships-in-every-example).

---

## `Minimax h3 Director - character replace example workflow 3x7s - elf vs giant orc.json`

A ready-to-run **ref2va character-replace** example in the **updated v2
layout/config**: 3 segments × 7 s (21 s @ 24 fps, 525 frames). Your referenced
elf woman replaces the lead in a condensed version of the giant-orc fight:

1. She sprints in under the hostile giant orc and begins climbing his leg,
2. she climbs to his shoulder and slashes the back of his neck — the giant starts
   to fall,
3. he crashes to the ground in an earthshaking fall; she leaps clear and lands
   unharmed with the dead giant orc sprawled behind her.

### Run it

1. Open the workflow in ComfyUI.
2. Provide the two references in the Director's **Common References** panel
   (Picture 1 = headshot, Picture 2 = character sheet — the same bundled
   `ref2va_example_assets/headshot.png` / `charsheet.png` work as placeholder
   elves; swap in your own character if you prefer).
3. Confirm the **ImpactSwitch `select` = 2** (the H3 **REF2VA** model path —
   already set).
4. **Generate** (Export mode: *Export all* → a single 21 s clip).

Identical model subgraph, VAE and audio-refine setup to the t2v example; top-level
**Power Lora Loader** is empty — add your own LoRA if you want one.

**The RefMod group ships bypassed here.** The replaced performer is carried by the
uploaded references in step 2, so the mod chain is present but inactive. `Ctrl+B`
on its three nodes hands identity to `people/elf_girl` instead — see
[The RefMod chain ships in every example](#the-refmod-chain-ships-in-every-example).

---

## `Minimax h3 Director - character replace (RefMod + SAM3) example workflow 2x5s.json`

The **replace-mode** example. Where the section above recasts the performer through
prompt-level ref2va, this one uses the Director's actual **Character Replace** feature:
the timeline is set to **Replace: ON** and the render runs `rv2v` windows whose subject
region is masked, so the new performer is drawn into the source footage itself.

Two 5.17 s windows (0-124 and 124-248 frames at 24 fps) cover the source; identity comes
from **RefMod** (no picture refs are attached).

### What is preconfigured

- timeline mode `video`, task `rv2v`, Replace ON, `replaceMode` set on the timeline.
- Per window: `enabled: true`, `render: anchor`, `audio_policy: source`, `lead: 12`,
  `grow: 1`, `feather: 1`, mask `kind: sam3` with `sam_prompts: ["the woman"]`.
- `wardrobe` and identity paragraphs are written for the RefMod path already (the prompt
  template from the prompt-writing guide, including the "no rooms from the reference"
  rule).

### Run it

1. Drop your source video into `ComfyUI/input` and set it as the timeline **Source Video**
   (`character_replace_source_example.mp4` is only a placeholder).
2. `Load H3 RefMods` slot 1 = your character mod, `strength_1` 1.0, `copies_1` 1. Keep the
   mod images cropped to the person - rooms and furniture in the reference leak into the
   render as content.
3. Open the replace windows editor, click **Test mask** on window 1 and **pick the subject
   with click points**. Text-only SAM3 is unreliable; the `the woman` prompt is only a
   fallback. Copy the points to window 2.
4. **Generate**. Watch the console: `Character Replace FELL BACK to plain RV2V` means the
   mask failed for that window and it will render as an unmasked regeneration (whole scene
   redrawn, original performer may remain) - fix the mask before judging the output.

### Notes

- `anchor` re-renders the whole frame; the mask removes the old identity, it does not
  freeze the background (use `inpaint` if pixel-exact background matters more than
  identity).
- `audio_policy: source` keeps the original track for the window (sample-rate handling
  fixed - the passthrough track is no longer slowed down).
- The **Perf** section's `verbose_logging` prints the pack's DEBUG diagnostics for a run;
  `MINIMAX_DIRECTOR_VERBOSE=1/0` forces it on or off server-wide.
