import assert from "node:assert/strict";
import fs from "node:fs";

// "Playing a result in the panel stutters the audio - it repeats a small chunk - but
// the exported file is clean."
//
// The preview clip is picture only, so the sound comes from a separate <audio> element
// that has to be kept on the video's clock. That clock was read from `state.index`,
// which a *later* `timeupdate` listener refreshes: on every tick the target was up to
// one update (~0.25 s) old, i.e. always behind an audio element that had kept playing.
// Correcting it meant seeking backwards - and seeking audio backwards replays it - so
// the preview repeated the same small chunk over and over. An exported file has no such
// clock, which is why only the in-panel playback sounded wrong.

import {
    AUDIO_SEEK_LAG_SECONDS,
    AUDIO_SEEK_LEAD_SECONDS,
    audioDriftNeedsSeek,
    clipGlobalSeconds,
} from "../minimax_output_player.mjs";

const ui = fs.readFileSync(new URL("../minimax_output_ui.mjs", import.meta.url), "utf8");

function functionBody(source, signature) {
    const at = source.indexOf(signature);
    assert.ok(at > 0, `${signature} must still exist`);
    const bodyStart = source.lastIndexOf("{", at + signature.length - 1);
    let depth = 0;
    for (let i = bodyStart; i < source.length; i += 1) {
        if (source[i] === "{") depth += 1;
        else if (source[i] === "}") {
            depth -= 1;
            if (depth === 0) return source.slice(bodyStart, i + 1);
        }
    }
    throw new Error(`unbalanced braces after ${signature}`);
}

// --- the policy -------------------------------------------------------------- //

// drift = audio - video. Behind -> pull up; ahead -> only when clearly out, because
// dragging audio back is what replays a chunk.
assert.equal(audioDriftNeedsSeek(0), false);
assert.equal(audioDriftNeedsSeek(-0.05), false);
assert.equal(audioDriftNeedsSeek(-AUDIO_SEEK_LAG_SECONDS - 0.01), true, "a lagging track is pulled up");
assert.equal(audioDriftNeedsSeek(0.2), false, "a small lead must NOT be dragged back (it would repeat)");
assert.equal(audioDriftNeedsSeek(AUDIO_SEEK_LEAD_SECONDS + 0.01), true, "a clearly leading track is re-synced");
assert.equal(audioDriftNeedsSeek(Number.NaN), false);
assert.equal(audioDriftNeedsSeek(undefined), false);

// The stale-index regression, spelled out: with a 0.25 s timeupdate cadence the old
// target sat 0.25 s behind the audio, which is > the lag threshold, so every tick
// seeked back ~0.13 s of sound.
const staleTargetDrift = 0.25;               // audio is 0.25 s ahead of a lagging target
assert.equal(audioDriftNeedsSeek(staleTargetDrift), false, "the fix must not re-seek on a stale-target lead");

assert.equal(clipGlobalSeconds(0, 0), 0);
assert.equal(clipGlobalSeconds(6.583333, 1.25).toFixed(4), "7.8333");
assert.equal(clipGlobalSeconds(-2, 1), 1, "a bad clip offset must not move time backwards");
assert.equal(clipGlobalSeconds("x", "y"), 0);

// --- the wiring -------------------------------------------------------------- //

assert.match(ui, /import \{ ResultPlaybackController, audioDriftNeedsSeek, clipGlobalSeconds \}/,
    "the UI must use the tested policy");

const sync = functionBody(ui, "const syncAudioToVideo = () => {");
assert.ok(
    !/state\.index\s*\n?\s*\//.test(sync) && !sync.includes("state.index /"),
    "the target must not come from the stale frame index",
);
assert.ok(sync.includes("Number(video.currentTime || 0)"),
    "the target is the element's live clock");
assert.ok(sync.includes("clipGlobalSeconds("),
    "on the playlist transport the clip's own start is added");
assert.ok(sync.includes("clipStartIndex("),
    "the clip start comes from the playlist, not from a running index");
assert.ok(sync.includes("audioDriftNeedsSeek(drift)"),
    "the decision goes through the shared policy");

// A stall during a clip transition must let the audio wait, then resume - not run ahead.
const stall = ui.slice(ui.indexOf('video.addEventListener(\n        "waiting"'), ui.indexOf('video.addEventListener(\n        "playing"'));
assert.ok(stall.includes("audio.pause()"), "the audio waits through a video stall");
const resumeAt = ui.indexOf('video.addEventListener(\n        "playing"');
const resume = ui.slice(resumeAt, resumeAt + 700);
assert.ok(resume.includes("syncAudioToVideo()"), "resuming realigns before playing");
assert.ok(resume.includes("audio.play?.()"), "resuming resumes the audio");

console.log("output audio sync: live clock + forward-only corrections");
