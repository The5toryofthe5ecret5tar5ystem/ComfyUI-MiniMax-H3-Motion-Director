# Motion Director - Prompt Writing Guide (r2v / ref2va + Character Replace)

Purpose: a single, current reference for writing MiniMax H3 Motion Director prompts.
Use it to author new `Director - pov-*.json` workflows, or to have an AI write them.
Applies to the **r2v (reference-to-video / ref2va)** mode and to **Character Replace** windows.

Companion files:
- `README.md` (this folder) - which reference slot each plan still needs attached.
- `docs/USER_GUIDE.md` in the pack repo - what each UI control does (not prompt prose).
- `chain/minimax-h3-prompting-reference.md` - the older Contex Loop chain doc. The section
  vocabulary below supersedes it for Motion Director work.

---

## 1. Where the prompts actually live

A Motion Director workflow is a ComfyUI workflow JSON. The whole project is ONE
`timeline_data` JSON string mirrored in three places. When you edit a file, keep all
three in sync:

1. `widgets_values[11]`
2. `widgets_values_named["timeline_data"]`
3. `properties.mmx_director_widget_state["timeline_data"]`

`timeline_data` top-level keys (observed on the "v2 - 3 REAUTHOR" files):

```text
version, editMode, totalFrames, frameRate, width, height, refMaxSize,
output, videoClips, video, global, segments, gen, runSelectEnabled,
runSelection, liveTaePreview, timelineMode, seedMode, r2vCommon, audioRoles
```

- `global` (the global prompt) is **empty** on the current files. Every segment carries
  its own full prompt block. This is intentional - see section 4.
- `r2vCommon` holds the Common References auto-applied to every segment.
- `segments[]` holds the shot list.

### Segment object

```text
id, start, length, frameCount, durationSec, prompt, negativePrompt,
taskType, refs, refAudios, refVideos, genImage, contextLink
```

- `start` is in **frames**; `frameCount`/`length` snap to the H3-valid grid
  (`frameCount % 17 == 5`, e.g. 124, 141, 243, 260, 277, 362, 719).
- `negativePrompt` stays empty (H3 is CFG-distilled - no negative).
- `taskType` is empty for r2v segments (mode is set at the job level).
- `contextLink` is `{schema: "previous_context_link_v1", enabled: false, visual: false, audio: false}`.
  Cross-segment continuity is handled by **Motion Context**, not by the Contex Loop
  `<Picture 0>` mechanism.

### Common References (`r2vCommon`)

```json
{
  "refs": [
    {"index": 0, "imageFile": "<face>.png", "type": "input", "subfolder": ""},
    {"index": 1, "imageFile": "<charsheet>.png", "type": "input", "subfolder": ""}
  ],
  "refAudios": [
    {"index": 0, "audioFile": "<voice>.wav", "type": "input", "subfolder": ""}
  ],
  "refVideos": []
}
```

Reference slot numbering: `refs[N-1]` is `<Picture N>`, `refAudios[N-1]` is `<Audio N>`,
`refVideos[N-1]` is `<Video N>`. Hard limits: 9 pictures, 3 videos, 3 audios.

---

## 2. Reference slot map (fixed roles)

| Slot | Role | What it may define | What it must NOT define |
|---|---|---|---|
| `<Picture 1>` | headshot | facial identity: face, skin tone, hair, expressions | pose, framing, angle |
| `<Picture 2>` | full-body character sheet | body shape, proportions, clothing, fit | the sheet's grid, standing poses, layout |
| `<Picture 3>` | scene / location photo | layout, key props, lighting, atmosphere | any person's identity |
| `<Picture 4..9>` | extra refs (second subject, props) | as declared in `subject_definitions` | anything undeclared |
| `<Video 0>` | motion-only reference | abstract technique / rhythm only | visual reproduction |
| `<Audio 1>` | Subject 1 voice | timbre, tone, delivery | the words (never its words) |
| `<Audio 2+>` | extra audio (ASMR, scene tone) | as declared | as declared |

Every reference used in a prompt must be **defined** in `subject_definitions` (its role
and its exclusions). Unused slots are bypassed - do not reference a slot you are not
attaching a file to, or the UI shows a missing-asset note.

---

## 3. The r2v segment prompt template

Each segment repeats the SAME three sections in this order. Copy this skeleton and fill
the placeholders:

```text
subject_definitions:
<Subject 1> is <identity line: who she is in this scene, incl. consent framing if CNC>.
<Picture 1> (headshot) is the sole source of her facial identity: her face, skin tone, hair and expressions. Static portrait - never copy its pose, framing or angle; use it for her face only.
<Picture 2> (full-body character sheet) is the sole source of her body shape, proportions, clothing and fit. Proportions and clothing ONLY - never reproduce the sheet's grid, standing poses or layout.
<Picture 3> (the <location>) is the sole source of its layout, <key props> and the <lighting>. Layout and atmosphere only; never any person's identity.
<Audio 1> is <Subject 1>'s voice reference: her timbre, tone and delivery only, never its words.
Camera: <POV rule - see 5.1>.
Scene: <one paragraph summarizing the WHOLE arc across all shots - see 5.2>.
Audio: <cue rules - see 5.3>.

summary:
<one-line essence of THIS shot only>.

detailed_description:
[Shot N] <opener - see 5.4>. <action prose>. <dialogue>. Audio: <beat-timed cues>. <closing beat>.
```

Rules that never change:
- Use plain hyphens, not em/en dashes (U+2014 / U+2013), anywhere in prompt text.
- Write the viewer's experience only; never describe a third-party narrator.
- Keep one locked-off POV framing per scene; only the head/neck may turn for glances.

---

## 4. Why the full block is repeated per segment

Earlier plans used a `prompt_prefix` shared across shots. The current Motion Director
files instead repeat the whole `subject_definitions` + `Scene` + `Audio` block in EVERY
segment (with `global` left empty). This gives per-shot control and is what the
"v2 - 3 REAUTHOR (fresh prompts)" files use.

Consequence: when you change a shared rule (identity line, camera rule, TALK-CONTROL,
NO MALE AUDIO), you must update it in every segment. When scripting a file, generate the
block once and splice it into all shots.

---

## 5. Section-by-section rules

### 5.1 `Camera:` (POV rule)

Always declare that the camera IS the viewer's eyes and that his body is never shown.

```text
Camera: the camera IS the viewer's eyes moving through the scene as he does, <path>. His body, hands and face are never visible; <how her contact reads on screen, e.g. her hands reaching toward and past the lens>.
```

### 5.2 `Scene:` (whole-arc summary)

One paragraph, identical across all shots, that states the arc so the model knows where
each shot sits. For a consent / CNC arc the canonical shape is:

```text
Scene: a consensual CNC roleplay across <N> shots. Shot 1 establishes her calm willing consent with the safe word; shots 2-<N-1> are the roleplay itself in which she is fully in character as <role>; shot <N> is aftercare where she drops character, thanks the viewer and checks in. <payoff beats>. Each shot progresses only as its own description states; she is the only person on screen; clothing matches <Picture 2> until removed; in the <location> matching <Picture 3>.
```

Generalize the arc for non-CNC scenes: shot 1 = setup, middle shots = progression, final
shot = resolution. Every beat that spans multiple shots lives here, not in one shot.

### 5.3 `Audio:` (cue rules + two hard controls)

```text
Audio: cue-by-cue and beat-timed in every shot - <her non-verbal sounds>, <foley: the wet sounds, fabric, furniture>, named at the instant they happen, all CLOSE to the camera mic, warm room tone low beneath. TALK-CONTROL: she speaks ONLY the exact <d> lines each shot carries; all moans/sobs/cries stay non-verbal; when her mouth is occupied she makes no words at all. NO MALE AUDIO: the viewer makes no sound at all - no voice, moan or breath - his release is silent except the wet sounds; never any male voice, male moan or male sound; the viewer stays completely silent.
```

- **TALK-CONTROL** and **NO MALE AUDIO** are mandatory in every segment (this is the
  "no man voices" guarantee). Keep the wording verbatim.
- Audio cues inside `detailed_description` use `Audio: <what happens, close at the mic>`.

### 5.4 `detailed_description:` openers (continuity)

- **Shot 1** begins from the supplied opening frame:

```text
[Shot 1] Live-action cinematic static POV shot, the camera locked at face level. Begin from the opening frame and its established composition, pose and lighting, then continue the action forward.
```

- **Shots 2+** continue from the previous shot (Motion Context):

```text
[Shot N] Continue the POV directly from the previous shot's final frame, preserving its pose, camera and lighting.
```

- Dialogue format (only the content goes inside the tag; speaker + language outside):

```text
She (S1) says <d>[English] <exact line>.</d>
```

- Every shot ends with a beat that hands off cleanly to the next ("End with ...").
- Whole-arc beats from `Scene:` must NOT be re-described as if they happen in this shot
  unless this shot actually performs them (the "leakproof" rule below).

### 5.5 Shot scoping (leakproof rule)

Scene-wide beats leak into early shots if you put them in the shared text or repeat them
early. Two guards:

- Keep arc-level facts only in `Scene:` and `Audio:`.
- Give the FIRST shot an explicit scope line so it does not show later content, e.g.
  "This shot only: <shot 1 beats>. Nothing from later shots appears yet."
- In every shot, describe only what that shot performs; carry forward state explicitly
  ("still wearing <Picture 2> clothing", "hands still tied") rather than re-staging.

### 5.6 Body orientation / geometry rule

For any position-sensitive scene, NAME the position and lock it:

- "REVERSE COWGIRL: straddling his thighs, her BACK to his chest and to the camera ..."
- Every "turn / look back" beat must be head-only: "turns only her head back over her
  shoulder", "her body never turns around", "torso, hips and legs never rotate to face
  the camera".
- The face reference pulls H3 to rotate the whole body to show the face; only an
  over-the-shoulder profile glance is safe if you must show it.

---

## 6. Character Replace windows

Character Replace re-renders selected source-video windows with a different subject while
the background stays true to the source. It rides inside the same `segments[]` list.

### 6.1 Per-segment spec (`replace` / `characterReplace`)

```json
{
  "enabled": true,
  "audio_policy": "source",
  "mask": {
    "kind": "sam3",
    "dir": "<optional mask dir>",
    "offset": 0,
    "grow": 1,
    "feather": 1.0,
    "sam_prompts": ["<text that selects the subject to replace>"],
    "obj_id": 1,
    "render": "anchor"
  },
  "lead": 12,
  "note": "<why this window>"
}
```

- `audio_policy`: `source` (keep original track) | `generate` (model voice for new
  subject) | `none` (silent).
- `mask.kind`: `none` | `frames` (premade `frame_%08d.png` mask dir, keyed to SOURCE
  frames) | `sam3` (runtime SAM3 auto-segmentation from `sam_prompts`).
- `grow` (int, tokens) / `feather` (float, sigma in tokens): seam softening. Defaults
  grow 1, feather 1.0.
- `lead` (frames): pre-roll runway so the new subject settles into pose; default 12,
  0 = off.
- Mask convention everywhere: **1 = regenerate (subject), 0 = keep (background)**.

### 6.2 `mask.render` - the two strategies

| Mode | How it works | Background | Identity |
|---|---|---|---|
| `anchor` | Full re-render of the window. Source window is fed as `<Video 1>` motion ref with the subject region drawn as a photographic NEGATIVE; target is a fresh empty AV latent. | re-rendered (not pixel-frozen) | strong - the new subject composes natively from `<Picture>` refs |
| `inpaint` | H3 noise-mask inpainting: keep region = source encode, regen region = subject. | pixel-exact (frozen) | weak - model may reconstruct the original performer |

Prefer **`anchor`** for character replacement (it is the recipe proven in CGlide). Use
`inpaint` only when pixel-exact background is more important than identity.

### 6.3 Prompt for a replace window

The replace window's `prompt` is a normal r2v block (sections 3-5) with these additions:

- The replacement subject's `<Picture N>` refs define the NEW identity (face + charsheet).
- The prompt must NOT describe the source performer - describe the new subject doing the
  action, and describe the background as "the room exactly as in the source video".
- If `audio_policy: source`, keep the TALK-CONTROL / NO MALE AUDIO rules and let the
  original track carry her voice; do not write `<d>` lines for the source performer.
- Windows are standalone (Previous / Motion Context forced OFF). Each window's prompt
  starts from "the opening frame of this window", not "the previous shot's final frame".

The engine feeds the source window as `<Video 1>` and silently prepends that tag when the
prompt never mentions a `<Video ...>` slot - so name `<Video 1>` yourself and give it its
role. Copy-and-fill template for ONE window (fill every `<...>`):

```text
subject_definitions:
<Subject 1> is <one identity line: who she is in this window>.
<Picture 1> is the sole source of her face, hair and skin: facial identity, expressions, skin tone and hair. Static portrait - never import its background, framing, angle or lighting; face and hair data only.
<Picture 2> is the sole source of her body: build, proportions and skin tone. Body data only - never import the sheet's grid, layout, standing poses or studio light.
wardrobe: she wears <the outfit: name the garments and their cut, seams, fabric, colours and fit>. Dress her in this outfit only - never in clothing from the reference images and never in the source performer's clothing.
<Video 1> is this window's source footage: the sole source of the action, pose, position, timing, camera, framing and setting. Its performer is a DIFFERENT, unrelated woman and is fully discarded - never carry over her face, hair, skin, body or clothing; <Subject 1> overwrites her completely.
Camera: exactly as <Video 1> - same framing, same angle, same movement; never re-shot or reframed.
Scene: the location, props and lighting exactly as <Video 1> has them, unchanged.
Audio: <audio policy line - see below>.

summary:
<Subject 1> replaces the source performer inside this window: same pose, same place, same motion, frame for frame - only she is redrawn, everything else stays as <Video 1>.

detailed_description:
[Shot 1] Begin from the opening frame of this window. <action prose: what SHE does, following the source window's action beat for beat>. Only <Subject 1> is regenerated: her face, hair, skin and body come from <Picture 1> and <Picture 2>, her outfit from the wardrobe line. She stays exactly where the source has her - same position, size in frame, body language and timing. The room, props, lighting, camera and audio stay exactly as <Video 1>. No second person. No on-screen text, subtitles or watermarks. End with <closing beat>.
```

Audio policy line for the `Audio:` slot:

- `source`: `the window keeps its original track exactly - no added lines, no added sounds, no regenerated speech; NO MALE AUDIO: never any male voice, male moan or male sound.`
- `generate`: the full section 5.3 cue block (cues + TALK-CONTROL + NO MALE AUDIO).

Rules for this template:

- The discard sentence ("DIFFERENT, unrelated woman ... fully discarded") is NOT optional.
  H3 treats a video reference as content to reproduce, so without an explicit discard line
  the original performer bleeds back into the render - the top failure mode of early
  reference-replace experiments.
- Keep only the reference lines for slots you actually attach. Replace the `wardrobe:`
  slot with the real garment description - it is the only place clothing is defined in the
  prompt, and an unfilled placeholder leaves the model free to keep the source performer's
  outfit. If a reference DOES carry the outfit you want, say so in that line ("the outfit
  shown in the character reference") or drop the line and use the section 2 wording ("sole
  source of her body shape, proportions, clothing and fit").
- Add one preservation line per other subject/object that must survive, e.g. "the man, the
  bed and the lamp stay exactly as `<Video 1>` has them, unchanged".
- In `anchor` mode the whole frame is re-rendered (nothing is pixel-frozen), so every
  property you want kept must be stated; `inpaint` freezes the background for you but is
  weaker on identity.
- Never write prose about the source performer's face, hair, skin or clothing - the only
  mention allowed is the discard line.
- Optional (proven in the CGlide recipe): a short `retention_analysis:` block after
  `summary:` listing what is preserved vs regenerated.

### 6.4 Identity from RefMod instead of Pictures

When the replacement identity is carried by RefMod (`refmod_conditioning` wired on the
Director) there are no `<Picture N>` slots to define. Swap the two `<Picture N>` lines
for the subject line plus the static-reference rule, keep everything else:

```text
subject_definitions:
<Subject 1> is the woman carried by the attached character reference: her face, hair, skin tone and build come from that reference and are not described in this text.
The character reference is static - it carries identity only: never import its background, framing, panel layout, lighting or standing pose. Action, camera and lighting come from <Video 1> alone.
wardrobe: she wears <the outfit: name the garments and their cut, seams, fabric, colours and fit>. Dress her in this outfit only - never in the character reference's clothing and never in the source performer's clothing.
<Video 1> is this window's source footage: the sole source of the action, pose, position, timing, camera, framing and setting. Its performer is a DIFFERENT, unrelated woman and is fully discarded - never carry over her face, hair, skin, body or clothing; <Subject 1> overwrites her completely.
Camera: exactly as <Video 1> - same framing, same angle, same movement; never re-shot or reframed.
Scene: the location, props and lighting exactly as <Video 1> has them, unchanged.
Audio: <audio policy line - see 6.3>.

summary:
<Subject 1> replaces the source performer inside this window: same pose, same place, same motion, frame for frame - only she is redrawn, everything else stays as <Video 1>.

detailed_description:
[Shot 1] Begin from the opening frame of this window. <action prose: what SHE does, following the source window's action beat for beat>. <Subject 1> is the woman from the attached character reference; she stays exactly where the source has her - same position, size in frame, body language and timing; her outfit is the wardrobe line exactly. The room, props, lighting, camera and audio stay exactly as <Video 1>. No second person. No on-screen text, subtitles or watermarks. End with <closing beat>.
```

RefMod rules:

- RefMod refs are appended to `minimax_refs` AFTER text encoding: the text encoder never
  sees the reference. Do not write a `<Picture N>` tag for it (there is none - the
  References audit flags unattached slots) and do not argue with the reference in prose.
- `<Subject 1>` is a narrative handle, not a lookup key; nothing in the prompt resolves
  to a mod.
- Keep ONE subject in the prose. Additional described people compete with the mod for the
  subject binding.
- If the mod alone under-delivers, add a SHORT clue (2-4 words, e.g. "the auburn-haired
  woman") once and re-test - the RefMod author's own identity success used a two-word
  clue. Do not expand it into a full appearance paragraph.
- The wardrobe line: the mod is a FULL visual reference. Whatever its images show (clothing,
  rooms, lighting, poses) reaches the DiT and can be reproduced, so the outfit CAN come from
  the mod - but there is no tag to aim it with: RefMod refs are appended after text encoding,
  the text encoder never sees them, and no prompt wording can select or filter part of a mod.
  Decide which channel owns the outfit:
  - Outfit from the mod: curate the mod images so they show the outfit you want (consistent
    in every image) and write the wardrobe line to MATCH it, or drop the line. Never write a
    different outfit than the mod shows.
  - Outfit from text: write the garment description and keep the "dress her in this outfit
    only" half - the prompt can argue with the reference but not filter it, so a strong
    conflicting outfit in the mod images will fight back.
  Never leave the slot unfilled: the model is then free to keep the source performer's outfit.
- Keep the full block in EVERY window's prompt - each window is sent on its own.

---

## 7. Recipe: write a new r2v workflow

1. Fix the job: aspect, megapixels, FPS, mode = r2v, steps (global widget - per-shot
   `steps` do not carry).
2. Attach Common References: `<Picture 1>` face, `<Picture 2>` charsheet, `<Audio 1>`
   voice; scene photo to `<Picture 3>` (common or per segment).
3. Write the shared block once: `subject_definitions` (identity + ref roles) + `Camera:`
   + `Scene:` (whole arc) + `Audio:` (cues + TALK-CONTROL + NO MALE AUDIO).
4. Split the arc into segments. Shot 1 = setup / consent; middle = progression; last =
   resolution / aftercare. Choose `frameCount` on the `% 17 == 5` grid, `start` = running
   sum of previous lengths.
5. Per segment: splice the shared block, write a one-line `summary`, then
   `[Shot N] <opener>` + action + dialogue + `Audio:` cues + closing beat.
6. Shot-scope each segment (5.5) and lock body orientation (5.6) if position matters.
7. Mirror `timeline_data` into all three sites; save; drag onto the canvas.

## 8. Recipe: write a Character Replace workflow

1. Source video stays a file reference; never embed frames.
2. Add windows as segments with explicit `start` / `length` (order = render order).
3. Attach NEW subject refs (face + charsheet) + set `audio_policy` + `mask` config
   (`sam3` + `sam_prompts` for runtime masks, or a premade mask dir).
4. Set `render: anchor` (default), `grow`/`feather`, and `lead` 12.
5. Write each window's r2v prompt per 6.3. Keep backgrounds source-true and identity
   refs strong. TALK-CONTROL / NO MALE AUDIO apply unless `audio_policy: generate`.

## 9. Hard constraints checklist

- `frameCount % 17 == 5` (H3-valid lengths).
- `negativePrompt` empty; no negative prompts.
- Plain hyphens only; no em/en dashes (U+2014 / U+2013).
- No male voice anywhere: NO MALE AUDIO block in every segment.
- TALK-CONTROL block in every segment (she speaks only the `<d>` lines).
- Steps are a single global widget; per-shot `steps` do not carry.
- Continuity = Motion Context, not `<Picture 0>`; shot 1 uses the "opening frame"
  opener, shots 2+ use "continue the POV directly".
- Keep the three `timeline_data` copies in sync.
