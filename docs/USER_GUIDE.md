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
4. **Add windows** with the `+ Add after` / `+ Add at playhead` buttons (default 5 s each, up to 20 s; lengths auto-snap to the H3 frame grid). Rows may overlap or be out of order - list order is render/output order.
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

## 16. Postprocess: Global Refine, Upscale and Face Refine

![Post-processing](images/tutorial/08-postprocess.webp)

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

### Recommended production order

```text
Low-resolution first pass → Check content/motion/composition → Reroll failed segments → Lock the shots → Global Refine / Upscale → Face Refine → Final Result
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
