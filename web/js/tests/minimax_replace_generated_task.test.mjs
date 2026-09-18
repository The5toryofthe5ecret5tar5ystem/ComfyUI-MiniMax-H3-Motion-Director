import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

// A generated row renders from its own prompt and references, and the one thing
// it cannot do on its own is start where the segment in front of it ended. The
// row therefore offers the two ways to join:
//
//   r2v - continues from the previous segment as context, whose last rendered
//         frame also arrives as a <Picture> anchor, and
//   i2v - locks that frame as this row's literal frame 0.
//
// Both hang off the row's task together with the cont switch, so this test pins
// the wiring rather than the rendering: the controls exist, they write the
// fields the plan reads (seg.kind / seg.taskType / the recipe's continuity), and
// the window-only controls still hide themselves on a generated row.

const here = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.join(here, "..", "minimax_timeline.js"), "utf8");

/** Body of a named function/method, by brace matching from its opening line. */
function functionBody(source, signature) {
    const at = source.indexOf(signature);
    assert.ok(at >= 0, `not found: ${signature}`);
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

const makeRow = functionBody(src, "function makeRow(seg) {");
assert.match(
    makeRow,
    /const genOnly = document\.createElement\("span"\);/,
    "the generated row gets its own control group",
);
assert.match(
    makeRow,
    /selectField\(\s*\["r2v", "i2v"\]/,
    "with the task choice: continue as context, or lock the previous frame",
);
assert.match(
    makeRow,
    /genOnly\.append\(taskSel\);/,
    "and holds the task choice on its own, so the control line keeps the window layout",
);
assert.match(
    makeRow,
    /line2\.append\(rowKindSel\);/,
    "with the kind selector last, where a window row has it",
);
assert.match(
    makeRow,
    /line2\.append\(contLbl, contInput\);/,
    "the cont switch stays visible for both kinds - a generated row joins with it too",
);

const syncRowValues = functionBody(src, "function syncRowValues(row, cfg, seg, fps) {");
assert.match(
    syncRowValues,
    /inp\.genOnly\.style\.display = generated \? "inline-flex" : "none";/,
    "the two groups swap with the row kind",
);
assert.match(
    syncRowValues,
    /inp\.taskSel\.value = String\(seg\.taskType \|\| ""\)\.trim\(\)\.toLowerCase\(\) === "i2v" \? "i2v" : "r2v";/,
    "the selector reflects the row, not the last click",
);

const bindRow = functionBody(src, "function bindRow(row) {");
assert.match(
    bindRow,
    /seg\.taskType = inp\.taskSel\.value === "i2v" \? "i2v" : "r2v";/,
    "the choice reaches the segment the plan reads",
);
assert.match(
    bindRow,
    /if \(String\(seg\.taskType \|\| ""\)\.trim\(\) === ""\) seg\.taskType = "r2v";/,
    "a row switched to generated gets the safe task, never an empty one",
);

const pushNew = functionBody(src, "function pushNewGeneratedSegment() {");
assert.match(
    pushNew,
    /seg\.taskType = "r2v";/,
    "a new generated row starts on the safe, always-available task",
);

console.log("minimax_replace_generated_task: OK");
