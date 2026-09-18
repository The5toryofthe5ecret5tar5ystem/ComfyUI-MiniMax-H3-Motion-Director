import assert from "node:assert/strict";
import fs from "node:fs";

// Character Replace falling back to plain rv2v used to be reported only in the
// final execution report, so the whole run had to render before the user learned
// it had done the wrong thing. The engine now emits a live event the moment a
// segment degrades, and the run banner leads with it so the run can still be
// stopped cheaply.
//
// Source-level because the banner is inline in a 15k-line file and only runs
// against a live LiteGraph canvas.

const src = fs.readFileSync(new URL("../minimax_timeline.js", import.meta.url), "utf8");
const i18n = fs.readFileSync(new URL("../minimax_i18n.js", import.meta.url), "utf8");
const progressPy = fs.readFileSync(
    new URL("../../../director/progress.py", import.meta.url),
    "utf8",
);

/** Brace-match a function body so a call site elsewhere cannot satisfy an assertion. */
function functionBody(source, signature) {
    const at = source.indexOf(signature);
    assert.ok(at > 0, `${signature} must still exist`);
    let depth = 0;
    let i = source.indexOf("{", at);
    for (; i < source.length; i += 1) {
        if (source[i] === "{") depth += 1;
        else if (source[i] === "}") {
            depth -= 1;
            if (depth === 0) break;
        }
    }
    return source.slice(source.indexOf("{", at), i + 1);
}

// --- the two sides agree on the event name -------------------------------------
// A rename on either side would silently stop the other from receiving anything.

const EVENT = "minimax_motion_director_warning";
assert.ok(
    progressPy.includes(`"${EVENT}"`),
    `the backend must still emit ${EVENT}`,
);
assert.ok(
    src.includes(`api.addEventListener("${EVENT}"`),
    `the frontend must still listen for ${EVENT}`,
);

// --- the listener routes to the editor ----------------------------------------

assert.match(
    src,
    /api\.addEventListener\("minimax_motion_director_warning", \(\{ detail \}\) => \{[\s\S]{0,220}?editor\._noteRunWarning\?\.\(detail\);/,
    "the event must reach the editor that owns the run banner",
);

// --- state, and dedupe ---------------------------------------------------------

const note = functionBody(src, "_noteRunWarning(detail)");
assert.match(
    note,
    /this\._runWarnings\.push\(\{/,
    "the warning must be recorded so later progress ticks can keep showing it",
);
assert.match(
    note,
    /if \(this\._runWarnings\.some\(\(w\) => w\.key === key\)\) return;/,
    "a repeated warning must not pile up - the engine emits one per segment",
);
assert.match(
    note,
    /this\.setRunProgress\(this\._lastRunProgressDetail\)/,
    "it must repaint immediately rather than wait for the next tick",
);

// Clean slate per run, or a fixed problem keeps being reported.
const active = functionBody(src, "_setRunActive(active)");
assert.match(
    active,
    /if \(this\._runActive && changed\) this\._runWarnings = \[\];/,
    "starting a run must clear the previous run's warnings",
);
assert.match(
    functionBody(src, "clearRunProgress(title, detail)"),
    /this\._runWarnings = \[\];/,
    "clearing the banner must clear its warnings",
);

// --- it is actually visible during the run -------------------------------------

const warnAt = src.indexOf("if (warningText) parts.push(warningText);");
const framesAt = src.indexOf("if (detail.frames_label) parts.push(detail.frames_label);");
assert.ok(warnAt > 0, "the warning must be added to the run banner detail line");
assert.ok(framesAt > 0, "the frames label must still be shown");
assert.ok(
    warnAt < framesAt,
    "the warning must lead the detail line - it is the only actionable item there",
);

// The banner must not blow away the notice on the next progress tick.
assert.match(
    functionBody(src, "_runWarningText()"),
    /return `\\u26a0 \$\{head\}\$\{more\}`;/,
    "the warning line must be visually marked as a warning",
);

// --- the common reason is localized, not echoed in English ---------------------

assert.match(
    functionBody(src, "_runWarningText()"),
    /first\.detail\.startsWith\("mask window unavailable"\)/,
    "the mask failure must be recognised so it can be explained in the UI language",
);

for (const key of [
    "run.warnReplaceFallback",
    "run.warnSegment",
    "run.warnSegmentUnknown",
    "run.warnMore",
    "run.warnMaskWindow",
]) {
    const hits = i18n.split(`"${key}"`).length - 1;
    assert.equal(hits, 2, `${key} must exist in both zh and en`);
}

// Placeholders must match the call sites, or the banner shows a literal brace.
assert.match(i18n, /"run\.warnReplaceFallback": "[^"]*\{n\}[^"]*\{detail\}[^"]*"/);
assert.match(i18n, /"run\.warnMore": "[^"]*\{n\}[^"]*"/);

console.log("replace run-warning tests passed");
