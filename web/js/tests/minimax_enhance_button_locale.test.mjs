import assert from "node:assert/strict";
import fs from "node:fs";
import { JSDOM } from "jsdom";

// The Enhance button on the Director's prompt row reflects a run by swapping its
// label to an in-progress one. That label used to be a hardcoded Chinese literal,
// so an English panel showed 扩写中… the moment a run started while every widget
// around it - the neighbouring Settings button, the panel itself - stayed English
// through `data-i18n`. The label is a translated string now; these assertions pin
// that, and pin that English output is actually English.

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

const enhance = functionBody(src, "async _enhanceActivePrompt(");

assert.match(
    enhance,
    /const loadingLabel = t\("pe\.statusEnhancing"\)/,
    "the in-progress label comes from the translation table, not from a literal",
);
assert.match(
    enhance,
    /buttons\.forEach\(\(btn\) => \{ btn\.disabled = true; btn\.textContent = loadingLabel; \}\);/,
    "every Enhance button shows it and is disabled for the duration",
);
assert.ok(
    !/[\u4e00-\u9fff]/.test(enhance),
    `the running state must not hardcode Chinese:\n${enhance}`,
);
assert.match(
    enhance,
    /const labels = buttons\.map\(\(btn\) => btn\.textContent\);/,
    "the resting labels are captured first, so the button returns to what it said",
);
assert.match(
    enhance,
    /btn\.textContent = labels\[index\];/,
    "and restored in a finally block, so a failed run does not leave it mid-flight",
);

// --- the key exists for both locales, and the English one is English ------------

assert.equal(
    (i18n.match(/"pe\.statusEnhancing":/g) || []).length,
    2,
    "one string per locale",
);

const dom = new JSDOM("<!doctype html><html><head></head><body></body></html>", { url: "http://localhost/" });
Object.assign(globalThis, { window: dom.window, document: dom.window.document });
Object.defineProperty(globalThis, "localStorage", { value: dom.window.localStorage, configurable: true });

const { getLocale, setLocale, t } = await import("../minimax_i18n.js");

setLocale("en");
assert.equal(getLocale(), "en");
const english = t("pe.statusEnhancing");
assert.ok(english.length > 0 && !/[\u4e00-\u9fff]/.test(english), `English UI must not show Chinese: ${english}`);

setLocale("zh");
const chinese = t("pe.statusEnhancing");
assert.ok(/[\u4e00-\u9fff]/.test(chinese), `Chinese UI must be Chinese: ${chinese}`);
assert.notEqual(english, chinese, "the label follows the UI language");

// Whatever the locale, the button never falls back to the bare key.
assert.ok(!english.includes("pe.") && !chinese.includes("pe."), "resolved, not a raw key");
