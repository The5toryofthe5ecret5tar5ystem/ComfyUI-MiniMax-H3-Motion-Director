# Anchor Ladder — beat-locked multi-pass rendering for MiniMax H3 Motion Director

**Status:** P1 implemented (soft mode, payload-driven) · 2026-09-20
**Evidence:** `anchor_drift_experiment.py` (3 segments) + `anchor_ladder_6seg.py` (6 segments) — both done, soft anchors win

## 1. The problem this solves

Chained rendering (`motion_context` / `latent continuation`) conditions segment *N+1* on segment
*N*'s render. Two failure modes accumulate over a long project:

1. **Drift** — identity, hair, wardrobe, lighting and colour creep away from the references.
2. **Off-script drift** — the model reinterprets the beat instead of performing it.

Measured (3 × 7.3 s segments, same prompts/seeds/refs, 1024×576, base ref2va):

| arm | conditioning | frame-hist corr vs seg1 (seg2 / seg3) | background-strip Δ |
|---|---|---|---|
| A chain | previous render's last frame as an extra ref | 0.426 / 0.470 | 107.6 / 59.1 |
| B soft anchors | pre-generated boundary anchors as refs | 0.698 / 0.746 | 58.3 / 54.6 |
| C hard FL2F | anchors as `first_frame`/`last_frame` | **0.784 / 0.736** | **36.1 / 38.4** |

Arm A additionally went **off-script** (seg2 lunged and grabbed at the viewer, not a scripted
beat). B and C stayed on the storyboard. So anchors act as a **beat lock**, not just an identity
lock — which for scripted choreography (ASMR, POV beats) is the more valuable property.

Cost: anchor pass = 4 × 0.9 min vs ~32 min of fills ⇒ **~10 % overhead** for a full storyboard.

### 6-segment run (74 min, 24 renders, 1024×576, 175 f fills, 22 f anchors)

Frame-histogram correlation vs each arm's segment 1 (higher = more stable) and
background-strip colour Δ (window/room; lower = more stable):

| seg | A chain corr / bgΔ | B soft anchors corr / bgΔ | C hard FL2F corr / bgΔ |
|---|---|---|---|
| 2 | 0.808 / 72.1 | 0.720 / 37.0 | 0.683 / 101.4 |
| 3 | 0.844 / 28.8 | 0.807 / 30.1 | 0.842 / 63.4 |
| 4 | 0.761 / 61.6 | 0.804 / 26.8 | 0.756 / 78.4 |
| 5 | **0.533 / 29.5** | 0.747 / **23.9** | 0.669 / 58.9 |
| 6 | **0.414 / 33.5** | **0.770 / 43.4** | 0.675 / 75.1 |

Findings:

1. **Chaining collapses late** — A holds ~0.8 for three segments then falls to 0.53 (seg5) and
   0.41 (seg6). Long projects live beyond segment 5; that is exactly where today's pipeline
   loses the character.
2. **Soft anchors hold flat** — B stays 0.72–0.81 across all six segments with the lowest
   background/lighting drift (23.9–43.4), while keeping character refs AND audio.
3. **Hard FL2F is middling and drifts the world** — C keeps identity-ish stability (0.67–0.68 at
   the tail) but its room/lighting changes most (bgΔ 58–101) because it carries no character
   refs: everything, including the set, is re-interpreted from anchors each segment. It is also
   silent (no audio VAE). **Verdict: soft anchors (`mode: soft`) is the shipping path; hard FL2F
   becomes competitive only once refs can be combined with first/last (native guides, phase 4)
   and audio is handled.**

Watchable side-by-side: `AI/output/anchor_ladder_6seg/film_arm_{A,B,C}.mp4` (43.8 s each),
`sheet_arm_*.png`, `sheet_cross_arm.png`, `drift_metrics.md`.

## 2. Concept

Add an optional **anchor pass** that runs *before* the segment fills:

* **Plan** — the timeline defines *beats*; every segment boundary gets a beat pose.
* **Anchors** — for each boundary, render a short chunk (default **22 frames ≈ 0.92 s**,
  valid H3 grid length) from the references + the beat prompt; keep the chunk's **first and
  last frame** as the boundary anchors (the chunk itself is a watchable bridge).
* **Review** — anchors are cheap; the user approves/re-rolls before any fill render.
* **Fill** — the existing segment loop runs unchanged, except each segment also conditions on
  its two boundary anchors.
* **Bisect (optional)** — insert anchors at segment midpoints and halve segment lengths.
  Because each render now conditions on anchors at both ends, continuity is *constrained*
  rather than inherited — and shorter segments mean **smaller attention workspaces**
  (243 f ≈ 1.3 GiB → 124 f ≈ 0.6 GiB at 1024×576).

Depth ladder: `0` = boundaries only · `1` = + midpoints (10 s → 2 × 5 s) · `auto` = deepest
depth whose worst planned render still fits the machine tier (see §6).

## 3. Where it plugs into the pack

| Piece | Use |
|---|---|
| `MiniMaxH3MotionDirector` (`timeline_data` v5, `editMode`) | new `anchors` block + `runPasses` in the payload; new `editMode: "anchor_ladder"` (or a flag on `segment`) |
| executor segment loop (`director/executor_core_legacy.py`) | anchor pass = a pre-loop phase that renders only anchor chunks and caches frames |
| `MiniMaxH3TaggedReferenceToVideo` | fill injection (soft): append anchors to the reference list with new tags, plus prompt lines |
| `MiniMaxH3ReferenceHub` | `refs_json` already carries 9 image slots; anchors take 2, leaving 7 for character refs |
| `MiniMaxH3ImageToVideo` | hard FL2F fills (`first_frame`/`last_frame`) — **video-only**, no audio VAE (see §8) |
| `lib/vram_budget.py` | per-pass token/workspace estimates, OCR of the current tier baseline, auto-depth |
| `director/preflight.py` | report the ladder plan before queueing ("24 renders, worst = 0.96 GiB") |
| reference cache fingerprints | anchors MUST be part of the fingerprint or caches serve stale fills |
| `MiniMaxH3DirectorGuide` (native guides) | the route to combine refs **and** hard first/last in one pass (phase 4) |
| Chain pack `MiniMaxH3ChainFirstSceneImage` | prior art: per-clip first (+optional last) scene images |
| `MiniMaxH3DriftControlModelPatch` | existing adjacent lever; document interaction (do not double-apply drift control) |

## 4. Data model (payload additions)

```jsonc
"anchors": {
  "mode": "off",            // off | soft | hard
  "chunkFrames": 22,        // 17k+5 grid; 22 ≈ 0.92 s
  "depth": 0,               // 0 | 1 | 2 | "auto"
  "candidates": 1,          // re-roll candidates per boundary
  "audioOwner": "fill",     // anchors never contribute audio
  "items": [
    { "index": 0, "beat": "she is standing at the edge of the room, about to step forward",
      "seed": 301, "files": ["anchors/A0_c1.png"], "status": "ready",
      "promptHash": "…", "model": "…" }
    // index 0..N for N segments → N+1 boundaries
  ]
}
```

Per segment (additions): `anchorIn: 0 | null`, `anchorOut: 1 | null`,
`anchorPrompt: "…"` (optional beat text used to generate the boundary), plus prompt
placeholders `{{anchor_in}}` / `{{anchor_out}}` that expand to the @-reference lines so users
never hand-write them.

Files live next to the project cache (e.g. `<output>/h3_chains/<project>/anchors/`), with a
sidecar JSON holding seed/prompt-hash/model/status; `approved` status is what the fill pass
requires in `mode: soft|hard`.

## 5. Passes and resume semantics

```
plan → anchors(ready) → [user approves] → fill → [optional] bisect → [optional] refine
```

* Anchor jobs are **idempotent**: cache key = (model, chunk length, seed, prompt hash,
  reference fingerprint). Approved anchors are never re-rendered on resume.
* Fill segments keep today's cache keys, **extended with the anchor files' hashes**.
* `runPasses: {anchors: true, fill: true}` (checkboxes in the run panel) so a user can render
  only missing anchors, or only fills, or both.
* Interruption at any point leaves a valid partial project; `Resume` continues at the first
  pending item of the current pass.

## 6. Budget-driven bisection

For every planned render the pack can already compute tokens + attention workspace
(`video_tokens`, `picture_tokens`, `attention_workspace_gb`, measured 34.1 KB/token).
So `depth: "auto"` becomes: *choose the deepest ladder whose worst render ≤ the tier
baseline (and ≤ free VRAM at queue time)*. Example on this box (32 GB, w4a8 model):

| shape @1024×576 | tokens (incl. 22 ctx) | workspace |
|---|---|---|
| 243 f (10.1 s) | 39.3 k | 1.28 GiB |
| 175 f (7.3 s) | 29.5 k | 0.96 GiB |
| 124 f (5.2 s) | 22.0 k | 0.72 GiB |

A 2-minute film at 10 s segments on a 32 GB card that cannot hold 1.3 GiB workspaces becomes
24 × 5 s renders at depth 1 — *with better continuity*, because the midpoints are anchors, not
inheritance.

**Grid note:** H3 lengths are 17k+5, so bisection does not halve cleanly (243 → 124+124 = 248).
Two options: (a) accept 5 frames of overlap and let the export blend/trim them, or
(b) render the boundary **chunk** (22 f) as a real bridge clip and let the two halves span
`[start … bridge₀]` and `[bridge₋₁ … end]` — no duplicated frames, and the bridge is visible
in the timeline. (b) is recommended for depth 0.

## 7. UI sketch

* New **anchor strip** under the segment rows: one cell per boundary showing the approved
  thumbnail, status dot, seed, and buttons *re-roll / candidates / approve*.
* Toolbar: **Anchors: generate all · approve all · clear**; *candidates* spinner (1–4).
* Run panel: pass checkboxes (anchors / fill), plus the existing run-selection.
* Preflight line: "anchor pass 7 renders ≈ 6 min · fill 6 × 7.3 s · worst render 0.96 GiB (ok)".
* Per-segment row gains two small slots: `in` / `out` (auto-filled from the strip, overridable).

## 8. Audio

* Anchor pass is **video-only** (its audio is discarded) — this also makes it cheap.
* `MiniMaxH3ImageToVideo` has **no audio VAE**, so hard-FL2F fills are **silent**: for
  `mode: hard` the fill must either regenerate audio by a second, ref-only pass, or the audio
  branch must come from the source (masked-replace runs) / Foley.
* Recommended default `mode: soft` (anchors as refs) until hard-FL2F + audio is solved.

## 9. Masked replace / character swap variant

For v2v runs the source provides exact motion, so the ladder is even stronger:

1. **Pass 0 (coarse swap)** — low-res or few-step masked swap of each window.
2. **Anchors** — harvest the boundary frames of that pass (pose-locked to the source *and*
   already carrying the new identity).
3. **Fill** — full-resolution masked windows conditioned on those anchors.

Everything needed already exists (SAM3 masks, mask assets, anchor/inpaint render modes,
`grow`/`feather`). The only new part is orchestration + the same anchor UI.

## 10. Testing

* unit: anchor plan expansion (boundaries, depth, grid snapping, overlap rules)
* unit: prompt placeholder expansion + reference-tag assignment (image3/image4)
* unit: cache keys/fingerprints include anchor hashes (else stale fills)
* unit: budget-driven depth selection (tier baselines, free VRAM, worst-case render)
* unit: resume idempotence across passes (anchors done, fill half done)
* integration: 2-segment miniature project end-to-end in CI (tiny lengths)
* regression: `mode: off` produces byte-identical payloads to today's

## 11. Phasing

| Phase | Deliverable |
|---|---|
| P0 | experiments (done: 3-seg + 6-seg running) |
| **P1** | **`mode: soft` end-to-end in the executor (DONE 2026-09-20)** — see §13 |
| P2 | anchor strip UI + approve/re-roll + pass checkboxes + preflight line |
| P3 | depth > 0 with bridge chunks + `depth: auto` budget selection |
| P4 | `mode: hard` via native guides (refs + first/last in one pass) incl. audio strategy |
| P5 | masked-replace ladder (pass 0 coarse swap → anchors → fill) |

## 13. P1 implementation (soft mode, payload-driven)

Files: `director/anchor_ladder.py` (new), `director/plan.py` + `director/gen_timeline.py`
(payload parsing, `SegmentPlan.anchor_prompt/anchor_in/anchor_out`, `DirectorPlan.anchors`),
`director/executor_core_legacy.py` (anchor pass + injection + standalone-anchor guards),
`tests/test_anchor_ladder.py` (35 tests).

Enable it by adding an `anchors` block to the Director's `timeline_data` payload:

```jsonc
"anchors": {
  "mode": "soft",              // off | soft (hard is P4)
  "chunkFrames": 22,           // snapped up to 17k+5
  "seedBase": 4242,            // boundary seed = seedBase + boundary index
  "beats": ["…", "…"],        // optional, len = segments + 1 boundary poses
  "open": "…",                // optional beat for boundary 0
  "promptTemplate": "…",      // optional; {{shared}} {{beat}} {{index}}
  "injectPrompt": true,        // expand {{anchor_in}}/{{anchor_out}} or append the default lines
  "renderPass": true           // false = reuse anchors already on disk
}
```

Per segment: `anchorPrompt` (this segment's END pose → next boundary's beat),
`anchorIn` / `anchorOut` (boundary index overrides; default boundary = own index / index+1).

Behaviour:

* The anchor pass runs **before** the fill loop: one standalone `r2v` chunk per boundary
  (22 f by default), rendered from the owner segment's references with its own seed
  (`seedBase + index`), no Motion Context, no replace window, no segment/context caches.
* Each anchor is cached as `minimax_seg_cache/<node>/anchors/A<ii>_s<seed>_v1_f<frames>.png`
  plus a `.json` sidecar (`status: ready`), so Resume and repeat runs reuse them instead of
  re-rendering (delete the PNG to re-roll that boundary).
* The fill segments get the resolved anchors as extra `<Picture N>` references (first free
  slots of the 9) and the matching prompt lines, so caches invalidate exactly when an anchor
  changes (`ref_image_tensors` + `prompt` are already in the segment-cache fingerprint).
* `cache_settings["anchors"]` carries the anchor digest for the context/first-pass caches.
* A failed anchor never aborts the run: it is reported as a warning and that boundary simply
  renders without an anchor.

Known P1 limits (P2/P3 work):

* no UI - the block is payload-only (scripts / presets can set it);
* no candidate/re-roll browser, no approval gate (`status` is written but not enforced);
* `depth > 0` (bisection) and `mode: hard` are parsed but not executed.
* `runPasses.fill = false` (anchors-only preview runs) is not supported yet.

## 12. Risks / open questions

* **Velocity pinning** — FL2F interpolation can ease in/out; mitigate with moving bridge chunks,
  soft mode, or FL2F on alternating boundaries.
* **Anchor error is systemic** — a bad anchor poisons every segment touching it: hence
  candidates + explicit approval, and generating anchors at *higher* resolution than the fill
  (anchors are token-cheap).
* **Reference-slot pressure** — 2 of 9 image slots per segment; heavy RefMod users may prefer
  hard mode for that reason.
* **Cache correctness** — anchors must enter every fingerprint (reference cache, upscale cache,
  postprocess fingerprint) or silent staleness appears.
* **Prompt discipline** — the anchor @-lines must state "open on X / end at Y" explicitly;
  measured behaviour shows the model honours them.
* **Drift-control overlap** — `MiniMaxH3DriftControlModelPatch` may fight anchors; document.
* **Long-ladder wall-clock** — depth 1 doubles the render count; make it user-visible in the
  preflight estimate and default to `auto`.

## 14. P2.5 implementation - pre-roll (story before the fills)

The boundary anchors already render *first*; pre-roll adds the missing half of the
idea: **stop there** and hand back something watchable, so the expensive fills only
run once the story skeleton looks right.

Contract: `timeline_data["anchors"]["preRollOnly"] = true` (UI: the existing
**"Render fill pieces"** checkbox, unchecked = pre-roll).

* Anchors are rendered/reused exactly as in a normal run (on-disk anchors are never
  re-rendered; only missing ones cost GPU time - measured: `1 rendered, 3 reused`).
* The executor then builds:
  * **animatic** - each boundary pose held `DEFAULT_STORYBOARD_HOLD = 12` frames
    (~0.5 s at 24 fps) in boundary order, returned as the node's normal `images`
    output so `CreateVideo` / `SaveVideo` / the auto-save path all just work
    (measured: 4 anchors -> 48 frames / 2.0 s),
  * **contact sheet** - `<anchors dir>/storyboard_contact_sheet.png`, one labelled
    cell per boundary (`#index seed beat`) for quick scanning.
* The fill loop is skipped, `plan.total_frames` is retargeted to the animatic length
  so downstream trimming does not clip it, and the run reports
  `Pre-roll only: N boundary anchor(s) ready and the fills were skipped.`
* Fail-open: if no anchor could be built, the run logs a warning and continues into
  the fills rather than emitting an empty video.

Two-run workflow: pre-roll -> review/approve/re-roll in the strip -> re-queue with
"Render fill pieces" checked; the fills then consume the approved anchors (and the
anchor pass reports them as reused).

API: `storyboard_frames()` / `write_contact_sheet()` in `director/anchor_ladder.py`;
the early return lives in `executor_core_legacy.py` right after `apply_injection`.
Tests: `tests/test_anchor_ladder.py` (hold/order/resize/best-effort + parse flag).

## 15. Strip controls (P2.6)

* **Per-boundary buttons** on every cell:
  * `▶` - render *just this* boundary now: the strip sets a transient
    `onlyIndices: [i]` + pre-roll flag, queues the graph itself, waits for the PNG
    to land, then restores the previous flags.
  * `◉/○` - include/exclude this boundary (writes the explicit `boundaries` list).
  * `✓` approve / `↻` re-roll (deletes every PNG for that boundary, then bumps its seed).
  * **Click the thumbnail** - moves the timeline playhead to that boundary's opening
    frame (`ed.seekToFrame`). Ctrl/Cmd+click opens the image.
* **Bar buttons**: `All` / `Bookends` / `Rendered` selections, `Pre-roll` (render the
  missing boundaries + storyboard, then stop), `Approve all`, `Clear`.
* **Collapse**: the ▾/▸ control folds the strip to a one-line summary
  (`mode · active/total · rendered`); the state is stored in
  `node.properties.mmxa_collapsed` so it survives with the workflow.
* `boundaries` accepts `"all"`, `"bookends"`, `"none"` or an explicit index list.
  Strict semantics: a boundary outside the selection is neither rendered nor
  injected, even when its PNG is already on disk.

## 7. Files, seeds and references (what the pass and the strip agree on)

An anchor PNG is named `A<boundary>_s<seed>_v<variant>_f<chunk>.png`, and one boundary can hold several
of them (re-rolls leave their predecessors behind). Two rules keep the run and the strip from
disagreeing about which picture is in play:

* **Lookup is by boundary, seed first.** The file for the boundary's configured seed wins; when it is
  not on disk, the **newest** PNG for that boundary is injected instead and the log names the file it
  used. Saving always writes the configured seed, so re-rendering converges back to one filename.
  (Before this, a boundary whose PNG had been re-rolled under another seed silently rendered with no
  anchor at all while the strip displayed the file it had.)
* **An anchor renders with the owning segment's references** - the same list the fill receives -
  plus the prompt built from `{shared}`, `{beat}`, `{index}` and, optionally, `{subject}` (that
  segment's own `subject_definitions:` block). If the owner carries no pictures, the plan-level
  picture pool is borrowed; if there is nothing at all, the pass warns instead of quietly producing a
  boundary pose of somebody else - an anchor without references is a stranger standing in the right
  place, and both sides of the boundary end up conditioned on it.
* Anchors are deliberately standalone: no Motion Context, no continuity, no source window, no audio.
  That is what makes them comparable from run to run, and why the fills' Motion Context head is the
  only thing carrying the join.

## 8. Placement: on the cut, or one second before it

Boundary placement makes **two independent generations** agree on a pose at the exact seam - each sees
the anchor only as a loose reference, so the pictures they land on differ. Lead placement
(`anchors.placement: "lead"`) moves the checkpoint *inside* the shot instead:

| | boundary (default) | lead |
|---|---|---|
| who is conditioned on the pose | the shot that ends on boundary *k* **and** the one that opens on it | only the shot that **ends** on boundary *k* |
| where the pose sits | at the cut | `leadFrames` before that shot's end (default 24 = 1 s) |
| what carries the join | both sides aiming at the same picture | the shot's own free tail + the normal Motion Context continuation |
| prompt line | `<Picture N> is the pose this shot must END on` | `<Picture N> is the pose this shot passes through about one second before it ends` |
| boundary 0 (the opening) | opening pose of shot 1 | unchanged - there is no earlier shot to lead into |

With `leadHard` the pose is additionally pinned as a **marked H3 keyframe** at
`canvas_frames - leadFrames` on the fill's conditioning. That is the same guide mechanism the Motion
Context head uses for its prefix (`patches/h3_layout.py` positions marked guides by frame index), so
the shot is *forced* through the picture; the last second then runs free and hands a freshly
generated pose to the next shot's head. Costs to watch: the planned beat now lands a second early,
the final second of the shot is unconstrained, and a hard interior guide can make the approach rush
if the pose is far from where the shot already is. Measure the seam (frame-to-frame MAD at the cut
vs. inside the shot) before and after - the doc's §1 method, `x step` 1.0 is normal motion, 5x and up
is a visible cut.

## 9. Prompting a boundary: whose words?

An anchor is the **last frame of a 0.92 s generative chunk** (`save_anchor_image` keeps `frame[-1]`), not
a posed still - so its body should describe an *arrival*, and the most predictive text for that arrival
is the shot it belongs to. Until this pass the anchor prompt was the project prompt + a short `beat` +
the owner segment's `subject_definitions:` block; the neighbours' own shot text was never used.

`anchors.promptSource` picks who lends the words:

| value | the body is built from |
|---|---|
| `template` (the previous behaviour) | `promptTemplate`, or the built-in quiet-beat body |
| `from` | the shot that **ends** on the boundary (`{from_tail}`, framing as `{from_camera}`) |
| `to` | the shot that **starts** on it (`{to_head}`, `{to_camera}`) |
| `both` | both, as a hand-off |
| `auto` (default) | `from` in **lead** placement, `both` **on the cut** |

`auto` follows the placement deliberately: a lead pose *is* a frame of the shot that ends there, so that
shot's words are the truthful ones, while a pose on the cut is a hand-off both sides converge on and both
shots have to be named. Tokens: `{shared}`, `{subject}`, `{beat}`, `{index}`, `{from_tail}`, `{to_head}`,
`{from_camera}`, `{to_camera}`, `{camera}`, `{from_label}`, `{to_label}` (single or doubled braces).

Extraction rules (`tail_clause` / `head_clause` / `camera_clause`):

* only the `detailed_description:` section is read, so an inline `Audio:` cue cannot split it in half,
* dialogue (`<d>...</d>`), markup and `[Shot N]` markers are dropped - an anchor is a **silent** chunk,
* **framing sentences are excluded from the action clauses** so they cannot fight `{camera}`
  ("reaches toward the lens" is a POV action, not camera work - the detector is word-bounded for exactly
  that reason),
* the tail keeps the last two sentences, the head the first two, each capped at ~240 characters: 0.9 s
  cannot stage a whole shot, and a body asking for one lands the chunk mid-motion,
* `{camera}` prefers the arriving shot (`from_camera`) and falls back to `to_camera`,
* `{subject}` is skipped when the project prompt already carries that exact block.

A token whose source does not exist is **reported** (`boundary 2: {from_tail} has no source - the shot
that ends on it has no text to borrow ...`) and rendered empty, instead of leaving braces in the prompt.

Per boundary, `anchors.prompts[k]` replaces the whole body (tokens still expand) and
`anchors.promptSources[k]` switches one boundary's source. The strip's ✎ opens an editor holding that
body, the neighbour material as insertable chips, and a *renders as* preview produced by
`compose_anchor_prompt` - the same function the render path calls, so the panel and the engine cannot
disagree. The preview is composed from an "as if soft" copy of the config, so prompts can be written
while the anchors mode is **off**.
