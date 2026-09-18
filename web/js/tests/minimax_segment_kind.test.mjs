import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
    SEGMENT_KIND_GENERATE,
    SEGMENT_KIND_REPLACE,
    generatedRowLength,
    isGeneratedRow,
    segmentKind,
} from "../minimax_segment_kind.mjs";

// A replace job's rows are either masked windows over the source video or
// generated rows that render from their own prompt and references. The Python
// plan builder decides what a row is with lib/segment_kind.py; this module is the
// frontend twin, and the two must never disagree:
//
//   - a row the plan renders source-free must not be clamped to the source total
//     by the timeline normalizer first (which would delete an extension row), and
//   - a row the UI treats as a window must not be planned as source-free.
//
// So the alias sets are asserted against the Python file itself, not against a
// copy of the list that can drift.

const here = path.dirname(fileURLToPath(import.meta.url));
const pythonSource = fs.readFileSync(
    path.join(here, "..", "..", "..", "lib", "segment_kind.py"),
    "utf8",
);

function pythonSet(name) {
    const match = pythonSource.match(new RegExp(`${name} = frozenset\\(([^)]*)\\)`, "s"));
    assert.ok(match, `${name} not found in lib/segment_kind.py`);
    return new Set(
        [...match[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]),
    );
}

const pythonGenerate = pythonSet("_GENERATE_VALUES");
const pythonReplace = pythonSet("_REPLACE_VALUES");

for (const value of pythonGenerate) {
    assert.equal(segmentKind({ kind: value }), SEGMENT_KIND_GENERATE, `kind: ${value}`);
    assert.equal(isGeneratedRow({ kind: value }), true, `kind: ${value}`);
}
for (const value of pythonReplace) {
    assert.equal(segmentKind({ kind: value }), SEGMENT_KIND_REPLACE, `kind: ${value}`);
}

// Unknown values fall back to a window: a window still renders, a source-free row
// with a bad kind has nothing to render from.
for (const row of [{}, { kind: "banana" }, { kind: "" }, { generate: false }, null, "generate", 7]) {
    assert.equal(segmentKind(row), SEGMENT_KIND_REPLACE, JSON.stringify(row));
    assert.equal(isGeneratedRow(row), false, JSON.stringify(row));
}

// The convenience spellings the JSON may carry.
for (const row of [
    { segmentKind: "generated" },
    { segment_kind: "gen" },
    { rowKind: "generate" },
    { segmentType: "ref2va" },
    { generate: true },
    { isGenerated: true },
]) {
    assert.equal(isGeneratedRow(row), true, JSON.stringify(row));
}

// The window path must stay the historic one: a plain window row is a window.
assert.equal(isGeneratedRow({ start: 0, length: 240, replace: { enabled: true } }), false);

assert.equal(generatedRowLength({ length: 243 }), 243);
assert.equal(generatedRowLength({ start: 100, end: 343 }), 243);
assert.equal(generatedRowLength({ frameCount: 120 }), 120);
assert.equal(generatedRowLength({}), 0);
assert.equal(generatedRowLength({ length: "nonsense" }), 0);

console.log("minimax_segment_kind: OK");
