# Example Workflows — MiniMax H3 Motion Director

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

### Default models & downloads

Place files under your ComfyUI `models/` folder (subfolders as shown):

| Role | Place in `ComfyUI/models/…` | Download |
|---|---|---|
| REF2VA diffusion model | `diffusion_models/Minimax/10Eros_Max_h3_TURBO-hybrid_beta4_int8_convrot.safetensors` | [10Eros-Max (TenStrip)](https://huggingface.co/TenStrip/10Eros-Max/blob/main/10Eros_Max_h3_TURBO-hybrid_beta4_int8_convrot.safetensors) |
| Text encoder (uncensored) | `text_encoders/qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors` | [Qwen3-VL-32B-Heretic (sakamakismile)](https://huggingface.co/sakamakismile/Qwen3-VL-32B-Heretic-MiniMax-H3-NVFP4/blob/main/qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors) |
| Video VAE | `vae/minimax_h3_video_vae_int8_convrot.safetensors` | [Kijai / MiniMax-H3-experimental](https://huggingface.co/Kijai/MiniMax-H3-experimental/blob/main/minimax_h3_video_vae_int8_convrot.safetensors) |

Also referenced by the model subgraph: the **audio VAE** (`vae/minimax_h3_audio_vae_fp32.safetensors`, same Kijai repo) and the **REF2V turbo LoRA** applied on the ref2va path (`loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors`). The workflow also contains a top-level **Power Lora Loader**, but it is intentionally left **empty** — add your own LoRA there if you want one.

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
