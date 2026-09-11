// Wiring contract for the resume start point.
//
// `minimax_resume_intent.mjs` is unit tested on its own. The integration risks
// are that the timeline goes back to coercing the dialog's <select> value by
// hand — `Number("")` is 0, so a blank selection becomes "resume at S1" — and
// that a resume call site bypasses the single intent funnel.
//
// Regression under test (2026-09-11): the resume dialog's cache check reported
// the prefix as reusable, yet the queued prompt carried
// `resumeRun {enabled: true, from: 0}` and the run restarted at segment 1.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const source = readFileSync(join(repoRoot, "web", "js", "minimax_timeline.js"), "utf8");

function slice(startMarker, endMarker) {
    const start = source.indexOf(startMarker);
    assert.ok(start !== -1, `missing marker: ${startMarker}`);
    const end = source.indexOf(endMarker, start);
    assert.ok(end !== -1, `missing end marker after ${startMarker}: ${endMarker}`);
    return source.slice(start, end);
}

/** A class method body, found structurally (class members sit at 4 spaces). */
function methodBody(signature) {
    const start = source.indexOf(signature);
    assert.ok(start !== -1, `missing method: ${signature}`);
    const rest = source.slice(start);
    const boundary = rest.slice(1).search(/\n {4}[A-Za-z_$#]/);
    assert.ok(boundary !== -1, `no following member after ${signature}`);
    return rest.slice(0, boundary + 1);
}

// --- the module is the single source of truth ---------------------------------

assert.ok(
    source.includes('} from "./minimax_resume_intent.mjs";'),
    "the resume-intent module must be imported",
);
assert.ok(source.includes("buildResumeRun"), "buildResumeRun must be used");
assert.ok(source.includes("parseResumeIndex"), "parseResumeIndex must be used");
assert.ok(source.includes("resolveSelectChoice"), "resolveSelectChoice must be used");

// --- _applyRunIntent is the funnel and does no inline coercion -------------------

const intentBody = methodBody("    _applyRunIntent({");

assert.ok(
    intentBody.includes("timeline.resumeRun = buildResumeRun({ resume, from });"),
    "the intent must be built by the shared module",
);
assert.ok(
    !/Number\(from\)/.test(intentBody),
    "no inline Number(from): it maps \"\" to 0 and would restart at S1",
);

// A non-resume run must not be able to carry a start point at all.
assert.ok(!/resumeRun\s*=\s*\{\s*enabled:\s*true/.test(intentBody), "no hand-built resumeRun object");

// --- every queue path funnels through it ----------------------------------------

const queueOnceBody = methodBody("    _queueOnce({");
assert.ok(
    queueOnceBody.includes("this._applyRunIntent({ resume, from });"),
    "_queueOnce must route the intent through _applyRunIntent",
);

const queueRunBody = methodBody("    _queueRunWithIntent({");
assert.ok(
    queueRunBody.includes("this._applyRunIntent({ resume, from });"),
    "_queueRunWithIntent must route the intent through _applyRunIntent",
);

// Sanity: the queue call the funnels end at still exists.
const rawResumeQueues = [...source.matchAll(/app\.queuePrompt\(\)/g)].length;
assert.ok(rawResumeQueues >= 1, "sanity: the queue prompt call still exists");

// --- the dialog parses its <select> through the module ---------------------------

const runHandler = slice('        layer.querySelector(\'[data-rd="run"]\')', '        layer.querySelector(\'[data-rd="apply"]\')');

assert.ok(
    runHandler.includes("const from = parseResumeIndex(value);"),
    "the dialog must parse the select through parseResumeIndex",
);
assert.ok(
    !/Number\(value\)/.test(runHandler),
    "the old `Number(value)` coercion is the bug: \"\" must not become 0",
);
assert.ok(
    !/Number\.isNaN\(from\)/.test(runHandler),
    "the NaN guard never fired, because Number(\"\") is 0 rather than NaN",
);
assert.ok(
    runHandler.includes("RESUME_START_FRESH"),
    "the Start Over option must be compared against the shared constant",
);

// The handler still has to distinguish "Start Over" (clears caches) from a start
// index; losing that branch would silently reuse caches on a fresh run.
assert.ok(
    runHandler.includes("this._queueRunWithIntent({ freshClear: true });"),
    "Start Over must still clear the caches",
);

// --- "Restart segment" parses its index the same way ---------------------------

const restartBody = methodBody("    restartSegmentRun() {");
assert.ok(
    restartBody.includes("parseResumeIndex(this._runCurrentSegment)"),
    "the live restart must parse the current segment through the module",
);
assert.ok(
    restartBody.includes("parseResumeIndex(this._resumeNext ?? total)"),
    "the offline restart must parse the next index through the module",
);
assert.ok(
    !/Number\(this\._resumeNext/.test(restartBody),
    "an unset next segment must not be coerced to segment 1",
);
assert.ok(
    restartBody.includes("this._pendingRestart = { from };"),
    "the pending restart must carry the parsed index directly",
);
// A genuine 0 still has to work: restarting segment 1 is a real action.
assert.ok(
    restartBody.includes("next != null && next < total"),
    "0 must still satisfy the range check",
);

// --- the select can never be left blank ------------------------------------------

const preset = slice('        const startSelect = layer.querySelector(\'[data-rd="start"]\');', "        const applyBtn =");

assert.ok(
    preset.includes('resolveSelectChoice(desired, optionValues, "0")'),
    "the preset must pick a value that is really offered",
);
assert.ok(
    !/startSelect\.value = String\(/.test(preset),
    "raw String() assignment leaves the select reporting \"\" when the value is not offered",
);

// `optionValues` has to mirror the rendered options, or the guard is a lie.
const optionsBlock = slice("        // Start-point options", "        const ppText =");
const pushes = (optionsBlock.match(/options\.push\(/g) || []).length;
const valuePushes = (optionsBlock.match(/optionValues\.push\(/g) || []).length;
assert.equal(
    valuePushes,
    pushes,
    "every rendered option must also be registered in optionValues",
);
assert.ok(pushes >= 3, "fresh + S1 + at least one reuse option");
assert.ok(
    optionsBlock.includes('optionValues.push("0")'),
    'the "0" fallback must exist whenever total > 0',
);

console.log("minimax_resume_intent wiring: all assertions passed");
