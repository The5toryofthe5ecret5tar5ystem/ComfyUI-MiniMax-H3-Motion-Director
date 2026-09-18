# MiniMax H3 Motion Director.  [English](README.md) | [简体中文](README_zh.md)

![Version](https://img.shields.io/badge/version-v1.8.4-2ea44f)
![License](https://img.shields.io/badge/license-GPL--3.0-blue)
![ComfyUI](https://img.shields.io/badge/ComfyUI-custom%20node-6f42c1)

> **Maintained fork** — upstream features plus a **per-scene Audio Room**, **Re-ground segments (anti-drift)**, an **in-process prompt enhancer** (no Ollama, no API key), a big **Generation-tab UI performance fix**, **newer-ComfyUI compatibility**, **CI**, and a ready-to-run **ref2va example workflow**. See [✨ Improvements in this fork](#-improvements-in-this-fork).

**One Director. From a single MiniMax H3 shot to a complete multi-segment video project.**

Here is  tutorial, or you like to read the introduction first? / 下面连结是教学，或者你想先往下看看介绍?

[English](docs/USER_GUIDE.md) | [简体中文](docs/USER_GUIDE_zh.md)

Build `T2V / I2V / FL2V / R2V / V2V / RV2V` shots in one production interface, mix generation methods segment by segment, carry visual and generated-audio context across shots, rerun only the segments that need work, manage reusable assets, preview the pipeline live, refine the result, and export the final video without turning the ComfyUI graph into a wall of nodes.

> Current version: **v1.8.4**

![MiniMax H3 Motion Director — Mixed Mode](docs/images/hero-mixed-selective-run.png)

The screenshot above shows the native **Mixed** timeline: five segments using different generation paths, per-boundary visual/audio continuity controls, and **Selective Run** enabled so only chosen segments are regenerated.

---

## ✨ Improvements in this fork

Maintained at [`The5toryofthe5ecret5tar5ystem/ComfyUI-MiniMax-H3-Motion-Director`](https://github.com/The5toryofthe5ecret5tar5ystem/ComfyUI-MiniMax-H3-Motion-Director), on top of upstream `j955229/…`.

### v1.8.4 — An enhancer that runs in ComfyUI, and writes the prompt from your images

**The prompt enhancer no longer needs a server.** It loads a GGUF model from your
own `models/LLM` folder with llama.cpp and runs inside ComfyUI's process — no
Ollama, no API key, no second thing to start. The model list is what is actually
on disk, the recommended Qwen3.8 27B abliterated is a one-click download whose
size is shown before anything is fetched, and a download reports real progress.
Nothing heavy is imported until you use it, and a card that cannot host the model
degrades down a VRAM ladder (fewer GPU layers, then a smaller context) instead of
raising. `Unload model` hands the VRAM back for a render — meaningful here
because the model lives in ComfyUI's own process. See
[`docs/PROMPT_ENHANCER_LOCAL_SETUP.md`](docs/PROMPT_ENHANCER_LOCAL_SETUP.md).

**`Build from images` writes the prompt instead of rewriting it.** A port of the
external Character Remake workflow ("Masked Motion + QwenVL"), which handled
character replacement reliably where rewriting did not — not because its prompt
was better, but because the language model was never asked to *write the
structure*. Two narrow vision calls answer two narrow questions ("what does this
character look like", "what happens in this source window") and this pack's own
code glues the answers into the section block, so every header, role line,
retention rule and the discard sentence is code-owned and cannot be reordered,
forgotten or invented. Identity sees only the reference slots, action only the
source frames. Six recipes are covered (character replace with and without a
RefMod, ref2va, source edit, start image, first/last), including the i2v/fl2v
endpoint frames the panel never used to send — a caption is the only way that
prose can agree with frame 0.

**A RefMod window can have its `wardrobe:` line filled in.** A mod reaches the
Director as an unnamed latent blob appended *after* text encoding, so the prompt
never described it and the one line the guide requires stayed empty.
`RefMod character` decodes the mod's own latents with the H3 video VAE, captions
them, and answers with a wardrobe line plus at most one 2-4 word clue. Never a
description of her face: prose about identity fights the reference instead of
helping it.

**And the performer being replaced can be hidden from the action caption.** A
caption model looking straight at her occasionally volunteers her description,
which then argues with your replacement reference for the rest of the prompt.
`Hide the source performer` inverts the subject region of those frames before
they are captioned, so nothing about the identity survives — and everything the
caption actually needs (silhouette, pose, camera, room) does.

**Plus:** `H3 prompt rules (compact)` and a `Recipe` selector that names the
target shape explicitly; the panel reports which backend actually loaded
(CUDA / Vulkan / Metal / CPU) and warns when a GPU build never mapped into the
process; and four failures on the way here are fixed — `Enhance` returning a 500
on every click, vision mode dying on Qwen3-VL's Jinja guards, caption mode being
unable to send *no* system turn, and an enhancement that finished without
changing the prompt in the box.

### v1.8.3 — An upscaler that stops reloading, and UI changes that arrive

**The learned-latent upscaler stops re-reading its own checkpoint.** Every call
re-read the file from disk and redid the float8 → fp16 conversion from scratch.
The last two decoded state dicts are now cached in CPU RAM, keyed on path, size
and mtime, so swapping the file still invalidates them.

**And its VRAM is actually returned.** Its cleanup dropped the model and then
called `empty_cache()` while two device tensors were still live, so the memory was
never released — `empty_cache()` only frees blocks that are already unused. Every
device reference is now dropped and collected first, the same fix the segment
cleanup needed.

**Optional: keep the upscaler resident.** The upscale stage runs after the H3 DiT
is unloaded, so an uncached call is a full load → free cycle stacked on the DiT's
own unload and reload. `latent_upscale_cache_model` (Global Refine → Upscale)
skips that churn for multi-segment runs, at the cost of holding its VRAM for the
rest of the session while sharing the card with the reloaded DiT. Off by default,
with the trade-off written beside the checkbox.

**The v1.8.2 UI actually appears now.** Two modules changed in v1.8.2 without
their `?boot=` cache token being bumped, so browsers kept running the cached
copies — the new controls were in the file on disk, served by ComfyUI the whole
time, and nothing ever asked for them. Both tokens are bumped.

### v1.8.2 — Character Replace that chains, and a masked pass that actually replaces

**Adjacent windows now chain.** Replace windows are independent re-renders, so both windows at a boundary are guessing at the same source frame, and the regenerated subject visibly popped when two guesses met. A window can now open from the **previous window's last rendered frame**, injected as an extra `<Picture>` reference with a prompt line naming it, so the subject starts in the pose the last window ended on instead of a fresh one. It is on by default, a no-op on the first window, and switchable per window (a **cont** checkbox) for deliberately gapped windows. Cache-reused windows record their tail too, so a resumed run keeps chaining.

**Cover the whole clip in one click.** A long clip no longer needs windows added by hand: **Long-form replace** fills the source with contiguous windows at the length you set (frames or seconds), the last window taking the remainder (a sub-second tail folds into the previous one), the first window's replace settings copied to all of them, continuity switched on across the board, and Export mode set to *by segment* - one named action instead of four settings in three places, with the outcome stated before it runs. Export each window on its own and one bad window can be re-rendered without touching its neighbours, which is the long-form Character Replace workflow.

**The masked (inpaint) path actually replaces the subject now.** A 97-frame inpaint window reported "masked replace ready" with a 0.71-mean noise mask attached, yet came back frame-for-frame identical to the source (mean |diff| 8/255, against 51+/255 for the same window in anchor mode). ComfyUI starts masked sampling from `latent_image + noise`, so the encoded source left inside the regenerate region is a strong hint: the denoiser refines the original performer instead of inventing the replacement. The regenerate region is now erased before the latent reaches the sampler, so it starts from pure noise there; the keep region still carries the source, so the background stays pixel-exact. A mask that does not line up with the latent is ignored rather than mis-aligned.

**SeedVR2 works on a live install.** ComfyUI imports custom-node packages at startup but does not keep `custom_nodes` on `sys.path` when a node later executes, so the lazy import raised `ModuleNotFoundError` and SeedVR2 quietly downgraded to the first pass. The directory is now added back through `folder_paths` before the import.

**Plus:** Clear VRAM no longer unloads twice per boundary, and keeps the DiT resident for a one-segment selection from a long timeline; refine failures name the model holding VRAM; the external-patch skip is visible in the panel instead of only appearing at render time; the Segment preview plays the window's own source audio in source/keep modes instead of coming up silent; and result audio streams from a Blob URL instead of a `data:` URL that crackled on every seek.

### v1.8.0 — VRAM that actually frees, plus a longer-clip refine

**Temporal split for Global Refine.** `temporal_split` re-samples the upscaled video one overlapping time chunk at a time and cross-fades the overlaps, so peak VRAM is bounded by a single chunk instead of the whole clip — which is what made long clips un-refinable. Chunk length and overlap snap to H3's 17-frame grid (`temporal_chunk_frames`, `temporal_overlap_frames`). It composes with Tiled refine (temporal outer loop, spatial inner), so temporal and spatial splitting can be combined on a small card. Audio is carried through untouched. Scoped by design: it is only used when there is no Motion Context repinning and no H3 noise mask, since only then does conditioning apply uniformly to every chunk without per-chunk time re-anchoring. The cross-fade weights sum to 1 per token, so with an identity sampler the stitch is lossless — the property the test suite pins.

**SeedVR2 upscaler.** `seedvr2` joins the pixel-space upscale methods. It is temporal-aware and much crisper than the latent upscalers, but slower and heavier: it loads its own 3B DiT + VAE (~6 GB on first use), so the H3 model is unloaded first and reloaded afterwards. It keeps aspect ratio, and the caller resizes to the exact target. The post-process panel now probes for it at runtime and tells you before a run if the node is missing, instead of failing inside the upscale stage.

**Clear VRAM Between Segments now does what it says.** Three separate bugs made this toggle look inert, and users reported it as "not working":

- A failure in the *first* cleanup step cancelled every step after it, so one raising call silently disabled the whole cleanup. Each step is now isolated.
- The end-of-segment cleanup always unloaded the model, so a single-segment run dropped it and immediately reloaded it for Global Refine / Face Refine — wasted work, and on a low-VRAM card that reload could OOM where staying loaded was fine. It now keeps the model loaded when there is only one segment.
- Everything was silent. A model ComfyUI *cannot* unload (its wrapper was collected, and `free_memory` skips dead entries) was reported only to the log, so "freed nothing" looked identical to "worked". Cleanup now reports into the node's execution report under a **VRAM** heading, naming the failure or the stuck model so you know which custom node is holding it.

The bundled example workflows also shipped `clear_vram_between_segments: false`, the opposite of the declared default — they now ship `true`.

### v1.7.0 — render once, then iterate on post-process without re-rendering

**Reuse the first pass.** Turn on **Reuse cached first pass** and the raw first-pass AV latent is written to disk keyed on everything that produced it *except* post-processing. Re-run with the same seed, prompt, references and resolution but different Global Refine, Face Refine or Audio Room settings and the expensive H3 sample is skipped — a 107-frame r2v render measured 363 s down to 33 s on reuse. The key only invalidates when the seed, prompt, references, resolution, sampler or model change, because those genuinely change the first pass. Every hit and miss is logged, and a settings snapshot plus a field-level drift diff explain any surprise miss.

**Tiled refine.** The Global Refine second pass can now run as overlapping spatial tiles (`tile_size`, `tile_overlap`), so a large upscale fits in less VRAM. Each tile is sampled alone with its own keyframe crop, brightness-matched back to the input, and stitched with a linear cross-fade on the interior edges; audio is taken from the first tile.

**Compare raw vs processed.** **Export comparison** writes `<prefix>_raw_firstpass` and `<prefix>_postprocessed` so the unprocessed and processed videos can be A/B'd side by side.

**Refine opt-out on an external patch.** `allow_refine_on_external_patch` lets the second sampling pass be skipped when a patch already supplied the output.

**Latent continuation (early test).** An opt-in, experimental `latent_continuation_enabled` port of the community "continue in latent space" joiner: the previous segment's final latent is injected into the next segment's sampling stream and locked with a nested H3 noise mask. Flagged EARLY TEST — not for production yet.

### v1.6.0 — RefMod identity references, and a Results player that streams

**A RefMod can now carry identity across a whole chain.** Connect `Apply H3 RefMod` and the Director harvests its reference blocks and appends them to every segment's conditioning — no headshot, no character sheet, just a saved `.safetensors` mod. The mod is attached to the DiT only: it is never presented to the text encoder, and no `<Picture n>` label is created for it, so the prompt names the *subject and action* and lets the reference own appearance.

**Fixing it meant finding it.** The wiring had been added to `nodes/director.py`, which never runs. Three classes share the name `MiniMaxH3MotionDirector` and chain by inheritance, and `__init__.py` imports `director_output` last, so the live `execute` belongs to `director_inputs`. The socket was declared, the wire connected and `/history` showed the reference attached — but the live execute had no such parameter, so ComfyUI dropped it into `**kwargs`. The same probe found `audio_refine_enabled`, `audio_refine_steps` and `audio_refine_denoise` declared but never bound. A test now walks the MRO for the first `execute` that names its parameters and fails if any declared input is unbound, and the Director prints any input it receives but did not declare instead of discarding it in silence.

**The mod carries face and body, not clothing.** Its latent is roughly a 96 x 54 thumbnail per frame — plenty for face structure, nothing like enough for a garment's cut and seams. That is a physical limit, not a bug, so clothing gets its own channel: a `wardrobe:` prompt section, or a full-resolution picture reference, with the prompt assigning each source its job. The example ships a usage guide covering all of it, including the ranked fixes for when a clothing reference starts handing you its model's face.

**Results streams instead of shipping base64.** Finished segments and final results are encoded to a small all-intra H.264 clip in ComfyUI's temp directory and streamed over `/view`. One 243-frame segment measured ~11.9 MB of base64 JPEG parsed synchronously on the browser main thread; the clip is ~2.5 MB with zero websocket cost. All-intra is deliberate, so every frame is a keyframe and a seek lands on the exact frame.

**Audio Refine tuning is free now.** The room and level chain runs once at final output assembly, never per segment, so `per_segment` is gone and changing a room invalidates no segment, context or audio cache.

**New example:** [`Minimax h3 Director - ref2va + RefMod example workflow 1x4s.json`](example_workflows/) — one 4 s shot for fast identity iteration, with the usage guide shipping inside the workflow.

### v1.5.0 — Audio Room: a real space, chosen per scene

**Generated audio no longer has to sound like a camera mic.** A new **Audio Room** column in the postprocess panel places the model's audio in an actual space. Pick a named room — `bedroom`, `bathroom`, `bar`, `office`, `car`, `hall`, `cathedral`, `outdoor` or `dry` — and all six reverberation parameters are set for you; choose **Custom** and dial them yourself: reverberance, HF damping, room size, stereo depth, pre-delay and wet gain. A separate **Level** section adds normalise and gain.

**Per scene, not per project.** A scene can declare its own space with a `room` field in the timeline, so a bathroom scene and a bedroom scene in one render stop sharing a single acoustic setting.

**It cannot invalidate a cache.** The chain runs at output assembly, downstream of the segment audio cache, and model audio is processed *before* the merge so a merged export still gets one space per scene. Turning a room on or changing it invalidates no segment, no context cache and no finished render — which is why it stays out of the segment cache fingerprint.

**Stereo is preserved, and failures are loud.** Built on SoX, which the render toolchain already shells out to (auto-detected; `pacman -S sox` on Arch/CachyOS). It replaces a third-party effects node that read `waveform[0, 0]` and returned **mono** from stereo input, returned the original audio silently on every failure, and round-tripped through 16-bit PCM. Here the channel count and sample count are preserved, and a track that cannot be processed is left dry and *named in the report* rather than passing through as though it worked. It needs **SoX** on PATH and the **`soundfile`** Python package — soundfile is not a ComfyUI dependency, so it is declared in `requirements.txt` rather than assumed.

**Never-spoken guard.** H3 generates audio from the same text it renders, so a bare token or quoted phrase sitting in shared reference material is a shape it can read aloud. A checkbox on the shared prompt block appends an explicit control line marking that block as reference-only.

**Resume correctness pass.** Four separate plan builders — the `prompt_batch`/gen path, `fl2v`, `mixed` and `external_groups` — were each dropping the resume flag, so Resume quietly restarted from segment 1 on those timeline shapes. The engine now decides the start point rather than the dialog, the preview and its audio check no longer have blind spots, and a stopped run no longer stays marked `running`. A structural test now scans every builder for the resume fields, which is how the fourth instance was found.

**Other fixes.** A CUDA **out-of-memory** in the external sampler was reported as "the sampler does not support MiniMax H3 inputs", sending you after the wrong problem; OOM now surfaces as OOM. The Replace-windows timeline loop ran at display rate for as long as a node sat on the canvas, even while idle; it now drops to a slow poll when nothing is happening and returns to full rate on hover, and the frame handle is stored so it can actually be cancelled.

### v1.4.0 — partial export on Stop, undo/redo, presets, sweeps

**Export the part that finished.** Pressing **Stop** no longer throws the run away. The engine finishes the current segment, assembles everything already completed into a real partial video, and records the run as `stopped` — leaving the resume manifest intact, so **Resume** still continues from the first unfinished segment. Stopping before *any* segment completes still cancels cleanly. ComfyUI's own **Cancel** button is unchanged: it aborts immediately and the segment caches make Resume work from there.

**Undo / redo for the timeline.** `Ctrl+Z` / `Ctrl+Shift+Z` (`Ctrl+Y` also works) plus toolbar buttons. History is bounded at 50 steps and recorded from the single commit funnel, so every timeline edit is covered — including applying a preset. It deliberately does not fire while you are typing in a text field, so prompt editing keeps its own undo.

**Named presets.** Save the current sampling / continuity / output settings under a name and re-apply them in a later project (**Presets…** in the output bar). A preset stores *settings only* — never your segments, prompts, task type or seed — so it cannot quietly rewrite a project. Shared references are opt-in behind a checkbox. Stored server-side in a single atomic JSON index; a corrupt index fails loudly instead of being silently replaced by an empty one.

**Multi-seed sweep.** Render the same project N times with N different seeds in one click (`Takes` + **Sweep**) and compare the takes. Take seeds are hashed rather than `seed + 1`, because consecutive seeds can produce visibly correlated results. Every take forces `resume: false` — without that, each take would reuse the first take's segment caches and the sweep would spend N× the GPU time producing one video.

**Fewer surprises before you queue.** **Validate** runs a pre-flight check (empty timeline, H3 frame-grid violations, missing references or audio, Character Replace setup mistakes, unknown source length) and reports problems in the output bar *before* a run starts. **Preview prompt** shows the exact text the model receives, including what the engine appends. **References…** cross-checks which reference slots your prompts mention against the files actually attached. Task types and segment modes now read in plain language, and segment length shows its seconds and snapped H3 frame count.

### Re-ground segments — stop visual / color drift on long runs

Long multi-segment chains can drift in color, contrast and identity after several hops. **Re-ground** marks a segment to re-anchor its continuity context at the **chain root** (the clean start of the job) instead of the immediately-previous segment — resetting accumulated error without breaking the visual flow.

- Every segment boundary in the timeline shows **two** small circles: the top `↔ / ×` is the existing context link; the **bottom `R` circle** is the Re-ground toggle.
- **Left-click** the bottom `R` circle to turn it on (it turns **amber**); click again to turn it off. Right-clicking either circle opens the boundary menu, which also contains **⟳ Re-ground**.
- A Re-ground segment stays fully continuous with the project but grounds itself on the root reference — use it every 3–5 shots on long jobs, alongside **Latent Scale Lock** and **Color Re-anchor**.

### Generation-tab / timeline performance

- Fixed a long freeze (up to ~30 s) when opening the Director modal on projects with large per-segment prompts: prompt truncation now uses binary search (`fitCanvasText`) instead of an O(n²) char-by-char `measureText` loop — measured ~525× faster on the draw path.
- Cheap rendering wins (`content-visibility` on batch group cards) and the Re-ground toggle circle shipped in the same pass.

### Compatibility with newer ComfyUI

- H3 node execution now uses keyword arguments, matching the ComfyUI core node API after the `io.Schema` / `ComfyNode` rewrite (v0.34.x-era builds). This removes the `unsupported operand //: 'str' and 'int'` crash those builds hit with the upstream positional calls.

### Stop / Resume run controls

Long jobs can be interrupted by the **Stop** button, a crash, or a ComfyUI restart. **Resume** continues the job instead of restarting it: finished segments are kept as on-disk caches, and Resume reuses every segment whose cache still matches the current project, re-sampling only from the first segment that does not match. Content-affecting settings (resolution / megapixels / ref-max, prompts, references, shot frame ranges, continuity, Color Re-anchor) invalidate the affected caches; sampling knobs (seed, steps, sampler, CFG), export bitrate/CRF, and the Global/Face Refine toggles do not. **Start Over** clears the caches for a guaranteed fresh run. Full rules and a settings table are in the [User Guide](docs/USER_GUIDE.md).

Pressing **Resume** first opens a cache-check dialog: it shows how many segments are cached, exactly where the run will continue, and - when a cached prefix cannot be reused - the per-segment reasons (resolution / megapixels, prompts, references, Color Re-anchor, etc.), with a button to restore the cached settings onto the node, a choice of start segment, and Start Over. The analysis is authoritative: it rebuilds the plan and runs the same fingerprint check the engine uses.

### Per-segment audio in Results

Each finished segment's audio is pushed to the Results player as soon as that segment completes, so the **Segment** view has real, aligned sound while the job is still running - not only after the whole run finishes. Multi / Final views keep the whole-run combined audio.

### Global Refine safety guard

Global Refine is now skipped automatically (keeping the first-pass result) when the diffusion model carries an external attention patch such as SLA or Spectrum, which would otherwise be corrupted by a second guidance-distilled sampling pass. An opt-out is available (`allow_refine_on_external_patch`) for advanced users who know the patch is compatible.

### Tests + CI

- Python unit/contract tests run from any directory without a live ComfyUI (`python -m pytest`, 807 tests); a CI workflow (`.github/workflows/tests.yml`) runs the Python suite and the standalone frontend tests on every push/PR. See [`docs/FORK_REVIEW_2026-09-05.md`](docs/FORK_REVIEW_2026-09-05.md) for the full engineering-pass notes.

### Example workflows

- [`example_workflows/`](example_workflows/) ships four ready-to-run samples, each documented in [`example_workflows/README.md`](example_workflows/README.md):
  - **ref2va** (`Minimax h3 Director - ref2va example workflow 3x7s.json`) — 3 x 7 s, with a bundled AI-generated placeholder headshot + character sheet.
  - **ref2va + RefMod** (`Minimax h3 Director - ref2va + RefMod example workflow 1x4s.json`) — a single 4 s shot with identity carried entirely by a RefMod, and the full usage guide in-workflow.
  - **t2v** (`Minimax h3 Director - t2v example workflow 5x7s - elf vs giant orc.json`) — 5 x 7 s, prompt only, no references.
  - **character replace** (`Minimax h3 Director - character replace example workflow 3x7s - elf vs giant orc.json`) — 3 x 7 s ref2va replacement.

---

## Models used by the example workflow (defaults)

The bundled `Minimax h3 Director - ref2va example workflow 3x7s.json` opens routed to the **REF2VA** model (`ImpactSwitch select = 2 → MODEL_2`). Place the files under your ComfyUI `models/` folder using the subfolders below (paths match the workflow's model subgraph):

| Role | Place in `ComfyUI/models/…` | Download |
|---|---|---|
| REF2VA diffusion model | `diffusion_models/Minimax/10Eros_Max_h3_TURBO-hybrid_beta4_int8_convrot.safetensors` | [10Eros-Max (TenStrip)](https://huggingface.co/TenStrip/10Eros-Max/blob/main/10Eros_Max_h3_TURBO-hybrid_beta4_int8_convrot.safetensors) |
| Text encoder (uncensored) | `text_encoders/qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors` | [Qwen3-VL-32B-Heretic (sakamakismile)](https://huggingface.co/sakamakismile/Qwen3-VL-32B-Heretic-MiniMax-H3-NVFP4/blob/main/qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors) |
| Video VAE | `vae/minimax_h3_video_vae_int8_convrot.safetensors` | [Kijai / MiniMax-H3-experimental](https://huggingface.co/Kijai/MiniMax-H3-experimental/blob/main/minimax_h3_video_vae_int8_convrot.safetensors) |

The example's model subgraph also references (same repos unless noted):

- **Audio VAE**: `vae/minimax_h3_audio_vae_fp32.safetensors` — also in [Kijai / MiniMax-H3-experimental](https://huggingface.co/Kijai/MiniMax-H3-experimental)
- **REF2V turbo LoRA** (ref2va path, applied inside the model subgraph): `loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors`
- The top-level **Power Lora Loader** node is present but has **no LoRA set** — it is an empty free slot if you want to add your own (this example does not apply one).
- The **FL2VA** and **H3 Fast Video** models wired to switch inputs 1 and 3 are unused by this ref2va example.

Swap the loader files inside the model subgraph if you use different names/paths on your machine.

---

## What it does

| Area | What Motion Director adds |
|---|---|
| **Standalone generation** | `T2V / I2V / FL2V / R2V / V2V / RV2V` |
| **Mixed Mode** | Choose `T2V / I2V / FL2V / R2V / Source Video` independently for each segment |
| **Selective Run** | Regenerate selected segments instead of rerunning the whole sequence |
| **Run controls** | Start / Resume / Restart / Stop / Start Over - Resume reuses finished segment caches that still match the project |
| **Cross-segment continuity** | Motion Context, Context Frames, Latent Scale Lock, generated-audio continuation, Color Re-anchor, **Re-ground** (re-anchor a segment at the chain root to stop drift) |
| **Segment Result reuse** | Reuse a decoded frame from an earlier Mixed segment as a later I2V / FL2V input |
| **Source-video workflow** | Dedicated V2V / RV2V handling and Source Bridge for standalone source-video boundaries |
| **Assets** | Common References plus a persistent Material Library for images, audio, video, and prompts |
| **Sampling** | Built-in sampling or external ComfyUI `SAMPLER + SIGMAS` |
| **Post-processing** | Global Refine, upscale, optional NVIDIA RTX VSR / Deblur, Face Refine |
| **Preview & output** | Director Live Preview, Segment / Multi Segment / Final Result views, final video saving |
| **ComfyUI integration** | External `Director Inputs / Director Assets`, plus `images / audio / fps` outputs |

Motion Director is an `OUTPUT_NODE`, so it can run as the end of a workflow while still exposing its final frames, audio, and FPS to downstream ComfyUI nodes.

---

## Live Preview

Motion Director has its own live preview instead of relying only on the normal sampler preview. It can show the active generation stage while the workflow is running, including later post-processing stages.

![MiniMax H3 Motion Director — Live Preview](docs/images/live-preview.gif)

---

## Mixed Mode: different generation methods in one timeline

A normal H3 workflow usually treats every generation as an isolated clip. Mixed Mode treats the project as a timeline instead.

Example:

```text
S1  T2V
S2  I2V
S3  R2V
S4  Source Video
S5  T2V
```

Each segment has its own mode, prompt, duration or source range, and legal media inputs.

### Mixed segment modes

| Mixed segment mode | Runtime path | Main use |
|---|---|---|
| `T2V` | T2V | Text-driven shot |
| `I2V` | I2V | Start from an uploaded image or earlier Segment Result |
| `FL2V` | FL2V | Control first frame, last frame, or both |
| `R2V` | R2V | Identity / scene / motion / voice references |
| `Source Video` | V2V or RV2V | Use source motion, optionally with identity pictures |

`Source Video` intentionally stays one Mixed mode:

```text
Source Video + 0 Identity Pictures  -> V2V
Source Video + Identity Pictures    -> RV2V
```

The source clip is segment-local. `Start sec` and `End sec` define the source range; the selected range determines that segment's duration.

### Per-boundary continuity

Continuity can be requested directly between Mixed segment cards:

```text
[S1]  S1 -> S2  [S2]  S2 -> S3  [S3]
        visual          visual
        audio           audio
```

The node-level continuity settings remain the global masters. This makes it possible to continue some boundaries while deliberately resetting others.

### Segment Result

Mixed Mode can reuse a static decoded frame from an earlier generated segment:

```text
Earlier Segment -> last frame
Earlier Segment -> explicit frame index
```

Typical uses:

- earlier segment -> I2V start image
- earlier segment -> FL2V first frame
- earlier segment -> FL2V last frame

A Segment Result is a static frame reference; it is separate from Motion Context, so the two mechanisms can be used together where the mode allows it.

### Selective Run

Long projects rarely need every shot regenerated. Enable **Selective Run**, mark only the segments that need another pass, and keep the rest of the sequence intact when cached/source results are available.

This is one of the main reasons the Director exists: fixing Shot 3 should not automatically mean paying for Shots 1, 2, 4, and 5 again.

---

## Standalone H3 modes

The same Director also supports six standalone MiniMax H3 task modes.

| Mode | Main input | Typical use |
|---|---|---|
| `T2V` | Prompt | Text-driven multi-shot generation |
| `I2V` | Prompt + start image | Animate a character or scene image |
| `FL2V` | Prompt + first/last image | Explicit start/end visual control |
| `R2V` | Prompt + multimodal references | Character, style, motion, scene, voice, or object references |
| `V2V` | Source Video + Prompt | Regenerate visuals while keeping source motion/content structure |
| `RV2V` | Source Video + Prompt + references | Source motion plus identity / audio references |

For R2V, each Assets group can contain up to:

```text
Picture 1-9
Video 1-3
Audio 1-3
```

Standalone V2V / RV2V use the Director's dedicated source-video workflow. Source Bridge can rebuild a short generated transition around eligible source-video segment boundaries instead of treating the split as only a hard cut.

---

## Common References

Common References are project-level media that many standalone segments can share. They are useful for recurring characters, scenes, props, reference motion, and audio without adding the same material to every segment manually.

![MiniMax H3 Motion Director — Common References](docs/images/common-references.png)

Segment-specific assets remain local to that segment/group. At execution time, common and local references are combined into the reference sequence used by the current task.

---

## Material Library

The persistent **Material Library** is for media you want to reuse across shots or later projects.

It can store:

- Images
- Audio
- Video
- Prompts

Images can be organized into categories such as characters, scenes, props, or other material. Search and allocation happen inside the Director UI instead of repeatedly browsing for the same files on disk.

![MiniMax H3 Motion Director — Material Library](docs/images/material-library.png)

In Mixed Mode, the Library targets the currently selected segment and only exposes media that are legal for that segment mode. The actual Mixed `Source Video` remains a local upload rather than a Material Library reference video.

---

## Post-processing

The Director can continue beyond first-pass generation instead of requiring a separate post-processing graph for every project.

![MiniMax H3 Motion Director — Postprocess](docs/images/postprocess.png)

### Global Refine

Global Refine can run a second sampling pass and optionally upscale the segment/result before refinement.

Available paths include, depending on the installed runtime and models:

- normal resize/upscale processing
- ComfyUI upscale models
- NVIDIA RTX Video Super Resolution
- NVIDIA RTX Deblur
- secondary H3 sampling/refinement

If Global Refine fails, the Director keeps the first-pass result instead of discarding the completed generation.

### Face Refine

Face Refine provides an integrated face-repair path with:

- face detection and tracking
- crop-based H3 regeneration
- adaptive refine strength
- mask / stitching controls
- color matching

If no usable face is detected or Face Refine fails, the assembled result is kept as the fallback.

---

## Results: Segment, Multi Segment, Final Result

Results are managed inside the Director rather than being reduced to one anonymous output batch.

![MiniMax H3 Motion Director — Final Result](docs/images/results-final.png)

The Results page has three levels:

- **Segment** — inspect one generated segment
- **Multi Segment** — preview/export a continuous segment range
- **Final Result** — inspect and save the complete pipeline result

The Final view also exposes video save options and a Director Report containing the actual run configuration, continuity state, sampling information, and post-processing status.

Public node outputs remain simple:

| Output | Type | Description |
|---|---|---|
| `images` | `IMAGE` list | Final generated video frames |
| `audio` | `AUDIO` list | Matching final audio |
| `fps` | `FLOAT` | Final frame rate |

---

## External Director Inputs / Assets

The Director is an all-in-one production interface, but it is not a closed box. Other ComfyUI nodes can still feed prompts and media into standalone modes through the external input architecture.

![MiniMax H3 Motion Director — External Inputs and Assets](docs/images/external-inputs.png)

```text
MiniMax H3 Motion Director Assets
        ↓
MiniMax H3 Motion Director Inputs
        ↓
MiniMax H3 Motion Director
```

The repository exposes three Director-related nodes:

| Node | Purpose |
|---|---|
| `MiniMax H3 Motion Director` | Main UI, execution, continuity, preview, post-processing, and results |
| `MiniMax H3 Motion Director Inputs` | Dynamic Prompt / image / Assets inputs |
| `MiniMax H3 Motion Director Assets` | Packages mode-specific media for an input group |

External input shapes by standalone mode:

```text
T2V   prompt_N
I2V   image_prompt_N + image_N
FL2V  fl_prompt_N + fl_assets_N
R2V   ref_prompt_N + ref_assets_N
RV2V  rv_prompt_N + rv_assets_N
V2V   Source Video is managed by Director
```

Mixed v1 uses its native Director timeline/media UI rather than the external group system.

---

## Sampling and performance

Motion Director can use either its internal sampler settings or an external ComfyUI sampling chain.

Connect both:

```text
SAMPLER
SIGMAS
```

and the Director uses external sampling. Otherwise it uses its internal sampler, scheduler, step count, Video Sigma Shift, and Audio Sigma Shift settings.

For longer jobs, **Clear VRAM Between Segments** can reduce memory pressure by releasing models/cache between segment runs. This trades some speed for lower VRAM usage and is intended as a stability option rather than a performance boost.

Each cleanup step is isolated, so one failing step no longer cancels the rest. If the models cannot be freed — usually because a third-party custom node is still holding a reference to a model whose ComfyUI wrapper was already released, which makes `free_memory` skip it — the node's execution report gains a **VRAM** section naming the problem, and the log carries a referrer scan pointing at the object that holds the model. Set `MINIMAX_DIRECTOR_LEAK_SCAN=0` to silence that scan.

---

## Installation

### ComfyUI-Manager / Comfy Registry

Search for:

```text
MiniMax H3 Motion Director
```

### Manual install

Upstream:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/j955229/ComfyUI-MiniMax-H3-Motion-Director.git
cd ComfyUI-MiniMax-H3-Motion-Director
python -m pip install -r requirements.txt
```

This fork (upstream + Re-ground segments, UI/perf fixes, newer-ComfyUI compatibility, example workflow):

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/The5toryofthe5ecret5tar5ystem/ComfyUI-MiniMax-H3-Motion-Director.git
cd ComfyUI-MiniMax-H3-Motion-Director
python -m pip install -r requirements.txt
```

If you use a Windows portable build, run `pip` with the Python executable used by that ComfyUI installation.

Restart ComfyUI completely after installation. If an update changes frontend files, restart ComfyUI and hard-refresh the browser.

---

## Requirements / compatibility

Motion Director requires a **recent ComfyUI build with official MiniMax H3 support**, including the official MiniMax H3 conditioning nodes used by the current runtime.

This fork calls the H3 nodes with **keyword arguments**, which is compatible with the ComfyUI core node API introduced by the `io.Schema` / `ComfyNode` rewrite (v0.34.x-era builds) — the build that changed the H3 node parameter order and broke the upstream positional calls. It also works on earlier builds that still accept the legacy signature.

Core Python dependencies are declared in the project package/requirements files. Some post-processing features have additional optional runtime/model requirements, for example:

- NVIDIA RTX VSR / Deblur requires the compatible NVIDIA VFX runtime/package and supported NVIDIA hardware
- Face Refine detector/SAM paths require the corresponding detector/model dependencies selected in the UI
- Upscale Model mode requires a compatible ComfyUI upscale model

If a feature is optional, the Director is designed to keep the usable earlier result when that post-processing stage cannot run.

> Do not load the standalone `ComfyUI-H3-Motion-Context` alongside this project. Motion Context compatibility is integrated into Motion Director.

---

## Mixed v1 notes

- Mixed v1 manages its media through the native Director UI instead of external `Director Inputs` groups.
- Mixed `Source Video` is local-upload only; Material Library videos are references, not the actual source-video input.
- Source Bridge is a standalone V2V / RV2V feature and is not used by Mixed v1.
- Segment Result references are backward-only: a later segment may reuse an earlier result, not a future result.
- Continuity improves cross-segment handoff but does not guarantee an invisible boundary in every generation; MiniMax H3 can still introduce visual, motion, lighting, or identity drift.

---

## Credits / upstream projects

Motion Director is intentionally an integrated project. It contains, modifies, or adapts code/algorithms from several existing ComfyUI H3 projects rather than pretending every component was invented independently.

- [AIMixer / ComfyUI_MiniMaxH3_Director](https://github.com/AIMixer/ComfyUI_MiniMaxH3_Director) — Apache-2.0
- [NikoDemon80 / ComfyUI-H3-Motion-Context](https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context) — GPL-3.0
- [Carasibana / ComfyUI-H3-FaceRefine](https://github.com/Carasibana/ComfyUI-H3-FaceRefine) — MIT
- [Kijai / ComfyUI-KJNodes](https://github.com/kijai/ComfyUI-KJNodes) — GPL-3.0; portions of packed-latent preview / TAEHV behavior were informed by its implementation

Thanks to the upstream authors and contributors.

See [`NOTICE`](NOTICE), [`LICENSE`](LICENSE), and [`LICENSES`](LICENSES) for the exact attribution and derivative-work details.

---

## Development / running tests

The test suites run without a live ComfyUI instance (CPU is enough for the Python tests):

```bash
# Python unit + contract tests (492 tests) — any working directory, no ComfyUI needed
python -m pytest

# Frontend unit tests (jsdom is a dev-only dependency)
npm install
npm test
```

Three frontend DOM tests additionally import ComfyUI's own frontend (`scripts/app.js`, `scripts/api.js`); they only run inside a ComfyUI checkout. A CI workflow (`.github/workflows/tests.yml`) runs the Python suite and the standalone frontend tests on every push/PR. See [`docs/FORK_REVIEW_2026-09-05.md`](docs/FORK_REVIEW_2026-09-05.md) for the full engineering pass notes.

## License

This project is distributed as a whole under **GNU GPL v3.0**.
