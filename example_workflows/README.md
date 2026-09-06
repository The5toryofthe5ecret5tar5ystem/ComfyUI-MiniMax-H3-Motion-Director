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
