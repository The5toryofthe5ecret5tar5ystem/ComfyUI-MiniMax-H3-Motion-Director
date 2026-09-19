import assert from "node:assert/strict";
import fs from "node:fs";

// A red "missing asset" chip used to be a dead end: the only ways out were to
// delete the chip and insert the mention again, or to re-add the reference and
// hope the re-add guessed the same asset. The Library path guesses by kind and
// document order, which is right most of the time and wrong the rest of it.
//
// The chip now opens a list of the assets this prompt can actually name and
// rewrites the token to the one you pick. These are source-level assertions
// because the module needs a live editor and a DOM to run; everything they guard
// is behaviour a future edit could silently drop.

const mentions = fs.readFileSync(new URL("../minimax_prompt_mentions.js", import.meta.url), "utf8");
const i18n = fs.readFileSync(new URL("../minimax_i18n.js", import.meta.url), "utf8");

// Only missing chips get the affordance: a working mention must stay inert, and a
// disabled one already has its own path (re-enable it in the segment).
assert.match(
    mentions,
    /if \(presentation\.state === "missing"\) \{[\s\S]{0,400}chip\.dataset\.relink = "1";/,
    "the relink affordance is attached to missing chips only",
);
assert.match(mentions, /openRelinkMenu\(chip, token, kind\);/);

// The menu lists the assets of that kind which are in scope, and writes the
// token of the chosen one - not a new id, and not a re-guess.
assert.match(
    mentions,
    /const candidates = mediaItems\(\)\.filter\(\(candidate\) => candidate\.kind === kind\);/,
    "candidates are filtered to the chip's own kind",
);
assert.match(
    mentions,
    /textarea\.value = String\(textarea\.value \|\| ""\)\.split\(token\)\.join\(replacement\);/,
    "picking a candidate rewrites exactly the token that was red",
);
assert.match(
    mentions,
    /textarea\.dispatchEvent\(new Event\("input", \{ bubbles: true \}\)\);/,
    "the rewrite goes through the normal input path, so the timeline sees it",
);

// An empty candidate list must not open an empty box over the prompt.
assert.match(mentions, /if \(!candidates\.length\) return;/);

// Dismissal is registry-managed, so destroying the editor removes it.
assert.match(mentions, /listeners\.add\(document, "mousedown", onOutside, true\);/);
assert.doesNotMatch(
    mentions,
    /document\.addEventListener\("mousedown", onOutside, true\);/,
    "no second, unmanaged listener for the same dismissal",
);

// Both locales ship the strings, or one language shows raw keys in a tooltip.
for (const key of ["mention.relinkTitle", "mention.relinkHint"]) {
    const count = (i18n.match(new RegExp(`"${key.replace(".", "\\.")}"`, "g")) || []).length;
    assert.equal(count, 2, `${key} must exist in zh and en`);
}

// The hint is appended to the tooltip that already explains the failure, rather
// than replacing it.
assert.match(mentions, /chip\.title = `\$\{presentation\.title\}\\n\$\{t\("mention\.relinkHint"\)\}`;/);
