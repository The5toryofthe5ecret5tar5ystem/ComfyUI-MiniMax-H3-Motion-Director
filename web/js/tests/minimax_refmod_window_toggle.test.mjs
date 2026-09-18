import assert from "node:assert/strict";
import fs from "node:fs";

// The Director harvests ONE set of RefMod blocks from the connected conditioning
// and appends it to every segment. A mod that belongs to some windows and not
// others therefore had no way to say so, and the prompt enhancer's RefMod recipe
// cannot fix that by itself: the switch has to reach the plan (refmodEnabled) and
// the executor (append_refmod_references per segment).
//
// Source-level, because the row builder only runs against a live LiteGraph canvas
// and a real Director node. The assertions are scoped to the function bodies so a
// call site elsewhere cannot satisfy them.

const src = fs.readFileSync(new URL("../minimax_timeline.js", import.meta.url), "utf8");

/** Brace-match a function body, so a call site elsewhere cannot satisfy an assertion. */
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

// --- the per-window checkbox in the replace list --------------------------------

const makeRow = functionBody(src, "function makeRow(seg) {");
assert.match(
    makeRow,
    /refmodInput\.checked = seg\.refmodEnabled !== false;/,
    "the checkbox opens in the state the segment is in, defaulting to on",
);
assert.match(
    makeRow,
    /winOnly\.append\(refmodLbl, refmodInput\);/,
    "and sits in the row's own control line",
);
assert.match(
    makeRow,
    /line2\.append\(winOnly, genOnly\);/,
    "that control group is attached to the row (generated rows hide it as a unit)",
);
assert.match(
    makeRow,
    /policy, contInput, refmodInput,/,
    "it is registered with the row's inputs, or syncRowValues cannot see it",
);

const syncRowValues = functionBody(src, "function syncRowValues(row, cfg, seg, fps) {");
assert.match(
    syncRowValues,
    /inp\.refmodInput\.checked = seg\.refmodEnabled !== false;/,
    "a redraw reflects the segment, not the last click",
);

const bindRow = functionBody(src, "function bindRow(row) {");
assert.match(
    bindRow,
    /inp\.refmodInput\.addEventListener\("change", \(\) => \{/,
    "the checkbox writes back",
);
assert.match(
    bindRow,
    /seg\.refmodEnabled = !!inp\.refmodInput\.checked;\s*\n\s*commitLight\(\);/,
    "and the timeline is committed, so the value reaches the render",
);

// --- the same switch on the segment menu ---------------------------------------

const menu = functionBody(src, "function openSegmentContextLinkMenu(event, editor, index) {");
assert.match(menu, /const refmodOn = editor\.getSegmentRefmod\?\.\(index\) !== false;/);
assert.match(menu, /\{ label: refmodOn \? "RefMod \(ON\)" : "RefMod \(OFF\)", refmodToggle: true \},/);
assert.match(
    menu,
    /if \(option\.refmodToggle\) \{\s*\n\s*editor\.toggleSegmentRefmod\?\.\(index\);\s*\n\s*return;/,
    "choosing it flips the segment",
);

const getter = functionBody(src, "getSegmentRefmod(index) {");
assert.match(getter, /return this\.timeline\.segments\?\.\[index\]\?\.refmodEnabled !== false;/, "on by default");

const toggler = functionBody(src, "toggleSegmentRefmod(index) {");
assert.match(toggler, /seg\.refmodEnabled = seg\.refmodEnabled === false;/, "flips, not forces");
assert.match(toggler, /this\.timeline\.shots\?\.\[index\]/, "the legacy shots mirror follows");
assert.match(toggler, /this\._commitContextLinkChange\(\);/, "and the change is persisted");

// The switch is only half the story: the field has to survive a save/load round
// trip. Segments are sanitized field by field, and they spread the rest.
const sanitizer = functionBody(src, "function sanitizeSegmentForPayload(seg) {");
assert.match(sanitizer, /\.\.\.rest,/, "unknown segment fields (refmodEnabled) are carried through");
