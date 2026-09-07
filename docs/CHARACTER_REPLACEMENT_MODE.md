# Character Replace Mode (Masked · Background-True) — Scope

Status: Proposed · Owner: Motion Director fork · Relation: keeps RV2V as-is; adds a new masked mode.

**One-line goal:** inside the Motion Director, the user picks a source video, adds any number of **non-contiguous, out-of-order windows** (each with its own start + length), and each window is rendered as a **background-true masked character replacement** — masking computed at runtime per segment as it starts (no premade masks, no whole-video preprocessing).

---

## 1. Product shape (what the user sees)

A new first-class Director mode: **"Character Replace"**.

1. **Pick source video** (reuse upload/file picker + Material Library path). The video stays a *file reference* — it is never embedded in the workflow.
2. **Identity setup (job-level):** replacement character refs (face + charsheet) + audio policy + SAM3 subject prompt(s) + mask options (feather/grow). Reuses the existing reference slots / Common References / Material Library.
3. **Segment list (window list):** the user adds N segments. Each segment row has:
   - **Start** — time (s) or frame in the source,
   - **Length** — seconds or frames,
   - label/order. Rows can be **reordered**, deleted, duplicated. They are **independent windows** — may be overlapping, non-contiguous, or in any order. Order in the list = render order & output order.
4. **Run controls:** existing Start / Stop / **Resume** (per-segment cache) / Start Over. Results player per segment (audio already per-segment from v1.3.3). Report per segment.

**Output:** each window is an independent masked replacement clip. Primary export = ordered concatenation of the segment results (backgrounds pixel-exact from their own source windows); per-clip export also available (Segment / Multi views already exist).

Segments are intentionally **not** chained visually (each window re-anchors on its own source background). Cross-window continuity is an optional later feature; window boundaries are natural hard cuts.

---

## 2. Feasibility — HIGH (everything is reused; the new work is one engine stage + a window editor + SAM3 runtime)

Existing, reusable:
- **Per-segment H3 sampling with own conditioning/denoise** — `core_sampling.sample_single_stage` (Global Refine + Face Refine already use it).
- **AV noise mask (keep-region / regen-region)** — `director/h3_noise_mask.py`; native masked inpainting honored by the H3 sampler (already used to freeze continuity heads).
- **Region regen + paste / feather template** — Face Refine (`face_refine_pipeline` + `face_stitch`) and its crop-condition-as-v2v trick.
- **Per-segment source window decode** — `lib/video_io.load_timeline_segment`/`load_video_resampled` already decode **only [start, end)** from real files (seeked), not whole files.
- **Cache / resume / report / results / run controls** — segment cache + fingerprint + v1.3.3 resume dialog + per-segment audio.

New work (the actual build):
1. Window-list timeline schema + editor UI (start/length/order).
2. `replace_engine.py` — masked stage per window.
3. SAM3 runtime + offload policy.
4. Fingerprint/cache extension + assembly for ordered non-contiguous clips.

---

## 3. Engine flow for ONE segment (runs when that segment starts — lazy)

```
segment i starts
  ├─ decode ONLY [start_i, start_i+len_i) of the source file  (seeked, resampled to project fps/size)
  ├─ (if enabled) SAM3 on THIS window only  -> subject mask M_i
  │     keyframes detected over the window, masks propagated/smoothed
  │     -> uint8 mask cache on disk (per window) ; SAM3 model unloaded
  ├─ build sanitized source ref (subject region identity-destroyed: blur/invert/fill)
  ├─ VAE-encode window -> AV latent L_i   (chunked to bound memory)
  ├─ attach noise_mask = M_i  (regen = subject); audio policy applied
  ├─ condition: sanitized source (motion, echo-free) + identity refs + replacement prompt
  ├─ sample_single_stage  (denoise ~0.6-1.0)  -> masked regen; background pixel-exact
  ├─ decode -> seam/feather (grow/feather on mask) -> trim to len_i
  ├─ cache segment result + audio  (fingerprint incl. source+window+mask+refs)
  └─ free window buffers ; next segment
```

- **Masking is strictly per segment as it starts** (your requirement): no full-video SAM3 pre-pass, no all-masks-in-RAM. If SAM3 misses on a window, fall back to a manually supplied mask (asset) or to plain RV2V for that window — never a hard failure.

---

## 4. Memory & responsiveness architecture (the crux — no UI lag, no RAM/VRAM blowups)

Rules borrowed from the CGlide OOM lesson + this engine's own patterns:

**Source video (system RAM)**
- Never decode the whole file to RAM. Only `[start_i, start_i+len_i)` is decoded, seeked (av/torchcodec), resampled to project fps + working resolution.
- Frames held as **uint8** until VAE encode (a 15 s / 362 f / 1216×672 window ≈ **0.9 GB** uint8; **~3.6 GB** if float32 — so keep uint8, fp16 VAE input, and encode in VAE-batches). Freed after the segment.
- The window list stores only start/length/labels + an on-demand poster — never embedded frames in the widget.
- Optional `frame_subsample` for SAM3 keyframes only (SAM3 never sees full-rate frames; it sees ~1–4 fps keyframes, masks are propagated/upsampled to full rate → big SAM3 cost cut and its RAM stays tiny).

**SAM3 (VRAM)**
- Loaded lazily, runs the current window's keyframes, then **unloaded before H3 sampling** — SAM3 (large) and DiT (resident ~15 GB on 24 GB) never coexist. Sequence per segment: SAM3 → offload → H3 sample. Reuse the pack's existing offload/`clear_vram_between_segments` infrastructure.
- Mask stored as **low-res uint8 on disk** per window (also keeps Resume/cache coherent).

**H3 sampling (VRAM)**
- Identical envelope to today's per-segment sample (one window latent + conditioning rows). No new resident footprint beyond the noise mask + source latent of the *current* window.

**UI (browser)**
- Window picker uses **on-demand server snapshots**: a "snapshot at cursor" fetch (debounced) to `/probe`-style route; scrub = thumbnail strip at low fps or a single poster + numeric start/length inputs — never a full in-browser decode of a long file.
- Editing N rows is cheap DOM (same patterns as the existing prompt-group/batch editor). All heavy work stays server-side.

**Scheduling**
- Segments render sequentially (existing run_indices pattern). Each segment's mask+sample happens at its turn; finished segments cached → Stop/Resume works exactly like v1.3.3.

---

## 5. Data model & cache

- Project state lives in the node's timeline widget (like today), holding: `sourceRef`, `segments: [{start_frame|start_sec, length_frames, label, overrides}]`, `identityRefs`, `audioPolicy`, `maskConfig`, `samPrompts`.
- **Fingerprint per segment** (`segment_cache_fingerprint`) adds: source file+window, mask config digest, SAM prompt digest, identity ref digests → the v1.3.3 resume dialog stays accurate.
- **Mask cache**: `<cache>/<node>/replace_masks/seg_XXXX.mask.pt` (uint8 low-res) — regenerated only if the window/SAM prompt changed. Keeps Resume from re-running SAM3 on cached segments.

---

## 6. Phases

**Phase 1 — Window editor + windowed engine (masks from asset)**
- Timeline schema for `replace` mode (source ref + ordered window list with start/length/reorder).
- Engine: per-window decode (seeked) → sanitized composite → noise-mask masked sample → feather → cache → ordered concat + per-clip outputs.
- Reuse rv2v conditioning; add fingerprint fields; per-segment audio; resume dialog reasons.
- UI: mode, segment rows, on-demand snapshot picker, refs.
- Tests. Exit: replace a window cleanly from the Director using a provided mask.

**Phase 2 — Runtime SAM3 (per segment as it starts)**
- `sam3_runtime`: loader (models dir), keyframe selection + propagation + temporal smoothing, prompt UI, offload policy, mask cache, capability route, graceful fallback.
- Exit: point at a video, add windows, run → masked background-true swaps without any premade masks.

**Phase 3 — Hardening + release**
- Seam/flicker tuning, wide-shot/missed-subject fallbacks, audio regen for the new character, 24 GB VRAM accounting, UI latency passes on a long source, docs + example, release.

---

## 7. Key risks

| Risk | Mitigation |
|---|---|
| Whole-video decode sneaking back in (RAM) | Windowed seeked decode only; assert no `plan.source_video` full-tensor path for this mode; uint8 buffers |
| SAM3 + DiT VRAM overlap on 24 GB | Strict sequence SAM3 → offload → sample; keyframe subsample |
| Identity echo (regenerated subject looks like source person) | Sanitized motion ref (identity-destroyed subject) + identity refs + strong prompt — proven approach; verify early |
| Native noise-mask not keeping background pixel-exact | Phase-1 gate test; if needed, per-step decode/re-encode anchor of unmasked region |
| UI lag picking windows on a long file | Server-side snapshots, debounce, numeric entry; never browser-decodes full video |
| Non-contiguous window semantics confusing | Row list = explicit order; outputs = per-clip + ordered concat |

---

## 8. Decisions still open

1. **Source video delivery**: keep the file on disk (input dir / Material Library) and reference by path (recommended), or stream through an upstream node?
2. **Replacement scope per window**: whole subject in frame always, or allow "only the person matching this SAM prompt" (multi-subject scenes)?
3. **New character voice**: default `source` audio (keep original track) — confirm you don't usually want regenerated voice.
4. **Segment length model**: free seconds/frames per window vs. H3-valid length snapping (%17==5) automatically — recommend auto-snap like the rest of the Director.
5. **Ordered-concat default** with per-clip available — OK?
