import assert from "node:assert/strict";
import fs from "node:fs";

// Three things the caption used to get wrong about its own input:
//
// 1. Frames came from the source video's whole length, so a Character Replace
//    window's action caption described three moments from somewhere else in the
//    footage - the same three for every window in the project.
// 2. The count was a constant (3, or 2 on Ollama) with no way to ask for more.
// 3. A reference picture that lived in a subfolder (or in outputs) could not be
//    read at all: `fetchImageB64` sent the name alone, and the single try/catch
//    around the whole collection meant one unreadable file threw the rest away -
//    silently, from the panel's point of view.
//
// Source-level: the panel needs a live Director node and a ComfyUI api object to
// run, so the assertions are scoped to the function bodies.

const src = fs.readFileSync(new URL("../minimax_prompt_enhancer.js", import.meta.url), "utf8");
const i18n = fs.readFileSync(new URL("../minimax_i18n.js", import.meta.url), "utf8");

/**
 * Brace-match a function body, so a call site elsewhere cannot satisfy an assertion.
 * The body brace is located after the parameter list, because a default like
 * `ref = {}` puts a brace *before* it.
 */
function functionBody(source, signature) {
    const at = source.indexOf(signature);
    assert.ok(at > 0, `${signature} must still exist`);
    const arrow = source.indexOf(") => {", at);
    const paren = source.indexOf(") {", at);
    let bodyAt = source.indexOf("{", at);
    if (arrow > 0 && arrow - at < 200 && (paren < 0 || arrow < paren)) bodyAt = arrow + 5;
    else if (paren > 0 && paren - at < 200) bodyAt = paren + 2;
    let depth = 0;
    let i = bodyAt;
    for (; i < source.length; i += 1) {
        if (source[i] === "{") depth += 1;
        else if (source[i] === "}") {
            depth -= 1;
            if (depth === 0) break;
        }
    }
    return source.slice(bodyAt, i + 1);
}

// --- the window, not the whole file --------------------------------------------

const windowHelper = functionBody(src, "function segmentWindowSeconds(block, editor) {");
assert.match(windowHelper, /const start = Number\(block\?\.start\);/, "the segment's own start");
assert.match(
    windowHelper,
    /const length = Number\(block\?\.length \?\? block\?\.frameCount\);/,
    "length, or the frameCount spelling other panels write",
);
assert.match(windowHelper, /const fps = Number\(editor\?\.timeline\?\.frameRate\) \|\| 24;/);
assert.match(windowHelper, /return \{ start_sec: start \/ fps, end_sec: \(start \+ length\) \/ fps \};/);
assert.match(windowHelper, /if \(!Number\.isFinite\(start\) \|\| !Number\.isFinite\(length\) \|\| start < 0 \|\| length <= 0\) return \{\};/);

const collect = functionBody(src, "pe.collectVisionImagesForBlock = async (block, taskKey) => {");
assert.match(collect, /const window = segmentWindowSeconds\(block, editor\);/, "the window is computed");
assert.match(collect, /\.\.\.window,/, "and sent with the extract request");

// --- the count is the user's --------------------------------------------------

assert.match(src, /const DEFAULT_VISION_FRAMES = 3;/);
assert.match(src, /const MAX_VISION_FRAMES = 5;/);
assert.match(
    src,
    /pe\.visionFramesInput\.min = "1";/,
    "the input cannot be set to zero frames",
);
assert.match(
    src,
    /pe\.visionFramesInput\.max = String\(MAX_VISION_FRAMES\);/,
    "and the ceiling is a single constant, here and in the clamp",
);
assert.match(src, /swallowKeys\(pe\.visionFramesInput\);/, "typing must not move the node");
assert.match(src, /savePeSettings\(\{ visionFrames: count \}\);/, "the choice persists per browser");
assert.match(
    src,
    /pe\.visionFramesInput\.value = String\(clampVisionFrames\(stored\.visionFrames\)\);/,
    "and is restored with the rest of the settings",
);
assert.match(collect, /const visionFrames = pe.resolveVisionFrames\(\);/, "the collector reads it");
assert.match(collect, /num_frames: visionFrames,/, "the window gets that many frames");

const resolver = functionBody(src, "pe.resolveVisionFrames = () => {");
assert.match(resolver, /pe\.apiSelect\?\.value === API_OLLAMA \? 2 : DEFAULT_VISION_FRAMES;/, "per-backend default");
assert.match(resolver, /Number\(pe\.visionFramesInput\?\.value\)/, "the typed value wins");
assert.match(resolver, /return clampVisionFrames\(loadPeSettings\(\)\.visionFrames, fallback\);/, "then the stored one");

const clamp = functionBody(src, "function clampVisionFrames(value, fallback = DEFAULT_VISION_FRAMES) {");
assert.match(clamp, /if \(!Number\.isFinite\(count\) \|\| count <= 0\) return fallback;/);
assert.match(clamp, /return Math\.max\(1, Math\.min\(MAX_VISION_FRAMES, count\)\);/, "1..5, always");

// The RefMod character stills follow the same knob, and the route already takes it.
assert.match(
    src,
    /refmod_frames: pe\.resolveVisionFrames\(\),/,
    "the mod decode is capped by the same setting",
);
assert.match(
    collect,
    /num_frames: Math\.max\(1, Math\.min\(2, Math\.ceil\(visionFrames \/ 2\)\)\),/,
    "an inserted clip keeps its own smaller count",
);

// --- the location of a reference picture --------------------------------------

const fetchBody = functionBody(src, "async function fetchImageB64(imageFile, ref = {}) {");
assert.match(fetchBody, /subfolder: ref\?\.subfolder \|\| "",/, "a picture in a folder is readable");
assert.match(fetchBody, /type: ref\?\.type \|\| "input",/, "so is one in outputs");
assert.match(
    collect,
    /const b64 = await fetchImageB64\(ref\.imageFile, ref\);/,
    "the slot travels with the fetch",
);
const endpointBody = functionBody(src, "pe.collectEndpointFrames = async (block, taskKey) => {");
assert.match(
    endpointBody,
    /return \(await fetchImageB64\(file, ref\)\) \|\| "";/,
    "endpoint frames get the same treatment",
);

// --- one bad input does not throw the rest away --------------------------------

assert.match(collect, /const issues = \[\];/);
assert.match(
    collect,
    /catch \(e\) \{\s*issues\.push\(`\$\{ref\.imageFile\}: \$\{e\.message\}`\);\s*\}/,
    "a reference that cannot be read is recorded, not thrown",
);
assert.match(collect, /if \(!resp\.ok\) issues\.push\(`source frames: \$\{data\.error \|\| resp\.status\}`\);/, "extract failures");
assert.match(collect, /if \(issues\.length\) console\.warn\("\[MiniMax H3 PE\] vision inputs skipped:", issues\);/, "and logged with detail");
assert.match(collect, /return \{ images, sourceCount, refCount, refSlots, refVideoCount, frameImages, issues \};/);

assert.match(
    src,
    /visionIssues = \[e\.message \|\| String\(e\)\];/,
    "a collection that fails outright is reported as such, not as a run without references",
);
assert.match(
    src,
    /const visionIssues = result\.vision\?\.issues \|\| \[\];/,
    "the status line reads them back",
);
assert.match(src, /t\("pe\.statusVisionIssues", \{ count: visionIssues\.length \}\)/, "and counts them");

// --- strings exist in both locales --------------------------------------------

for (const key of ["pe.visionFrames", "pe.visionFramesTip", "pe.statusVisionIssues"]) {
    assert.equal((i18n.match(new RegExp(`"${key}":`, "g")) || []).length, 2, `${key} needs one string per locale`);
}
