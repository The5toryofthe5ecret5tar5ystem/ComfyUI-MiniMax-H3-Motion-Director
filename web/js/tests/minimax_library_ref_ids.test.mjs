import assert from "node:assert/strict";
import fs from "node:fs";

import {
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

// --- the Library actually asks -------------------------------------------------

const modal = fs.readFileSync(new URL("../minimax_material_library_modal.mjs", import.meta.url), "utf8");

assert.match(
    modal,
    /function refRecord\(kind, materialized, item, index, assetId = ""\)/,
    "a Library-added reference record must carry an asset id",
);
assert.match(
    modal,
    /container\[field\]\.push\(refRecord\(kind, mat, entry\.item, slot, assetId\)\)/,
    "the pushed record carries the id that was resolved for it",
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
    /resolveReferenceAssetId\(\n\s+editor\.timeline,\n\s+kind,\n\s+prompts,\n\s+fileRef,\n\s+claimed,\n\s+\)/,
    "one Apply shares one `claimed` set across the files it brings in",
);
