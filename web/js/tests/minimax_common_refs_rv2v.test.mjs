import assert from "node:assert/strict";
import fs from "node:fs";

import { syncR2vCommonToggleForTask } from "../minimax_r2v_common_ui.mjs";
import { effectivePictureRefs } from "../minimax_reference_assets.mjs";

// The Character Replace workflow's identity references live in Common References
// (`timeline.r2vCommon`): the engine reads that block as each window's fallback
// when the window carries none of its own, and the replace setup checklist tells
// the user to put the face + full-body sheet there. The output-bar button that
// opens it was shown for the `r2v` task only, so in rv2v the instruction pointed
// at a control the mode never displayed.
//
// The visibility rule is a two-line function, so it is tested by calling it
// rather than by matching source text - a fake button is enough DOM for it.

function fakeButton() {
    const classes = new Set();
    const button = {
        textContent: "",
        title: "",
        attrs: {},
        classList: {
            toggle(name, on) {
                if (on) classes.add(name);
                else classes.delete(name);
            },
        },
        setAttribute(key, value) {
            this.attrs[key] = value;
        },
        removeAttribute(key) {
            delete this.attrs[key];
        },
    };
    return { button, isHidden: () => classes.has("hidden") };
}

for (const task of ["r2v", "rv2v", "R2V", "RV2V"]) {
    const { button, isHidden } = fakeButton();
    syncR2vCommonToggleForTask(button, { taskKey: task });
    assert.equal(isHidden(), false, `${task} can consume Common References, so the button shows`);
}

for (const task of ["t2v", "i2v", "fl2v", "v2v", "r2i", "", undefined]) {
    const { button, isHidden } = fakeButton();
    syncR2vCommonToggleForTask(button, { taskKey: task });
    assert.equal(isHidden(), true, `${task} cannot consume the shared block: ${String(task)}`);
}

// An expanded popover must not be re-hidden by the sync that follows it (the
// popover's onOpenChange calls the same helper), so visibility is asserted to be
// independent of `expanded` for both modes that can show it.
for (const task of ["r2v", "rv2v"]) {
    const { button, isHidden } = fakeButton();
    syncR2vCommonToggleForTask(button, { taskKey: task, expanded: true, label: "Common" });
    assert.equal(isHidden(), false, `${task} keeps the button while its popover is open`);
    assert.equal(button.attrs["aria-expanded"], "true");
}

// --- the Material Library's "Common References" target -------------------------

const modal = fs.readFileSync(new URL("../minimax_material_library_modal.mjs", import.meta.url), "utf8");

assert.match(
    modal,
    /function supportsCommonTarget\(mode\) \{\s*return mode === "r2v" \|\| mode === "r2flv" \|\| mode === "rv2v";/,
    "the library must treat rv2v like r2v for the shared target",
);
assert.equal(
    (modal.match(/supportsCommonTarget\(state\.mode\)/g) || []).length,
    4,
    "the four gates that used to say r2v (default type, prompt tab, target button, prompt->image) all ask the helper",
);
assert.match(
    modal,
    /if \(supportsCommonTarget\(state\.mode\)\) addTargetButton\(targets, "common", mlT\("common"\)\);/,
    "the Common References target button is offered where the block can be consumed",
);
assert.ok(
    !/state\.mode === "r2v" && state\.target === "common"/.test(modal),
    "no r2v-only common-target gate may remain",
);

// --- what a replace window actually renders with --------------------------------

const FACE = { index: 0, imageFile: "face.png", assetId: "r2v-common-picture-face" };
const BODY = { index: 1, imageFile: "body.png", assetId: "r2v-common-picture-body" };
const OWN = { index: 0, imageFile: "window-only.png", assetId: "local-picture-0" };
const COMMON = { refs: [FACE, BODY], refAudios: [], refVideos: [] };

const ids = (pictures) => pictures.map((picture) => picture.item.assetId);

// The shared block is a pool, not a fallback: a window with pictures of its own
// still renders with the shared ones, and the numbering is common-first in both
// cases - the order the prompt's <Picture N> tags were written in.
assert.deepEqual(ids(effectivePictureRefs(COMMON, { refs: [] })), [FACE.assetId, BODY.assetId]);
assert.deepEqual(ids(effectivePictureRefs(COMMON, {})), [FACE.assetId, BODY.assetId]);
assert.deepEqual(
    ids(effectivePictureRefs(COMMON, { refs: [OWN] })),
    [FACE.assetId, BODY.assetId, OWN.assetId],
    "the window's own picture follows the shared ones instead of replacing them",
);
assert.deepEqual(
    effectivePictureRefs(COMMON, { refs: [OWN] }).map((picture) => picture.index),
    [0, 1, 2],
    "slots are dense, zero-based, and are what the render will number",
);
assert.equal(effectivePictureRefs(COMMON, { refs: [OWN] })[2].tag, "<Picture 3>");

// The per-segment switches the Material Library writes.
assert.deepEqual(
    ids(effectivePictureRefs(COMMON, { excludedCommonAssetIds: [FACE.assetId] })),
    [BODY.assetId],
);
assert.deepEqual(
    ids(effectivePictureRefs(COMMON, { useCommonAssets: false, refs: [OWN] })),
    [OWN.assetId],
    "opted out entirely still keeps its own pictures",
);

// Tasks that cannot consume reference pictures never see the block.
assert.deepEqual(
    ids(effectivePictureRefs(COMMON, { refs: [OWN] }, { taskUsesReferences: false })),
    [OWN.assetId],
);
assert.deepEqual(effectivePictureRefs(COMMON, {}, { taskUsesReferences: false }), []);

// --- and the prompt enhancer's vision pass asks the same question ---------------

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

const enhancer = fs.readFileSync(new URL("../minimax_prompt_enhancer.js", import.meta.url), "utf8");
const collect = functionBody(enhancer, "pe.collectVisionImagesForBlock = async (");

assert.match(
    collect,
    /const pictureRefs = effectivePictureRefs\(\s*editor\.timeline\.r2vCommon \|\| \{\},\s*block \|\| global,\s*\{ taskUsesReferences: taskUsesReferenceImages\(taskKey\) \},\s*\);/,
    "the caption pass reads the same references the render will use, in the same order",
);
assert.match(
    collect,
    /for \(const \{ item: ref, index: slot \} of pictureRefs\)/,
    "and tells the model the slot the render gives each picture",
);
assert.match(
    collect,
    /const refsBlock = \{ \.\.\.\(block \|\| global\), refs: pictureRefs\.map\(\(entry\) => entry\.item\) \};/,
    "the segment still supplies its reference video; only the picture list is resolved",
);
