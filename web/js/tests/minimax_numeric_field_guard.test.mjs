import assert from "node:assert/strict";
import fs from "node:fs";

// Typing "1.2" into the Director's megapixels field used to end up as "12": the
// field's `input` handler debounces 280 ms, and a background refresh
// (syncOutputUIFromTimeline / _applyMixedSharedControls) writes the value back.
//
// The trap is that `<input type="number">` never exposes an in-progress draft: while
// the visible text is "1." the `.value` getter already reports "1" (Chromium drops the
// trailing dot and keeps `badInput` false — verified in a real Chromium number field).
// So the refresh wrote "1", the dot vanished, and the next keystroke produced "12".
//
// setNumericFieldValue() routes every one of those writes through a focus check, so
// the digits the caret is sitting in are never touched. These tests pin both the
// helper's behaviour and the fact that the timeline actually uses it.

import { parseMegapixelsInput, setNumericFieldValue } from "../minimax_gen_timeline.js";

const timeline = fs.readFileSync(new URL("../minimax_timeline.js", import.meta.url), "utf8");
const genTimeline = fs.readFileSync(new URL("../minimax_gen_timeline.js", import.meta.url), "utf8");

/** The smallest stand-in for a Chromium number input, including the sanitised getter. */
function numberField(initial = "") {
    let text = String(initial);
    const field = {
        writes: 0,
        get value() {
            // Chromium: "1." is not a valid floating-point number, so the getter
            // reports the sanitised value and the draft is invisible to scripts.
            return /^-?\d+\.$/.test(text) ? text.slice(0, -1) : text;
        },
        set value(next) {
            field.writes += 1;
            text = String(next);
        },
        /** What the user sees (the getter can't show this). */
        get text() {
            return text;
        },
        ownerDocument: { activeElement: null },
    };
    return field;
}

function functionBody(source, signature) {
    const at = source.indexOf(signature);
    assert.ok(at > 0, `${signature} must still exist in minimax_timeline.js`);
    // Signatures end with the body's own `{` so the backwards search below lands on it.
    const bodyStart = source.lastIndexOf("{", at + signature.length - 1);
    let depth = 0;
    for (let i = bodyStart; i < source.length; i += 1) {
        if (source[i] === "{") depth += 1;
        else if (source[i] === "}") {
            depth -= 1;
            if (depth === 0) return source.slice(bodyStart, i + 1);
        }
    }
    throw new Error(`unbalanced braces after ${signature}`);
}

// --- the reported bug, end to end ------------------------------------------ //

const focused = numberField();
focused.ownerDocument.activeElement = focused;
// User types "1" then "." — the field is holding the caret the whole time.
focused.value = "1";
assert.equal(setNumericFieldValue(focused, 1), false, "a focused field must not be written");
focused.value = "1."; // the dot the user just typed
assert.equal(focused.text, "1.", "the typed dot must survive the background refresh");
assert.equal(setNumericFieldValue(focused, 1), false, "refresh while typing: still skipped");
assert.equal(focused.text, "1.");
// ... and the next keystroke lands on the draft instead of replacing it.
focused.value = `${focused.text}2`;
assert.equal(focused.text, "1.2");
assert.equal(parseMegapixelsInput(focused.value), 1.2, "the debounced commit sees 1.2, not 12");

// The regression, for the record: the old code assigned unconditionally, which is
// what rewrote "1." into "1" (and then "1" + "2" = "12").
const stomped = numberField();
stomped.ownerDocument.activeElement = stomped;
stomped.value = "1";
stomped.value = "1.";
stomped.value = "1"; // <- what the unguarded refresh did
assert.equal(stomped.text, "1");
stomped.value = `${stomped.text}2`;
assert.equal(stomped.text, "12", "without the guard the same keystrokes produce 12");

// --- helper contract -------------------------------------------------------- //

const idle = numberField("1");
idle.ownerDocument.activeElement = {}; // some other control has focus
assert.equal(setNumericFieldValue(idle, 1.2), true, "an idle field is written");
assert.equal(idle.text, "1.2");

const stable = numberField("1.2");
stable.ownerDocument.activeElement = {};
assert.equal(setNumericFieldValue(stable, 1.2), true);
assert.equal(stable.writes, 0, "an identical value must not touch the DOM");

assert.equal(setNumericFieldValue(null, 5), false, "a missing field is a no-op");
assert.equal(setNumericFieldValue(undefined, 5), false);

// Numbers arrive as numbers from resolutionFromSelector; the field is text.
const fractional = numberField("0");
fractional.ownerDocument.activeElement = {};
setNumericFieldValue(fractional, 0.8);
assert.equal(fractional.value, "0.8");
setNumericFieldValue(fractional, 1);
assert.equal(fractional.value, "1");

// --- the timeline must route its numeric refreshes through the helper ------- //

assert.match(
    timeline,
    /setNumericFieldValue,/,
    "the Director must import the guard",
);
assert.match(
    timeline,
    /from "\.\/minimax_gen_timeline\.js\?boot=numeric_field_guard_v1"/,
    "a module that gained an export must be fetched fresh (boot token)",
);
assert.match(genTimeline, /export function setNumericFieldValue\(/, "the guard is exported");

const mixed = functionBody(timeline, "_applyMixedSharedControls() {");
for (const field of ["this.outMp", "this.outW", "this.outH", "this.outLong", "this.outMaxFrames", "this.fpsInput"]) {
    assert.ok(
        mixed.includes(`setNumericFieldValue(${field},`),
        `${field} refresh in _applyMixedSharedControls must be guard-protected`,
    );
}
assert.ok(
    !/this\.outMp\.value\s*=/.test(mixed),
    "no raw megapixels write may come back to _applyMixedSharedControls",
);

const sync = functionBody(timeline, "syncOutputUIFromTimeline() {");
for (const field of ["this.outMp", "this.outW", "this.outH", "this.outLong", "this.outMaxFrames", "this.segmentContinuityOverlap"]) {
    assert.ok(
        sync.includes(`setNumericFieldValue(${field},`),
        `${field} refresh in syncOutputUIFromTimeline must be guard-protected`,
    );
}
assert.ok(
    !/this\.outMp\.value\s*=/.test(sync),
    "syncOutputUIFromTimeline must not write the megapixels text directly",
);

assert.ok(
    functionBody(timeline, "applyResolutionSelector(aspectRatio = null, megapixels = null) {").includes("setNumericFieldValue(this.outMp,"),
    "resolution changes must keep the typed megapixels draft",
);
assert.ok(
    functionBody(timeline, "applyCustomResolution(width = null, height = null) {").includes("setNumericFieldValue(this.outMp,"),
    "custom resolution changes must keep the typed megapixels draft",
);

// The commit path may still normalise the text on purpose (Enter/blur = done typing).
const mpWiring = timeline.slice(timeline.indexOf("const applyMp = ("), timeline.indexOf("this.outMp.addEventListener(\"keydown\""));
assert.ok(mpWiring.includes("if (force) this.outMp.value = String(parsed);"),
    "an explicit commit still normalises the field text");
assert.ok(mpWiring.includes("parseMegapixelsInput(this.outMp.value)"),
    "the debounce must still refuse incomplete drafts");
assert.ok(mpWiring.includes("applyMp({ force: false })"),
    "the debounced refresh must stay non-forcing");

console.log("numeric field guard: drafts survive background refreshes");
