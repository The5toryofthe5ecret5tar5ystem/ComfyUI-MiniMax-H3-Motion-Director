# Changelog

Notable changes in this fork. Older releases are tagged in git and published on the
[releases page](https://github.com/The5toryofthe5ecret5tar5ystem/ComfyUI-MiniMax-H3-Motion-Director/releases).

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
