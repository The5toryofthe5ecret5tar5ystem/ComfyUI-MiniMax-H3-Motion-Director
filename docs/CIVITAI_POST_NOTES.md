# CivitAI post — media plan & publish notes

Companion to `docs/CIVITAI_POST.md`. **Do not publish this file.**

---

## Before you publish — 3 things to confirm

The post body is complete except for two placeholders:

1. `[LINK NEEDED]` — **REF2V turbo LoRA** `minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors`
2. `[LINK NEEDED]` — **FL2V turbo LoRA** `minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors`

Both are referenced by all three bundled workflows but are **not** in the repos I could verify
(Kijai's repo carries the `-Acc-8Step` LoRAs instead). Tell me where you got them and I'll add the links.

Also worth a sanity check — I verified the *repositories* exist but not every individual file path:

| File | Confidence |
|---|---|
| `10Eros_Max_h3_TURBO-hybrid_beta4/beta5_*.safetensors` | Repo verified (TenStrip/10Eros-Max). Note the repo is tagged **Not-For-All-Audiences** on HF, so readers may need to accept the gate. |
| `qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors` | **File verified** (15.7 GB) |
| `minimax_h3_video_vae_int8_convrot.safetensors` | **File verified** (3.17 GB) |
| `minimax_h3_fastvideo_vsa_datafree_1300step_4step_int8_convrot.safetensors` | **File verified** (22.9 GB) |
| `minimax_h3_fl2va_pruned_int8_convrot.safetensors` | Repo verified, exact filename **not** seen in the listing — confirm |
| `minimax_h3_audio_vae_fp32.safetensors` | Repo verified, exact filename **not** seen in the listing — confirm |

---

## Cover image

**`docs/images/hero-mixed-selective-run.png`** — 1713×911 (≈1.88:1, close enough to 16:9 to work as a cover).

It is the right choice: it shows the Mixed timeline with five different generation paths, the
per-boundary continuum circles, and Selective Run enabled. One image communicates "this is a
timeline, not a node" better than any paragraph.

---

## Gallery — in this order

| # | Asset | Why |
|---|---|---|
| 1 | `docs/images/hero-mixed-selective-run.png` | Cover. Mixed timeline + Selective Run. |
| 2 | **NEW — Audio Room A/B video** | The v1.5.0 headline. Same clip, same seed, `dry` vs `bathroom`, split-screen or back-to-back. Nothing else proves the feature as fast. |
| 3 | **NEW — Character Replace before/after video** | Source window on top, replaced output below. This is the most technically impressive thing the fork does. |
| 4 | `docs/images/live-preview.gif` | Already animated (426×240 — small, but it moves, so it reads). |
| 5 | **NEW — Mask check card screenshot** | The `source \| red subject overlay \| motion reference` card from Live Preview during a replace run. Shows the user can validate before spending GPU time. |
| 6 | `docs/images/postprocess.png` | 1706×891. Shows the postprocess panel including the new third **Audio Room** column. |
| 7 | `docs/images/common-references.png` | 801×553. Explains how a character stays consistent across shots. |
| 8 | `docs/images/results-final.png` | 1718×892. Results + Director Report. |
| 9 | `docs/images/material-library.png` | 1112×768. The persistent asset library. |
| 10 | `docs/images/generation-modes.webp` | 720×623. Mode overview — pairs well with the quick-start section. |

Deliberately skipped: `director-node.webp` (376×639) and `director-pages.webp` (340×563) are too
small and read as noise at gallery size. `external-inputs.png` is a niche feature — link it, don't feature it.
The `docs/images/tutorial/*.webp` set duplicates the gallery; use them in the repo docs, not here.

---

## Videos

### Already in the repo — `demo/`

| File | Spec | Notes |
|---|---|---|
| `t2v_test_1_a.mp4` / `_b.mp4` | 864×480, 10.3 s, 248 f, stereo | A/B pair |
| `t2v_test_2_a.mp4` / `_b.mp4` | 864×480, 15.5 s, 372 f, stereo | A/B pair |
| `i2v_test_1_a.mp4` / `_b.mp4` | 480×864 portrait, 15.5 s, 372 f, stereo | A/B pair |

**I don't know what the `_a` / `_b` pairs demonstrate** — they were added in one commit
("docs: prepare user-facing release repository") with no README. Tell me what each pair shows
(e.g. on/off for a feature, two seeds, two samplers) and I'll write the captions. Until then, don't post
them unlabelled — a viewer can't tell what they're looking at.

### Worth capturing — in priority order

1. **Render the bundled ref2va forest workflow.** 21 s, one continuous run, character consistent
   across all three segments. This is the single best proof of the concept, and it uses the shipped
   workflow so anyone can reproduce it.
2. **Render the t2v 5×7s elf-vs-orc workflow.** 35 s from pure text, five segments, context links on.
   Demonstrates long-form.
3. **A 30–60 s UI screen recording** — add segments, drag to reorder, toggle Selective Run, open the
   Resume dialog and show the cache-reuse reasons, undo/redo a change. Fastest way to communicate the
   workflow to someone deciding whether to install.
4. **Audio Room A/B** (gallery #2 above).
5. **Character Replace before/after** (gallery #3 above).

The two rendered examples double as the download's showcase and as the "run it yourself" proof.

---

## CivitAI-specific notes

- **civitai.com and civitai.red are the same platform, not two sites.** One content database behind
  two front doors: the same article IDs, model version IDs, collection IDs and image CDN resolve on
  both hosts. You upload once — there is no separate submission and no duplicate post to maintain.
  What differs is gating and curation: adult-rated media is shown unfiltered on `.red` while `.com`
  puts it behind the age gate / adult toggle, and the front-page featured picks differ.
  **Share the `civitai.com` link** — it works for everyone and is where people find tools.
- **Rating.** The tool itself is SFW and the bundled examples are non-explicit (a forest run, an
  elf-vs-orc fight). The recommended *models* are uncensored builds, which is normal for H3 work.
  Set the rating to match whatever examples you actually upload — if you post nothing explicit, the
  post doesn't need an adult rating. Note that an Adult rating only affects the *media* visibility on
  `.com`; the post body and install instructions read the same either way.
- **External links.** CivitAI is inconsistent about auto-flagging posts that link to other model hosts.
  The HuggingFace links here are for base models and dependencies, not for redistributed files, which is
  the normal and accepted case — but be ready to re-save the post if it gets flagged.
- **No weights are bundled or mirrored** — the post says so explicitly at the bottom, which is both true
  and the safest framing.
- **Tags to use:** `minimax h3`, `h3`, `comfyui`, `custom node`, `workflow`, `text to video`,
  `image to video`, `video`, `multi shot`, `long video`, `character consistency`, `video editing`.
- **Name the node consistently** with what Comfy Registry shows — `MiniMax H3 Motion Director` — so
  search inside ComfyUI-Manager matches the post.
