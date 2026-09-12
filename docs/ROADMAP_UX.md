# Roadmap - Director UX Tiers 2 & 3

Status: planning document. Tiers 0 and 1 are implemented (see "Completed" below), and
items 1-6 and 8 are implemented. Item 7 was measured and closed as not justified.
started.

This is a *revised* plan: research for it changed the ranking versus the original
tier list, because several items turned out to be partly or mostly built already.

---

## Reassessment: what already exists

Before planning work, these were verified in the tree:

**Crash / interrupt resume is mostly built.**

| Module | API |
|---|---|
| `director/resume_state.py` | `begin_run`, `mark_segment_done`, `mark_run_state`, `resume_status`, `clear_run`, `segment_cache_preview`, `request_graceful_stop`, `clear_stop_request`, `stop_requested`, `raise_graceful_stop` |
| `director/segment_cache.py` | `segment_cache_fingerprint`, `save_segment_cache`, `load_segment_cache`, `save_segment_audio_cache`, `load_segment_audio_cache`, `segment_cache_status`, `segment_reusable`, `resolve_resume_from_index` |
| `director/executor_core_legacy.py` | resume-prefix reuse (~L1799), graceful-stop check (~L1890) |
| frontend | resume dialog + `resume_preview` route (`analyze_resume_cache`) |

So "per-segment completion persistence + crash resume" is **not** greenfield. What is
missing is the *end* of the story: stopping mid-run does not produce a usable result
for the part that finished.

**Genuinely absent (verified):**

- **Timeline undo/redo** - the only undo in the file is the SAM3 point-picker's
  "Undo last" (`minimax_timeline.js` ~L3298). No edit history for the timeline.
- **Named presets / templates** - no store exists. `postprocess_config` is the only
  saved config blob.
- **Multi-seed sweep** - only a `seedMode` control; no seed list or batch sweep.
- **Partial export on stop** - planned, not started (scaffolding exists).

**Known technical debt (confirmed present):**

- Three `zz_*` override layers: `zz_minimax_audio_drive_ui.js`,
  `zz_minimax_director_runtime_fix.js`, `zzzz_minimax_audio_editor_backdrop_guard.js`.
- 11k-line `web/js/minimax_timeline.js` monolith.
- ~34 real widgets + group headers on one node.

---

## Recommended order

Ordered by value ÷ (effort × risk), with dependencies noted.

### 1. Partial export on Stop  *(Tier 2, small, highest value remaining)* — **DONE**

**Problem.** Stopping a 10-segment run at 6/10 keeps the caches (Resume works) but
hands back nothing usable. A long run that dies at 90% produces no video.

**What shipped.**

- `director/partial_export.py` (new) owns the decision as a pure, torch-free
  function: `narrow_to_completed_prefix(...)` returns a `PartialExport` holding the
  kept run, the kept bridge pairs, the `unsampled` remainder, and the report text.
- `director/executor_core_legacy.py`: the graceful-stop check now sets
  `stopped_early`, records the manifest state as `stopped`, clears the request and
  `break`s instead of raising. The block after the segment loop narrows
  `run_list` / `run_indices` / `seg_total` / `source_bridge_pairs` to the finished
  prefix (Source Bridges need **both** sides, so pairs crossing the stop point are
  dropped). The assembly guards (`missing_selected`, `missing_all`, the export
  lists) accept a partial prefix when `stopped_early`.
- The tail rewrites `plan.run_indices` and `plan.total_frames` to the partial run so
  the saved-file metadata and the split-path source-audio length describe what
  actually shipped, and marks the run `stopped` rather than `done`.
- ComfyUI's own Cancel is deliberately untouched: it aborts from inside sampling via
  `InterruptProcessingException`, which is never caught. The node's own Stop button
  is the graceful path.

**Verified.**

- `tests/test_partial_export.py` (14) - the pure decision.
- `tests/test_partial_export_executor_contract.py` (13) - executor wiring contracts
  (Stop breaks the loop, no interrupt is swallowed, nothing-completed still hard
  cancels, the manifest is never reset).
- `tests/test_partial_export_finalize.py` (8) - the real `finalize_director_outputs`
  and `pad_or_trim_frames`; pins that a partial prefix keeps its true length and that
  the split path's audio falls back to `plan.total_frames`.
- Full suite 246 pass (was 211).

**Frontend needed no change.** A stopped run now ends in `execution_success` rather
than `execution_interrupted`, and the UI already handles both: `_onRunInactive()`
resets the run controls, `refreshResumeState()` sees `state = "stopped"`, drops the
"Stopping..." notice, and re-enables Resume at the first unfinished segment. The
`[Final]` report carries the `STOPPED (partial export)` block.

**Still open.** A hard Cancel (not the node's Stop) intentionally still discards the
in-flight result; the caches survive, so Resume covers it.

---

### 2. Timeline undo/redo + state-sync integrity check  *(Tier 3, medium)*

**Problem.** The three-site `timeline_data` mirror is the top file-corruption vector in
this project (it produced real breakage twice during Tiers 0-1 work). There is no undo.

**Approach.** `commit(skipRender, { syncTimeline })` in `minimax_timeline.js` (search for
`commit(skipRender = false`) is the **single funnel** every timeline mutation already goes
through - that is the natural hook. Push a serialized snapshot on commit, keep a bounded
ring buffer, wire `Ctrl+Z` / `Ctrl+Shift+Z`.

Pair it with a cheap integrity guard: after writing, re-read the three mirror sites and
warn (footer) if they disagree, instead of silently persisting a divergent project.

**Verify.** Frontend logic test for the ring buffer (push/undo/redo/bound). Manual:
edit a prompt, undo, confirm the segment reverts and the widget re-syncs.

**Status: DONE.**

**What shipped.**

- `web/js/minimax_undo_buffer.mjs` (new) - the pure, DOM-free pieces:
  `createUndoBuffer({ limit })` (bounded undo/redo over opaque snapshots, with
  `suppress()` so applying a snapshot never records itself), `compareTimelineMirrors`
  (the integrity guard), `isUndoShortcut`, and `isTextEntryTarget`.
- `commit()` is the single recording funnel: it records a snapshot at the end of
  **both** branches (mixed and classic), after normalisation, so every mutation path
  is covered without touching the callers. The buffer auto-seeds on the first record,
  so the initial load does not create a bogus history entry.
- Undo/redo restore through the existing loader (`parseTimeline` / mixed payload) and
  then `commit(true, { syncTimeline: true })` **inside `suppress()`** - the timeline
  repaints without re-sampling and without pushing new history.
- Ctrl/Cmd+Z, Ctrl/Cmd+Shift+Z and Ctrl/Cmd+Y are bound on `window` but scoped to
  events originating inside this editor (`root.contains(target)`), and they refuse to
  fire on `INPUT`/`TEXTAREA`/`SELECT`/contenteditable so they never steal undo from a
  half-typed prompt. `disposeUndoTimelineKeys()` unbinds.
- Discoverable `撤销` / `重做` toolbar buttons whose disabled state tracks
  `canUndoTimeline()` / `canRedoTimeline()`; both languages added to `minimax_i18n.js`.
- The integrity guard compares the two **persisted** mirrors
  (`widgets_values_named.timeline_data` and
  `properties.mmx_director_widget_state.timeline_data`) - both written during
  `onSerialize` from the same widget values, so a healthy file has them identical.
  Drift surfaces as an `error` in the pre-flight footer rather than a console
  whisper. It no-ops when a mirror was never written, so old workflows stay quiet.
- **Fixed false positive (2026-09-10).** The first cut also compared the *live*
  widget value and ran on every write. That was wrong: the editor rewrites the live
  widget during load normalisation and on every commit, so `live != saved` is the
  normal state between saves - every freshly opened workflow reported drift that was
  not there. The guard now ignores the live widget entirely and runs once at load
  (after `onConfigure` restores the mirrors). `web/js/tests/minimax_undo_buffer.test.mjs`
  keeps a regression case for exactly that scenario.

**Verified.** `web/js/tests/minimax_undo_buffer.test.mjs` (bounded history, redo-branch
invalidation, suppression incl. on throw, reset/clear, mirror comparison incl. key-order
independence / absent vs differing mirrors / unparseable JSON, shortcut + text-field
rules) and `web/js/tests/minimax_undo_wiring.test.mjs` (recording in both commit
branches and after normalisation, suppressed restore, scoped keyboard binding,
disposal, button binds, i18n keys, guard on both write branches). JS suite was 12/15 at the
time (3
skipped - need a ComfyUI frontend checkout), against a baseline of 10/13. (Current: 19/22.)

**Not done here.** History does not survive a page reload and is not shared across
nodes (per-editor instance). `seedUndoTimeline()` exists for an explicit reset on
project open but is not wired to a load hook yet.

---

### 3. Named presets / templates  *(Tier 2, medium)*

**Problem.** Recurring setups (show standard: continuity + sampling + common refs +
output) are re-entered by hand every project.

**Status: DONE (2026-09-10).**

**What shipped.**

- `director/director_presets.py` - `DirectorPresetStore` over a single atomic JSON
  index under ComfyUI's user directory, mirroring the Material Library's conventions
  (singleton `STORE`, `SCHEMA_VERSION`, `_resolve_under` guard, `_normalize_*`
  validators, typed error). No per-preset files, so an id is only ever a dict key -
  there is no path to traverse.
- `director/director_presets_routes.py` - `GET/POST /presets` plus
  `GET/PATCH/DELETE /presets/{preset_id}`, registered from `director/http_routes.py`.
- `web/js/minimax_director_presets.mjs` - the pure capture/apply logic:
  `PRESET_WIDGET_NAMES` (an explicit allowlist verified against the live node schema),
  `collectPresetPayload`, and `planPresetApply`, which returns a *plan* instead of
  mutating so applying is inspectable and testable.
- `web/js/minimax_director_presets_api.mjs` + a `Presets...` entry in the output bar
  with a manager modal (save current / apply / rename / delete).

**What a preset deliberately does NOT capture**, because a preset that silently
rewrites a project is worse than no preset:

- segments and prompts (`global_prompt` included) - those are the project;
- `seed` - applying a preset should not silently change which take you get;
- `task_type` - it reshapes the node and can invalidate existing segments, so it is a
  mode change, not a setting;
- derived/widget-less fields (`total_frames`, `model`, `*_vae`, `clip`, `sampler`,
  `sigmas`, `director_inputs`);
- shared references (`r2vCommon`) unless the "Include shared references" box is ticked,
  since attaching files a project does not have is a surprise, not a convenience.

**Scope correction worth recording.** The first cut also preset `timeline.output` keys
(`exportMode`, `maxExportFrames`, `audioMode`, ...). Those have no drivable control, and
`continuityEnabled`/`continuityOverlapFrames` are owned by the output bar's own controls,
which the editor re-derives `timeline.output` from on every commit - writing the key
directly is discarded by the next `commit()` and silently does nothing. The payload now
carries only the continuity pair, applied *through its controls*.

**Applying goes through `commit()`**, so a preset apply repaints and lands in the undo
history for free.

**Verified.** `tests/test_director_presets.py` (39: round trip, atomic write, payload
detachment, JSON-only/NaN rejection, size cap, partial updates, corrupt-index failure
that refuses to overwrite, traversal-id rejection, preset limit) and
`tests/test_director_presets_routes.py` (5: namespace, method/path table, static path
before the id catch-all, decorator-style route tables).
`web/js/tests/minimax_director_presets.test.mjs` (allowlists/exclusions, capture
detachment, apply planning, hostile payloads, summaries) and
`..._presets_wiring.test.mjs` (commit on apply, continuity via its control, no direct
`timeline.output` write, no markup injection). Python 290 pass, JS 14/17 (3 skipped).

**Known gaps.** Rename/delete use `window.prompt`/`confirm`. There is no JSON
export/import yet, which is the natural next step for sharing a template between
machines. The picker fetches each payload on open (fine for a small library).
Expose `GET/POST/DELETE /minimax/motion-director/presets`, store under the pack's user
dir, and add a picker in the output bar that applies a preset to the node widgets
(sampling / continuity / output) and to `timeline.r2vCommon` (references).

**Verify.** Route unit test (save/list/delete round-trip, sanitized names, no path
traversal - mirror the existing security tests).

**Risk.** Low. Additive; touches no render path.

---

### 4. Multi-seed sweep  *(Tier 2, medium)*

**Problem.** Picking the best take of a tricky segment is manual: change seed, re-run,
compare by eye.

**Status: DONE (2026-09-10).**

**What shipped.**

- `web/js/minimax_seed_sweep.mjs` - pure seed expansion: `parseSeedList` (tolerant of
  `,`/`;`/whitespace/newlines, and reports junk instead of guessing), `expandSeedSweep`
  (count mode / explicit list mode, dedupe, bounds), `formatTakeLabel`, `isSweepActive`.
- `minimax_timeline.js`: the single-queue body was extracted into `_queueOnce(...)`, and
  `_queueRunWithIntent({..., sweep: seeds })` now routes to `_startSeedSweep(seeds)`.
  An output-bar control (`Takes [n]`, optional `seeds 1,2,3`, **Sweep**) drives it.

**The two decisions that make or break this feature.**

1. **Every take forces `resume: false`.** With resume enabled, take 2 reuses take 1's
   segment caches and every take comes out byte-identical - a feature that looks like it
   works, costs N times the GPU, and produces one video. This is the single most
   important line in the change and has its own assertion.
2. **Derived seeds are hashed, not `base + i`.** Consecutive seeds can produce visibly
   correlated takes on some samplers, which defeats the point of a sweep. Seeds stay
   inside 32 bits so they are exact JS integers and valid ComfyUI INT values.

**Verified.** `web/js/tests/minimax_seed_sweep.test.mjs` (parser junk/negatives/fractions/
out-of-range, list order, dedupe + reporting, list-beats-count, determinism, take counts
1 and max, refusal of 0/-1/over-max/fractional, injected-RNG collision nudge, non-arithmetic
derivation, labels, opt-in boundary) and `..._seed_sweep_wiring.test.mjs` (resume forced
false, seed stamped before each queue, user's seed restored, `_queueOnce` shared rather
than duplicated, run-active guard, unusable-list reporting, sweep state cleared on run
end). JS 16/19 (3 skipped).

**Known gaps.** No side-by-side take comparison strip yet - takes land as separate runs
with separate saved files, which is enough to compare manually but not the "results strip"
from the original plan. Each take's report names its take/seed. A sweep does not hold the
run bar across all takes, so it re-activates per take rather than reading as one continuous
job. If the node's `seed` has a `control_after_generate` of `randomize`, the takes will
still be N distinct takes, but not the exact seeds shown.

**Not yet proven end-to-end:** a real 3-take sweep on the GPU (needs the user's box).

---

### 5. Fold the `zz_*` override layers back  *(Tier 3, medium)*

**Problem.** Three load-order-dependent override files make it easy for the base module
and the override to drift (flagged in the fork review). `zz_minimax_director_runtime_fix.js`
is the riskiest because it patches runtime behaviour.

**Status: CLOSED (2026-09-10). 1 of 3 folded, the serving bug fixed, the rest deliberately
not done.** The headline finding is that this item's premise did not survive contact with
the code - see "Correction" below. The real drift problem in this pack was not the
filenames; it was stale duplicate modules being served from a backup directory.

**Done: `zzzz_minimax_audio_editor_backdrop_guard.js` -> `zz_minimax_audio_drive_ui.js`.**

The guard (a document-level pointerdown/click/pointercancel listener that stops an
accidental drag-out from dismissing the audio editor) now lives in the module that owns
the backdrop DOM and its CSS. It already imported from `minimax_audio_editor_core.mjs`, so
the fold added `shouldCloseEditorBackdrop` to that existing import plus a
`BACKDROP_SELECTOR` constant. Registering earlier on `document` capture is
behaviour-preserving: the listener only acts while a backdrop exists, and as the first
capture-phase listener at the document level its ordering is unaffected.
`minimax_audio_editor.test.mjs` now asserts the guard against the host, and asserts the
override file is **gone** - a stray copy would be auto-loaded and register duplicate
listeners. The install had to lose the file too (the sync removes it explicitly).

**Correction to this item's premise, found while doing it.** The `zz_` prefix in this pack
is a **load-order hack, not an override pattern**, and the remaining two files cannot be
"moved into a host module":

- `zz_minimax_audio_drive_ui.js` (803 lines) is not an override of anything - it *is* the
  audio-roles extension (`MiniMaxH3.MotionDirector.AudioRoles`). There is no base module to
  fold it into; the `zz_` prefix only forces it to load late.
- `zz_minimax_director_runtime_fix.js` (367 lines) is a genuine patch layer
  (`RuntimeContinuityFix`), but it is not the only one: **four** modules wrap the same six
  node hooks (`onNodeCreated`, `onConfigure`, `onConnectionsChange`, `onWidgetChanged`,
  `onDrawBackground`, `onRemoved`) by capturing `prototype[hook]` and chaining via
  `original?.apply(this, arguments)` - `director_inputs.js`, `director_sections.js`,
  `runtime_fix.js` and the audio drive UI.

The wrap chain is best left alone; see the correction above for why.

---

**Found while doing this: stale duplicates were being served and executed.**

`WEB_DIRECTORY` for this pack is `./web/js`, and ComfyUI's `/extensions` route globs it
**recursively** - so a subdirectory under `web/js` is not inert, it is imported as
extension code. The installed pack had accumulated
`web/js/_perf_backup_20260909-210305/` containing two-day-old copies of
`minimax_timeline.js` (615 KB vs the live 688 KB), `minimax_director_inputs.js` and
`minimax_director_sections.js`. All three registered the **same extension names** as the
live modules (`ComfyUI.MiniMaxH3MotionDirectorPlugin`,
`MiniMaxH3.MotionDirector.UnifiedInputs`, `MiniMaxH3.MotionDirector.MainSections`).

That is this item's problem statement in its worst form: not just a module and an override
drifting apart, but a stale copy of the *base* module being loaded on top of the current
one, from a path that is invisible when you look at the repo. It also inflates every
session by ~650 KB of dead module fetch.

Fixed by moving the directory to `<pack>/_unserved_backups/`, outside the served root. The
`/extensions` list dropped 20 -> 17 entries and the change took effect **without a
restart** (the route globs per request), though a browser reload is needed to stop the
already-imported duplicates in an open session.

Guarded by `tests/test_web_dir_serving_guard.py` (4 tests): only expected directories under
`web/js`, no backup-looking module files, and **no extension name registered from more than
one served module** - scanned recursively, so it catches both a stale copy in a backup
subdir and a renamed duplicate in the flat tree. The guard was verified to *fail* on both
reproduced cases before being kept, and a fourth test pins that the registration scan still
finds real registrations (otherwise the duplicate check could silently pass forever).

**Also learned: the `zz_` prefix does not actually sequence these files.** The live
`/extensions` order puts `minimax_image_batch.js`, `minimax_i18n.js` and
`minimax_timeline.js` *after* both `zz_` files, so the prefix is not achieving "loads
last". Whatever ordering the four wrap sites depend on today is incidental, which raises
the priority of making it explicit rather than leaving it to filenames.

---

**Topology now measured and pinned (2026-09-10).**

I initially wrote the wrap table from partial reads and it was **wrong for two of the four
modules**. Extracted from source instead, the real topology is 19 wrapper installs over the
six hooks:

| Module | Hooks it wraps |
|---|---|
| `minimax_director_inputs.js` | onNodeCreated, onConfigure, onConnectionsChange, onRemoved |
| `minimax_director_sections.js` | + onDrawBackground (5) |
| `zz_minimax_audio_drive_ui.js` | onNodeCreated, onConfigure, onWidgetChanged, onDrawBackground |
| `zz_minimax_director_runtime_fix.js` | **all six** |

The `zz_minimax_audio_drive_ui.js` site wraps three hooks from a `for (const hook of [...])`
loop with a *computed* `prototype[hook]` assignment, so a naive regex misses it - the scan
expands those loops from their literal lists.

**Correction: the order is NOT load-bearing, and the remaining consolidation should not be
done.** My previous revision of this section claimed the correction layer could "run before
the layer it corrects", which would be a live bug. That was inferred from the wrap sites
and it is **wrong** - reading `runtime_fix.js` shows why:

```js
const onDrawBackground = nodeType.prototype.onDrawBackground;
nodeType.prototype.onDrawBackground = function () {
    // Reassert ownership before LiteGraph paints any widget so neither the
    // old sampling rows nor old-language labels can reach a visible frame.
    syncRuntimeFix(this);
    const result = onDrawBackground?.apply(this, arguments);
    syncRuntimeFix(this);
    return result;
};
```

The correction runs on **both sides of the inner chain, every draw frame**, so it is the
last writer regardless of which module wrapped first. On top of that it re-asserts at
`[0, 80, 250, 800]` ms after every hook plus a microtask and a rAF, while `sections` polls
on its own interval. The two layers do not race for *position*; the correction layer wins
by construction. Order-independence here is deliberate and documented in the code.

**Therefore the remaining `zz_*` work has no correctness motivation.** It is architectural
tidiness (four modules wrapping nineteen hook sites) with a real risk profile: the modules
cannot be loaded in Node (they import ComfyUI's `app` and touch the DOM at module scope),
so any restructuring needs browser verification, and the thing it would protect against is
already handled. Recommendation: **leave it**, and revisit only if the wrap sites start
causing bugs. This is a deliberate "investigated and decided against", not an open task.

Guarded by `tests/test_director_hook_wrap_topology.py` (14 tests), verified by probe:

1. an added wrapper -> caught, naming the unexpected hook;
2. a broken chain (`return onRemoved?.apply(this, arguments);` neutered) -> caught, naming
   `onRemoved (capture #4)`;
3. the pre-chain `syncRuntimeFix` re-assertion removed -> caught, "the correction layer must
   re-assert on both sides of the inner chain".

Each probe was applied to a copy and the file restored byte-identical (md5 checked).

The first version of the chain check **failed probe 2**: it searched a text window and
missed the break, and the second version searched the whole file per variable name and
still missed it because `director_inputs.js` captures `onRemoved` twice. It is now scoped
per capture *site*. Two lessons, both the same mistake: **extract the real topology rather
than inferring it** - my first table was guessed and wrong, my first probe targeted a line
shape (`const result = onRemoved?.apply(...)`) that does not exist in the file so it was a
no-op, and the "order is load-bearing" conclusion was inferred from the wrap sites rather
than read from the code that disproves it.

---

### 6. Collapse the 49-widget node surface  *(Tier 3, medium)*

**Status: precondition satisfied; the bulk of the premise was already delivered (2026-09-10).**

**The surface is already grouped and collapsible.** `minimax_director_sections_core.mjs`
declares four titled sections - `bd_grp_sample` (Sampling Settings), `bd_grp_motion`
(Cross-Segment Continuity), `mmx_postprocess_group` (Post Processing), `bd_grp_perf`
(Performance) - with localized titles, and `minimax_director_sections.js` hides the member
widgets (`widget.hidden` / `options.hidden` / `element.style.display`) and inserts an
`MMX_SECTION_GAP` separator. So "the node stops looking like a wall of numbers" is mostly
already true; this item is not the greenfield cleanup the original entry implied.

**The precondition is now met.** `tests/test_director_input_order.py` (10 tests) freezes the
node's declaration order, the required/optional split, and the six section-header indices.
Detection power verified by probe: inserting an input mid-list fails the test with "The
Director node's input order changed", and the file was restored byte-identical afterwards.
Adding at the end of a block remains safe; inserting mid-list does not.

**Measured facts worth keeping.**

- `MiniMaxH3MotionDirector.INPUT_TYPES()` declares **41** entries; `/object_info` serves
  **40**. The served view drops `i2v_groups` / `r2v_groups` (popped in
  `nodes/director_inputs.py`) and exposes `director_inputs`, which `INPUT_TYPES()` does not
  list. `mmx_postprocess_group` is not declared at all - the frontend postprocess UI adds it.
- **Stale doc claim corrected:** older notes (and this file) referred to `timeline_data` as
  `widgets_values[11]`. It is index **14** of the declaration order today. Indices drift;
  that is the whole reason for the freeze.
- The declaration order is *not* the runtime `widgets_values` order: `model`, `video_vae`,
  `audio_vae`, `clip`, `sampler`, `sigmas` and `director_inputs` are connection or custom
  inputs, not widgets.

**The one real remaining gap.** Six group headers are declared; four are managed sections,
and `bd_grp_advanced` / `bd_grp_experimental` are handled by the sampling UI because the
sampling source toggles them. **`bd_grp_audio_refine` is referenced by no frontend module**,
so its three widgets (`audio_refine_enabled`, `audio_refine_steps`,
`audio_refine_denoise`) are always visible and cannot be collapsed like every other section.

**Deliberately not fixed here.** Wiring it into the section system changes the default
surface - those three widgets would start collapsed - which is a UI behaviour change needing
browser verification, and the header sits mid-list so moving it would shift later positions.
Pinned as an explicit expectation in the test instead, so the gap stays visible and any
future change to the set of unmanaged headers fails loudly.

---

### 7. Plan-builder code merge  *(carried over, high risk)*

**Status: verdict stands (do NOT merge) - but the 2026-09-10 EVIDENCE IS WRONG.
Re-measured and corrected 2026-09-12.**

The conclusion was reached by comparing *function names* across the two modules and finding
the sets disjoint. That measurement is sound, and "do not merge" is still the right call.
What it failed to detect is **behavioural divergence** - a field present in one builder and
absent from its siblings, which leaves no trace whatsoever in symbol overlap. See
"Counter-evidence" at the end of this section.

The item's justification was that the two builders "keep causing bugs" through divergence.
Measured rather than assumed:

**There is no duplicated code to merge.** Comparing the two modules by AST, the sets of
function names are **disjoint** — `plan.py ∪ gen_timeline.py` share **zero** helper names:

```
plan.py          : 42 functions
gen_timeline.py  : 21 functions   (all 21 gen-only)
mixed_plan.py    :  6 functions
shared names plan ∩ gen : []
```

`gen_timeline.py` imports nothing from `plan.py`. The dependency runs one way:
`plan.py` imports `build_gen_director_plan` / `is_gen_timeline` and **dispatches** to the
gen builder for gen-mode timelines. These are two sibling implementations for two different
project shapes, not a copy-paste pair — so "merging them into one builder" is not a
de-duplication, it is a rewrite of two distinct things into one.

**The claim that "no fix has ever had to be applied twice", recorded here on 2026-09-10, was
DISPROVEN on 2026-09-12.** It was an artefact of measuring commits and symbol names rather
than behaviour. Kept verbatim below as the record of what was believed at the time:

| | count |
|---|---|
| commits touching `plan.py` | 19 |
| commits touching `gen_timeline.py` | 9 |
| **commits touching BOTH** | **7** |
| of those, `fix:` commits | **0** |

The seven shared commits are six `feat:` and one `perf:` — i.e. deliberate symmetric feature
work ("this mode also needs the feature"), which a merge would not eliminate: you would
still be changing both behaviours, just inside one file.

**Method note (a trap worth recording).** My first pass used
`git log -- director/plan.py director/gen_timeline.py` and read the output as "commits that
touched both". `git log -- <a> <b>` is a **union**, not an intersection — it lists commits
touching either path. That made a `gen_timeline.py`-only fix look like a duplicated fix and
briefly appeared to support the merge. The counts above come from intersecting the two
per-file commit sets explicitly.

**The overlap did become painful - two days after this was written.** See Counter-evidence.
The remedy predicted here is exactly the one that worked, and it is now implemented:
a symmetry test that asserts a behaviour for **every** builder in one place, which converts
"remember to change both" into "the test tells you". That remains a fraction of the cost
and risk of a ~2,000-line merge, and it should stay the first thing to reach for.

#### Counter-evidence (2026-09-12)

`Resume` was wired into `build_director_plan` in `director/plan.py` and **nowhere else**. Four
sibling builders construct their own `DirectorPlan` and silently dropped the fields:

```
plan.py            build_director_plan               resume wired
 gen_timeline.py    build_gen_director_plan           0 references   <- prompt_batch, THE UI'S MODE
fl2v_timeline.py   build_fl2v_director_plan          0 references
mixed_plan.py      build_mixed_director_plan         0 references
external_groups.py build_plan_from_external_groups   0 references
```

Observed from a real queued prompt carrying `resumeRun {enabled: true, from: 6}`:

```
_resume_enabled(timeline)  -> True     (the helpers were fine)
_resume_from_index         -> 6
plan.resume                -> False    (dropped by the builder)
plan.resume_from           -> None
```

`resume_active` was therefore `False`, `begin_run(reset_done=True)` wiped the done marks,
and the run re-rendered from segment 1 - while the Resume dialog, which reads the on-disk
caches, reported the prefix as perfectly reusable. The user saw "Resume from S7" start at
group 1/7. **A symbol-level comparison cannot see this class of defect at all.**

Two durable lessons:

1. **Duplicated *construction sites* are the risk, not duplicated *functions*.** Five
different modules each build a complete `DirectorPlan` field list. Disjoint helper names
gave false comfort.
2. **The prescribed remedy works.** `tests/test_resume_reaches_plan_builders.py` scans
`director/*.py` for `DirectorPlan(` and requires the resume fields. On its first run it
found `external_groups.py` - a fourth instance that had been missed by hand. That is the
symmetry test doing precisely what it was predicted to do.

Verdict unchanged: **do not merge the builders.** Prefer the symmetry test, and when adding a
field to a builder, check the other four.

---

### 8. Quick wins still open

- ~~**Plan-summary logging:** the builder logs a full plan summary (with per-segment prompt
  previews) on every rebuild, including every Validate click. Drop to DEBUG and/or strip
  prompt previews - cleaner console, and keeps scene text out of scrollback.~~ **DONE
  (2026-09-10).** `plan_summary(plan, *, include_prompts=True)`; the three per-rebuild
  `log.info` sites in `nodes/director_common.py` now log the prompt-free form, with the
  full text kept at `log.debug`. Both per-segment loops (video and batch branches) honour
  it. The in-UI run report is unchanged - it is once per run, not once per rebuild, and
  the detail is useful there. `tests/test_plan_summary_logging.py` (8) pins both halves:
  no scene text at INFO, detail still present by default.
- **Unify the three i18n stores** (`minimax_i18n.js`, `minimax_mixed_i18n.mjs`,
  `minimax_material_library_i18n.mjs`). Low value, purely hygiene. **Still open.**

### 5, 6, 7 - resolved

Item 5 closed after folding one override and fixing the served-duplicate bug; the rest was
found to need no restructuring. Item 6's precondition is met and its bulk was already
delivered. Item 7 was measured and closed as not justified - **a verdict that still stands,
though its 2026-09-10 justification was disproven on 2026-09-12** (see Counter-evidence).
See each section above for the evidence.

**The in-repo freeze exists; the risk is now cross-repo.** `tests/test_director_input_order.py`
(10 tests) already pins the declaration order, the required/optional split and the six
section-header indices, with probe-verified detection power. That covers this repository.

It does not cover the consumers outside it. `qwen_md_to_workflow.py` (prompts tree, outside
version control) hard-codes the **serialized** indices `widgets_values[1]` = global_prompt,
`[10]` = total_frames and `[11]` = timeline_data, and validates that all three mirror to the
other two sync sites; the shared-template fixer locates `[39]` = clear_vram_between_segments
by a two-key signature match against its neighbour. Verified against five real workflow files
(2026-09-12).

**Two index spaces - do not conflate them.** The *declaration* order puts `timeline_data` at
14 (as this file notes above); the *serialized* `widgets_values` array puts it at 11, because
link inputs are not serialized while BDGROUP headers are. The wizard depends on the
serialized numbering, and nothing outside this repo is covered by CI - so a widget inserted
mid-list breaks saved workflows AND the wizard, silently, at every layer. **Append only.**

---

## Verification playbook (established during Tiers 0-1)

| Layer | Command |
|---|---|
| Python suite | `PYTHONPATH=<ComfyUI> <embedded_py> -m pytest tests/ -p no:warnings -q` (344 tests, 2026-09-12) |
| JS suite | `npm test` (19/22; 3 need a ComfyUI frontend checkout) |
| Syntax | `node --check web/js/minimax_timeline.js`, `py_compile` |
| Integration | symlink repo to `/tmp/packval/mdpack`, put ComfyUI on `sys.path`, stub `plan.load_timeline_segment` -> `torch.zeros` when no real video is needed |
| Pure logic | keep algorithms in module-scope functions (e.g. `auditReferenceSlots`, `_fallback_common_refs`) so they can be tested without ComfyUI |

**Rule learned the hard way:** do one edit per call and syntax-check after each. Batched
edits to `http_routes.py` and `minimax_timeline.js` were mangled twice during Tiers 0-1.

---

## Completed (Tiers 0 & 1)

| Tier | Item | Where |
|---|---|---|
| 0 | Pre-flight Validate | `director/preflight.py` + `/validate` route + footer |
| 0 | Auto-derive source frames | `_ensureSourceFrameCount()` |
| 0 | Seconds + H3-grid hint | `gen-seg-fc-hint` + snap on commit |
| 0 | Plain-language mode labels | `lib/task_prompts.py` |
| 1 | Shared prompt-block editor | "Shared block..." modal |
| 1 | Effective-prompt preview | `director/prompt_preview.py` + `/preview_prompt` |
| 1 | Plan paths unified (semantics) | `_fallback_common_refs` in `plan.py` |
| 1 | Character Replace guided setup | "Replace setup..." wizard |
| 1 | Reference audit | `auditReferenceSlots()` + "References..." modal |
