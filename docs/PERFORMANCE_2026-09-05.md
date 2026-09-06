# Performance — MiniMax H3 Motion Director (audit 2026-09-05)

An evidence-based look at where time goes and what is (and is not) safe to
optimize without changing generated output.

## 1. Where the wall-clock time goes

MiniMax H3 is a video-diffusion model; the **H3 sampling steps dominate** every
segment (often >90% of per-segment time). Conditioning (text + reference VAE
encode), final AV decode and video assembly are one or two orders of magnitude
smaller. The Director already reports a real per-segment breakdown in the run
report (`H3 Sampling` vs `AV Decode` vs refine total), so you can confirm this
on your own runs.

## 2. What is already optimal (verified, file:line evidence)

- **One model / VAE / audio-VAE is shared across all segments** — no per-segment
  checkpoint reload when `Clear VRAM Between Segments` is off
  (`director/executor_core_legacy.py::execute_director_plan_core`).
- **Source video is decoded once** into `plan.source_video` / `seg.source_clip`;
  segments slice cached tensors instead of re-reading files
  (`director/segment_runtime.py::resolve_segment_raw_clip`).
- **Full-segment + Motion-Context disk caches with strict fingerprints**, so
  Selective Run / partial re-runs skip finished segments entirely
  (`director/segment_cache.py`, `director/context_cache.py`,
  `director/latent_context_cache.py`, `director/cache_policy.py`).
- **Run Selection** renders only the segments you mark.
- **Frontend writes are debounced** (500 ms) and rendering is rAF-coalesced;
  per-keystroke prompt edits do not full-serialize synchronously
  (`web/js/minimax_timeline.js` `scheduleTimelineSync`).
- Preview encode/push runs on a **bounded background thread** that drops work
  rather than stalling sampling.

## 3. Safe wins applied in this fork

- **Live TAE preview decode cadence cap (new in this fork).**
  With the shipped defaults (live preview on, `preview_every = 1`) the live
  preview decoded an 8-frame clip **on every diffusion step** of every stage
  (generation, Global Refine, Face Refine), on the sampling thread, on the same
  GPU doing diffusion — far faster than the UI can display.
  `DirectorPreviewManager` now caps decodes at **one per 400 ms per
  (segment, stage)**, while always decoding the **first and final step** of each
  stage so the preview stays a faithful first/mid/final progression.
  *Output-neutral* (preview is a side channel). Config:
  `preview_min_interval_ms` in the preview config (`0` = legacy every-step).
  Files: `director/preview_manager.py`, `tests/test_preview_manager.py`.

## 4. Speed levers you can flip TODAY with zero output change

These only trade wall-clock / VRAM, never the generated video:

| Lever | Where | Faster setting | Effect |
|---|---|---|---|
| Clear VRAM Between Segments | Director toggle | **OFF** (if your GPU fits the model) | Removes per-segment model unload/reload; biggest single non-output speedup on multi-segment runs. Default is ON for low-VRAM safety. |
| Live Preview cadence | `preview_min_interval_ms` | raise (e.g. 800–1000) | Fewer TAE decodes; preview updates less often but still live. |
| Live Preview | Director toggle | OFF while not watching | Zero preview-decode cost. |
| `preview_every` | Sampling settings | raise (e.g. 8–16) | Decode preview every N steps instead of every step. |
| Run Selection | Director | mark only changed segments | Skips finished segments entirely (disk cache + fingerprints). |
| Global Refine / Face Refine | Postprocess | OFF when not needed | Skips entire second sampling passes. |

## 5. Things that would NOT be safe (do not do)

- **Changing the model/VAE/timestep/sampler settings** to "speed up" — changes output.
- **Reusing a reference-image VAE encode across different segment canvases** —
  H3 conditioning encodes depend on width/height/length; dedup is only safe when
  every dimension matches, and even then the official node owns the encode.
- **Reducing context/source frames** to skip work — changes continuity/output.
- **Decoding fewer output frames** or downscaling the final decode — changes the
  result.
