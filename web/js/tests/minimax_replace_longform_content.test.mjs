import assert from "node:assert/strict";
import fs from "node:fs";

import {
    SEGMENT_CONTENT_KEYS,
    carrySegmentContent,
    contentSourceForWindow,
} from "../minimax_replace_layout_core.mjs";

// "Long-form replace - cover whole clip" rebuilds timeline.segments to lay the
// clip out in equal windows. It used to build every window with the plain
// new-window factory, so every window came back with an empty prompt and no
// references: covering a clip destroyed exactly the work the user had just done
// on it. These assertions pin the carry, and pin the carry to the fields the
// new-window factory actually blanks out, so a field added later cannot quietly
// start getting wiped again.

const src = fs.readFileSync(new URL("../minimax_timeline.js", import.meta.url), "utf8");

/** The real applyLongForm body, and the new-window factory it rebuilds with. */
function functionBody(name) {
    const start = src.indexOf(`function ${name}(`);
    assert.ok(start > 0, `${name} must still exist in minimax_timeline.js`);
    // Walk braces so a nested block cannot cut the body short.
    let depth = 0;
    let i = src.indexOf("{", start);
    const from = i;
    for (; i < src.length; i += 1) {
        if (src[i] === "{") depth += 1;
        else if (src[i] === "}") {
            depth -= 1;
            if (depth === 0) break;
        }
    }
    return src.slice(from, i + 1);
}

const newWindowBody = functionBody("newWindowSeg");
const longFormBody = functionBody("applyLongForm");

// --- the fields the factory blanks are content, so they must be carried ---

const literal = newWindowBody.match(/const seg = \{([\s\S]*?)\n\s*\};/);
assert.ok(literal, "newWindowSeg must still build its payload as an object literal");
const declared = [...literal[1].matchAll(/^\s*(\w+):/gm)].map((m) => m[1]);
const LAYOUT_KEYS = ["id", "start", "length", "frameCount"];
const contentKeys = declared.filter((key) => !LAYOUT_KEYS.includes(key));
assert.ok(contentKeys.includes("prompt"), "the factory must still blank prompt");

for (const key of contentKeys) {
    assert.ok(
        SEGMENT_CONTENT_KEYS.includes(key),
        `newWindowSeg blanks "${key}", so SEGMENT_CONTENT_KEYS must carry it - `
            + "otherwise covering a clip wipes it again",
    );
}

// --- a fresh window is what the factory produces, so build one the same way ---

function freshWindow(start, length) {
    const seg = {
        id: `seg-${start}`,
        start,
        length,
        frameCount: null,
        prompt: "",
        negativePrompt: "",
        taskType: "",
        refs: [],
        refAudios: [],
        refVideos: [],
        genImage: { imageFile: "", fileName: "" },
        contextLink: { schema: "previous_context_link_v1", enabled: false, visual: false, audio: false },
    };
    seg.frameCount = seg.length;
    return seg;
}

/** The rebuild applyLongForm performs, so the carry is exercised as used. */
function reCut(previous, windowCount) {
    const windows = [];
    for (let index = 0; index < windowCount; index += 1) {
        const seg = freshWindow(index * 100, 100);
        carrySegmentContent(seg, contentSourceForWindow(previous, index, windowCount));
        windows.push(seg);
    }
    return windows;
}

// --- the reported bug ---

const typed = {
    ...freshWindow(0, 900),
    prompt: "summary:\nA woman turns to camera.\n\ndetailed_description:\n[Shot 1] ...",
    negativePrompt: "blur",
    refs: [{ index: 1, imageFile: "charsheet.png" }],
    contextLink: { schema: "previous_context_link_v1", enabled: true, visual: true, audio: false },
};

const covered = reCut([typed], 27);
assert.equal(covered.length, 27);
for (const seg of covered) {
    assert.equal(seg.prompt, typed.prompt, "covering the clip must not delete the prompt");
    assert.equal(seg.negativePrompt, "blur");
    assert.deepEqual(seg.refs, [{ index: 1, imageFile: "charsheet.png" }]);
    assert.equal(seg.contextLink.enabled, true);
}

// Each window needs its own copy: the per-window ref editor mutates seg.refs in
// place, and a shared array would make one window's edit rewrite its siblings.
covered[0].refs.push({ index: 2, imageFile: "second.png" });
assert.equal(covered[1].refs.length, 1, "windows must not share one refs array");
assert.equal(typed.refs.length, 1, "the source window must not be aliased either");

// --- re-cutting to the same count re-lays-out the same windows ---

const pair = [
    { ...freshWindow(0, 100), prompt: "first window" },
    { ...freshWindow(100, 100), prompt: "second window" },
];
const relaid = reCut(pair, 2);
assert.deepEqual(
    relaid.map((s) => s.prompt),
    ["first window", "second window"],
    "an unchanged window count must keep each window's own prompt",
);

// A different count has no positional mapping, so the clip collapses to one
// recipe taken from the first window - the same rule the replace config uses.
const collapsed = reCut(pair, 3);
assert.deepEqual(
    collapsed.map((s) => s.prompt),
    ["first window", "first window", "first window"],
);

// --- edges ---

assert.equal(contentSourceForWindow([], 0, 4), null, "an empty list has no template");
assert.equal(contentSourceForWindow(null, 0, 4), null);
assert.equal(contentSourceForWindow(pair, 9, 2), null, "an out-of-range index is not a source");
assert.equal(carrySegmentContent(freshWindow(0, 1), null), false, "a missing source is a no-op");
assert.equal(carrySegmentContent(null, typed), false);

const noPrompt = freshWindow(0, 10);
assert.equal(carrySegmentContent(noPrompt, { id: "x" }), false);
assert.equal(
    Object.prototype.hasOwnProperty.call(noPrompt, "prompt"),
    true,
    "a key the source lacks stays as the factory left it",
);
assert.equal(noPrompt.prompt, "");

// Layout and the replace recipe belong to the caller, not the carry.
const target = freshWindow(500, 50);
target.replace = { enabled: false };
carrySegmentContent(target, typed);
assert.equal(target.start, 500);
assert.equal(target.length, 50);
assert.deepEqual(target.replace, { enabled: false }, "the carry must not touch the replace recipe");

// --- the real code uses this, and no longer templates everything from window 1 ---

assert.match(
    longFormBody,
    /const previous = segs\.slice\(\);/,
    "applyLongForm must snapshot the windows before clearing the list",
);
assert.match(longFormBody, /const source = contentSourceForWindow\(previous, index, plan\.windows\.length\);/);
assert.match(longFormBody, /carrySegmentContent\(seg, source\);/);
assert.match(
    longFormBody,
    /const base = replaceConfigFromSeg\(source \|\| seg\);/,
    "each window's own recipe must survive when the cut is unchanged",
);
assert.doesNotMatch(
    longFormBody,
    /firstCfg/,
    "the old template-from-window-1-only shortcut must be gone",
);
assert.match(
    longFormBody,
    /ed\.selectedIndex = clamp\(/,
    "the prompt box reads segments[selectedIndex], so a shorter cut must re-clamp it",
);

console.log("replace long-form content carry tests passed");
