import assert from "node:assert/strict";
import fs from "node:fs";

import {
    clipDescriptor,
    clipPlaylistOf,
    totalClipFrames,
} from "../minimax_output_clips.mjs";

// The Results page played a lone preview clip through the *playlist* transport.
// That transport re-derives the frame index on `seeked` only, which never fires
// during ordinary playback, so a result that was playing perfectly well still
// showed "0.00 / 9.96" and "Frame 1 / 250" - and anything that re-synced the
// element to the stale index 0 yanked it back to the start, so only the opening
// frames were ever seen.
//
// The fix is that one clip is one continuous video, played through the element
// itself. These assertions pin both halves: a lone clip must not populate the
// playlist, and the element's clock must drive the index.

const src = fs.readFileSync(new URL("../minimax_output_ui.mjs", import.meta.url), "utf8");

/** The rendered function body, located by brace matching. */
function functionBody(name) {
    const start = src.indexOf(`function ${name}(`);
    const arrow = start < 0 ? src.indexOf(`const ${name} = (`) : -1;
    const from = start >= 0 ? start : arrow;
    assert.ok(from > 0, `${name} must still exist in minimax_output_ui.mjs`);

    let depth = 0;
    let i = src.indexOf("{", from);
    for (; i < src.length; i += 1) {
        if (src[i] === "{") depth += 1;
        else if (src[i] === "}") {
            depth -= 1;
            if (depth === 0) break;
        }
    }
    return src.slice(src.indexOf("{", from), i + 1);
}

const renderFrame = functionBody("renderFrame");
const seekHandler = src.slice(src.indexOf('seek.addEventListener(\n        "input"'));
const syncIndex = functionBody("syncIndexFromVideo");

// --- a lone clip is not a playlist ---

assert.match(
    renderFrame,
    /const singleClip =\s*\n\s*playlist\.length\s*\n\s*===\s*1/,
    "renderFrame must recognise a one-clip playlist as a single clip",
);
assert.match(
    renderFrame,
    /state\.clipPlaylist =\s*\n\s*singleClip\s*\n\s*\?\s*\[\]\s*\n\s*:\s*playlist;/,
    "a single clip must be kept OUT of the playlist transport",
);
assert.match(
    renderFrame,
    /state\.videoClip =\s*\n\s*singleClip;/,
    "the single clip must be remembered for the scrub paths",
);
assert.match(
    renderFrame,
    /state\.clipFrames =\s*\n\s*singleClip\s*\n\s*\?\s*Math\.max\(/,
    "the frame count must come from the lone clip, not from an empty playlist",
);

// Keeping the count matters: visibleFrameCount() returns clipFrames whenever
// isVideo, so an empty playlist must not zero the timeline.
assert.match(
    renderFrame,
    /const isVideo =\s*\n\s*playlist\.length > 0/,
    "isVideo must still be derived from the real playlist, not the emptied one",
);

// The element is pointed at the clip once, and a fresh load rewinds it.
assert.match(
    renderFrame,
    /video\.getAttribute\("src"\)\s*\n\s*!==\s*singleClip\.url/,
    "the lone clip must be assigned to the element",
);
assert.match(
    renderFrame,
    /video\.load\(\);\s*\n\s*\n\s*\/\/ A load rewinds the element to 0[\s\S]{0,240}state\.index =\s*\n\s*0;/, "a fresh load must reset the index, or the scrubber claims a frame the picture is not on",
);

// --- the element's clock drives the index ---

assert.match(
    syncIndex,
    /if \(onSingleClipTransport\(\)\) \{/,
    "syncIndexFromVideo must handle the single-clip transport",
);
assert.match(
    syncIndex,
    /Math\.round\(\s*\n\s*Number\(video\.currentTime \|\| 0\)\s*\n\s*\* fps,/,
    "the index must be derived from the element's own currentTime",
);
assert.match(
    syncIndex,
    /\n        if \(!state\.clipPlaylist\.length\) return;/,
    "the playlist branch must still guard against an empty playlist",
);

// `timeupdate` is what actually makes the bar move; `seeked` alone never fires
// during plain playback.
assert.match(
    src,
    /video\.addEventListener\(\s*\n\s*"timeupdate",\s*\n\s*syncIndexFromVideo,\s*\n\s*\);/,
    "syncIndexFromVideo must be bound to timeupdate, not only seeked",
);

// --- scrubbing moves the element, not a wall-clock index ---

assert.match(
    seekHandler.slice(0, 2600),
    /if \(state\.videoClip\) \{/,
    "a scrub on a single clip must take the element branch",
);
assert.match(
    seekHandler.slice(0, 2600),
    /video\.currentTime =\s*\n\s*value\s*\n\s*\/ Math\.max\(/,
    "a scrub must move the element itself",
);

// --- audio must survive the change ---

// Both audio paths used `!state.clipPlaylist.length` as "not a clip", so a lone
// clip would silently play mute. They have to accept the single-clip case.
const audioGuards = [
    ["syncVideoPlayState", functionBody("syncVideoPlayState")],
];
for (const [name, body] of audioGuards) {
    assert.match(
        body,
        /!state\.clipPlaylist\.length\s*\n\s*&& !state\.videoClip/,
        `${name} must treat a lone clip as a clip, or the result plays silent`,
    );
}
const audioBody = src.slice(src.indexOf("const syncAudioToVideo = ()"));
assert.match(
    audioBody.slice(0, 400),
    /!state\.clipPlaylist\.length\s*\n\s*&& !state\.videoClip/,
    "syncAudioToVideo must treat a lone clip as a clip, or the audio never starts",
);

// --- the pure helpers this relies on still agree ---

const single = clipDescriptor(
    { preview_url: "/view?filename=final.mp4", preview_frame_count: 250, fps: 25 },
    (route) => route,
);
assert.ok(single, "a preview payload must still describe a clip");
assert.equal(single.frames, 250);
assert.equal(totalClipFrames([single]), 250, "a lone clip still has a full timeline");
assert.equal(totalClipFrames([]), 0, "and an emptied playlist has none - hence clipFrames");
assert.deepEqual(
    clipPlaylistOf({ preview_url: "/view?x", preview_frame_count: 5 }),
    [clipDescriptor({ preview_url: "/view?x", preview_frame_count: 5 })],
    "clipPlaylistOf still wraps a single result in a one-entry list; the UI unwraps it",
);

console.log("results-page transport tests passed");
