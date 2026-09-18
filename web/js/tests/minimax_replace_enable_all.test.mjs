import assert from "node:assert/strict";
import fs from "node:fs";

// The backend gate for character replace is `seg.replace.enabled`, so a
// long-form chain only engages if EVERY window's own checkbox is ticked. The
// panel's Replace ON/OFF toggle does not set those, which made "Replace: ON"
// look engaged while the run was still plain rv2v. The master switch exists to
// do the whole list at once, and it has to mirror the real state - claiming
// "all on" while half the list is off is the exact confusion it removes.
//
// Source-level because the installer is inline in a 15k-line file and only runs
// against a live LiteGraph canvas.

const src = fs.readFileSync(new URL("../minimax_timeline.js", import.meta.url), "utf8");
const i18n = fs.readFileSync(new URL("../minimax_i18n.js", import.meta.url), "utf8");

const start = src.indexOf("function installReplaceWindowsMode(");
assert.ok(start > 0, "installReplaceWindowsMode must still exist");

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

const body = functionBody(src, "function installReplaceWindowsMode(");

// --- the control exists and sits in the panel header, next to the badge counts ---

assert.match(
    body,
    /enableAll\.dataset\.a = "replace-enable-all";/,
    "the master switch needs a stable hook so it can be found and tested",
);
assert.match(
    body,
    /enableAll\.type = "checkbox";/,
    "the master switch must be a checkbox",
);
assert.match(
    body,
    /header\.append\(hTitle, countBadge, coverBadge, onBadge, enableAllWrap, mkSpacer\(\), unit, hSub\);/,
    "the master switch belongs in the header row with the window-count badges",
);
assert.match(
    body,
    /enableAllLbl\.dataset\.i18n = "replace\.enableAll";/,
    "the label must carry data-i18n or applyI18nDom cannot re-localise it",
);

// --- the header must not read as approval while nothing is switched on ---
// Coverage answers "do the windows tile the clip?", and stays true with every
// window switched off. The enabled count is the number the engine obeys.
assert.match(
    body,
    /onBadge\.dataset\.a = "replace-enabled-badge";/,
    "the enabled-count badge needs a stable hook so it can be found and tested",
);
assert.match(
    body,
    /onBadge\.textContent = t\("replace\.badge\.enabledNone"\);/,
    "zero enabled windows must say so outright rather than showing a healthy count",
);
assert.match(
    body,
    /setBadgeMuted\(onBadge, !enabled\.all\);/,
    "the badge must only read as healthy when every window is on",
);
assert.match(
    body,
    /const enabled = replaceEnabledCount\(segs\);/,
    "the count must come from the shared helper, not a second derivation",
);

// Both locales must carry the new keys, or the badge falls back to the raw key.
for (const key of ["replace.badge.enabled", "replace.badge.enabledNone", "replace.badge.enabledTitle"]) {
    const hits = i18n.split(`"${key}"`).length - 1;
    assert.equal(hits, 2, `${key} must exist in both zh and en`);
}

// --- it drives the flag the backend reads, and only that flag ---

const handler = body.slice(
    body.indexOf('enableAll.addEventListener("change"'),
    body.indexOf('enableAll.addEventListener("change"') + 900,
);
assert.ok(handler.length > 100, "the master switch must have a change handler");
assert.match(handler, /cfg\.enabled = want;/, "it must write the replace flag");
assert.match(
    handler,
    /for \(const seg of segs\)/,
    "it must apply to every window, not just the selected one",
);
assert.match(
    handler,
    /ensureReplaceConfigOnSeg\(seg, cfg\);/,
    "the flag has to be written back through the segment helper to persist",
);
assert.doesNotMatch(
    handler,
    /\bkind\b|\bdir\b|sam_prompt/,
    "the master switch must not touch the mask fields - it is not a masking control",
);

// --- tri-state, so it never lies about a mixed list ---
//
// Brace-matched rather than sliced from a fixed offset: the assertion window
// used to end 700 characters into the function and silently truncate once the
// function grew, which reports a missing line that is really a short slice.
const sync = functionBody(body, "function syncEnableAll()");
assert.match(
    sync,
    /const enabled = replaceEnabledCount\(segs\);/,
    "the master switch must count through the shared helper",
);
assert.match(
    sync,
    /enableAll\.checked = enabled\.all;/,
    "checked only when every window is enabled",
);
assert.match(
    sync,
    /enableAll\.indeterminate = enabled\.on > 0 && enabled\.on < enabled\.total;/,
    "a partly-enabled list must show half-filled, not checked or unchecked",
);
assert.match(
    sync,
    /enableAll\.disabled = enabled\.total === 0;/,
    "with no windows there is nothing to enable",
);

// --- and it stays in step in both directions ---

assert.match(
    functionBody(body, "function refreshLongForm("),
    /syncEnableAll\(\);/,
    "refreshLongForm must call syncEnableAll so every re-render and locale change re-mirrors it",
);
assert.match(
    body,
    /inp\.enabled\.addEventListener\("change",[\s\S]{0,500}?syncEnableAll\(\);/,
    "ticking one row must move the master switch, or it keeps claiming the old state",
);

// --- both locales, or the label is blank in Chinese ---

const zhCount = (i18n.match(/"replace\.enableAll"/g) || []).length;
const enCount = (i18n.match(/"replace\.enableAllTitle"/g) || []).length;
assert.equal(zhCount, 2, "replace.enableAll must be defined in both locales");
assert.equal(enCount, 2, "replace.enableAllTitle must be defined in both locales");

console.log("replace enable-all master switch tests passed");
