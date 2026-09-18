# QA readiness sweep

One command that answers *"is this build actually ready to use, and what is wrong
with it?"* across the whole pack: node classes, Python backend, frontend modules,
the contracts between them, the user-facing flow, and optionally a live ComfyUI.

```bash
python scripts/qa_readiness.py            # static sweep + both test suites
python scripts/qa_readiness.py --live     # + probe a running ComfyUI
python scripts/qa_readiness.py --fast     # static only, skip the suites
python scripts/qa_readiness.py --only contracts,i18n
npm run qa                                # same as the first form
```

Reports land in `artifacts/qa_readiness_report.{json,md}`; a summary prints to
stdout. **Exit code** is 0 when nothing reached the fail threshold (default
`ERROR`), 1 when something did, 2 when the sweep itself could not run. So it can
gate a release or a CI job, and `--fail-on warning` / `--fail-on blocker` /
`--fail-on never` tune how strict that is.

## Why this exists next to `pytest` and `npm test`

The suites prove individual behaviours. They cannot tell you:

- whether the copy ComfyUI actually loads matches the copy you edited;
- whether a frontend module still resolves every import it declares;
- whether a module is loaded twice under two `?boot=` tokens;
- whether the frontend calls an endpoint that no longer exists;
- whether a registration function is defined but never called, so a whole
  feature is missing at runtime;
- whether a backend event is emitted into the void because nothing listens;
- whether a translation key was added to one locale only, or is requested under a
  name that does not exist;
- how much UI text never reaches the translator at all.

Every one of those presents to a user as *"the feature silently did nothing"*,
which is the most expensive kind of bug to chase. Each check is written so that
it can actually fail.

## Layers

The layers are the columns of the readiness matrix in the report.

| Layer | What it covers |
| --- | --- |
| `toolchain` | Interpreter, ComfyUI/torch import, external binaries, **dev-vs-install drift** |
| `backend` | Syntax of every module, node class completeness, blocking I/O in async handlers |
| `frontend` | Parse check, import resolution, module identity, orphan libraries |
| `suites` | `pytest` and the standalone JS tests |
| `contracts` | Routes ↔ fetch calls, events ↔ listeners, registration wiring |
| `i18n` | Locale parity, placeholder counts, unknown/unused keys, untranslated text |
| `flow` | Dead node inputs, failure surfacing, maintainability snapshot |
| `live` | Node registration, module serving, GET route health (needs `--live`) |

Each layer rolls up to **READY / PARTIAL / BROKEN / NOT RUN**.

## Severities

| Severity | Meaning | Fails the run? |
| --- | --- | --- |
| `BLOCKER` | The pack cannot load or run at all | yes |
| `ERROR` | A feature is broken or unreachable | yes (default) |
| `WARNING` | Probably wrong; needs a human to confirm | no |
| `INFO` | Context, or a metric worth watching | no |
| `SUGGESTION` | Improvement opportunity, heuristic | no |

Checks are labelled `exact` or `advice`. **Exact** checks are derived from parsed
source or real process output, so a failure is a defect. **Advice** checks are
heuristics meant to point at places worth a look — they never gate a release on
their own. `--no-advice` skips them entirely.

## The checks that earn their keep

**Dev-vs-install drift (`tc_drift`).** ComfyUI loads the install copy while you
edit the dev checkout. When they diverge, every symptom you observe comes from
code you are not reading. Runtime files (`nodes/`, `director/`, `web/js/`, …)
differing is an `ERROR`; tests/docs/examples differing is `INFO`, because ComfyUI
never loads those and reporting them at the same severity would drown the signal.

**Dead wiring (`ct_wiring`).** Finds `register_*` / `install_*` functions with no
call site. Nothing about such a module looks wrong — it imports, the handlers are
written, the route table is explicit — it is simply never invoked, so everything
it declares is missing at runtime.

**Route contract (`ct_routes`).** Enumerates the real route table by importing
`director.http_routes` with a recording stub, then compares it against every
`api.fetchApi(...)` call site. Paths are matched segment-wise so route
parameters (`{preset_id}`) and interpolated URLs compare correctly. Only paths
under `/minimax/` are considered — ComfyUI's own core routes are the host's
business.

**Module identity (`fe_boot_tokens`).** ES modules are keyed by full URL
*including the query string*, so the same file imported as both `./x.js` and
`./x.js?boot=token` — or under two different tokens — is instantiated twice. Two
instances means two sets of module-level state, two stylesheets, and listeners
that fire twice. Module-local guards do not help, because there are two modules.

**Locale accuracy (`i18n_*`).** The three locale modules do not share one style:
bare keys, quoted dotted keys, and `Object.freeze({...})` wrappers all appear, so
the parser handles all three — a parser that understands only the first reports
the others as empty and turns their parity check into a no-op that always passes.
Usage is detected through every channel: call sites, `data-i18n*` attributes,
indirection tables, and keys built by concatenation (only the literal fragment is
visible statically, so anything under that fragment counts as reachable). Call
sites are matched only against identifiers the locale modules actually export,
because `querySelector("button.cancel")` is a CSS selector, not a translation.

## Live checks (`--live`)

Opt-in, and skipped cleanly when nothing is listening.

- **Node registration** — the three node classes are present in `/object_info`
  with real input counts.
- **Module serving** — every frontend module returns 200 from
  `/extensions/<pack>/<file>`. A 404 here is the "panel never appears / retries
  forever" failure: the browser cannot report a missing ES module other than by
  failing the whole import graph.
- **External imports** — specifiers that climb out of the pack
  (`../../scripts/app.js`) address ComfyUI's own frontend, which ships as a built
  bundle rather than loose files. Only HTTP can settle those, so they are
  verified against the server rather than guessed from disk.
- **GET route health** — parameterless GET routes must not 5xx.

## Adding a check

```python
@check("my_id", LAYER_CONTRACTS, "Human-readable title", kind=KIND_ADVICE)
def my_check(ctx: Context):
    if ctx.comfy_root is None:
        return STATUS_SKIP, "no comfy root"          # say why coverage is missing

    ctx.metrics["my_metric"] = 42                     # lands in the JSON report
    ctx.add(Finding(
        ERROR, LAYER_CONTRACTS,
        "Short title shown in the summary",
        "What it means and why it matters.",
        evidence=["file.py:12 -> detail"],            # capped at 40 lines
        hint="What to do next.",
    ))
    return STATUS_FAIL, "one-line status for the table"
```

Rules that keep the report trustworthy:

1. **A check that cannot run must `SKIP` with a reason**, never pass. A silent
   pass for a check that did not look at anything is worse than no check.
2. **Include a location** in the evidence — a finding the reader cannot navigate
   to does not get fixed.
3. **Prefer failing loudly over guessing.** If a signal can be derived exactly
   (parse it), do that; only fall back to heuristics with `kind=KIND_ADVICE`.
4. **Verify a new check against reality before trusting it.** Run it, then check
   each finding by hand. Several checks in this file initially reported
   confident nonsense — a package shadowing bug, CSS selectors read as
   translation keys, test fixtures counted as production emitters. A check that
   cries wolf gets ignored, which is worse than not having it.
5. `raise` is contained per check (`WARNING`, "Check crashed") so one bad check
   cannot end the sweep.

## Interpretation

A green sweep means no *known* class of failure is present. It does not mean the
UI is pleasant, the renders are good, or the flow is intuitive — those need eyes.
The `SUGGESTION` findings are the raw material for that judgement, not a verdict.
