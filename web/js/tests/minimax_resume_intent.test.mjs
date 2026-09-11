// Resume intent: turning a resume-dialog choice into the `resumeRun` payload.
//
// The bug this pins down: `from` is 0-based and 0 is a legitimate value, while
// a <select> with no matching <option> reports "" — and `Number("")` is 0, not
// NaN. So a blank selection used to be indistinguishable from "start at S1".
// The engine obeyed the 0 and restarted the run at segment 1 even though the
// cache check had reported the prefix as reusable.

import assert from "node:assert/strict";
import {
    RESUME_START_AUTO,
    RESUME_START_FRESH,
    buildResumeRun,
    parseResumeIndex,
    resolveSelectChoice,
} from "../minimax_resume_intent.mjs";

// ---------------------------------------------------------------------------
// parseResumeIndex — a blank is an absent choice, never segment 0
// ---------------------------------------------------------------------------

assert.equal(parseResumeIndex(""), null, '"" must not become 0');
assert.equal(parseResumeIndex("   "), null, "whitespace must not become 0");
assert.equal(parseResumeIndex(null), null);
assert.equal(parseResumeIndex(undefined), null);
assert.equal(parseResumeIndex(RESUME_START_FRESH), null, '"fresh" is not an index');

// "Auto" is the dialog's default and must mean "engine decides", never index 0.
assert.equal(parseResumeIndex(RESUME_START_AUTO), null, '"auto" means engine decides');
assert.equal(parseResumeIndex("auto"), null);
assert.equal(parseResumeIndex(" auto "), null);
assert.equal(buildResumeRun({ resume: true, from: RESUME_START_AUTO }).from, null);

// Junk must not be coerced into a real segment number.
assert.equal(parseResumeIndex("abc"), null);
assert.equal(parseResumeIndex(NaN), null);
assert.equal(parseResumeIndex(Infinity), null);
assert.equal(parseResumeIndex(-1), null, "negative indices are not resumable");
assert.equal(parseResumeIndex("-2"), null);
assert.equal(parseResumeIndex({}), null);
assert.equal(parseResumeIndex([]), null);

// A genuine 0 survives — it is the explicit "re-render from S1" choice.
assert.equal(parseResumeIndex(0), 0, "0 is a real choice, not a blank");
assert.equal(parseResumeIndex("0"), 0, '"0" is a real choice');
assert.equal(parseResumeIndex(" 0 "), 0);
assert.equal(parseResumeIndex(2), 2);
assert.equal(parseResumeIndex("2"), 2);
assert.equal(parseResumeIndex("2.7"), 2, "indices are floored");

// ---------------------------------------------------------------------------
// buildResumeRun — the exact object handed to the engine
// ---------------------------------------------------------------------------

assert.deepEqual(
    buildResumeRun({ resume: true, from: "" }),
    { enabled: true, from: null },
    "the reported bug: a blank start must mean 'engine decides'",
);
assert.deepEqual(
    buildResumeRun({ resume: true, from: null }),
    { enabled: true, from: null },
);
assert.deepEqual(
    buildResumeRun({ resume: true }),
    { enabled: true, from: null },
    "omitted `from` is auto, not 0",
);
assert.deepEqual(buildResumeRun({ resume: true, from: 0 }), { enabled: true, from: 0 });
assert.deepEqual(buildResumeRun({ resume: true, from: "3" }), { enabled: true, from: 3 });

// A non-resume run must never carry a stale start point.
assert.deepEqual(buildResumeRun({ resume: false, from: 4 }), { enabled: false, from: null });
assert.deepEqual(buildResumeRun({}), { enabled: false, from: null });
assert.deepEqual(buildResumeRun(), { enabled: false, from: null });

// The payload is JSON-serialized into timeline_data; null must survive as null
// (the engine's `raw is None -> None` branch) rather than becoming 0.
const wire = JSON.parse(JSON.stringify(buildResumeRun({ resume: true, from: "" })));
assert.deepEqual(wire, { enabled: true, from: null });
assert.equal(wire.from === 0, false, "must not be 0 after a JSON round-trip");

// ---------------------------------------------------------------------------
// resolveSelectChoice — never leave the <select> disagreeing with the state
// ---------------------------------------------------------------------------

const choices = [RESUME_START_FRESH, "0", "1", "2"];

assert.equal(resolveSelectChoice("1", choices), "1", "keeps an offered value");
assert.equal(resolveSelectChoice(2, choices), "2", "numbers match after stringifying");
assert.equal(resolveSelectChoice("0", choices), "0", "0 is a selectable value");
assert.equal(resolveSelectChoice(0, choices), "0");

// Not offered -> fall back deterministically instead of silently reporting "".
assert.equal(resolveSelectChoice("9", choices, "0"), "0");
assert.equal(resolveSelectChoice("9", choices, "7"), "fresh", "falls back to the first option");
assert.equal(resolveSelectChoice("", choices, "0"), "0", "a blank desired value uses the fallback");
assert.equal(resolveSelectChoice(null, choices, "1"), "1");

// A select with only the destructive option must still resolve to something.
assert.equal(resolveSelectChoice("3", [RESUME_START_FRESH], "0"), "fresh");
assert.equal(resolveSelectChoice("3", []), "", "no options -> empty value");

console.log("minimax_resume_intent: all assertions passed");
