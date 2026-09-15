# MiniMax H3 Motion Director — a whole video project in one node (v1.5.0)

**One ComfyUI node that turns MiniMax H3 from "generate a clip" into "produce a video."**

Build a timeline of shots, mix generation methods segment by segment, carry visual and generated-audio context across the cuts, rerun only the shots that need fixing, refine the result, and export the finished video — without your graph turning into a wall of duplicated nodes.

---

## Where this came from

This is a **maintained fork** of [j955229's MiniMax H3 Motion Director](https://github.com/j955229/ComfyUI-MiniMax-H3-Motion-Director). Full credit for the original architecture and the upstream feature set goes to the upstream author — everything below is built on top of their work, not instead of it.

The project is deliberately integrated rather than pretending everything was invented from scratch. Upstream contains and adapts work from:

- [AIMixer / ComfyUI_MiniMaxH3_Director](https://github.com/AIMixer/ComfyUI_MiniMaxH3_Director) — Apache-2.0
- [NikoDemon80 / ComfyUI-H3-Motion-Context](https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context) — GPL-3.0
- [Carasibana / ComfyUI-H3-FaceRefine](https://github.com/Carasibana/ComfyUI-H3-FaceRefine) — MIT
- [Kijai / ComfyUI-KJNodes](https://github.com/kijai/ComfyUI-KJNodes) — GPL-3.0

Thanks to all of them. Full attribution lives in the repo's `NOTICE`, `LICENSE` and `LICENSES/`.

**This fork:** <https://github.com/The5toryofthe5ecret5tar5ystem/ComfyUI-MiniMax-H3-Motion-Director>
**License:** GPL-3.0

---

## Install

**ComfyUI-Manager / Comfy Registry:** search `MiniMax H3 Motion Director`

**Manual:**

```
cd ComfyUI/custom_nodes
git clone https://github.com/The5toryofthe5ecret5tar5ystem/ComfyUI-MiniMax-H3-Motion-Director.git
cd ComfyUI-MiniMax-H3-Motion-Director
python -m pip install -r requirements.txt
```

Restart ComfyUI completely afterwards. If a frontend file changed, do a hard refresh in the browser too.

**Requirements:** a recent ComfyUI build with official MiniMax H3 support. This fork calls the H3 nodes with keyword arguments, which matches the ComfyUI core node API from the `io.Schema` / `ComfyNode` rewrite (v0.34.x-era) that broke the older positional calls — and it still works on earlier builds.

---

## Quick start: the four workflows people actually use

The Director exposes native **T2V / I2V / FL2V / R2V / V2V / RV2V** modes plus **Mixed Mode**, where every segment picks its own method. Here are the four most useful patterns. Full walkthroughs are in `docs/USER_GUIDE.md`.

### 1. T2V — text to video

The simplest path, and the best way to test the node.

1. **Generate →** select `T2V — Text to Video`.
2. Set aspect ratio, megapixels and FPS.
3. **Add Prompt Group** once per shot. Give each group its own prompt and duration.
4. Write each shot so it carries character, environment and action state forward — that is what makes separate segments read as one scene.
5. Run, watch **Live Preview**, then **Results → Final Result** to save.

For a 30-second piece, use three 10-second groups rather than one long one. If a single shot comes out wrong, turn on **Selective Run** and reroll just that shot.

### 2. I2V — animate an image

Use this when you already have the frame you want to start from.

1. Select `I2V`.
2. Upload **one start image** to the segment.
3. Describe what happens *next*. Don't re-describe what the image already makes unambiguous — spend the prompt on motion, camera and performance.
4. Set duration and generate.

Works well for animating a character portrait, starting from a designed scene, or continuing from a previous segment's last frame (**Segment Result** lets you pull a decoded frame from an earlier Mixed segment straight into an I2V input).

### 3. Ref2V / ref2va — one character, many shots

This is the mode for a recurring character. The node's `R2V` mode drives the **REF2VA** model path.

1. Select `R2V`.
2. Put the identity references in **Common References** so every group inherits them:
   - **Picture 1 = headshot** (face identity)
   - **Picture 2 = character sheet** (front / side / back — body shape and wardrobe)
3. Add one **Assets Group** per shot. Each group takes up to `Picture 1–9`, `Video 1–3`, `Audio 1–3`.
4. Keep only shot-specific material local to each group — a scene plate, a motion reference, a voice clip.
5. Write each shot's prompt, including how each reference should be used (and what it should *not* be used for).
6. Generate. Reroll only the shots that miss.

Because references live at project level, the character stays consistent across the whole sequence without re-uploading anything.

### 4. Character Replace — swap the performer in real footage

Re-renders chosen **windows** of a source video with your referenced character. Each window gets an automatic subject mask (SAM3, by text prompt) and is rendered as an independent masked clip: the person is regenerated from your references, the background stays the real source background.

1. Load a **Source Video** and add your replacement character to **Common References** (Picture 1 = face, Picture 2 = character sheet) — set it up as you would for RV2V.
2. Flip **Replace: ON** on the timeline.
3. Add windows with **+ Add after** / **+ Add at playhead** (default 5 s, up to 20 s; lengths snap to the H3 frame grid). Windows may overlap or be out of order — list order is render order.
4. Per window, set:
   - **kind = sam3** (auto mask from a text prompt, no mask files needed)
   - **render = anchor** (recommended — strongest identity) or **inpaint** (pixel-exact background, weaker identity)
   - **SAM3 prompt** describing the source person, e.g. `the woman, full body from head to toe, including every strand of her hair`
   - **grow / feather** for seam control
5. Generate. During the prepare phase, **Live Preview** shows a **Mask check** card (source | red subject overlay | motion reference) so you can abort before sampling if the mask is wrong.

If SAM3 misses, OOMs, or can't run, that window **falls back to a plain RV2V re-render** — it never hard-fails the run. **Resume** reuses finished windows from cache and does not re-run SAM3 on them.

*Validated on an RTX 3090 (24 GB): 0.4 MP working resolution, 5–10 s windows, in-run SAM3 auto-masking. 16 GB users should prefer the pre-made `frames` mask kind.*

---

## What's new in this fork

Everything below is additive on top of upstream. Upstream's full feature set is untouched.

### v1.5.0 — Audio Room, per scene

Generated audio no longer has to sound like a dry camera mic.

- Pick a named space — `dry`, `bedroom`, `bathroom`, `bar`, `office`, `car`, `hall`, `cathedral`, `outdoor` — and all six reverberation parameters are set for you. Or choose **Custom** and dial reverberance, HF damping, room size, stereo depth, pre-delay and wet gain yourself. A separate **Level** section adds normalise and gain.
- **Per scene, not per project.** A scene can declare its own room, so a bathroom scene and a bedroom scene in the same render stop sharing one acoustic setting.
- **It cannot invalidate a cache.** The chain runs at output assembly, downstream of the segment audio cache, and model audio is processed *before* the merge so a merged export still gets one space per scene. Turning a room on or changing it invalidates no segment, no context cache, no finished render.
- **Stereo is preserved, failures are loud.** Built on SoX. Unlike the third-party effects node it replaces — which read `waveform[0, 0]` and returned **mono** from stereo input, silently returned the original on every failure, and round-tripped through 16-bit PCM — channel count and sample count are preserved, and a track that can't be processed is left dry and *named in the report*.
- **Never-spoken guard.** H3 generates audio from the same text it renders, so a bare token or quoted phrase in shared reference material is a shape it can read aloud. A checkbox appends an explicit control line marking the block as reference-only.

### Re-ground — stop drift on long chains

Long multi-segment chains drift in colour, contrast and identity after several hops. **Re-ground** re-anchors a segment's continuity context at the **chain root** (the clean start of the job) instead of the immediately-previous segment, resetting accumulated error without breaking the flow.

Every segment boundary shows two small circles: the top `↔ / ×` is the existing context link, the bottom **`R`** is Re-ground. Left-click to toggle (it turns amber); right-click either circle for the boundary menu. Use it every 3–5 shots on long jobs, alongside **Latent Scale Lock** and **Color Re-anchor**.

### Performance

- **~525× faster** prompt truncation on the draw path. Prompt fitting used an O(n²) character-by-character `measureText` loop and could freeze the Director modal for up to ~30 s on projects with large per-segment prompts; it now uses binary search.
- **Live preview decode cap.** With shipped defaults the live preview decoded an 8-frame clip on *every diffusion step* of every stage, on the sampling thread, on the same GPU doing the diffusion. Decodes are now capped at one per 400 ms per segment/stage, while always decoding the first and final step so the preview stays a faithful progression. Output-neutral.
- **Idle timeline loop.** The Replace-windows loop ran at display rate as long as a node sat on the canvas. It now drops to a 250 ms poll when idle and returns to full rate on hover — and the frame handle is finally stored, so it can actually be cancelled (previously `cancelAnimationFrame` was a no-op).
- Cheap rendering wins (`content-visibility` on batch group cards).

### Resume, Stop and correctness

- **Resume was being ignored by four separate plan builders** — `prompt_batch`/gen, `fl2v`, `mixed` and `external_groups` each dropped the resume flag, so Resume silently restarted from segment 1 on those timeline shapes. Fixed, and a structural test now scans every builder for the resume fields (which is how the fourth instance was found).
- **The engine now decides the resume start point**, not the dialog. The preview and its audio check no longer have blind spots that could present a partially-cached run as complete, and a stopped run no longer stays marked `running`.
- **Resume was greyed out** whenever the manifest had no done marks, even when caches were present and reusable. Fixed.
- **A CUDA out-of-memory was reported as a sampler incompatibility** — an OOM in the external-sampler branch got wrapped into "the sampler does not support MiniMax H3 inputs," sending you after the wrong problem entirely. OOM now surfaces as OOM.

### v1.4.0 — Stop, undo/redo, presets, sweeps

- **Partial export on Stop.** Stopping no longer throws the run away: the current segment finishes, everything completed is assembled into a real partial video, and the run is recorded as `stopped` with the resume manifest intact — so **Resume** continues from the first unfinished segment.
- **Timeline undo / redo** — `Ctrl+Z` / `Ctrl+Shift+Z` (`Ctrl+Y` too), bounded at 50 steps, recorded from the single commit funnel so every edit is covered. Deliberately inert while you're typing in a text field.
- **Named presets** storing *settings only* — never your segments, prompts, task type or seed, so a preset can't quietly rewrite a project. Server-side atomic storage; a corrupt index fails loudly rather than being replaced by an empty one.
- **Multi-seed sweep** — render N takes with N seeds in one click. Take seeds are hashed rather than `seed + 1`, because consecutive seeds can produce visibly correlated results.
- **Fewer surprises before you queue** — **Validate** runs a pre-flight check (empty timeline, H3 frame-grid violations, missing references, Character Replace setup mistakes), **Preview prompt** shows the exact text the model receives including what the engine appends, and **References…** cross-checks which slots your prompts mention against the files actually attached.

### Safety guards

- **Global Refine is skipped automatically** when the diffusion model carries an external attention patch such as SLA or Spectrum, which a second guidance-distilled pass would otherwise corrupt. An opt-out exists for advanced users.
- **Per-segment audio in Results** — each segment's audio reaches the Results player as soon as that segment finishes, so the Segment view has real aligned sound while the job is still running.

### Tests + CI

- Python unit and contract tests run from any directory with no live ComfyUI (`python -m pytest`), plus standalone frontend tests. A CI workflow runs both on every push and PR.
- **410 Python tests, 21 frontend tests.**

---

## Models used by the bundled example workflows

Drop these under your ComfyUI `models/` folder using the subfolders shown. The paths match the workflows' model subgraphs — swap the loader entries if your filenames differ.

| Role | Place in `ComfyUI/models/…` | Source |
|---|---|---|
| REF2VA diffusion (beta4) | `diffusion_models/Minimax/10Eros_Max_h3_TURBO-hybrid_beta4_int8_convrot.safetensors` | [TenStrip/10Eros-Max](https://huggingface.co/TenStrip/10Eros-Max) |
| REF2VA diffusion (beta5) | `diffusion_models/Minimax/10Eros_Max_h3_TURBO-hybrid_beta5_int8.safetensors` | [TenStrip/10Eros-Max](https://huggingface.co/TenStrip/10Eros-Max) |
| FL2VA base | `diffusion_models/Minimax/minimax_h3_fl2va_pruned_int8_convrot.safetensors` | [Kijai/MiniMax-H3-experimental](https://huggingface.co/Kijai/MiniMax-H3-experimental) |
| Fast-video path | `diffusion_models/minimax_h3_fastvideo_vsa_datafree_1300step_4step_int8_convrot.safetensors` | [Kijai/MiniMax-H3-experimental](https://huggingface.co/Kijai/MiniMax-H3-experimental/blob/main/minimax_h3_fastvideo_vsa_datafree_1300step_4step_int8_convrot.safetensors) |
| Text encoder (uncensored, nvfp4) | `text_encoders/qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors` | [sakamakismile/Qwen3-VL-32B-Heretic-MiniMax-H3-NVFP4](https://huggingface.co/sakamakismile/Qwen3-VL-32B-Heretic-MiniMax-H3-NVFP4/blob/main/qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors) |
| Video VAE (int8 convrot) | `vae/minimax_h3_video_vae_int8_convrot.safetensors` | [Kijai/MiniMax-H3-experimental](https://huggingface.co/Kijai/MiniMax-H3-experimental/blob/main/minimax_h3_video_vae_int8_convrot.safetensors) |
| Audio VAE (fp32) | `vae/minimax_h3_audio_vae_fp32.safetensors` | [Kijai/MiniMax-H3-experimental](https://huggingface.co/Kijai/MiniMax-H3-experimental) |
| REF2V turbo LoRA (4-step) | `loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors` | [LINK NEEDED] |
| FL2V turbo LoRA (4-step, 768p) | `loras/minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors` | [LINK NEEDED] |

**Base model:** [MiniMaxAI/MiniMax-H3](https://huggingface.co/MiniMaxAI/MiniMax-H3) — the official release, including the `FL2VA`, `Ref2VA`, `vae`, `text_encoder` and `transformer_ref` folders.

**Notes**

- The int8-convrot VAE needs **ComfyUI 0.31.0 or newer** or you get black outputs. It also speeds up VAE decode by roughly 1.5×.
- The nvfp4 text encoder is ~15.7 GB and fits a single 16 GB card.
- The bundled workflows also wire an **empty Power Lora Loader** — it is deliberately left empty as a free slot for your own LoRA.
- Kijai's repo also carries an alternative set of accelerator LoRAs (`MiniMax-H3-Ref2VA-Acc-8Step`, `MiniMax-H3-FL2VA-Acc-8Step`, pruned and unpruned) if you prefer 8-step acceleration over the 4-step turbo LoRAs.

---

## Example workflows included

Three ready-to-run workflows ship in `example_workflows/`:

| File | What it shows |
|---|---|
| `Minimax h3 Director - ref2va example workflow 3x7s.json` | 3 × 7 s continuous golden-hour forest run. One character, dynamic camera, three segments, with bundled AI-generated placeholder headshot + character sheet. |
| `Minimax h3 Director - t2v example workflow 5x7s - elf vs giant orc.json` | 5 × 7 s pure-prompt story (35 s @ 24 fps), 8-step hybrid path, Audio Refine on, all cross-segment context links on. |
| `Minimax h3 Director - character replace example workflow 3x7s - elf vs giant orc.json` | 3 × 7 s ref2va character replacement — your referenced character replaces the lead of the source action. |

Each one opens routed to the right model path via the workflow's `ImpactSwitch` — `select = 1` for the FL2VA/T2V-I2V path, `= 2` for REF2VA, `= 3` for the fast-video path. Nothing else needs wiring.

The bundled `ref2va_example_assets/headshot.png` and `charsheet.png` are **AI-generated placeholder characters, not real people** — swap in your own.

---

## Things worth knowing

- **Do not** load the standalone `ComfyUI-H3-Motion-Context` alongside this pack — Motion Context compatibility is already integrated.
- Continuity improves cross-segment handoff but does not guarantee an invisible boundary every time. H3 can still introduce visual, motion, lighting or identity drift — that is what Re-ground, Latent Scale Lock and Color Re-anchor are for.
- **Clear VRAM Between Segments** is the biggest non-output speed lever on multi-segment runs. Turn it **OFF** if your GPU fits the model resident; turn it **ON** when SAM3 is in use so SAM3 and the DiT never peak together.
- Cache rules are precise and documented: resolution/megapixels, prompts, references, shot ranges and continuity **invalidate**; seed, steps, sampler, CFG, bitrate/CRF and the refine toggles **do not**.
- Optional post-processing (NVIDIA RTX VSR / Deblur, Face Refine detectors, upscale models) degrades gracefully — if a stage can't run, the Director keeps the usable earlier result instead of discarding the generation.

---

## Credits

Upstream: **[j955229 / ComfyUI-MiniMax-H3-Motion-Director](https://github.com/j955229/ComfyUI-MiniMax-H3-Motion-Director)**

Model and tooling credits: MiniMax (H3), TenStrip (10Eros-Max), Kijai (experimental H3 quantisations and VAEs), sakamakismile (uncensored nvfp4 text encoder), SoX (audio room DSP).

This fork: **[The5toryofthe5ecret5tar5ystem / ComfyUI-MiniMax-H3-Motion-Director](https://github.com/The5toryofthe5ecret5tar5ystem/ComfyUI-MiniMax-H3-Motion-Director)** — GPL-3.0. Issues and PRs welcome.

---

<small>MiniMax H3 Motion Director is a ComfyUI custom node pack. Bring your own MiniMax H3 weights — none are redistributed here. Check the MiniMax H3 community licence before commercial use.</small>
