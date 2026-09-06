# Fork Review — MiniMax H3 Motion Director (2026-09-05)

**Fork:** `Wakapedia/ComfyUI-MiniMax-H3-Motion-Director`
**Upstream:** `j955229/ComfyUI-MiniMax-H3-Motion-Director` @ `f993906` (v1.2.0, last upstream commit 2026-08-20)
**Scope:** Full engineering pass over the Python backend, frontend, tests/CI, docs and repo hygiene.
**Method:** Static review, import/architecture mapping, execution of both test suites, and targeted verification of each claim below (no claim is speculative).

---

## 1. Verdict

This is an unusually well-engineered ComfyUI node pack — clearly the product of careful, test-driven iteration. The repo is ahead of the typical custom-node bar in several important ways:

- A large **contract test suite** (83 Python tests + 13 frontend tests) that locks down cross-module wiring.
- **Defensive degradation everywhere**: post-processing, Face Refine, VSR/Deblur and audio features fall back to the earlier usable result instead of discarding completed generations.
- HTTP routes are **security-conscious** (safe basenames, chunked uploads, item-ID-based asset store, no raw path traversal).
- Clean git hygiene, consistent licensing headers, and honest upstream attribution.

The findings below are therefore mostly **maintainability and headroom** issues, not correctness failures. The single biggest risk is the growing **load-order-coupled override layer** (see §3.1), which is where future regressions are most likely.

---

## 2. Changes made in this fork (already applied)

| # | Change | Why |
|---|---|---|
| 1 | `conftest.py` (new, repo root) | Makes the Python suite runnable from **any CWD without ComfyUI**: pins CWD to the repo root (fixes tests using `Path("director/…")`) and installs a minimal `nodes` stand-in when ComfyUI's real module isn't loaded (fixes `refine_latent_stage` monkeypatch shadowing). |
| 2 | `tests/test_h3_learned_latent.py`, `tests/test_h3_learned_internal_runtime.py` | Their `install_runtime()`/`_install_comfy_stubs()` helpers **leaked fake `sys.modules["nodes"/"comfy"/…]` entries across tests** (no restore), which poisoned every later test in the same process. Added snapshot + autouse restore fixture. **Suite went from "cannot run green in any single invocation" to 83/83 green.** |
| 3 | `pytest.ini` (new) | Declares `testpaths`/quiet opts so `python -m pytest` just works. |
| 4 | `.github/workflows/tests.yml` (new) | Adds a **CI test job** (Python suite on CPU torch, frontend `node --check` + standalone JS tests). Upstream had **no test CI** — only the Comfy Registry publish action on tag push. |
| 5 | `package.json` | Declared `jsdom` devDependency (3 DOM tests import it but it was **undeclared**) and added `npm test` via a new cross-platform `scripts/run_js_tests.mjs`. |
| 6 | `artifacts/live_ui_report.json` untracked + `.gitignore`d | It is a **machine-generated** "LIVE UI VALIDATED" dev report (`comfyOrigin: http://127.0.0.1:8190`) that was committed to the repo. |
| 7 | `README.md` | Removed 7 leftover **"IMAGE SLOT n" editor placeholder comments** that referenced local screenshot filenames (`螢幕擷取畫面 …`); images retained. |

**Verification:** `python -m pytest` → **83 passed** from the repo root *and* from `/tmp` (CWD-independent, no ComfyUI). `npm test` → **10/13 passed** standalone; the remaining 3 require ComfyUI's frontend `scripts/app.js`/`api.js` (see §3.4).

---

## 3. Findings

### 3.1 Python backend — architecture & wiring

- **[HIGH] Load-order-coupled monkeypatch stack.** The whole Audio Drive + Audio Context Refresh feature set is implemented as **module-attribute wrappers installed at import time**:
  - `director/audio_drive.py::install_audio_drive_support()` wraps `executor_core.execute_director_plan_core`, `_build_minimax_inputs`, `sample_single_stage` and `audio_export.build_director_audio_outputs`.
  - `director/audio_context_refresh.py::install_audio_context_refresh()` wraps `motion_context.apply_exported_motion_context`.
  - `patches/` monkeypatches ComfyUI H3 internals.
  
  This is *correct today* only because `__init__.py` runs the installers **before** it imports the public node modules (`nodes.director.py:16`, `nodes/director_inputs.py:15`, `nodes/director_common.py:19` all `from ..director… import …` and would otherwise bind the *original* functions). I verified the ordering is sound (ComfyUI loads the pack by file-spec, only `comfy/` is on `sys.path`, so no runtime `nodes` shadowing). **Recommendation:** codify this ordering as an explicit contract test (the repo already has several `test_*_handoff_contract.py` files — extend the pattern) and document it in `director/__init__.py`, so a future refactor cannot silently break Audio Drive.
- **[MEDIUM] `executor_core.py` performs function-object surgery** (`types.FunctionType` rebuilt from `_legacy.execute_director_plan_core.__code__` with new globals/closure, ~lines 414–430) to inject a per-call context hook into the "legacy" implementation. It works, but it is fragile and hard to debug. `executor_core_legacy.py` (1,878 lines) is *not* dead — it is the real implementation behind the `executor_core.py` facade.
- **[MEDIUM] 37 `print()` calls in production modules** (`director/nodes/lib/patches`). Several look like leftover debug tracing. Recommend routing through the existing `logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director…")` hierarchy so users can silence/tune without editing files.
- **[LOW] Broad `except Exception` paths that return fallbacks** are intentional (degrade-gracefully design), but several log at `warning` with no `exc_info=True`, making silent fallbacks hard to diagnose. Prefer `log.exception` or `log.warning(..., exc_info=True)` on the non-happy paths.

### 3.2 Frontend — architecture

- **[MEDIUM] 11,202-line `web/js/minimax_timeline.js` monolith.** It is the main ESM entry that imports ~20 `.mjs` "core" modules. Considerable logic is still inside it (timeline, segments, run). Splitting by concern (state vs. render vs. nodes) would help, but this is a large refactor with high regression risk — do it behind the existing contract tests.
- **[MEDIUM] Hotfix-layering pattern in the frontend.** `zz_minimax_audio_drive_ui.js`, `zz_minimax_director_runtime_fix.js`, `zzzz_minimax_audio_editor_backdrop_guard.js` are **active** extensions (they call `app.registerExtension`; the `zz` prefix forces them to load last). These are override/hotfix layers on top of the "real" modules rather than edits to them. Functionally fine, but the split makes it easy for the base and the override to drift. Recommend folding each `zz_*` fix into its host module after the next stable release and removing the override.
- **[LOW] 45 `setTimeout/setInterval` + rAF/MutationObserver usages in `web/js`.** The Director UI's lifecycle hooks appear to clean up timers in `destroy()`/`onRemoved` (several tests enforce this), but a targeted audit for any un-cleared interval in node lifecycle would close the last leak risk (node duplication/reloads are the usual trigger).
- **[LOW] Three parallel i18n stores.** `minimax_i18n.js` (~55 KB), `minimax_mixed_i18n.mjs`, `minimax_material_library_i18n.mjs` each carry locale maps. A single locale registry (or a shared lookup) would remove duplicated keys and make adding locales one-file work. Purely cosmetic today.

### 3.3 Tests & CI (verified)

- Upstream had **no test CI** (`.github/workflows/publish_action.yml` publishes to the Comfy Registry only on `v*` tags) and **no pytest config**, so regressions were never gated.
- The Python suite was **not runnable green in any single invocation**: (a) many tests resolve sources with CWD-relative `Path("director/…")`, so they only work from the repo root; (b) the repo's own top-level `nodes/` package shadows ComfyUI's `nodes` module, breaking `refine_latent_stage` tests whenever the repo root is on `sys.path[0]`; (c) two test helpers leaked fake `sys.modules` entries across tests. — **Fixed in this fork (§2).**
- Frontend: the standalone `.test.mjs` files are self-contained Node scripts; **`jsdom` was required but undeclared** (no devDependencies at all). — **Fixed in this fork.**
- The three DOM tests that still need ComfyUI's frontend import `../../../scripts/app.js` / `../../scripts/api.js`, which only resolve inside a ComfyUI checkout. They are not standalone-runnable by design.

### 3.4 Docs & repo hygiene

- `artifacts/live_ui_report.json` was a **committed machine-generated** dev report. — **Fixed (§2).**
- `README.md` contained 7 editor **"IMAGE SLOT" placeholder comments**. — **Fixed (§2).**
- `docs/superpowers/{plans,specs}/2026-08-19-*.md` are internal dated planning docs committed to the public tree. They document a specific feature (h3-latent-refine-mask-seams) and are harmless but read as internal scratch; consider moving them out of `docs/` if you publish the fork to a broad audience.
- Version strings are consistent (`1.2.0` in `pyproject.toml` + README badge). Git tags run `v1.0.0…v1.2.0`.
- **Fork publish caveat:** `pyproject.toml` `[project.urls].Repository` and `[tool.comfy].PublisherId` still point at the upstream (`j955229`). If you ever publish this fork to the Comfy Registry, update those or it will collide with the upstream listing. The `.github/workflows/publish_action.yml` also uses the upstream registry secrets — leave it alone unless you own the fork's registry entry.

### 3.5 Security (positive)

Reviewed the HTTP surface (`http_routes.py`, `material_library_routes.py`, `material_library.py`, `prompt_enhance_routes.py`). This is **better than most ComfyUI nodes**: chunked uploads with strict `upload_id` regexes, safe basename sanitization, chunk-index range checks, item-ID-based Material Library (no arbitrary-path delete/serve), temp-file cleanup, idempotent route registration, and graceful handling when `PromptServer` is not ready. No path-traversal or arbitrary read/write issues found. Standard caveat applies: ComfyUI binds to localhost; don't expose it to untrusted networks.

---

## 4. Improvements worth making (ranked)

1. **[High value, low risk] Pre-flight project validator.** Validate the whole Director project *before* any GPU work: per-segment mode legality, H3 frame-count grid (`% 17 == 5`), continuation references only pointing backwards, duplicate/missing asset files, audio-drive interval sanity, Face Refine prerequisites. Surfaced as a "Validate" button + non-blocking footer warnings. This directly prevents expensive half-rendered runs — the same class of problem the CGlide project already solves with offline plan validation.
2. **[High value] Multi-seed / batch sweep.** A per-run seed list (or sweep count) that queues the same project with N seeds, storing them as distinct result runs (the report already records seeds — `execution_report.py`). Great for deterministic A/B comparisons and for picking the best take of a tricky segment.
3. **[Medium] Named project Templates/Presets.** Save/load a full Director configuration (Mixed timeline + continuity + common refs + sampling) as a named template in the existing persistent store, so recurring workflows (e.g., a show's "standard opener") are one click instead of re-setup.
4. **[Medium] OOM/interrupt resume for long Mixed runs.** Selective Run exists, but a crash mid-run still loses the in-progress segment's completed state to the UI. Persist per-segment completion to disk (like the CGlide `.h3proj` `done` marks) so a restart can continue from the first unfinished segment.
5. **[Low] Fold `zz_*` frontend overrides back into their host modules** and unify the three i18n stores (see §3.2).

---

## 5. The single biggest architectural risk

The project's power comes from **layered instrumentation** (ComfyUI `patches/`, `audio_drive`, `audio_context_refresh`, executor facades, frontend `zz_` override extensions) that all assume a precise import/execution order. Any of these reordered in a refactor silently disables a feature (Audio Drive, Motion Context refresh) without an obvious error. **Recommendation:** keep extending the contract-test pattern to pin each override's binding, and add a one-line comment block in `__init__.py` documenting the required install-then-import ordering.

---

## 6. Running the tests (after this fork)

```bash
# Python (any CWD, no ComfyUI needed; CPU torch is enough)
python -m pytest            # 83 passed

# Frontend standalone tests
npm install                 # installs jsdom (dev only)
npm test                    # 10/13 pass standalone; the other 3 need a ComfyUI frontend checkout

# CI
# .github/workflows/tests.yml runs both on push/PR.
```
