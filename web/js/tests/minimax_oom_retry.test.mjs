import assert from "node:assert/strict";

import { oomRetryActions } from "../minimax_oom_retry.mjs";

// A VRAM failure used to be prose: "ran out of VRAM during H3 sampling. Reduce
// resolution, use fewer references...". The user had to translate that back into
// settings themselves. The engine now emits the failing shape and the same
// suggestions the pre-flight check prints, so the run panel can offer the exact
// change - and this module is the parsing between the two.

const t = (key, values = {}) => `${key}(${Object.entries(values).map(([k, v]) => `${k}=${v}`).join(",")})`;

const FAILING = {
    stage: "h3_sampling",
    timeline_segment_index: 3,
    free_gb: 0.06,
    shape: {
        index: 3, label: "S4", frames: 311, sampled_frames: 345,
        width: 1376, height: 768, pictures: 2, ref_long_edge: 1376,
        tokens: 91848, attention_gb: 2.99,
    },
    suggestions: [
        "Set reference size to 1024 px (this machine's baseline) - the references alone are adding 2064 tokens at 1376 px.",
        "Render at most 243 frames per segment on this machine (this one is 311).",
        "The tier's default is 175 frames; split this segment rather than rendering it whole.",
    ],
};

const plan = oomRetryActions(FAILING, t);

assert.equal(plan.label, "S4");
assert.equal(plan.index, 3);
assert.match(plan.title, /segment=S4/);

// Both fixes are offered, the segment-length one first because it is the local
// change: the reference size is a node-level setting that reaches every segment.
assert.deepEqual(plan.actions.map((action) => action.kind), ["frames", "ref_size"]);
assert.equal(plan.actions[0].value, 243, "the tier's cap, not its default");
assert.equal(plan.actions[0].index, 3, "the retry resumes from the failed segment");
assert.match(plan.actions[0].label, /frames=243/);
assert.equal(plan.actions[1].value, 1024);
assert.match(plan.actions[1].note, /oomProjectWide/);

// Only the first frames suggestion becomes a button: offering both the cap and
// the default would be two buttons that do the same thing at different sizes.
assert.equal(plan.actions.filter((action) => action.kind === "frames").length, 1);

// A payload whose only advice is the default length still offers that.
const defaultOnly = oomRetryActions({
    timeline_segment_index: 1,
    suggestions: ["The tier's default is 175 frames; split this segment rather than rendering it whole."],
}, t);
assert.equal(defaultOnly.actions.length, 1);
assert.equal(defaultOnly.actions[0].value, 175);

// Without a segment index there is nothing safe to retry: the shape alone is
// reported, and no button pretends to know which row to change.
const noIndex = oomRetryActions({
    suggestions: ["Render at most 243 frames per segment on this machine (this one is 311)."],
    shape: { label: "Source Bridge", frames: 5 },
}, t);
assert.equal(noIndex.label, "Source Bridge");
assert.deepEqual(noIndex.actions, []);

// Defensive: a failure that carries nothing must not produce an empty box.
assert.equal(oomRetryActions(null, t), null);
assert.equal(oomRetryActions({}, t), null);
assert.equal(oomRetryActions({ suggestions: ["something else entirely"] }, t), null);

// Round-trip against the real suggestion wording: the patterns must match what
// lib/vram_budget.suggest_fit actually emits, or the buttons never appear.
const realWordings = [
    "Set reference size to 768 px: brings this shape to 1.20x.",
    "Drop the canvas to 1344x768: attention cost tracks tokens, and tokens track pixels.",
];
const canvasOnly = oomRetryActions({ timeline_segment_index: 0, suggestions: realWordings }, t);
assert.deepEqual(canvasOnly.actions.map((a) => [a.kind, a.value]), [["ref_size", 768]]);
