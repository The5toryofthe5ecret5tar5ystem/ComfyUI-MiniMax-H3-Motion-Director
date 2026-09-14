// Unit tests for preview-clip playlist index mapping.
//
//   node web/js/tests/minimax_output_clips.test.mjs
//
// The Results page plays one clip per segment but exposes a single global frame
// index, so an off-by-one here would seek to the wrong frame or skip a segment
// boundary entirely. Pure logic, no DOM.

import assert from "node:assert/strict";

import {
    clipDescriptor,
    clipPlaylistOf,
    clipPositionFor,
    clipStartIndex,
    totalClipFrames,
} from "../minimax_output_clips.mjs";

const clip = (frames, fps = 24) => ({ url: `/view?f=${frames}`, frames, fps });

// --- clipDescriptor -------------------------------------------------------

assert.equal(clipDescriptor(null), null, "null result has no clip");

assert.equal(
    clipDescriptor({ preview_frame_count: 10 }),
    null,
    "a result with no preview_url falls back to the frame array",
);

assert.equal(
    clipDescriptor({ preview_url: "/view?x", preview_frame_count: 0 }),
    null,
    "zero frames is not a usable clip",
);

assert.deepEqual(
    clipDescriptor({ preview_url: "/view?x", preview_frame_count: 243, fps: 24 }),
    { url: "/view?x", frames: 243, fps: 24 },
    "a complete payload resolves to a descriptor",
);

assert.equal(
    clipDescriptor({ preview_url: "/view?x", preview_frame_count: 5 }, (r) => `BASE${r}`).url,
    "BASE/view?x",
    "the route resolver is applied",
);

// --- clipPlaylistOf -------------------------------------------------------

assert.deepEqual(clipPlaylistOf(null), [], "no result yields no playlist");

assert.equal(
    clipPlaylistOf({ preview_url: "/view?a", preview_frame_count: 4 }).length,
    1,
    "a single result yields a one-clip playlist",
);

const explicit = [clip(4), clip(3)];
assert.equal(
    clipPlaylistOf({ clipPlaylist: explicit })[0],
    explicit[0],
    "an explicit playlist is used as-is",
);

assert.deepEqual(
    clipPlaylistOf({ clipPlaylist: [] }),
    [],
    "an empty explicit playlist does not fall back to a descriptor",
);

// --- totalClipFrames ------------------------------------------------------

assert.equal(totalClipFrames([]), 0, "empty playlist has no frames");
assert.equal(totalClipFrames([clip(4), clip(3)]), 7, "frames sum across clips");
assert.equal(totalClipFrames(null), 0, "null playlist is safe");

// --- clipStartIndex -------------------------------------------------------

const list = [clip(243), clip(124), clip(362)];

assert.equal(clipStartIndex(list, 0), 0, "first clip starts at 0");
assert.equal(clipStartIndex(list, 1), 243, "second clip starts after the first");
assert.equal(clipStartIndex(list, 2), 367, "third clip starts after two clips");
assert.equal(clipStartIndex(list, 0), 0, "negative positions clamp to the start");
assert.equal(clipStartIndex(list, -5), 0, "negative positions clamp to the start");
assert.equal(clipStartIndex(list, 99), 367, "positions past the end clamp to the last clip");
assert.equal(clipStartIndex([], 0), 0, "empty playlist starts at 0");

// --- clipPositionFor ------------------------------------------------------

assert.deepEqual(clipPositionFor([], 0), { position: -1, offset: 0 }, "empty playlist");

assert.deepEqual(clipPositionFor([clip(10)], 0), { position: 0, offset: 0 });
assert.deepEqual(clipPositionFor([clip(10)], 9), { position: 0, offset: 9 }, "last frame of a single clip");
assert.deepEqual(
    clipPositionFor([clip(10)], 99),
    { position: 0, offset: 9 },
    "an index past the end clamps to the final frame, never outside the media",
);

// Boundaries are where a one-frame drift would show up.
assert.deepEqual(clipPositionFor(list, 242), { position: 0, offset: 242 }, "last frame of clip 1");
assert.deepEqual(clipPositionFor(list, 243), { position: 1, offset: 0 }, "first frame of clip 2");
assert.deepEqual(clipPositionFor(list, 366), { position: 1, offset: 123 }, "last frame of clip 2");
assert.deepEqual(clipPositionFor(list, 367), { position: 2, offset: 0 }, "first frame of clip 3");
assert.deepEqual(clipPositionFor(list, 728), { position: 2, offset: 361 }, "last frame of clip 3");
assert.deepEqual(
    clipPositionFor(list, 729),
    { position: 2, offset: 361 },
    "past the end stays on the last frame",
);

assert.deepEqual(clipPositionFor(list, -3), { position: 0, offset: 0 }, "negative clamps to the start");

// Round trip: every global index must map back to itself.
for (const playlist of [list, [clip(1)], [clip(5), clip(1), clip(7)], [clip(0), clip(3)]]) {
    const total = totalClipFrames(playlist);
    for (let index = 0; index < total; index += 1) {
        const { position, offset } = clipPositionFor(playlist, index);
        assert.equal(
            clipStartIndex(playlist, position) + offset,
            index,
            `index ${index} round-trips through the playlist`,
        );
        assert.ok(
            offset >= 0 && offset < Math.max(1, playlist[position].frames),
            `index ${index} stays inside clip ${position}`,
        );
    }
}

// A zero-frame entry must not swallow the frame that follows it.
assert.deepEqual(
    clipPositionFor([clip(0), clip(3)], 0),
    { position: 1, offset: 0 },
    "a zero-frame clip still occupies one slot",
);

console.log("minimax_output_clips: all assertions passed");
