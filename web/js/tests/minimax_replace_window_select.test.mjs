import assert from "node:assert/strict";
import fs from "node:fs";

// Replace mode hides the canvas timeline (`.bd-viewport`) - and the canvas is how
// a segment is normally selected by clicking it. The window list that replaces it
// had no way to select anything either, so the prompt box, the negative prompt,
// the reference/audio slots and every panel that follows `selectedIndex` stayed on
// window 1 no matter which window the user was working in.
//
// Source-level because the installer is inline in a 15k-line file and only runs
// against a live LiteGraph canvas; the assertions are scoped to the function body
// so a call site elsewhere cannot satisfy them.

const src = fs.readFileSync(new URL("../minimax_timeline.js", import.meta.url), "utf8");
const i18n = fs.readFileSync(new URL("../minimax_i18n.js", import.meta.url), "utf8");

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

const panel = functionBody(src, "function installReplaceWindowsMode(");

// --- the row selects the window it stands for ----------------------------------

assert.match(
    panel,
    /function selectRow\(segId\) \{/,
    "the window list owns the selection it is the only picker for",
);
assert.match(
    panel,
    /const idx = segs\.findIndex\(\(s\) => String\(s\.id\) === String\(segId\)\);/,
    "looked up by id, because the list keeps the user's drag order, not timeline order",
);

const selectRow = functionBody(panel, "function selectRow(");
assert.match(selectRow, /ed\.selectedIndex = idx;/, "it moves the selection");
assert.match(
    selectRow,
    /ed\.updateSelectionUI\?\.\(\);/,
    "and re-points the prompt box / references at the new segment - a highlight alone would switch nothing",
);

// The row and its W label both select; the row's own controls keep their clicks.
assert.match(panel, /label\.addEventListener\("click",[\s\S]{0,120}selectRow\(seg\.id\);/);
assert.match(
    panel,
    /row\.addEventListener\("click", \(ev\) => \{[\s\S]{0,200}ev\.target\.closest\?\.\("input, button, select, textarea, a"\)[\s\S]{0,80}selectRow\(seg\.id\);/,
    "a click on the row selects it, except on the controls inside it",
);
assert.match(panel, /row\.title = isGeneratedRow\(seg\)/, "the row explains what clicking does (and adds the generated note when it is one)");

// --- the selected row is visibly the selected one ------------------------------

const mark = functionBody(panel, "function markSelectedRow(");
assert.match(mark, /const selectedId = String\(segs\[idx\]\?\.id \?\? ""\);/);
assert.match(mark, /String\(row\.dataset\.replaceRow\) === selectedId/);
assert.match(panel, /row\.dataset\.replaceRow = String\(seg\.id\);/, "rows carry the id they stand for");
assert.match(panel, /markSelectedRow\(\);\n    \}/, "the mark is painted after every render");
assert.match(
    panel,
    /ed\._replaceMarkSelectedRow = markSelectedRow;/,
    "exposed so the one funnel every selection change goes through can repaint it",
);
assert.match(
    functionBody(src, "updateSelectionUI() {"),
    /this\._replaceMarkSelectedRow\?\.\(\);/,
    "updateSelectionUI is that funnel: canvas clicks, batch cards and this list all reach it",
);

// --- and the user is told, in both locales -------------------------------------

assert.equal(
    (i18n.match(/"replace\.rowSelectTitle":/g) || []).length,
    2,
    "one string per locale",
);
