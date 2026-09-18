import assert from "node:assert/strict";
import fs from "node:fs";

// Story -> segments: one call splits a brief into a world paragraph plus one paragraph
// per segment, the panel writes them into the timeline, and the review list produces
// the final prompt for each. Two things have to stay true or the feature is a footgun:
// the panel must not invent segments in a timeline the user laid out by hand, and the
// frame arithmetic must be the same one the rest of the pack uses.
//
// Source-level: mounting needs a live Director node and a ComfyUI api object.

import {
    STORY_GROW_MODES,
    storyMayGrow,
    storyTargetKind,
} from "../minimax_story_targets.mjs";

const enhancer = fs.readFileSync(new URL("../minimax_prompt_enhancer.js", import.meta.url), "utf8");
const batch = fs.readFileSync(new URL("../minimax_prompt_enhance_batch.mjs", import.meta.url), "utf8");
const genTimeline = fs.readFileSync(new URL("../minimax_gen_timeline.js", import.meta.url), "utf8");
const i18n = fs.readFileSync(new URL("../minimax_i18n.js", import.meta.url), "utf8");
const timeline = fs.readFileSync(new URL("../minimax_timeline.js", import.meta.url), "utf8");
const batchPanel = fs.readFileSync(new URL("../minimax_image_batch.js", import.meta.url), "utf8");
const fl2vPanel = fs.readFileSync(new URL("../minimax_fl2v.js", import.meta.url), "utf8");

function functionBody(source, signature) {
    const at = source.indexOf(signature);
    assert.ok(at > 0, `${signature} must still exist`);
    // Signatures end with the body's own `{`, and one of them carries a parameter
    // object (`{ seconds = 0, frames = 0 }`): start from the last `{` of the
    // signature so the parameters cannot be mistaken for the body.
    const bodyStart = source.lastIndexOf("{", at + signature.length - 1);
    let depth = 0;
    for (let i = bodyStart; i < source.length; i += 1) {
        if (source[i] === "{") depth += 1;
        else if (source[i] === "}") {
            depth -= 1;
            if (depth === 0) return source.slice(bodyStart, i + 1);
        }
    }
    throw new Error(`${signature} body is not brace-balanced`);
}

// --- the frame grid is one implementation, not two ------------------------------

assert.match(
    genTimeline,
    /const rem = \(\(5 - \(n % 17\)\) % 17 \+ 17\) % 17;/,
    "the panel's official frame formula is still the 17k+5 grid",
);

// --- the story section ---------------------------------------------------------

const planStory = functionBody(enhancer, "pe.planStory = async () => {");
assert.match(planStory, /pe\.getLlmConfig\(\);/, "the story uses the same model settings as the enhancer");
assert.match(planStory, /if \(!cfg\.model\) \{[\s\S]*?pe\.setStatus\(t\("pe\.storyNeedModel"\)/, "no model, no silent nothing");
assert.match(planStory, /"\/minimax\/motion-director\/story_plan"/, "one call to the splitter route");
assert.match(planStory, /story,\s*\n\s*segments,\s*\n\s*seconds,/, "the brief, the count and the length all travel");
assert.match(planStory, /task_type: editor\.getTaskKey\?\.\(\)/, "the splitter knows which task the story is for");
assert.match(planStory, /Math\.max\(1, Math\.min\(60, Math\.round\(Number\(pe\.storySegmentsInput\?\.value\) \|\| 10\)\)\)/,
    "segments are clamped 1..60, and not by the vision-frames clamp");

// --- writing the plan into the timeline ----------------------------------------

const ensure = functionBody(enhancer, "pe.ensureStorySegments = (count, frames, seconds) => {");
assert.match(
    ensure,
    /editor\.createStorySegments\(want, \{ seconds, frames \}\)/,
    "the timeline owns what may be created - the panel only asks",
);
// The fallback is for an editor that predates the hook, and it must carry the same
// guard: only an empty timeline or a generation timeline is grown, never a laid-out one.
assert.match(
    ensure,
    /const mayCreate = !timeline\.segments\.length \|\| !!editor\?\.isGenMode\?\.\(\);/,
    "only an empty timeline or a generation timeline is grown - a hand-laid video or replace timeline is not",
);
assert.match(ensure, /frameCount: frames,/, "a created segment gets the aligned frame count");
assert.match(ensure, /editor\?\.normalizeGenSegments\?\.\(\);/, "and the timeline is re-tiled by its own normaliser");
assert.match(ensure, /editor\?\.commit\?\.\(false, \{ syncTimeline: true \}\)/, "one commit, so the change is undoable as a step");

const apply = functionBody(enhancer, "pe.applyStoryPlan = (plan) => {");
assert.match(apply, /pe\.ensureStorySegments\(beats\.length, frames, seconds\)/, "the plan sizes the timeline");
assert.match(
    apply,
    /const text = world \?/,
    "each segment gets the shared world paragraph plus its own beat",
);
assert.match(apply, /: beat;/, "and the beat alone when the plan carries no world paragraph");
assert.match(
    apply,
    /if \(editor\?\.writeStoryBeat\?\.\(index, text\) !== true\) \{\s*\n\s*pe\.setPromptTextForBlock\(text, index\);/,
    "the beat goes where that mode keeps prompts, and the panel's own writer is the fallback",
);
assert.match(apply, /editor\?\.refreshStoryTargets\?\.\(\);/, "one repaint for the whole pass");
assert.match(apply, /if \(!beat\) continue;/, "an empty beat is skipped, not written as a blank prompt");
assert.match(apply, /pe\.storyNote\.textContent = notes\.join\(" "\)/, "notes are shown, not swallowed");

// --- the review list can fix one segment ---------------------------------------

assert.match(batch, /async function regenerate\(row, index\) \{/, "one row can be regenerated on its own");
assert.match(
    batch,
    /await pe\.callEnhanceApi\(row\.original, row\.taskKey, row\.block, \{/,
    "regeneration uses the row's own original text, task and block",
);
assert.match(batch, /row\.enhanced = result\.text;/, "the preview updates in place");
assert.match(batch, /\{\s*\.\.\.activeCfg,\s*skipVision: true,/, "with the settings the run actually used");
assert.match(batch, /const regenAllBtn = button\(t\("pe\.regenerateAll"\)/, "and all of them can be redone");
assert.match(
    batch,
    /rows\.push\(\{ segmentIndex, original: prompt, enhanced: result\.text, block, taskKey \}\);/,
    "a row carries what regeneration needs",
);

// --- which modes the story may touch -------------------------------------------

// A prompt batch (t2v / i2v / r2v cards) is a list of generation segments - one card,
// one render - so the story may create the cards it needs. That is the mode the feature
// was written for and the one it used to be unreachable in.
assert.ok(STORY_GROW_MODES.has("prompt_batch"), "a batch of generation segments may grow");
assert.ok(!STORY_GROW_MODES.has("video"), "a laid-out source timeline may not");
assert.ok(!STORY_GROW_MODES.has("fl2v"), "fl2v shots need their own images: fill, do not invent");
assert.equal(storyMayGrow("prompt_batch", 3), true, "and it grows a batch that already has cards");
assert.equal(storyMayGrow("video", 0), true, "an empty timeline has nothing to re-time");
assert.equal(storyMayGrow("video", 12), false, "but a laid-out replace job is never re-timed");
assert.equal(storyMayGrow("fl2v", 0), false);
assert.equal(storyMayGrow("mixed", 4), false);
assert.equal(storyTargetKind("fl2v"), "shots", "fl2v keeps its prompts on shots");
assert.equal(storyTargetKind("prompt_batch"), "segments");
assert.equal(storyTargetKind("mixed"), null, "mixed owns its own editor");

// --- every mode the story offers can be reached --------------------------------

// The section lives in the enhancer settings panel, opened from the Enhance / Settings
// buttons on a prompt row - and those rows are hidden in exactly the modes above. The
// batch and Long-form panels carry their own button, wired by the timeline.
assert.ok(
    batchPanel.includes('data-a="story-plan"'),
    "the batch panel (t2v / i2v / r2v) offers Story to segments",
);
assert.ok(
    fl2vPanel.includes('data-a="story-plan"'),
    "Long-form offers it too - it writes into the shots that already exist",
);
assert.ok(
    timeline.includes('forward(\'[data-a="story-plan"]\''),
    "and the button is wired to the panel, not left dead",
);
assert.match(
    functionBody(timeline, "createStorySegments(count, { seconds = 0, frames = 0 } = {}) {"),
    /timeline\.segments\.push\(newBatchSegment\(\{\s*\n\s*durationSec: sec,/,
    "a created card is a prompt-batch segment with a duration - the normalizer turns it into 17k+5 frames at H3's 24 fps",
);
assert.match(
    functionBody(timeline, "writeStoryBeat(index, text) {"),
    /shot\.prompt = text;\s*\n\s*syncFl2vFromShots\(this\);/,
    "an fl2v beat goes on the shot, which is the source of truth there",
);
assert.match(
    functionBody(timeline, "async _openStoryPlanner() {"),
    /pe\.storyBox\.open = true;/,
    "the button opens the section itself, not just the panel it hides in",
);

// --- the strings exist in both locales -----------------------------------------

const CJK = /[\u4e00-\u9fff]/;
for (const key of [
    "pe.storySummary",
    "pe.storyTip",
    "pe.storyPlaceholder",
    "pe.storySegments",
    "pe.storySeconds",
    "pe.storyPlan",
    "pe.storyPlanning",
    "pe.storyNeedText",
    "pe.storyNeedModel",
    "pe.storyFailed",
    "pe.storyCreated",
    "pe.storyTooFew",
    "pe.storyFilled",
    "pe.storyFl2vNote",
    "pe.storyReviewAsk",
    "pe.storyReviewAsk2",
    "pe.regenerate",
    "pe.regenerateAll",
    "pe.regenerating",
    "pe.regenerateFailed",
]) {
    const values = [...i18n.matchAll(new RegExp(`"${key.replace(/\./g, "\\.")}": "([^"]*)"`, "g"))]
        .map((match) => match[1]);
    assert.equal(values.length, 2, `${key}: one string per locale`);
    assert.ok(values.some((value) => !CJK.test(value)), `${key}: an English one`);
    assert.ok(values.some((value) => CJK.test(value)), `${key}: a Chinese one`);
}

console.log("Story to segments wiring passed");