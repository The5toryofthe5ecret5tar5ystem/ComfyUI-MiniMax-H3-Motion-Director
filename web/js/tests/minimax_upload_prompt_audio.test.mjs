import assert from "node:assert/strict";
import fs from "node:fs";

// Two editor UX bugs found in the field:
//
// 1. Uploading a source video rebuilds the timeline as ONE whole-clip segment,
//    which used to throw away the prompt the user had just composed. The text
//    is now captured before the reset and re-applied to the new segment.
//
// 2. Playback in the source player (Replace mode keeps it visible as the
//    scrubber) was silent because the stage <video> is muted, which made the
//    Output volume slider look broken -- that slider only drives the RENDERED
//    result. The transport now has its own audio toggle.
//
// Source-level because both live inside a 15k-line editor class that needs a
// live LiteGraph canvas.

const src = fs.readFileSync(new URL("../minimax_timeline.js", import.meta.url), "utf8");

// --- 1. prompt survives a re-upload -----------------------------------------

assert.match(src, /const carriedPrompt = this\._captureSegmentPromptForReload\(\);/, "upload must capture the current prompt first");
assert.match(src, /this\._restoreSegmentPromptAfterReload\(carriedPrompt\);/, "upload must restore it on the new segment");
assert.match(src, /_captureSegmentPromptForReload\(\) \{/, "capture helper must exist");
assert.match(src, /_restoreSegmentPromptAfterReload\(prompt\) \{/, "restore helper must exist");

// The restore must never clobber a prompt that is already on the segment.
const restore = src.slice(src.indexOf("_restoreSegmentPromptAfterReload(prompt) {"));
assert.match(
    restore.slice(0, 600),
    /if \(!seg \|\| String\(seg\.prompt \|\| ""\)\.trim\(\)\) return;/,
    "restore must bail out when the target segment already has prompt text",
);
// ...and it must run AFTER the single-segment rebuild, or the reset wins.
const applyLoaded = src.slice(src.indexOf("async _applyLoadedVideo("));
const resetAt = applyLoaded.indexOf("this._setSingleSegment(totalFrames);");
const restoreAt = applyLoaded.indexOf("this._restoreSegmentPromptAfterReload(carriedPrompt);");
assert.ok(resetAt > 0 && restoreAt > resetAt, "restore must come after _setSingleSegment");
assert.ok(
    applyLoaded.indexOf("_captureSegmentPromptForReload()") < resetAt,
    "capture must happen before the timeline is reset",
);

// --- 2. transport player audio ---------------------------------------------

assert.match(src, /const PREVIEW_AUDIO_STORAGE_KEY = "mmx_director_preview_audio";/, "the toggle pref needs a storage key");
assert.match(
    src,
    /data-a="player-audio"/,
    "the transport must expose a preview-audio button",
);
assert.match(src, /bind\('\[data-a="player-audio"\]', \(\) => this\.togglePreviewAudio\(\)\);/, "the button must be bound");
assert.match(src, /togglePreviewAudio\(\) \{/, "toggle method must exist");
assert.match(src, /refreshPreviewAudioButton\(\) \{/, "button refresh must exist");
assert.match(src, /_applyPreviewAudio\(\) \{/, "apply method must exist");

// Only real playback may unmute; scrubbing (seeks while paused) stays silent.
const apply = src.slice(src.indexOf("_applyPreviewAudio() {"));
assert.match(
    apply.slice(0, 400),
    /const sound = this\.isPreviewAudioEnabled\(\) && !!this\.isPlaying;/,
    "audio must be gated on playback, not on scrubbing",
);
assert.match(apply.slice(0, 400), /this\.stageVideo\.muted = !sound;/, "the stage element owns the sound");
assert.match(apply.slice(0, 400), /this\.refreshPreviewAudioButton\(\);/, "the glyph must follow the state");

// Stop mutes, play unmutes, and a failed native play must not hold audio open.
const stopPlay = src.slice(src.indexOf("_stopPlay() {"));
assert.match(stopPlay.slice(0, 200), /this\.isPlaying = false;\s*this\._applyPreviewAudio\(\);/, "stop must re-apply the mute");
const togglePlay = src.slice(src.indexOf("togglePlay() {"));
assert.match(togglePlay.slice(0, 500), /this\.isPlaying = true;[\s\S]{0,200}this\._applyPreviewAudio\(\);/, "play must apply the audio state");
assert.match(
    src,
    /this\._nativePlayFailed = true;\s*\/\/[^\n]*\n\s*if \(this\.stageVideo\) this\.stageVideo\.muted = true;/,
    "a blocked native play must fall back to silent frame-clock playback",
);

// The label must be refreshed on locale switches like the loop button is.
assert.match(
    src,
    /this\.refreshLoopButtonTitle\?\.\(\);\s*this\.refreshPreviewAudioButton\?\.\(\);/,
    "locale switch must refresh the audio toggle label",
);

console.log("upload prompt + preview audio tests passed");
