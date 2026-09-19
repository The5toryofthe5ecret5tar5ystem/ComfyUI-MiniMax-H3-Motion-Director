# MiniMax H3 Motion Director User Guide

**English** | [简体中文](USER_GUIDE_zh.md)

This guide is for users operating **MiniMax H3 Motion Director** for the first time. It focuses on practical use: **what each control does, when to use it, and how to run T2V / I2V / FL2V / R2V / V2V / RV2V / Mixed workflows.**

> Red numbers in the annotated screenshots follow the recommended interaction order. Controls that do not apply to the selected task are normally hidden by the Director.

---

## 1. The shortest useful workflow

Almost every project follows the same pipeline:

```text
Generation mode → Output settings → Segments/assets → Prompt → Generate → Live Preview → Postprocess → Results → Save Video
```

For a first test, generate a 5–10 second T2V clip:

1. On **Generate**, select `T2V — Text to Video`.
2. Set aspect ratio, megapixels and FPS.
3. Add one Prompt Group, then enter its prompt and duration.
4. Execute the ComfyUI workflow.
5. Watch the active stage under **Live Preview**.
6. Once the content is worth keeping, enable **Postprocess**. This avoids spending upscale/refine time on clips you may reroll.
7. Open **Results → Final Result**, inspect the output and save the video.

---

## 2. Choosing one of the six standalone modes

| Mode | Main input | Use it when |
|---|---|---|
| `T2V` | Prompt | The shot is created entirely from text |
| `I2V` | Prompt + start image | You already have a character/scene/composition image and want to animate it |
| `FL2V` | Prompt + First / Last Image | You need explicit control over the visual start, end, or both |
| `R2V` | Prompt + image/video/audio references | You need identity, scene, prop, motion, style or voice references |
| `V2V` | Source Video + Prompt | You want to preserve source motion/timing structure while regenerating visuals |
| `RV2V` | Source Video + Prompt + References | You need source motion plus identity/audio/other references |

If different shots in one project need different methods, use **Mixed Mode** instead of building separate Director nodes.

---

## 3. T2V: basic text-to-video

![Standalone T2V controls](images/tutorial/01-standalone-t2v.webp)

| # | Control | What it does |
|---:|---|---|
| 1 | Generation mode | Selects `T2V / I2V / FL2V / R2V / V2V / RV2V / mixed` |
| 2 | Output aspect/resolution | Selects the project aspect ratio such as 16:9 or 9:16 |
| 3 | Megapixels | Controls first-pass generation scale; the calculated size is shown beside it |
| 4 | FPS | Output frame rate; normally keep it consistent across the project |
| 5 | Export mode | Controls the output range/method for this run |
| 6 | Material Library | Opens persistent reusable assets |
| 7 | Add Prompt Group | Adds another standalone T2V segment |
| 8 | Selective Run | When enabled, only selected Prompt Groups are executed |
| 9 | Duration | Target duration of the current Prompt Group |
| 10 | Delete | Deletes the current group |
| 11 | Prompt | MiniMax H3 prompt for this segment |
| 12 | Between-group control | Boundary/continuity operations; available actions depend on mode and global settings |

### Generate a 30-second T2V as three 10-second segments

1. Select `T2V`.
2. Press **Add Prompt Group** twice so there are three groups.
3. Set each group to 10 seconds.
4. Write a prompt for each segment. For a continuous scene, explicitly carry forward character, environment and action state in later prompts.
5. Set output aspect, megapixels and FPS.
6. Run the workflow.
7. If one segment is poor, enable **Selective Run** and rerun only that segment.

---

## 4. I2V: animate one image

Use I2V when you already have a character, scene or composition image.

1. Select `I2V`.
2. Upload **one start image** to the segment.
3. Write what should happen next. Do not waste the prompt repeating every visual fact that is already unambiguous in the image.
4. Set duration and generate.

Common uses include animating a character portrait, starting from a designed scene, adding camera motion to a product image, or continuing from a previous segment's last frame.

---

## 5. FL2V: control the first and/or last frame

FL2V is for explicit visual endpoints.

- First Image only: start from a specified frame.
- Last Image only: make the generation arrive at a specified ending.
- First + Last: constrain both ends and let the model create the transition.

Workflow:

1. Select `FL2V`.
2. Upload First Image, Last Image, or only the endpoint you need.
3. Use the prompt to describe the motion and camera change between the endpoints.
4. Generate and inspect the transition. Fixed endpoints do not guarantee that every intermediate motion will be identical across rerolls.

---

## 6. R2V: identity, scene, motion and audio references

![R2V controls](images/tutorial/02-r2v-assets.webp)

R2V is the most useful standalone mode for recurring characters. Each Assets Group can contain up to:

```text
Picture 1–9
Video 1–3
Audio 1–3
```

| # | Control | What it does |
|---:|---|---|
| 1 | R2V mode | Switches to reference-based video generation |
| 2 | Add Assets Group | Adds another R2V segment/group |
| 3 | Output aspect | Sets project framing |
| 4 | Export mode | Selects output range/method |
| 5 | Common References | Adds project-level references shared by multiple groups |
| 6 | Material Library | Assigns persistent image/audio/video/prompt assets |
| 7 | Reference preview/upload | Uploads or previews the current group's references |
| 8 | Assets Group | The complete input scope for the current R2V segment |
| 9 | Reference Pictures | Character, scene, prop, etc.; up to 9 |
| 10 | Prompt | Describes action, camera, dialogue and how references are used |
| 11 | Duration | Current group duration |
| 12 | Delete | Deletes the current group |

### Example: one character across three shots

1. Enter `R2V`.
2. Put the character's portrait/full-body identity references in **Common References**.
3. Create three Assets Groups.
4. Add only shot-specific scene, motion or audio references to each local group.
5. Write each shot prompt.
6. Generate, then rerun only shots that need another pass.

---

## 7. Common References: share assets across standalone groups

![Common references](images/tutorial/04-common-references.webp)

| # | Control | What it does |
|---:|---|---|
| 1 | Reference Images | Project-level shared pictures, up to 9 |
| 2 | Reference Videos | Project-level shared reference videos, up to 3 |
| 3 | Reference Audio | Project-level shared reference audio, up to 3 |

Use **Common References** for assets needed by many segments: a recurring character, location, prop, motion reference or voice.

Use **local segment assets** for media needed only by one segment. At execution time, the Director combines common and local references into the effective reference sequence for that task.

Rule of thumb:

- Needed by many groups → Common References.
- Needed by one group → local assets.

---

## 8. Material Library: persistent reuse across projects

![Material Library](images/tutorial/05-material-library.webp)

The Material Library is different from Common References. Common References belong to the current project; the Library stores assets for reuse across shots and later projects.

| # | Control | What it does |
|---:|---|---|
| 1 | Images / Audio / Video / Prompt | Switches asset type |
| 2 | Apply To | Shows the current target Segment/Group |
| 3 | Categories | Filters characters, scenes, props, other, etc. |
| 4 | Search | Finds assets by title |
| 5 | Clear Current Page Selection | Clears selections on the visible page |
| 6 | Clear All Selection | Clears selections across all pages |
| 7 | Add Material | Stores a new asset in the Library |
| 8 | Material cards | Selects assets to assign |
| 9 | Allocation Preview | Previews where selected assets will be assigned |
| 10 | Apply | Writes the current selection into the target |
| 11 | Close | Closes the Library |
| 12 | X | Closes the dialog |

### Referencing Library assets in prompts

A reference added from the Library behaves exactly like one uploaded through a slot:

- If the prompt already mentions that asset (a red **missing asset** chip, as left behind by a
  prompt copied from another project, a plan import, or a reference you removed), the added
  reference **reconnects** to the mention instead of creating a second, unrelated identity.
- Otherwise the id is derived from the file, so removing and re-adding the same material keeps
  existing mentions bound to it.
- A Library reference is labelled with the **material's title**, and the file it points at is a
  copy in `input/minimax_material_library/`, so the name you see in the panel is the one you
  gave the material rather than the copy's generated file name.

Adding several pictures in one *Apply* reconnects their mentions in order: the first picture
heals the first missing picture chip, the second heals the next one. If the Library adds more
pictures than there are missing chips, the extras get their own new identity.

### Important Mixed Mode rule

The Library targets the **currently selected Segment** and only exposes media that are legal for that mode.

The actual Mixed `Source Video` must still be uploaded locally to that Segment. A Library video is a Reference Video; it does not replace the Mixed Source Video input.

---

## 9. Reference Audio and Original Audio Drive

![Reference audio and drive timeline](images/tutorial/06-reference-audio.webp)

Reference audio can have two roles:

- **Normal reference**: audio is provided as reference information to H3.
- **Original Audio Drive**: the original audio is placed at a specific time on the segment's Drive timeline and becomes part of the segment's timed audio-driving setup.

| # | Control | What it does |
|---:|---|---|
| 1 | Reference Video area | Adds reference videos |
| 2 | Video slots | Individual video reference slots |
| 3 | Reference Audio area | Current audio references |
| 4–5 | Audio cards | Play, edit and inspect each audio item |
| 6 | Audio Role | Switches Normal reference / Original Audio Drive |
| 7 | Empty Audio slot | Uploads another audio item |
| 8 | Drive timeline | Drag Audio Drive blocks to the time where they should occur |

Two direct Drive timeline constraints apply:

1. Drive intervals cannot overlap.
2. A Drive block cannot extend beyond the current Segment; move it earlier or trim it shorter.

### Audio editor

![Audio editor](images/tutorial/07-audio-editor.webp)

| # | Control | What it does |
|---:|---|---|
| 1 | Waveform | Shows the audio and lets you adjust the retained range |
| 2 | Trim start | Start time of the kept range |
| 3 | Trim end | End time of the kept range |
| 4 | Play | Previews the current selection |
| 5 | Undo | Undoes one edit |
| 6 | Redo | Redoes an edit |
| 7 | Reset | Restores the original trim range |
| 8 | Trim | Applies the current trim range |
| 9 | Cancel | Discards the current editor changes and closes the editor |
| 10 | Done | Saves the edit and returns to the Director |

`Effective` is a read-only duration display, so it does not receive a red operation number.

A typical dialogue workflow is: trim a long recording to the required line, then drag that block on the Drive timeline to the exact point where the line should occur.

---

## 10. V2V: preserve source motion, regenerate visuals

V2V uses `Source Video + Prompt`.

Typical uses:

- Keep the source performance/timing while changing clothes, environment or style.
- Use a live-action clip as a motion template.
- Regenerate a shot without designing movement from scratch.

Workflow:

1. Select `V2V`.
2. Upload Source Video.
3. Select the required Source Range.
4. State clearly what must change and what must remain.
5. Generate and inspect whether the motion structure is preserved well enough.

Standalone V2V/RV2V can also use the Director's **Source Bridge** around eligible source-video segment boundaries instead of treating every split as a simple hard cut.

---

## 11. RV2V: source motion plus identity/audio references

RV2V adds reference media on top of V2V's Source Video.

Example: replace the performer in a source clip with a character defined by reference images while preserving the source motion.

1. Select `RV2V`.
2. Upload Source Video.
3. Add Identity Pictures.
4. Add audio/reference media only when needed.
5. In the prompt, state the identity replacement and which source motion/camera properties must remain.
6. Generate.

Source Video provides motion/timing structure; Identity/Reference media provide character or other reference features. Treat them as separate input roles.

---

## 12. Character Replace (ref2va + SAM3): VRAM settings guide (16 / 24 / 32 GB)

**Character Replace** re-renders one or more **windows** of a Source Video with a referenced character. Each window gets an automatic subject mask (SAM3, by prompt) and is rendered as an independent masked clip: the subject region is re-generated from your identity references while the window keeps its real source background. A full how-to and per-VRAM settings matrix follow.

### 12.1 Prerequisites and the recommended runbook

Character Replace needs the RV2V family of inputs, so set the node up as you would for RV2V first:

1. Give the Director a **Source Video** (this is the footage whose performer you replace).
2. Add the replacement character in **Common References**: **Picture 1 = face** (headshot) and **Picture 2 = character sheet** (front/side/back) - see sections 7 and 11.
3. Set **Replace: ON** on the timeline (the toggle appears when a source video is loaded).
4. **Fill the windows**, either way:
   - **Long-form - the whole clip in one click:** set **len**, then press **Long-form replace - cover whole clip**. It cuts the source into equal windows, enables replace and continuity on every one of them, and switches **Export mode** to *by segment* so a single bad window can be re-rendered alone. The preview line above the button states what it will produce before you commit. Alternatively, press the **Long-form Character Replace** bar that appears while Replace is OFF.
   - **By hand:** `+ Add after` / `+ Add at playhead` (default 5 s each, up to 20 s; lengths auto-snap to the H3 frame grid). Rows may overlap or be out of order - list order is render/output order.
5. On each window row choose:
   - **kind = sam3** (auto mask from a text prompt - no mask files needed) or **frames** (pre-made per-frame mask PNGs).
   - **render = anchor** (recommended: full re-render, subject drawn as a photographic negative in the motion reference - strongest identity) or **inpaint** (pixel-exact background, but identity is weaker on this stack).
   - **SAM3 prompt** (describe the source person, e.g. `the woman, full body from head to toe, including every strand of her hair`).
   - **grow** / **feather** / **lead** (pre-roll frames) / **audio policy**.
6. **Generate.** During the prepare phase the **Live Preview** page shows a **Mask check** card under Preview Settings (source | red subject overlay | motion reference) so you can abort before sampling if the mask is wrong.
7. Inspect per-window results, then export (per clip, or ordered concatenation). **Resume** reuses finished windows from cache and does not re-run SAM3 on cached windows.

If SAM3 cannot run, misses the subject, or OOMs, that window **automatically falls back to a plain RV2V re-render** - never a hard failure.

### 12.2 What actually costs VRAM

In priority order:

1. **Working resolution** (aspect + megapixels in the Generate panel; default 0.4 MP = 864x480 @ 16:9).
2. **Window length** (frames live in the video latent, and the source window is held in RAM while a window renders).
3. **Model residency**: the H3 DiT (int8 convrot, ~10.5 GB) plus text encoder (nvfp4, ~5 GB) with the VAEs offloaded is roughly a **15 GB resident** envelope. SAM3 (video predictor) runs **on top of that** while the window mask is built, then is released before sampling.

Steps/sampler change time (and slightly, intermediate buffers), not the resident model size. Grow/feather and the pre-roll lead are cheap.

### 12.3 Settings by VRAM tier

| Setting | 16 GB (borderline) | 24 GB (sweet spot, validated on RTX 3090) | 32 GB (comfortable) |
|---|---|---|---|
| Overall | Runs only with aggressive offload, small windows, and **no in-run SAM3**. Prefer mask **frames** assets. | Recommended minimum for full experience incl. in-run SAM3 auto-mask. | Model fully resident; fastest iteration; largest windows/resolutions. |
| Working resolution (16:9 example) | 0.2-0.3 MP (e.g. 640x360, up to 736x416) | 0.4 MP default (864x480); up to ~0.7 MP (960x544 / 1136x640) for windows <= 5 s | 0.4-1.3 MP (864x480 up to 1216x672 / 1280x720) |
| Max window length | <= 5 s (124 f) | 5-10 s typical (124-243 f); 15 s (362 f) only if resolution is <= 0.4 MP | Up to 15-20 s (362-481 f); drop MP if you also go long |
| SAM3 auto-mask (kind = sam3) | Avoid: SAM3 overlaps the resident H3 stack and will likely OOM. Use kind = frames / a mask asset. | Works. Plan ~3 min/window: ~7 s predictor build + propagation (~1.5 it/s); SAM3 is released before sampling. | Works and is fastest; mask cache means Resume does not re-run SAM3 on finished windows. |
| Render mode | anchor | anchor (recommended); inpaint only when the background must stay pixel-exact and you accept weaker identity | anchor; inpaint also fine |
| grow / feather | 1 / 1.0 | 1 / 1.0 by default; try grow = 2 if a fine-hair halo remains | 1 / 1.0, grow up to 2-3 for stubborn wispy hair (each grow step reclaims roughly one 32 px token ring) |
| Pre-roll lead | 12 frames | 12 (default) | 12 (more only adds a little RAM, not VRAM) |
| Steps / sampler | res_multistep + simple; drop to ~10-14 steps to shorten runs | Default 25 is fine; 14 is a good time/quality trade | Keep 14-25. If a REF2V turbo LoRA is wired in the model subgraph, 4-6 steps work on every tier |
| Audio policy | source (reuse original track) only | source recommended; generate OK for short windows | source or generate |
| Clear VRAM Between Segments | ON (mandatory) | ON when SAM3 is in use (keeps SAM3 and DiT from peaking together); OFF only for plain non-SAM3 runs | OFF for max throughput (keeps the model resident); per-segment reload is the main cost of leaving it ON |
| Model variants | DiT int8 convrot + text encoder nvfp4 (smallest footprint); VAEs offloaded | Same int8/nvfp4 pair; text encoder may briefly page to RAM during encode - normal | Same int8/nvfp4 pair keeps headroom for SAM3 and large latents |
| ComfyUI launch flags | `--lowvram` (dynamic VRAM low) strongly recommended | Default, or `--reserve-vram 2` | Default; no reserve needed |
| Live Preview max resolution | Keep small (<= 480) and jpeg quality ~70 (encode CPU) | 640-768 | Up to 1024 |
| Mask check card | Free (a small JPEG) on every tier | Same | Same |

### 12.4 Fastest iteration path

1. Smoke-test **one short window first** (3-5 s, low MP, one segment) and watch the **Mask check** card: red overlay should hug the person you are replacing (hair included), and the motion-reference panel should show the subject as a dark/negative silhouette in anchor mode.
2. Abort immediately if the red region misses hair, covers background, or is absent (`no subject mask!`) - fix the SAM3 prompt or the window first.
3. Only when one window looks right, add the rest and run in small batches, then **Resume** the remainder.
4. Keep expensive Global Refine / Face Refine / upscale for after the replacement windows are locked (section 16).

---

## 13. Mixed Mode: combine generation methods on one timeline

![Mixed Mode controls](images/tutorial/03-mixed-mode.webp)

Mixed Mode is the most practical choice for a complete project.

Example:

```text
S1  T2V
S2  I2V
S3  R2V
S4  Source Video
S5  T2V
```

| # | Control | What it does |
|---:|---|---|
| 1 | `mixed` | Enters Mixed Mode |
| 2–5 | Output settings | Resolution mode, width, height and FPS |
| 6 | Export mode | Sets output behavior |
| 7 | Material Library | Assigns legal assets to the currently selected Segment |
| 8 | Add Segment | Adds another Segment |
| 9 | Selective Run | Runs only selected Segments |
| 10 | Segment timeline | Select, inspect, copy, delete and organize Segments |
| 11 | Boundary controls | Requests visual/generated-audio continuity between adjacent Segments |
| 12 | Selected Segment | Green outline shows which Segment is being edited |
| 13 | Generation mode | Per-Segment T2V / I2V / FL2V / R2V / Source Video |
| 14 | Duration | Segment duration; Source Video uses the selected Source Range |
| 15 | Prompt | Prompt for the selected Segment |

### Mixed Source Video rule

Mixed intentionally exposes one `Source Video` mode:

```text
Source Video + 0 Identity Pictures  → V2V
Source Video + Identity Pictures   → RV2V
```

`Start sec / End sec` define the Source Range and therefore the Segment duration.

### Segment Result

A later Segment can reuse a decoded static frame from an earlier completed Segment:

```text
Earlier Segment → last frame
Earlier Segment → explicit frame index
```

Typical uses:

- S1 last frame → S2 I2V start image.
- A frame from S2 → S3 FL2V First Image.
- Earlier result → later FL2V Last Image.

Segment Result references are **backward-only**: later Segments can use earlier results, not future Segments that do not exist yet.

### Boundary continuity

The controls between Segment cards decide whether that boundary requests visual and/or generated-audio continuity. Node-level continuity settings remain the global master switches.

Enable continuity for a continuing scene; reset a boundary when deliberately changing scene, identity or style.

---

## 14. Selective Run: reroll only the bad shot

The expensive mistake in a long project is rerunning every shot because one shot failed.

Recommended workflow:

1. Generate all segments once.
2. Identify the segments that are not good enough.
3. Enable **Selective Run**.
4. Select only those Segment/Groups.
5. Keep the other cached/source results.
6. Once the edit is locked, run final Global Refine / Face Refine.

This is also why a low-resolution first pass is efficient: spend upscale/refine time only on clips you have decided to keep.

---

## 15. Resume, Stop and Start Over

Long jobs are expensive, so the run bar is built around stopping and continuing instead of always re-rendering everything:

- **Start run** - queues a fresh run of the project. Every selected segment is rendered; caches are not reused.
- **Resume** - continues an interrupted run. Finished segments that are still valid are reused from disk cache, and only the segments that cannot be reused are re-rendered.
- **Restart** - interrupts the current run and re-renders from the current (or first unfinished) segment with a fresh seed.
- **Stop** - lets the current segment finish, then stops. Hit Resume later to continue from where it stopped.
- **Start Over** - clears this node's segment caches and run history, then queues a fresh run.

### What Resume reuses

Finished segments are kept as best-effort on-disk caches. When you press Resume, the Director walks the timeline from the start and reuses every segment whose cache still matches the current project settings, then re-renders from the first segment whose cache does not match. If nothing changed since the run stopped or crashed, Resume continues exactly at the interruption and only re-renders the segment that was in flight.

### Which settings keep a cache reusable

A segment cache is keyed to the settings that decide what that segment renders. Change one of the settings in the left column and the segment (plus everything after it) is stale, so Resume re-renders from there. Change one on the first segment and the whole project re-renders.

| Changing these invalidates the cache | Changing these is safe (cache still reused) |
|---|---|
| Prompt / negative text | Seed |
| Resolution: width, height, megapixels / ref-max | Steps |
| Reference files and their content | Sampler / scheduler |
| Shot frame range (start/end or Source Range) | CFG / guidance |
| Generation task type (T2V / I2V / FL2V / R2V / V2V / RV2V) | Export bitrate / CRF / encoder |
| Output mode / resolution scaling | Global Refine and Face Refine on/off |
| Continuity on/off and Context Frames | Live Preview settings |
| Color Re-anchor, Re-ground and context links |  |
| V2V / RV2V Source Bridge and overlap frames |  |

Practical rules:

- Crashed or hit Stop mid-run? Leave the content knobs alone and press Resume. It continues from the interruption and only re-renders the segment that was in flight.
- **Resume now opens a cache-check dialog first.** It shows how many segments are cached, where the run will continue, and - when the node settings changed (for example resolution / megapixels / ref-max) - exactly which cached settings differ, with a button to restore the cached settings onto the node so the finished prefix is reused. You can also pick a different start segment, or Start Over from the dialog. **Restart** re-renders from the current / first unfinished segment with a fresh random seed.
- Changing resolution / megapixels / ref-max is the most common accidental full restart, because the old caches were rendered at a different size. Set them back to the cached size and Resume reuses the finished prefix again.
- Bitrate / CRF (Results > Save Video) and the Global / Face Refine toggles are export and post-process choices - they never invalidate finished segment caches. (Refine output is baked into the cache, so a cached segment keeps the refine state it was generated with.)
- Use **Start Over** only when you want a guaranteed-fresh render: it deliberately discards the caches.

Segment caches live under your ComfyUI output directory in `minimax_seg_cache/<node id>`. They are best-effort: if that folder is not writable (for example a read-only network or cloud mount), caches cannot be written and Resume always re-renders.

---

## 16. Postprocess: Global Refine, Upscale, Face Refine and Audio Room

![Post-processing](images/tutorial/08-postprocess.webp)

The panel has three columns: **Global Refine**, **Face Refine** and **Audio Room**.

| # | Control | What it does |
|---:|---|---|
| 1 | Postprocess page | Opens the post-processing pipeline |
| 2 | Global Refine master | Enables/disables the global refine pipeline |
| 3 | Secondary Sampling | Second H3 sampling pass; seed, denoise and steps are configurable |
| 4 | Upscale | Selects H3 Learned Latent or other available upscale paths |
| 5 | Output Resolution | Sets the postprocess target size |
| 6 | NVIDIA RTX Deblur | Optional RTX deblur; requires the corresponding NVIDIA runtime/hardware |
| 7 | Face Refine master | Enables face refinement |
| 8 | Detection | Face detector, confidence and target face |
| 9 | Refine | Face regeneration strength and canvas quality |
| 10 | Pasteback | Mask, blend and color matching controls |
| 11 | Advanced Settings | Less commonly changed parameters |

### Audio Room

Places the model's **generated** audio in an actual space instead of leaving it dry on the camera mic. It never touches source audio: with **Audio mode: source** the video keeps the original track exactly as it is.

| Control | What it does |
|---|---|
| **Audio Room** master | Enables the stage. Off by default, and nothing downstream changes while it is off. |
| **Room** | A named space, or **Custom**. A named room sets all six values at once: `dry`, `bedroom`, `bathroom`, `bar`, `office`, `car`, `hall`, `cathedral`, `outdoor`. |
| **Reverb** | Master for the reverberation itself. Off leaves only the Level controls. |
| **Reverberance / HF Damping / Room Size / Stereo Depth / Pre-delay / Wet Gain** | The six SoX parameters. They appear only when **Room** is set to Custom. **HF damping** matters most for realism: high damping reads as soft furnishings and bedding, low damping as tile and glass. |
| **Normalize / Gain (dB)** | Level section. Normalise balances the track; gain adjusts it. |
| **Limiter / SoX Path** | Advanced. The limiter clamps peaks when gain is positive. SoX is auto-detected; the path only needs setting if `sox` is not on PATH. |
| **Per-segment** | Also applies the chain as each segment is produced, so per-segment previews carry the room sound. This **joins the segment cache fingerprint**, so anything already rendered must be re-rendered. Leave it off unless you specifically want wet previews. |

**Per-scene spaces.** A scene can declare its own room through a `room` field in the timeline, overriding the panel's choice for that scene only. There is no timeline widget for it yet, so it is set in the timeline data (accepted keys: `room`, `roomPreset`, `room_preset`). This is what lets a bathroom scene and a bedroom scene in the same render stop sharing one acoustic setting; a scene that sets nothing falls back to the panel's room.

**Why it is safe to experiment with.** The chain runs at output assembly, *after* the segment audio cache is written, and model audio is processed before segments are merged so that a merged export still gets one space per scene. Enabling it, changing a room, or switching presets therefore invalidates **no segment, no context cache and no finished render**. Only **Per-segment** changes cache identity.

**Ordering note.** Reverb runs before levelling, deliberately: normalising first would let the reverberant tail push the result into clipping, because the reverb adds energy on top of an already-peaked dry signal.

**Requires SoX** on PATH (`sudo pacman -S sox` on Arch/CachyOS). It is auto-detected. If a track cannot be processed it is left dry and named in the report, rather than failing the render. The **`soundfile`** Python package is required as well and is declared in `requirements.txt`; it is not a ComfyUI dependency, so a bare ComfyUI install will not have it.

### Recommended production order

```text
Low-resolution first pass → Check content/motion/composition → Reroll failed segments → Lock the shots → Global Refine / Upscale → Face Refine → Audio Room → Final Result
```

If Global Refine fails, the completed first-pass result is retained. If Face Refine cannot find a usable face or the stage fails, the assembled result remains available instead of invalidating the whole pipeline.

---

## 17. Live Preview: see what the pipeline is doing

![Live Preview](images/tutorial/09-live-preview.webp)

| # | Area | What it does |
|---:|---|---|
| 1 | Live Preview page | Opens Director Live Preview |
| 2 | General / Global Refine / Face Refine | Switches the stage being observed |
| 3 | Preview | Shows intermediate frames for the active stage |
| 4 | Progress/status | Current Segment, stage, step and overall progress |
| 5 | Preview Settings | Preview frame count, FPS, max resolution, JPEG quality and refresh interval |

Live Preview is observational; it does not change the prompt or generation result. Preview resolution/FPS can be lower than final output to reduce overhead.

---

## 18. Results: inspect and save the final video

![Results](images/tutorial/10-results.webp)

| # | Control | What it does |
|---:|---|---|
| 1 | Results page | Opens Results |
| 2 | Segment / Multi Segment / Final Result | Switches between one segment, a continuous range and the complete result |
| 3 | Player / playback controls | Checks final video and audio |
| 4 | Save Video panel | Video export settings |
| 5 | Auto-save final result | Writes the final video automatically when the pipeline completes |
| 6 | Path | Output directory |
| 7 | Filename prefix | Prefix for the saved file |
| 8 | Format | Container/format; `auto` lets the Director choose |
| 9 | Encoder | Video encoder; `auto` uses automatic selection |
| 10 | Encoding mode | Encoding strategy |
| 11 | Save Video | Manually saves the current final result |
| 12 | Copy report | Copies the current Director Report to the clipboard |

**Final Result Information** and the **Report body** are read-only information areas. Red callout `12` points to the operable Copy button. The report records the actual execution configuration, continuity, sampling and postprocess status.

The three result levels are:

- **Segment** — inspect one generated segment.
- **Multi Segment** — preview/export a continuous segment range.
- **Final Result** — inspect and save the complete pipeline output.

---

## 19. Common workflows you can follow directly

### A. Three continuous text-generated shots

```text
T2V
→ Add Prompt Group × 3
→ Prompt + Duration for each group
→ Enable required cross-segment continuity
→ Generate
→ Inspect each segment
→ Selective Run failed segments
→ Postprocess
→ Final Result
```

### B. Animate a character image

```text
I2V
→ Upload start image
→ Prompt for action/camera
→ Set Duration
→ Generate
```

### C. Force a shot to move from image A to image B

```text
FL2V
→ First Image = A
→ Last Image = B
→ Prompt describes the transition
→ Generate
```

### D. Same character across many shots

```text
R2V
→ Character references in Common References
→ One Assets Group per shot
→ Shot-specific scene/motion/audio in local assets
→ Prompt per group
→ Generate
```

### E. Keep source motion but regenerate the visuals

```text
V2V
→ Upload Source Video
→ Select Source Range
→ Prompt says what changes and what stays
→ Generate
```

### F. Replace the source performer with a referenced character

```text
RV2V
→ Source Video
→ Identity Pictures
→ Optional Reference / Drive Audio
→ Prompt: identity replacement + preserve source motion
→ Generate
```

For per-window **Character Replace** with SAM3 auto-masks (masking + identity settings and the 16/24/32 GB VRAM guide), follow **section 12** instead.

### G. Five shots using different methods

```text
Mixed
→ Add Segment × 5
→ S1 T2V
→ S2 I2V
→ S3 R2V
→ S4 Source Video
→ S5 FL2V
→ Set visual/audio continuity at each boundary
→ Generate
→ Selective Run only failed shots
```

### H. Place recorded dialogue at an exact time

```text
R2V / RV2V
→ Upload Audio
→ Audio Role = Original Audio Drive
→ Edit Audio to the required range
→ Drag it to the correct time on Drive timeline
→ Verify no overlap and no segment overrun
→ Generate
```

---

## 20. Concepts that are easy to confuse

| Concept | Meaning |
|---|---|
| Common References | References shared by multiple segments in the current project |
| Segment/Group Local Assets | Assets used only by the current segment |
| Material Library | Persistent assets reusable across projects |
| Source Video | Motion/timing structure for V2V/RV2V |
| Reference Video | Reference information; not the same role as Source Video |
| Segment Result | Static decoded frame from an earlier segment for later I2V/FL2V |
| Motion Context | Cross-segment motion/context continuity; separate from Segment Result |
| Selective Run | Reruns only selected segments while keeping other available results |
| Global Refine | Global second-pass sampling/upscale after first-pass generation |
| Face Refine | Local H3 refinement on detected face regions followed by pasteback |

---

## 21. Pre-run checklist

Before a long generation, verify:

- The correct generation mode is selected.
- Aspect ratio, megapixels and FPS match the project.
- Duration / Source Range is correct for every segment.
- I2V / FL2V images are assigned to the correct endpoint.
- V2V / RV2V uses an actual Source Video, not merely a Reference Video.
- Common and local R2V/RV2V assets are assigned correctly.
- Audio Drive intervals do not overlap or exceed the segment.
- Mixed boundary continuity matches the story intent.
- Selective Run has not accidentally selected or omitted a segment.
- Expensive upscale/Face Refine is postponed until first-pass content is worth keeping.

That check prevents the most common avoidable reruns in long projects.

## 22. When a button does nothing at all

The frontend is a set of ES modules that the browser loads and keeps. ComfyUI
sends `Cache-Control: no-store` for `.js` files but not for `.mjs` ones, so a
browser that is holding an old copy of a `.mjs` module can keep using it after
an update - including a copy that is missing something the new code imports. A
panel loaded on demand then fails to start, and the button that opens it looks
alive but does nothing.

What to do, in order:

1. **Reload the page** (F5). This is enough for the prompt enhancer and the other
   panels whose modules are now imported under a version token: the new token
   makes the browser ask for the file again.
2. **Hard refresh** (Ctrl+Shift+R, or Cmd+Shift+R on macOS) if a panel is still
   dead. That bypasses the browser cache for every file, not just the ones with
   a new URL.
3. **Restart ComfyUI** once after updating the pack. The pack asks its own server
   to serve its `.mjs` files with `Cache-Control: no-store` too (the same rule
   the core applies to `.js`), which is what stops this from happening again -
   and that rule is installed at startup.

A panel that cannot load now says so on the button you pressed instead of
failing quietly. The browser console (`F12`) has the reason; a line like
*"does not provide an export named ..."* means the browser used a stale module
file, and step 2 or 3 above is the fix.

## 23. Your own prompt recipes

The prompt enhancer's **Recipe** dropdown decides what shape the enhanced prompt takes:
a replace window needs the discard sentence and the role lines, a reference segment
needs the full block, and so on. The dropdown holds the nine shapes the pack ships.
Your own are loaded through the **Browse...** button beside it.

Your recipes live in a file of your own:

```
<ComfyUI>/user/minimax_h3_motion_director/recipes.json
```

That is outside the custom-node folder, so a pack update never overwrites it. The panel
shows the exact path for your machine under the dropdown, and re-reads the file every
time it opens - an edit needs no ComfyUI restart. **Browse...** lists what is in it
(with how many), shows each recipe's summary, and marks the one that is active; the
button itself lights up while one of yours is the recipe being sent. A recipe you pick
keeps its place in the dropdown, marked `(yours)`, so the panel always shows what it is
about to use.

Start from a ready-made template instead of a blank file: the pack ships one per shape
in `recipe_templates/` (`character_replace.json`, `ref2va.json`, `first_last.json`, ...).
Copy the entry into your `recipes.json`, rename the `key`, and edit the `block` - the
shape instruction the enhancer sends.

```json
{
  "version": 1,
  "recipes": [
    {
      "key": "my_pov_replace",
      "label": "My POV replace",
      "based_on": "character_replace",
      "block": "Shape the answer as ..."
    }
  ]
}
```

`based_on` names the built-in your recipe is a variant of. It supplies everything you
leave out - including the block itself - and, in `Build from images` mode, the assembly
(that part of the block is written by code, not by a model, so a variant of
`character_replace` builds exactly like `character_replace`). Add `"auto": true` if you
want **Auto** to pick your recipe for its tasks; without it, Auto keeps choosing the
pack's own.

If something in the file is wrong - a duplicate key, a `based_on` that is not a recipe,
broken JSON - the panel says so under the dropdown instead of silently dropping the
entry. `recipe_templates/README.md` has the full field reference.

## 24. Story to segments

A multi-segment project is a story spread over N renders, and writing each segment's
prompt by hand is the slowest part of it. The enhancer panel has a **Story to segments**
section (open it, it is collapsed by default) that does that step for you:

1. Describe the **whole story in a few sentences** - who, where, and what happens in
   order. It does not have to be well written; it has to be complete.
2. Set **how many segments** and **how long each one is**. Each segment is one
   continuous take, so cuts happen between segments, and the seconds are snapped to
   H3's frame grid: 7 seconds is 175 frames, 10 segments is about 73 seconds total.
3. Press **Plan story**. One model call splits the brief into a shared `world`
   paragraph (the place, the light, her look - stated once) plus one paragraph per
   segment.
4. The segments are written into the timeline. If the timeline can hold them - a
   **prompt batch** (`t2v`, `i2v`, `r2v` cards) or an empty timeline - the missing
   segments are **created** for you, as cards of that length, exactly as if you had
   added them by hand. Segments that already exist keep their own timing and just
   receive a prompt. A hand-laid video or Character Replace timeline is never re-timed,
   and in **Long-form** (`fl2v`) the beats fill the shots you have (a shot needs its own
   first/last image, so nothing is invented there).
5. Confirm the follow-up: each segment then goes through the normal enhancement, one
   prompt per segment, and the **review list** shows every result before anything is
   applied. Untick what you do not want, **Regenerate** a single segment you do not
   like (it re-runs just that one, from the same original text), **Regenerate all** if
   the run came out poorly, then **Apply selected**.

### Finding it in every mode

The section lives in the enhancer settings panel, which is normally opened by the
**Enhance / Settings** buttons beside a prompt field. Those prompt rows are hidden in
the modes that show a card list or a shot list instead, so the batch panel
(`t2v` / `i2v` / `r2v`) and the Long-form panel each carry their own **Story to
segments** button: pressing it opens the panel with the section already expanded and the
cursor in the story box. That is the whole flow for a batch - describe the story, plan
it, approve the list - without a single segment having to exist first.

The plan itself follows the rules the rest of the pack enforces, because a screenwriter's
instincts break them:

- **One take per segment.** The camera holds or moves inside a segment; a cut is a
  segment boundary.
- **Every beat changes something** - a position, a possession, a state, a distance
  closed. A beat where nothing changes is a wasted render.
- **Each segment ends where the next can start.** Chaining feeds the previous segment's
  final frames in as the anchor, so a segment ends on a stable pose and the next opens
  by continuing it. Never mid-air, unless the fall itself is the point.
- **Her look is stated once**, in the world paragraph and the reference images. It is not
  repeated inside every segment, where it would compete with the references.

What it does not do: it plans, it does not render - you still queue the segments
(Selective Run is the cheap way to try one). It also does not see your source video; the
split is a text task, and `Build from images` is what grounds each segment's prose in
its own frames.

---

## 25. Extending past the footage (generated rows)

A Character Replace chain does not have to end where the source video ends. Any row in
the replace list can be a **generated row** instead of a replace window: it has no source
range at all and renders from its own prompt and references, which is what lets a chain
continue past the last frame of the footage - or break away from it in the middle.

Rows without a kind are replace windows, so every project written before this existed
loads unchanged. To hand-author a generated row, add `"kind": "generate"` and give it a
length instead of a source window:

```json
{
  "kind": "generate",
  "length": 243,
  "prompt": "Continue directly from the previous segment's final frame...",
  "taskType": "r2v",
  "refs": []
}
```

What happens on run:

- It renders with one of H3's **source-free tasks** (`r2v`, or `t2v` for no character
  references). A row that asks for `v2v`/`rv2v` - tasks that read source pixels - is
  rendered as `r2v` instead, with a warning: it has no source window to give them.
- Its length is snapped to H3's frame grid (17k+5) exactly like a window's, and it is
  **never clipped** by the source's frame total - that is the whole point of it.
- The rows run and export in the order the table shows them, so a chain can be
  `window, window, generated, window`.
- **Continuity comes from the previous segment's frames** (Motion Context), not from the
  footage. That carries the room, light, wardrobe and grade across the join, but not the
  pose: a replace window after a generated row still starts from its own source frame, so
  finish the generated part on a pose close to the next window's opening one.
- **Audio** follows the row order. In **source audio** mode each window keeps its own
  track and a generated row takes the source audio at its insertion point - past the end
  of the footage there is none, so those frames are silent. Switch the project to
  **generate** audio if you want the model to produce sound there.
- If a generated row still carries an old Character Replace window (a row switched to
  generated in the table), the row kind wins, the window block is ignored, and both the
  plan and the pre-run **Validate** say so instead of silently rendering the window.

In the panel, every row has a **kind** selector at its start:

- **`window`** - the default: a masked Character Replace over a range of the source.
- **`generate`** - the row owns no source range and renders from its prompt and
  references. **+ Add segment** appends one after the last row, using the same len
  field as **+ Add after**. Its window controls (mask source, render mode, mask dir /
  SAM3 prompt, grow, feather, lead, audio, continuity, refmod, Test mask, Pick
  subject) are hidden, because none of them apply - and the row is labelled **G**
  instead of **W** so a list of windows does not read as one window having lost its
  range. Switching a row to `generate` switches its Replace off; the mask recipe stays
  on the row and comes back if you switch it to a window again.

Two readouts stay honest about the mix:

- **covers n%** counts the *windows* only. A generated row does not cover the source,
  it is added to the output, so it never pushes coverage past what the footage allows.
- a second badge reports the generated side: **`n generated · time`**.
- **Replace ON n/total** counts windows too: a generated row has no Replace switch to be
  on or off, and counting it made the header read `1/2` (and the master switch
  half-filled) while every window was in fact enabled.

A generated row is presented as part of the job it sits in: it keeps the panel style of
its windows (the job's task decides the layout, not the row's own source-free task),
and its control line reads the same way - the row's task choice where a window has its
mask controls, then `cont`, then the kind selector last. Its explanation is the row
tooltip rather than a sentence in the control line.

**Long-form replace** re-cuts the windows, and generated rows are not part of that
layout, so they are **kept** and put back where they were (counted in windows, so one
that sat between window 1 and 2 still does). The preview line and the completion
message both say how many were kept.

Not there yet: per-row audio for a generated row. In a **generate**-audio project it
gets model audio; in a **source**-audio project it takes the source audio at its
insertion point, and past the end of the footage it is silent.

### How a generated row joins the segment in front of it

A generated row renders from its prompt and references, and the one thing it cannot do
by itself is start where the last segment ended. Two controls decide that:

- **`cont`** - open from the previous segment's last rendered frame. For a replace
  window this is a `<Picture N>` anchor with an "open matching that frame" instruction;
  a generated row gets the same anchor.
- **the row's own task**, which a generated row picks with the small selector next to
  its note:
  - **`r2v`** (default) - continues from the previous segment as *context*: the previous
    frames steer the render, plus the `<Picture>` anchor above. The opening pose lands
    near the previous last frame, not exactly on it.
  - **`i2v`** - locks that frame as this row's **literal frame 0**, which is a real
    join rather than a near-continuation. If the previous segment has no render and no
    cache yet, the row falls back to its own first reference image and logs a warning.

So: `i2v` when the seam has to be exact (the row picks up the pose the last segment
ended on), `r2v` when the row is a new beat and a small settle at the start is fine.
A window after a generated row keeps its own source frame as frame 0 - that join is the
row's business, not this one's.

---

## 26. Frame rate: 24 fps is the model's rate

MiniMax H3 has **no fps input**. A frame count *is* a duration, and the model's joint
video+audio latent is defined at a fixed **24 fps** - ComfyUI's own H3 nodes say so (the
17k+5 grid is "at 24 fps", and a ref2va reference video is specified as "reference video
frames at 24 fps").

So a project whose frame rate is not 24 hands N frames of, say, 30 fps footage to the
model as N model frames, and they come back as 24 fps content. The one consequence the
pack cannot undo is **speed**:

- the **picture plays 25% slow** against the footage (4.57 s of action shown over 5.71 s).

Everything else is kept at the model rate so the pack's own files agree with each other:
the segment audio is measured against the picture at 24 fps, and the merged export is
stamped 24 fps like the per-segment clips. (Before, the audio was trimmed at the project
rate - a silent tail on every clip - and the merged export played 25% fast.)

**Validate** warns about this (`frame_rate_not_24`) whenever the project rate is not 24,
says which direction the speed will be off, and recommends a 24 fps source. The run
report repeats it as a one-line note.

What to do about it:

1. **Use 24 fps footage for the video whose character is being replaced** (recommended).
   Then the model's rate *is* the footage's rate and the timing is exact. If the footage
   is not 24 fps, one ffmpeg pass converts it and keeps the duration, so the audio stays
   in sync: `ffmpeg -i in.mp4 -vf fps=24 -c:a copy out24.mp4`. Frame-keyed masks have to
   be converted with the same filter (regenerate them, or rebuild the folder and use the
   mask's *offset* field to re-base the numbering), because the mask is addressed by
   source frame. Window numbers change size by the same ratio: a 30 fps frame 1000 is
   frame 800 at 24 fps. SAM3 windows need nothing - they re-segment whatever frames they
   are given.
2. **Leave it and accept the slow motion.** The render is still valid and everything the
   pack writes is now consistent, but the picture runs 25% long against the footage.
   Setting the project rate to 24 does *not* change that: the window boundaries move (a
   "5 s" window becomes 120 frames, not 150) and the timeline is addressed in the new
   rate, but the motion stays 25% slow, because the model still receives 30 fps frames as
   24 fps ones.

Plan rows that only *generate* (the `G`/generate rows of a section 25 chain) have no
source footage at all, so they are unaffected - their length is already model frames.

One place still counts in the project's rate: a *duration* you type for a generated shot
(**Long-form**, **Mixed**, shot groups). The renderer turns it into frames with
`duration × project rate`, so a "5 s" shot in a 30 fps project is 150 frames where the
model's own formula expects 24 fps - 6.25 s of picture - and the panel's own duration
readout can disagree with what gets rendered. Those jobs have no source footage to stay in
step with, so **set the project frame rate to 24** for them: the durations you type then
mean what they say.

## 27. Settings: machine profile, baselines, export, cache, diagnostics

The **设置 / Settings** gear sits at the right end of the Director's top bar (next to the
time bounds). It is *app-wide*: one settings file per ComfyUI user, shared by every
Director node and every workflow - not a per-project widget. The prompt **Enhancer**'s own
button next to the prompt box is now labelled **扩写设置 / Enhancer…** so the two can never
be confused.

### Machine

Everything here is **detected, not typed**:

| Row | Meaning |
| --- | --- |
| GPU | device name and compute capability |
| VRAM | total and *free right now* |
| Profile | which baseline tier the numbers came from (`Compact` ≤12 GB, `Mid` ≤20 GB, `Large` ≤32 GB, `Workstation` 33 GB+) |
| Pack / ComfyUI, Runtime | pack version, ComfyUI version, Python / torch / CUDA |
| Attention backends | which of `sdpa`, `sage`, `comfy_kitchen` (int8 attention), `xformers`, `flash_attn`, `triton` actually import *on this machine* |

Two things are worth knowing:

- **Free VRAM matters as much as total.** When something else holds most of the card (an
  Ollama server holding 16 GB of a 24 GB GPU is the classic case), the recommended profile
  drops one tier and says why. *Detect again* re-reads it.
- **"Installed" and "usable" are different questions.** SageAttention is compiled against
  one torch ABI and ComfyKitchen's int8 kernels against specific SM versions, so a backend
  that imports on one machine can fail on another. The backend table is the honest answer,
  and the panel then compares it with the workflow: if a node in the *current* graph asks
  for a backend this machine cannot run (`attention_backend`, `dense_backend`, `engine`
  widgets), you get a warning naming the node *before* a render finds out - instead of a
  CUDA crash thirty minutes in.

*Manual override* (device index, VRAM override) exists for a multi-GPU box or a driver
that reads wrong. Leave the override at 0 unless you know better than the driver.

### Baselines

Starting points **for new content only**: a new segment, a new card, a new long-form shot.
Existing segments keep their lengths and existing projects keep their size - changing them
would invalidate the segment caches and the Resume Done marks, so the pack never does it
behind your back.

| Setting | What it starts |
| --- | --- |
| Aspect ratio, Megapixels | the canvas for a new project (fixed W×H overrides the pair; `0` + `0` means "derive") |
| Default segment frames | how long a new segment is (on H3's 17k+5 grid; the seconds readout shows what that means) |
| Max frames per segment | the length you get warned above (frames drive both time and VRAM) |
| Reference image long edge | how far reference images are downscaled (`0` = never) |
| Segment guidance / overlap | continuity defaults for new timelines |
| Clear VRAM between segments, Export mode | run defaults |

**Apply to this project** writes those values through the panel's own output controls:
canvas, export mode, continuity, `clear_vram_between_segments`, `verbose_logging`, and the
default length used by segments created from then on. It never re-times existing segments,
and the status line says what it did.

**Reset to detected** puts the baseline numbers back to the detected profile.

#### Practical limit: segment length is what makes a render fit

Frames cost memory twice over - the latent/activation grows with the frame count, and H3's
attention grows with its *square* - and an attention kernel can need one large contiguous
allocation on top (SLA's sparse path asks for its workspace in a single block: ~3 GB at the
lengths below). A real over-budget run looks like this, on a 32 GB card at 1376×768 with two
full-size references:

```
SLA kernel failed (engine=comfy_kitchen) ... Allocation on device 0 would exceed allowed memory
Currently allocated: 22.19 GiB   Requested: 2.99 GiB   Free (CUDA): 63 MiB
-> SLA falls back to dense, dense needs 1.59 GiB more -> Motion Director ran out of VRAM
```

So treat the tier numbers as a starting point for a *plain* graph, and halve them when you
stack attention patches (SLA / Spectrum / ComfyKitchen int8), carry several references, or
keep references at full resolution (`ref_max_size` = the output long edge means "do not
scale them down at all"). Measured on the same 32 GB card: 311-frame segments at 1376×768
with two 1376 px references sit within a few hundred MB of the ceiling, while 175-frame
segments at the same settings have room to spare.

If a render does hit it, the cheapest order to try is: (1) shorten the long segments, (2)
lower `ref_max_size`, (3) lower the resolution, (4) free GPU headroom
(`PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` and a larger `--reserve-vram` help a
single large workspace allocation fit), and only then (5) turn SLA off for the long
segments - its fallback to dense attention is the *more* expensive path, which is why the
error arrives in two stages.

### Run & UI

Render behaviour and interface preferences that have no per-project home: auto-save the
workflow after each segment (Resume needs a saved workflow to keep its Done marks), keep
models resident between segments, verbose logging, default export mode, language, live
preview, preview audio, and the cache warning size.

The toolbar's language button and this setting are the same value: whichever you use, the
other follows.

### Export: the workflow inside the video

ComfyUI writes the **workflow** and **prompt** tags into every video its own `Save Video`
node produces (unless it was launched with `--disable-metadata`). That is how dropping the
file back onto the canvas restores the graph, and for this pack it restores the whole
project - the timeline, every segment prompt, the references and the sampling settings all
live in the workflow.

Those same two tags also carry your prompt text, model and LoRA names and local paths, so
they travel with anything you share. The **Export** tab decides what happens:

| Choice | Behaviour |
| --- | --- |
| **Auto** (default) | follow ComfyUI: embed unless `--disable-metadata` is set |
| **Always embed** | embed even when ComfyUI was launched with that flag |
| **Never embed** | strip both tags when saving |

The row under it says what is in effect right now and why, so a missing tag is explainable
instead of mysterious. The choice applies to **this pack's save route** (the Results page's
save button and the auto-save); a save node in your own graph, such as the core
`Save Video`, decides for itself.

**Strip metadata from an existing file** cleans a file that was written before you chose:
enter a path relative to ComfyUI's output folder (e.g.
`mm-director/2026-09-19/143710_00001_.mp4`) and it writes a `_clean` copy with the streams
copied, not re-encoded. Only files inside the output folder can be cleaned.

Turning the tags off costs nothing you cannot get back: a Director project is also
recoverable from its exported plan / `.h3proj.json` and from the segment caches.

### Cache

Every cache the pack writes, with real sizes, per project node:

| Kind | What it holds |
| --- | --- |
| Segment caches | rendered frames, per-segment audio and the run manifest (`minimax_seg_cache`) |
| Motion context | the Motion Context and AV latent caches (`minimax_motion_context_cache`) |
| First-pass | first-pass latent caches (`minimax_first_pass_cache`) |

Rows are sorted biggest first and show the run state (`rendering` / `stopped` / `done` /
`idle`) plus how many segments are marked done. **Clear** deletes one project's cache,
**Clear <kind>** deletes all of them; both need a second click and refuse while that
project looks like it is rendering right now. Deleting a segment cache only costs a
re-render - it never touches your rendered videos, which live in the output directory.

This is the place to look when a long chain has eaten tens of GB of disk (a 1400×800
project can hold ~4 GB *per segment*).

### Diagnostics

**Copy** or **Download JSON** gathers the pack version, ComfyUI/Python/torch/CUDA
versions, the detected machine and backend probes, the stored settings, cache totals and
run states, the current project's shape, the workflow-backend warnings, and the last run
report. Paste it into a bug report instead of a screenshot of the console.

### Where the file lives

The settings live in one JSON document under ComfyUI's user directory
(`.../user/minimax_h3_motion_director/settings.json`), next to the Director **Presets**.
It is written atomically, and a corrupt file is reported rather than silently reset - so
"my settings vanished" cannot happen quietly. Deleting the file restores the detected
defaults.

**Presets** and **Settings** are different things on purpose: a preset is a settings
*package* you apply to one project (sampling, continuity, output), while Settings are the
machine-level defaults every new project starts from.

#### Keeping two machines in step

The same project rendered on a 24 GB card and a 32 GB card wants different starting
points, and their attention backends differ. Nothing in the workflow file has to carry
that: each machine keeps its own `settings.json`, the project keeps its own numbers, and
the panel tells you when a workflow asks for a backend the machine cannot run.

#### What Settings never does

- It never rewrites an existing project (only *Apply to this project* touches one, and it
  says so).
- It never changes `seed`, prompts, segments or task type.
- It never edits the node's wiring - backends are still selected by the nodes in your
  graph; Settings only tells you whether they will run here.
