# Changelog

Notable changes in this fork. Older releases are tagged in git and published on the
[releases page](https://github.com/The5toryofthe5ecret5tar5ystem/ComfyUI-MiniMax-H3-Motion-Director/releases).

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
  that cannot be processed is left dry and named in the report rather than failing the run.

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
