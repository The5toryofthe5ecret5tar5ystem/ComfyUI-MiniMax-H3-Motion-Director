# Changelog

Notable changes in this fork. Older releases are tagged in git and published on the
[releases page](https://github.com/The5toryofthe5ecret5tar5ystem/ComfyUI-MiniMax-H3-Motion-Director/releases).

## Unreleased

The long-form Character Replace workflow was four settings spread across three
parts of the UI, and the one button that covered a whole clip looked identical to
the two that add a single window. It is now one named action - and it no longer
deletes the prompt it was supposed to be applied to.

The Director also repairs its own widget tail when a workflow loads, so a file
saved before a widget existed heals itself instead of arriving unqueueable.

### Changed

- **`Cover entire clip` is now `Long-form replace - cover whole clip`**, styled
  and placed as the panel's primary action instead of the seventh control in a
  10 px row. It does the whole recipe in one click: cut the source into equal
  windows at the chosen length, enable replace and continuity on every window,
  and set Export mode to *by segment* so a single bad window can be re-rendered
  without touching its neighbours. The outcome is stated before it runs
  (`Will create 27 windows x 15.08 s . covers 6:50 . continuity: on . export mode
  set to by segment`), and the window utilities (`+ Add after`,
  `+ Add at playhead`) moved behind a divider.
- **The panel now reads its own state**: `27 windows` and `covers 100%` badges in
  the header, and per-row hints (`first window - no anchor`,
  `anchors to W1 tail`) that explain what `cont` does.
- **A way in while Replace is OFF.** A slim bar appears when a source is loaded
  and is longer than one window: `6:50 source . this clip needs 27 replace
  windows` plus a one-click entry that turns Replace on and covers the clip. The
  only entry point used to be a toggle that advertised nothing.
- **No source loaded now says so.** With an empty timeline the button is disabled
  and the panel reads `Load a source video first` rather than returning silently,
  which made it look broken.
- **The replace panel is localised.** Its strings were hardcoded English in a UI
  that is otherwise translated, so there was nothing to search for in Chinese.

### Fixed

- **Covering a clip no longer deletes its prompt.** The action rebuilds
  `timeline.segments` to lay the clip out in equal windows, and it built every
  window with the plain new-window factory, which starts blank. So the prompt you
  had just written for the clip was gone the moment you covered it - and since the
  prompt box reads the selected window, the box emptied in front of you. The
  character references beside the prompt went with it, which is worse: a replace
  render that silently loses its refs has nothing left to hold the identity it was
  replacing. Only the layout is rebuilt now. A window's position (`start`,
  `length`) is the layout and is always replaced; its prompt, negative prompt,
  task type, pictures/audio/video refs, generated source image and context link
  are content and are carried across, each window getting its own copy so one
  window's edits cannot rewrite its siblings.
  Re-cutting to the same number of windows is the same windows laid out again, so
  each keeps what it had - including its own mask recipe, which previously
  collapsed to window 1's. Any other count is a different cut with no positional
  mapping left, and the clip collapses to a single recipe taken from the first
  window, which is what it already did. A shorter cut also re-clamps
  `selectedIndex`, since the prompt box reads `segments[selectedIndex]` and a
  stale index there looks exactly like a deleted prompt.
  Pinned by `web/js/tests/minimax_replace_longform_content.test.mjs`, which also
  fails if a field added to the new-window factory later is not added to the carry
  list - otherwise this exact bug returns with the next content field.

- **A workflow saved before a widget was declared now loads instead of failing to
  queue.** ComfyUI writes `null` into every widget a file predates, because it has
  no saved value to restore them from, and the type coercion happens on the way in:
  `int(None)` and `float(None)` raise, while `str(None)` and `bool(None)` do not.
  So a file from before a numeric widget existed dies with
  `Failed to convert an input value to a FLOAT value: audio_refine_denoise, None`
  and the whole workflow is unqueueable — including the five example workflows in
  this repo, which had to be hand-patched one at a time.
  `repairDirectorWidgetTailWorkflow` now does that on load, before the graph is
  configured, so the bug stops coming back with every save.
  It is anchored on the `postprocess_config` value rather than counted back from
  the end of the array: a file saved before a widget existed is simply *shorter*,
  and counting backwards would line the table up against the wrong slots and
  overwrite live values with defaults. Only two tail shapes are recognised — the
  current one and the pre-`verbose_logging` one — so an unfamiliar file is left
  alone rather than guessed at. Slots are only touched when the value is missing,
  null, or of the wrong type, and the loose `*_ui` mirrors are filled only where
  they already carry the key and hold null, so a value the user set is never
  rewritten. A stray section header sitting in a boolean slot is replaced too.
  Guarded at both ends: the per-case behaviour is covered by
  `web/js/tests/minimax_director_widget_tail.test.mjs`, and
  `tests/test_director_widget_tail_parity.py` fails if the frontend table drifts
  from the node's declaration in `nodes/director.py` — a repair that writes into
  the wrong slot would be worse than the null it was fixing.

## v1.8.3 — 2026-09-16

The learned-latent upscaler stops re-reading and re-converting its checkpoint on
every call and finally gives its VRAM back, and the v1.8.2 UI changes are made to
reach the browser at all.

### Added

- **Keep the learned-latent upscaler resident (opt-in, off by default).**
  `latent_upscale_cache_model` keeps the built upscaler on the device instead of
  freeing it, so a multi-segment run stops paying a load per call. The upscale
  stage runs after the H3 DiT is unloaded, so an uncached call is a full
  load → free cycle stacked on the DiT's own unload and reload; a resident
  upscaler trades that churn for VRAM held for the rest of the session, sharing
  the card with the reloaded DiT. That trade-off is why it ships off, and the note
  beside the checkbox says so (en + zh). The cache is a single entry keyed on
  `(checkpoint path, dtype, device)`, so a precision or device change rebuilds; a
  stale model is released **before** its replacement is built, so the two are
  never resident together; and clearing the flag releases it.
  `clear_resident_model()` / `has_resident_model()` are exposed for explicit
  reclaim. It changes speed, not frames — the first-pass cache is unaffected.

### Fixed

- **The upscaler re-read and re-converted its checkpoint on every call.** Each
  call re-read the file from disk and ran the float8 → fp16 conversion again. The
  last two decoded state dicts are now kept in CPU RAM, keyed on the path plus its
  size and mtime so that replacing the file on disk invalidates the entry. The
  decoded dict is read-only for every caller (`build_model` reads shapes,
  `load_state_dict` copies), so it is handed out without copying, and
  `clear_checkpoint_cache()` is available for file swaps.
- **The upscaler's VRAM was never actually returned.** Its `finally` block
  dropped the model and the input, then called `empty_cache()` while `mean` and
  `std` were still live device tensors. `empty_cache()` only returns blocks that
  are already unused, and unreachable-but-uncollected tensors keep holding their
  memory — the same trap the segment VRAM cleanup hit. Every device reference is
  now dropped and collected before emptying.
- **The v1.8.2 UI changes never reached the browser.** ComfyUI caches frontend
  modules by URL, so a changed module is only re-served when the `?boot=` token on
  its import changes. Two modules changed in v1.8.2 without their token being
  bumped — `minimax_postprocess_ui.mjs` (the external-patch note and the
  resident-upscaler toggle) and `minimax_timeline.js` (Cover entire clip and the
  `cont` checkbox) — so browsers kept running the cached copies: the controls were
  in the file on disk and served by ComfyUI the whole time, and nothing ever asked
  for them. Both tokens are bumped and the two guard tests were updated in
  lockstep. Worth stating plainly: those guards assert the token *string*, so they
  stay green while a token is stale — they only catch the reverse mistake (bumping
  a token and forgetting the test). Nothing detects that a module changed on its
  own.

### Tests

- **Checkpoint cache.** Covers the hit, invalidation when the file changes on
  disk, the two-entry bound, the explicit clear, and that building a model does
  not mutate the cached dict.
- **Resident model.** Covers the cache key, the bound and the release path, the
  config parse and its default, that the option does not invalidate the first-pass
  cache, and a source contract for the `keep_resident` wiring through the call
  chain.

## v1.8.2 — 2026-09-16

Seamless long-form Character Replace, a masked-replace fix that makes the inpaint
path actually replace the subject instead of returning the source, and audio fixes
across the Segment and Results views.

### Added

- **Character Replace continuity anchor.** Adjacent replace windows are independent
  re-renders, so both windows try to match the same source frame at their shared
  boundary — and being two different guesses, the regenerated subject popped
  ("teleported") whenever windows met. A window can now condition on the previous
  window's **last rendered frame**, injected as an extra `<Picture>` reference plus
  a prompt line naming it, so it opens from the prior output's pose instead of a
  fresh one. On by default (`replace.continuity`), a no-op on the first window, and
  a per-window **cont** checkbox turns it off for deliberately gapped windows.
  Fresh renders and cache-reused windows both record their tail, so a resumed run
  keeps chaining.
- **"Cover entire clip" auto-windowing.** Long clips no longer need windows added by
  hand: one button fills the whole source with contiguous windows at the chosen
  length (frames or seconds), the last window taking the remainder (a sub-second
  tail is folded into the previous window so it cannot become a degenerate stub),
  and the first window's replace settings are copied to every generated window.
  Together with per-window export this is the long-form ("infinite") Character
  Replace workflow: set the length once, cover the clip, export each window on its
  own so a single bad window can be re-rendered without touching its neighbours.

### Fixed

- **Masked (inpaint) replace returned the source unchanged.** A 97-frame inpaint
  window reported "masked replace ready" with a 0.71-mean video noise mask attached
  to the sampler, yet came back frame-for-frame identical to the source (mean |diff|
  8/255, against 51+/255 for the same window in anchor mode). ComfyUI starts masked
  sampling from `latent_image + noise`, so the encoded source left *inside* the
  regenerate region is a strong hint — the denoiser refines what it is shown and
  reconstructs the original performer instead of inventing the replacement. The
  regenerate region is now erased before the latent reaches the sampler, so sampling
  starts from pure noise there, while the keep region still carries the source and
  the noise mask still blends it back every step (the background stays pixel-exact).
  A mask whose shape does not line up with the latent is ignored rather than risking
  a misaligned erase, and the audio stream is untouched.
- **SeedVR2 upscaling silently fell back to the first pass.** ComfyUI imports
  custom-node packages at startup but does not keep the `custom_nodes` directory on
  `sys.path` when a node later executes, so the lazy import raised
  `ModuleNotFoundError: No module named 'seedvr2_videoupscaler'` and the failure was
  downgraded to "keeping first-pass result". The directory is now added back through
  `folder_paths` before the import.
- **Global Refine failures did not name the model holding VRAM.** The refine-failure
  path deliberately keeps models loaded, which skipped the anchored-model scan
  inside the VRAM cleanup — precisely when it matters, since a model ComfyUI can no
  longer unload is a likely cause of the OOM. The scan now runs on failure and the
  warning names the count, with the referrer dump (naming the custom node holding
  the module) in the log.
- **Clear VRAM unloaded the model at the wrong time, twice per boundary.** The
  segment-end cleanup keyed off the timeline's segment count rather than the
  segments actually rendered, so a one-segment selection from a long timeline
  dropped the DiT even though the post-loop refine passes wanted it resident; it now
  matches the pre-sampling call. The loop-top cleanup was also removed outright: the
  segment-end cleanup already unloads before the next segment, so it was a second
  unload plus `gc` plus `empty_cache` on every single segment boundary.
- **The external-attention-patch skip was invisible.** Global Refine is skipped for
  H3-SLA / Spectrum-patched models unless you opt in, but the panel said nothing
  about it — the only evidence was a render-time warning. A note next to the toggle
  now explains the skip (and that the reason is reported at render time) whenever
  the toggle is off.
- **The Segment audio preview was silent in source/keep modes.** Audio is only
  decoded in `generate` mode, so the Segment view had nothing to play even though
  the exported window does keep its original track. It now falls back to the
  window's own source audio — exactly what the export uses. Muted windows stay
  silent, and generated audio still wins whenever it has samples.
- **Result audio crackled and clicked when seeking.** The player pointed at a
  `data:` URL, which has to be re-parsed and re-seeked out of a giant attribute
  string, so the drift helper's seeks produced audible artifacts. Playback now uses
  a streamed, seekable Blob URL that is revoked on every swap so a long run does not
  pin every track in memory; an empty or header-only payload clears the source and
  disables the volume control instead of pointing at a broken URL.
- **The bundled faceswap example workflow shipped `latent_continuation_enabled:
  null`** in all three widget mirrors. ComfyUI coerces `bool(None)` without raising,
  which is why it loaded, but the frontend re-injects the `None` on load. It now
  ships `false`, matching the node default and the other shipped examples.

### Tests

- **Upscaler + Global Refine routing matrix.** Sweeps all five `upscale_method`
  values (lanczos, upscale model, RTX VSR, SeedVR2, H3 learned latent) across
  second sampling on/off, tiled refine, temporal split, and the external-patch /
  `skip_fl2v` / `force_skip` / disabled guards. 25 CPU-only tests; this is the
  canary that would have caught both upscaler regressions at dispatch time.
- **Real-upscaler GPU smoke.** Runs each upscaler once on a tiny input and asserts
  the output shape — the "does it actually produce frames" layer on top of the
  offline matrix. Every GPU case skips cleanly without CUDA or the model files, so
  the file is safe to leave in the normal suite.
- **Regression for the upscaler logger `NameError`** that broke upscaling: forces
  the non-empty VRAM report the CUDA branch logs, which the existing CUDA tests
  never produced.
- **Multi-segment + postprocess ordering contract.** Pins the per-segment sequence
  and both clear-VRAM sites, including that the DiT is *not* cleared between
  first-pass sampling and Global Refine.
- **Stub-module leak containment.** Stub-style tests install fake `director.*` /
  `comfy.*` modules into `sys.modules` and never remove them, so a later test that
  imported the real module got the fake. Modules are now snapshotted per test and
  reverted, with real modules deliberately left alone so torch's one-time
  `TORCH_LIBRARY` namespace registration is not re-triggered.
- **Masked-replace erase cases** (split region, all-keep, nested stream, mismatched
  mask, audio untouched) and a source contract pinning the Character Replace
  continuity wiring.

## v1.8.1 — 2026-09-15

Hotfix for the upscaler regression that stopped Global Refine from upscaling.

### Fixed

- **Global Refine silently kept the first pass.** A `log.warning` had been added to
  the learned-latent upscaler, but the module has no logger, so every CUDA upscale
  raised `NameError: log is not defined` — and the Global Refine catch-all swallowed
  it into "keeping first-pass result", which read as "upscaling just stopped
  working". The logger is now defined, Global Refine logs the full traceback when it
  fails, and a CUDA OOM re-raises as a hard error instead of quietly downgrading to
  the first pass.

## v1.8.0 — 2026-09-15

Refine longer clips by splitting them in time, a new video upscaler, and a
Clear-VRAM toggle that actually frees memory.

### Added

- **Temporal split for Global Refine (`temporal_split`, `temporal_chunk_frames`,
  `temporal_overlap_frames`).** The second-sampling pass re-sampled the entire upscaled
  latent at once, so activation VRAM scaled with sequence length. It now re-samples one
  overlapping time chunk at a time and cross-fades the overlaps, bounding peak VRAM to a
  single chunk. Chunk length and overlap snap to H3's 17-frame grid. Audio is carried
  through unchanged (never re-sampled). Deliberately scoped: used only when there is no
  Motion Context repinning and no H3 noise mask, so conditioning applies uniformly to every
  chunk and needs no per-chunk time re-anchoring. Composes with Tiled refine as a temporal
  outer loop around the spatial inner loop, and falls back to the tiled or plain
  single-stage path when one chunk covers the whole clip. The cross-fade weights sum to 1
  per token, so an identity sampler reproduces the input exactly.
- **SeedVR2 upscale method (`upscale_method: "seedvr2"`).** Temporal-aware pixel-space
  upscaling. It loads its own 3B DiT + VAE (the H3 model is unloaded first, then reloaded),
  keeps aspect ratio, and the caller resizes to the exact target.
- **Runtime probe for SeedVR2.** The post-process panel checks whether the SeedVR2 package
  is importable and reports it in the capability line, so a missing install is visible
  before a run instead of failing inside the upscale stage.

### Fixed

- **Clear VRAM Between Segments could silently do nothing.** Three causes:
  - Every cleanup step ran inside a single `try`, so a raise in the *first* step
    (`cleanup_models_gc`) skipped the unload and the cache empty that follow — one failing
    call disabled the entire cleanup. Each step now runs in its own guarded call and
    reports its own failure.
  - The end-of-segment cleanup always unloaded the model, so a single-segment run dropped
    it and immediately reloaded it for Global Refine / Face Refine. That is wasted work,
    and on a low-VRAM card the reload could OOM where staying loaded was fine. It now
    honours `seg_total > 1`, matching the pre-sampling call.
  - A model ComfyUI cannot unload (dead wrapper — `free_memory` skips those entries) was
    reported only to the log.

  `cleanup_segment_vram` now returns a summary and the executor surfaces it as a **VRAM**
  section in the execution report, naming the failing step or the anchored model, so
  "freed nothing" no longer looks identical to "worked".
- **The bundled example workflows shipped `clear_vram_between_segments: false`**, the
  opposite of the declared default. They now ship `true`.
- **The legacy widget-reorder migration could reassign the Clear-VRAM toggle.**
  `migrateReorderedDirectorTail` rewrites widget values in place, and its guard only
  compared value *types*, which unrelated layouts satisfy. It now also requires real
  group-header labels (`Performance` / `性能`) on both header slots.
- **`_split_streams` mis-split a plain tensor in tiled refine.** `torch.Tensor` has
  `unbind`, so the `hasattr(samples, "unbind")` branch matched a bare tensor before the
  `isinstance` check could. The tensor check now comes first.

### Changed

- **`gaussian_blur_frames` runs on CUDA when available.** The inpaint echo-free reference
  blurs hundreds of RGB frames; on CPU that was a multi-minute stall. The result is
  returned on the input device (identical up to fp rounding).
- Four `log.info` calls around the Character Replace echo-free reference,
  subject-erasing keep/cond source, and masked-source VAE encode, so a slow stage is
  identifiable from the log instead of looking like a hang.

### Tests

- New `tests/test_temporal_refine.py` (grid snapping, edge ramp, and a lossless-stitch
  invariant under an identity sampler) and expanded
  `tests/test_vram_cleanup_leak_report.py` covering per-step failure isolation, the
  partial-failure report, the anchored-model report, `unload_models=False`, the disabled
  no-op, and a missing `comfy` module.

## v1.7.0 — 2026-09-14

Render once, then iterate on post-processing without re-rendering; VRAM-bounded
refine; and an opt-in experimental latent-space continuation.

### Added

- **Reuse first pass (`save.reuse_first_pass`).** The first-pass H3 sample is the
  expensive half of a render. With the checkbox on, the raw AV latent is cached on disk
  keyed on everything that produced it *except* post-processing, so a later run with the
  same seed / prompt / references / resolution but different Global Refine, Face Refine or
  Audio Room settings skips sampling entirely and only re-runs post-processing. A 107-frame
  r2v render measured 363 s down to 33 s on reuse. The key deliberately invalidates when
  the seed, prompt, references, resolution, sampler or model change, because those
  genuinely change the first pass. Every hit and miss is now logged, and a settings
  snapshot plus a field-level drift diff explain any unexpected miss (e.g. the H3 loader's
  non-deterministic quantization-op registration order shifting the model-runtime hash
  across restarts).
- **Tiled refine (`tiled_refine`, `tile_size`, `tile_overlap`).** The Global Refine
  second-sampling pass can now be split into overlapping spatial tiles, so a large upscale
  fits in less VRAM: each tile is sampled alone (with its own keyframe crop), brightness is
  matched back to the input, and tiles are stitched with a linear cross-fade on the interior
  edges. Audio is taken from the first tile.
- **Export comparison (`export_comparison`).** Writes both the raw first pass and the
  post-processed result to `<prefix>_raw_firstpass` and `<prefix>_postprocessed` so the two
  can be compared side by side.
- **Refine opt-out on an external patch (`allow_refine_on_external_patch`).** When a patch
  (external) supplies the output, the second sampling pass can now be skipped via config.
- **Latent continuation (EXPERIMENTAL, opt-in `latent_continuation_enabled`).** Ports the
  community "video joiner / continue in latent space" mechanism natively: the previous
  segment's final latent is injected directly into the next segment's sampling stream and
  locked with a nested H3 noise mask (0 = preserve, 1 = generate), instead of the
  conditioning-only Motion Context. Marked EARLY TEST in the tooltip; needs GPU validation
  before production use.

### Changed

- The post-process page now puts the reuse / performance toggles in a compact bar at the
  top instead of scattering them through Global Refine.

### Tests

- 492 tests, with new suites for the first-pass cache, tiled refine, and latent
  continuation.

## v1.6.0 — 2026-09-13

RefMod identity references, a Results player that streams instead of shipping base64, and
Audio Refine made cache-free.

### Added

- **RefMod identity references.** A connected `Apply H3 RefMod` chain now reaches every
  segment: the Director harvests its reference blocks and appends them to each segment's
  own conditioning, so a character mod can carry identity across a whole chain with no
  headshot and no character sheet. The mod is attached to the DiT only — it is never
  presented to the text encoder, and no `<Picture n>` label is created for it.
- **`Minimax h3 Director - ref2va + RefMod example workflow 1x4s.json`** — a single 4 s shot
  for fast identity iteration, shipping an in-workflow usage guide covering identity,
  wardrobe, the knobs and their reasons, the failure modes, and a bisect order.
- **A wardrobe channel.** A RefMod latent is roughly a 96 x 54 thumbnail per frame, so it
  carries face and body and physically cannot carry a garment's cut, seams or trim. Clothing
  now comes from a `wardrobe:` prompt section, or from a full-resolution picture reference,
  with the prompt assigning each source its job so the two do not fight.
- **Streamed preview clips in Results.** Finished segments and final results are encoded to
  a small all-intra H.264 clip in ComfyUI's temp directory and streamed over `/view`, instead
  of pushing every frame as base64 JPEG through the websocket. One 243-frame segment measured
  ~11.9 MB of base64 parsed synchronously on the browser main thread; the clip is ~2.5 MB and
  streams with ordinary HTTP range requests, at zero websocket cost. All-intra is deliberate:
  every frame is a keyframe, so a seek lands on the exact frame rather than the nearest
  earlier one.

### Fixed

- **The RefMod wiring was in dead code.** Three classes share the name
  `MiniMaxH3MotionDirector` and chain by inheritance, and `__init__.py` imports
  `director_output` last, so the live `execute` is `director_inputs`'. The RefMod wiring had
  been added to `director.py`, which never runs. The socket was declared, the wire connected
  and `/history` showed it — but the live execute had no such parameter, so ComfyUI dropped
  it into `**kwargs` and discarded it. Moved to the class that actually executes, and a test
  now walks the MRO for the first `execute` that names its parameters and fails if any
  declared input is unbound.
- **`audio_refine_enabled` / `audio_refine_steps` / `audio_refine_denoise` were declared but
  never bound**, so they were silently discarded exactly like the RefMod input. Found by the
  same probe, now guarded by the same test.
- **`None` in saved widget values broke prompt validation.** Re-saving a workflow in ComfyUI
  wrote explicit `None` into the Director's audio-refine slots, the frontend restored them
  into `widgets_values`, and `int(None)` failed with *"Failed to convert an input value to an
  INT/FLOAT value"*. All mirrors of the affected example workflows are corrected.
- **A misleading warning on RefMod-only segments.** The plan builder warned that an `r2v`
  segment "has no reference media — will behave like t2v/t2i. Upload 图片/音频/视频 on this
  material card", which is precisely what a RefMod run does not need. It now reports the
  reference block count instead, and only warns when nothing was appended.
- **Audio Refine no longer participates in the segment cache fingerprint.** The room and
  level chain runs once at final output assembly, never per segment, so `per_segment` is gone
  and tuning a room invalidates nothing — no segment, context or audio cache.
- **Undeclared inputs are now reported.** The Director prints any input it received but did
  not declare, instead of dropping it into `**kwargs` in silence. That probe is what surfaced
  the two unbound parameter sets above.

### Documentation

- New RefMod usage guide shipping inside the example workflow, plus a rewritten
  [`example_workflows/README.md`](example_workflows/README.md) section covering how the
  reference actually reaches the model, the identity and wardrobe prompt patterns, and the
  ranked fixes for when a clothing reference takes over the face.

## v1.5.0 — 2026-09-12

A new post-processing stage, plus a Resume correctness pass.

### Added

- **Audio Room — per-scene acoustic space.** A third column in the postprocess panel
  places model-generated audio in a real space instead of leaving it dry on the camera
  mic. Nine named rooms (`dry`, `bedroom`, `bathroom`, `bar`, `office`, `car`, `hall`,
  `cathedral`, `outdoor`) each set all six SoX reverberation parameters at once, or pick
  **Custom** and set reverberance, HF damping, room size, stereo depth, pre-delay and wet
  gain yourself. A separate **Level** section provides normalise and gain.
- **Per-scene rooms.** A scene can declare its own space via a `room` field in the
  timeline, so a bathroom scene and a bedroom scene in one render no longer share a
  single acoustic setting.
- **Never-spoken guard on the shared prompt block.** H3 generates audio from the same
  text it renders, so a bare token or quoted phrase in shared reference material is a
  shape it can read aloud. A checkbox appends an explicit control line marking the block
  as reference-only, and the risk check strips that line before testing for dialogue.

### Fixed

- **Resume was ignored by four different plan builders.** `prompt_batch`/gen, `fl2v`,
  `mixed` and `external_groups` each dropped the resume flag, so Resume silently restarted
  from segment 1 on those timeline shapes. A structural test now scans every builder for
  the resume fields, which is how the fourth instance was located.
- **Resume start point.** The engine decides where a resumed run begins; the dialog no
  longer computes it independently, and the authoritative cache check agrees with it.
- **Resume preview honesty.** The preview and its audio check had blind spots that could
  present a stale or partially-cached run as complete, and a stopped run could be left
  marked `running` indefinitely.
- **Resume was greyed out** whenever the manifest carried no done marks, even when
  caches were present and reusable.
- **CUDA out-of-memory was reported as a sampler incompatibility.** An OOM inside the
  external-sampler branch was wrapped into "the sampler does not support standard ComfyUI
  SAMPLER objects and MiniMax H3 NestedTensor inputs", sending you after the wrong
  problem. OOM now surfaces as OOM.
- **Idle requestAnimationFrame loop.** The Replace-windows timeline loop ran at display
  rate for as long as a node sat on the canvas, doing nothing when the node was idle. It
  now drops to a 250 ms poll when the node is neither selected nor in Replace mode, and
  returns to full rate immediately on hover. The frame handle is stored, so it can
  actually be cancelled — previously `cancelAnimationFrame` was a no-op and the loop only
  stopped by accident, via its own `isConnected` check.

### Changed

- Postprocess config schema **v10 → v11** (`audio_refine` section).

### Notes

- The Audio Room chain runs at output assembly, downstream of the segment audio cache,
  and processes model audio *before* the merge. Enabling or changing a room therefore
  invalidates no segment, context cache or finished render; only the **Per-segment** opt-in
  changes cache identity.
- Requires **SoX** on PATH (auto-detected; `sudo pacman -S sox` on Arch/CachyOS). A track
  that cannot be processed is left dry and named in the report rather than failing the run. SoX is not enough on its own: the `soundfile`
  Python package performs the temp-file round trip and is **not** a ComfyUI
dependency, so it is now declared in `requirements.txt`.

## v1.4.0 — 2026-09-10

- **Partial export on Stop.** Stopping assembles everything already completed into a
  usable partial video and records the run as `stopped`, leaving the resume manifest
  intact so Resume continues from the first unfinished segment.
- **Timeline undo / redo** (`Ctrl+Z` / `Ctrl+Shift+Z`, `Ctrl+Y`), bounded at 50 steps and
  recorded from the single commit funnel. Deliberately inert while typing in a text field.
- **Named presets** storing settings only (never segments, prompts, task type or seed),
  with server-side atomic storage and a loud failure on a corrupt index.
- **Multi-seed sweep** rendering N takes with hashed seeds, with `resume: false` forced so
  each take actually re-renders.
- **Pre-run tools**: Validate, Preview prompt, and a References cross-check.

## Earlier releases

See the [releases page](https://github.com/The5toryofthe5ecret5tar5ystem/ComfyUI-MiniMax-H3-Motion-Director/releases)
and git tags `v1.0.0` … `v1.4.0`.
