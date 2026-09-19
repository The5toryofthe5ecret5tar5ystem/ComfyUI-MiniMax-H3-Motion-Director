import assert from "node:assert/strict";
import fs from "node:fs";

import {
    referenceKindOf,
    resolveReferenceAssetId,
    semanticReferenceToken,
} from "../minimax_reference_assets.mjs";

// Adding a reference from the Material Library used to mint a brand-new asset
// id, so a prompt that already mentioned that asset kept its red "missing
// asset" chip, and removing + re-adding the same material never reconnected.
// A local upload heals the mention instead (that is where the resolver was
// called from), which is why the two ways of adding the same file behaved
// differently. The Library now resolves ids through the same rules.
//
// The file shapes below are the ones the Library passes: the materialized
// `relative_path` copy under ComfyUI's input folder, plus the stored name.

const FACE = semanticReferenceToken("picture", "r2v-common-picture-face");
const BODY = semanticReferenceToken("picture", "r2v-common-picture-body");
const VOICE = semanticReferenceToken("audio", "r2v-common-audio-voice");

const libraryFile = (name) => ({ imageFile: `mmx_material_library/${name}`, fileName: name });

const timelineWith = (common = {}) => ({
    global: {},
    r2vCommon: { refs: [], refAudios: [], refVideos: [], ...common },
    segments: [{ id: "s1", prompt: "", refs: [], refAudios: [], refVideos: [] }],
});

// --- a dangling mention is reconnected -----------------------------------------

const danglingPrompt = `subject_definitions:\n${FACE} her face.\n${BODY} her body.`;
const empty = timelineWith();

assert.equal(
    resolveReferenceAssetId(empty, "picture", [danglingPrompt], libraryFile("mat_a.png")),
    "r2v-common-picture-face",
    "the first picture added reconnects to the mention left red in the prompt",
);

// --- one Apply of two pictures reconnects two chips ----------------------------

const claimed = new Set();
const resolveForApply = (fileRef) => resolveReferenceAssetId(
    empty,
    "picture",
    [danglingPrompt],
    fileRef,
    claimed,
);

assert.equal(resolveForApply(libraryFile("mat_a.png")), "r2v-common-picture-face");
assert.equal(
    resolveForApply(libraryFile("mat_b.png")),
    "r2v-common-picture-body",
    "the second picture must heal the second chip, not fight over the first id",
);

// Without the shared `claimed` set both files claim the first id, and the
// schema then re-ids the loser: that is the bug this guards.
assert.equal(
    resolveReferenceAssetId(empty, "picture", [danglingPrompt], libraryFile("mat_b.png")),
    "r2v-common-picture-face",
);

// --- an id that is already live is never handed out twice ----------------------

const live = timelineWith({
    refs: [{ index: 0, imageFile: "mmx_material_library/mat_a.png", assetId: "r2v-common-picture-face" }],
});
assert.notEqual(
    resolveReferenceAssetId(live, "picture", [danglingPrompt], libraryFile("mat_a.png")),
    "r2v-common-picture-face",
    "a mention that resolves today must not be stolen by a second copy of the file",
);

// --- same file, same id: removing and re-adding keeps mentions bound -----------

const reAdd = resolveReferenceAssetId(empty, "picture", ["no mentions here"], libraryFile("mat_a.png"));
assert.match(reAdd, /^f-[0-9a-f]{16}$/, "a file-derived id is used when nothing is dangling");
assert.equal(
    resolveReferenceAssetId(empty, "picture", ["no mentions here"], libraryFile("mat_a.png")),
    reAdd,
);

// --- audio and video go through the same resolver ------------------------------

const audioTimeline = timelineWith();
assert.equal(
    resolveReferenceAssetId(
        audioTimeline,
        "audio",
        [`${VOICE} and only her voice.`],
        { audioFile: "mmx_material_library/mat_voice.mp3", fileName: "mat_voice.mp3" },
    ),
    "r2v-common-audio-voice",
);

// A picture chip must not be healed by an audio add: the kinds are separate.
assert.equal(
    resolveReferenceAssetId(empty, "audio", [danglingPrompt], { audioFile: "a.mp3" }) !== "r2v-common-picture-face",
    true,
);

// --- the Library's vocabulary must reach the prompt's ----------------------------

// The Library assigns *media* ("image"), prompts speak *references* ("picture").
// Passing the media kind through to the resolver matched no token at all, so the
// fallback id was handed out and the mention stayed red - the exact failure this
// file exists for. The names are normalized now, and both spellings must land on
// the same dangling mention.
assert.equal(referenceKindOf("image"), "picture");
assert.equal(referenceKindOf("images"), "picture");
assert.equal(referenceKindOf("video"), "video");
assert.equal(referenceKindOf("audio"), "audio");
assert.equal(referenceKindOf("picture"), "picture");
assert.equal(semanticReferenceToken("image", "x"), "{{mmx-ref:picture:x}}");

const claimedByMediaKind = new Set();
assert.equal(
    resolveReferenceAssetId(empty, "image", [danglingPrompt], libraryFile("mat_a.png"), claimedByMediaKind),
    "r2v-common-picture-face",
    'an "image" add must reconnect a "picture" mention',
);
assert.equal(
    [...claimedByMediaKind][0],
    "r2v-common-picture-face",
    "the media-kind add claims the picture id, so a second file heals the next chip",
);

// A file-stable id must not depend on which vocabulary the caller used, or the
// same file re-added from the Library and from a slot would never agree.
assert.equal(
    resolveReferenceAssetId(empty, "image", ["none"], libraryFile("mat_a.png")),
    resolveReferenceAssetId(empty, "picture", ["none"], libraryFile("mat_a.png")),
);

// --- the Library actually asks -------------------------------------------------

const modal = fs.readFileSync(new URL("../minimax_material_library_modal.mjs", import.meta.url), "utf8");

assert.match(
    modal,
    /const REFERENCE_KIND = \{ image: "picture", audio: "audio", video: "video" \};/,
    "the Library maps its media kinds onto the schema's reference kinds",
);
assert.match(
    modal,
    /resolveAssetId\(REFERENCE_KIND\[kind\] \|\| kind, fileRef\)/,
    "the resolver is called with the reference kind, not the media kind",
);
assert.match(
    modal,
    /function refRecord\(kind, materialized, item, index, assetId = ""\)/,
    "a Library-added reference record must carry an asset id",
);
assert.equal(
    (modal.match(/name: label,/g) || []).length,
    3,
    "picture, audio and video records all carry the material title as their name",
);
assert.equal(
    (modal.match(/libraryAssetIdResolver\(editor, state\.target\)/g) || []).length,
    2,
    "both the r2v and rv2v applies resolve ids the way a local upload does",
);
assert.match(
    modal,
    /import \{ batchReferencingPrompts, normalizeImageBatchSegments \} from "\.\/minimax_image_batch\.js";/,
    "the Library reuses the batch prompt scope instead of rescanning prompts itself",
);
assert.match(
    modal,
    /editor\.refreshPromptMentions\?\.\(\);/,
    "an apply repaints the mention chips instead of leaving the old red id on screen",
);
assert.match(
    modal,
    /resolveReferenceAssetId\(\n\s+editor\.timeline,\n\s+kind,\n\s+prompts,\n\s+fileRef,\n\s+claimed,\n\s+\)/,
    "one Apply shares one `claimed` set across the files it brings in",
);

// The copied file is named `mat_<id>.<ext>`, which tells the user nothing: the
// display name has to survive a save/reload to stay useful.
const timelineSrc = fs.readFileSync(new URL("../minimax_timeline.js", import.meta.url), "utf8");
assert.equal(
    (timelineSrc.match(/name: ref\.name \|\| ""/g) || []).length,
    3,
    "the payload sanitizers keep the reference display name for all three kinds",
);
