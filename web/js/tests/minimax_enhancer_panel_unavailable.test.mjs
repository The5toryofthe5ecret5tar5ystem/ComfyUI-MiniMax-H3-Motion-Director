import assert from "node:assert/strict";
import fs from "node:fs";

// A failed prompt-enhancer load used to be invisible.
//
// The panel is imported lazily, on the first click, and the import was wrapped
// in a `.catch` that logged and returned null. Every caller then did `if (!pe)
// return;` - so when the import genuinely failed (a stale cached `.mjs` missing
// an export the fresh entry needed, which is what happened), both the Enhance
// button and the Settings button stayed on screen, looked alive, and did
// nothing whatsoever on click. Nothing on screen said why.
//
// Source-level: mounting needs a live Director node and a ComfyUI api object, so
// these assertions are scoped to the function bodies and to the locale table.

const timeline = fs.readFileSync(new URL("../minimax_timeline.js", import.meta.url), "utf8");
const enhancer = fs.readFileSync(new URL("../minimax_prompt_enhancer.js", import.meta.url), "utf8");
const i18n = fs.readFileSync(new URL("../minimax_i18n.js", import.meta.url), "utf8");

/** Brace-match a function body, so a call site elsewhere cannot satisfy an assertion. */
function functionBody(source, signature) {
    const at = source.indexOf(signature);
    assert.ok(at > 0, `${signature} must still exist`);
    let depth = 0;
    for (let i = source.indexOf("{", at); i < source.length; i += 1) {
        if (source[i] === "{") depth += 1;
        else if (source[i] === "}") {
            depth -= 1;
            if (depth === 0) return source.slice(source.indexOf("{", at), i + 1);
        }
    }
    throw new Error(`${signature} body is not brace-balanced`);
}

// --- the failure is remembered ------------------------------------------------

const ensure = functionBody(timeline, "async _ensureEnhancerPanel(");
assert.match(
    ensure,
    /this\._enhancerLoadError = error\?\.message \|\| String\(error \|\| ""\);/,
    "the load error is kept, so a click can say what happened",
);
assert.match(
    ensure,
    /this\._enhancerPanelPromise = null;/,
    "a failed attempt must not be cached, or the panel can never load later",
);

// --- and reported on the button that was pressed -------------------------------

const flash = functionBody(timeline, "_flashEnhancerUnavailable(");
assert.match(
    flash,
    /const message = t\("pe\.statusEnhancerUnavailable"\);/,
    "the message comes from the translation table, not a literal",
);
assert.match(
    flash,
    /btn\.disabled = true;/,
    "the button cannot be clicked again while it shows the message",
);
assert.match(
    flash,
    /btn\.textContent = labels \? labels\[index\] : btn\.textContent;/,
    "and it restores itself, so a transient failure does not retire the button",
);
assert.ok(
    !/[\u4e00-\u9fff]/.test(flash),
    `the panel follows the UI language:\n${flash}`,
);

for (const [signature, why] of [
    ["async _enhanceActivePrompt(", "the Enhance button on the prompt row"],
    ["async _enhanceAllPrompts(", "the batch Enhance button"],
    ["async _toggleEnhanceSettings(", "the Settings button"],
]) {
    const body = functionBody(timeline, signature);
    assert.match(
        body,
        /if \(!pe\) \{[\s\S]*?_flashEnhancerUnavailable\(/,
        `${why} must report a failed load instead of returning silently`,
    );
    assert.ok(
        !/if \(!pe\) return;/.test(body),
        `${why} still has the silent early return`,
    );
}

// --- the label exists, in both languages ---------------------------------------

assert.equal(
    (i18n.match(/"pe\.statusEnhancerUnavailable":/g) || []).length,
    2,
    "one string per locale",
);
assert.match(
    enhancer,
    /from "\.\/minimax_reference_assets\.mjs\?boot=[A-Za-z0-9_]+";/,
    "the shared module is imported under a version token, so a stale browser "
    + "cache cannot answer with a copy that lacks the export",
);

console.log("Prompt enhancer failure reporting passed");
