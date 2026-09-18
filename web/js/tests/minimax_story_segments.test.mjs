import assert from "node:assert/strict";
import fs from "node:fs";

// Story -> segments: one call splits a brief into a world paragraph plus one paragraph
// per segment, the panel writes them into the timeline, and the review list produces
// the final prompt for each. Two things have to stay true or the feature is a footgun:
// the panel must not invent segments in a timeline the user laid out by hand, and the
// frame arithmetic must be the same one the rest of the pack uses.
//
// Source-level: mounting needs a live Director node and a ComfyUI api object.

const enhancer = fs.readFileSync(new URL("../minimax_prompt_enhancer.js", import.meta.url), "utf8");
const batch = fs.readFileSync(new URL("../minimax_prompt_enhance_batch.mjs", import.meta.url), "utf8");
const genTimeline = fs.readFileSync(new URL("../minimax_gen_timeline.js", import.meta.url), "utf8");
const i18n = fs.readFileSync(new URL("../minimax_i18n.js", import.meta.url), "utf8");

function functionBody(source, signature) {
    const at = source.indexOf(signature);
    assert.ok(at > 0, `${signature} must still exist`);
    let depth = 0;
    for (let i = source.indexOf("{", at); i < source.length; i += 1) {
        if (source[i] === "{") depth += 1;
        else if (source[i] === "}") {
            depth -= 1;
            if (depth === 0) return source.slice(source.indexOf("{", at), i + 1);
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

const ensure = functionBody(enhancer, "pe.ensureStorySegments = (count, frames) => {");
assert.match(
    ensure,
    /const mayCreate = !timeline\.segments\.length \|\| !!editor\?\.isGenMode\?\.\(\);/,
    "only an empty timeline or a generation timeline is grown - a hand-laid video or replace timeline is not",
);
assert.match(ensure, /frameCount: frames,/, "a created segment gets the aligned frame count");
assert.match(ensure, /editor\.normalizeGenSegments\?\.\(\);/, "and the timeline is re-tiled by its own normaliser");
assert.match(ensure, /editor\.commit\?\.\(false, \{ syncTimeline: true \}\)/, "one commit, so the change is undoable as a step");

const apply = functionBody(enhancer, "pe.applyStoryPlan = (plan) => {");
assert.match(apply, /pe\.ensureStorySegments\(beats\.length, frames\)/, "the plan sizes the timeline");
assert.match(
    apply,
    /pe\.setPromptTextForBlock\(world \? `\$\{world\}\\n\\n\$\{beat\}` : beat, index\);/,
    "each segment gets the shared world paragraph plus its own beat",
);
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
