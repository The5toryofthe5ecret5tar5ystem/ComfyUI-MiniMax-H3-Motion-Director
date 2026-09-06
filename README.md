# MiniMax H3 Motion Director.  [English](README.md) | [简体中文](README_zh.md)

![Version](https://img.shields.io/badge/version-v1.2.0-2ea44f)
![License](https://img.shields.io/badge/license-GPL--3.0-blue)
![ComfyUI](https://img.shields.io/badge/ComfyUI-custom%20node-6f42c1)

> **Maintained fork** — upstream features plus **Re-ground segments (anti-drift)**, a big **Generation-tab UI performance fix**, **newer-ComfyUI compatibility**, **CI**, and a ready-to-run **ref2va example workflow**. See [✨ Improvements in this fork](#-improvements-in-this-fork).

**One Director. From a single MiniMax H3 shot to a complete multi-segment video project.**

Here is  tutorial, or you like to read the introduction first? / 下面连结是教学，或者你想先往下看看介绍?

[English](docs/USER_GUIDE.md) | [简体中文](docs/USER_GUIDE_zh.md)

Build `T2V / I2V / FL2V / R2V / V2V / RV2V` shots in one production interface, mix generation methods segment by segment, carry visual and generated-audio context across shots, rerun only the segments that need work, manage reusable assets, preview the pipeline live, refine the result, and export the final video without turning the ComfyUI graph into a wall of nodes.

> Current version: **v1.2.0** · Registry package: **1.2.0**

![MiniMax H3 Motion Director — Mixed Mode](docs/images/hero-mixed-selective-run.png)

The screenshot above shows the native **Mixed** timeline: five segments using different generation paths, per-boundary visual/audio continuity controls, and **Selective Run** enabled so only chosen segments are regenerated.

---

## ✨ Improvements in this fork

Maintained at [`The5toryofthe5ecret5tar5ystem/ComfyUI-MiniMax-H3-Motion-Director`](https://github.com/The5toryofthe5ecret5tar5ystem/ComfyUI-MiniMax-H3-Motion-Director), on top of upstream `j955229/…`.

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

### Tests + CI

- Python unit/contract tests run from any directory without a live ComfyUI (`python -m pytest`, 94 tests); a CI workflow (`.github/workflows/tests.yml`) runs the Python suite and the standalone frontend tests on every push/PR. See [`docs/FORK_REVIEW_2026-09-05.md`](docs/FORK_REVIEW_2026-09-05.md) for the full engineering-pass notes.

### Example workflow

- [`example_workflows/`](example_workflows/) ships a ready-to-run **ref2va** sample (`ref2va example workflow 3x7s.json`) with bundled AI-generated placeholder headshot + character sheet — see [`example_workflows/README.md`](example_workflows/README.md).

---

## Models used by the example workflow (defaults)

The bundled `ref2va example workflow 3x7s.json` opens routed to the **REF2VA** model (`ImpactSwitch select = 2 → MODEL_2`). Place the files under your ComfyUI `models/` folder using the subfolders below (paths match the workflow's model subgraph):

| Role | Place in `ComfyUI/models/…` | Download |
|---|---|---|
| REF2VA diffusion model | `diffusion_models/Minimax/10Eros_Max_h3_TURBO-hybrid_beta4_int8_convrot.safetensors` | [10Eros-Max (TenStrip)](https://huggingface.co/TenStrip/10Eros-Max/blob/main/10Eros_Max_h3_TURBO-hybrid_beta4_int8_convrot.safetensors) |
| Text encoder (uncensored) | `text_encoders/qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors` | [Qwen3-VL-32B-Heretic (sakamakismile)](https://huggingface.co/sakamakismile/Qwen3-VL-32B-Heretic-MiniMax-H3-NVFP4/blob/main/qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors) |
| Video VAE | `vae/minimax_h3_video_vae_int8_convrot.safetensors` | [Kijai / MiniMax-H3-experimental](https://huggingface.co/Kijai/MiniMax-H3-experimental/blob/main/minimax_h3_video_vae_int8_convrot.safetensors) |

The example's model subgraph also references (same repos unless noted):

- **Audio VAE**: `vae/minimax_h3_audio_vae_fp32.safetensors` — also in [Kijai / MiniMax-H3-experimental](https://huggingface.co/Kijai/MiniMax-H3-experimental)
- **REF2V turbo LoRA** (ref2va path): `loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors`
- **Optional MysticXXX REF2VA LoRA** (top-level Power Lora Loader): `loras/Minimax/MysticXXX_MMH3-V4-ref2va.safetensors`
- The **FL2VA** and **H3 Fast Video** models wired to switch inputs 1 and 3 are unused by this ref2va example.

Swap the loader files inside the model subgraph if you use different names/paths on your machine.

---

## What it does

| Area | What Motion Director adds |
|---|---|
| **Standalone generation** | `T2V / I2V / FL2V / R2V / V2V / RV2V` |
| **Mixed Mode** | Choose `T2V / I2V / FL2V / R2V / Source Video` independently for each segment |
| **Selective Run** | Regenerate selected segments instead of rerunning the whole sequence |
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
# Python unit + contract tests (94 tests) — any working directory, no ComfyUI needed
python -m pytest

# Frontend unit tests (jsdom is a dev-only dependency)
npm install
npm test
```

Three frontend DOM tests additionally import ComfyUI's own frontend (`scripts/app.js`, `scripts/api.js`); they only run inside a ComfyUI checkout. A CI workflow (`.github/workflows/tests.yml`) runs the Python suite and the standalone frontend tests on every push/PR. See [`docs/FORK_REVIEW_2026-09-05.md`](docs/FORK_REVIEW_2026-09-05.md) for the full engineering pass notes.

## License

This project is distributed as a whole under **GNU GPL v3.0**.
