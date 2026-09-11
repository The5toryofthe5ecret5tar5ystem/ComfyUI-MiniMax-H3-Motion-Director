// Named Director presets: what is captured, and how it is applied.
//
// The dangerous failure mode for a preset is capturing or applying something it
// should not - a seed, a prompt, a task type, or an arbitrary widget name from a
// stale/hand-edited payload. These tests pin the allowlists and the exclusions.

import assert from "node:assert/strict";
import {
    PRESET_EXCLUDED_WIDGETS,
    PRESET_OUTPUT_CONTROLS,
    PRESET_SCHEMA_VERSION,
    PRESET_WIDGET_NAMES,
    collectPresetPayload,
    describePresetPayload,
    formatPresetSummary,
    planPresetApply,
} from "../minimax_director_presets.mjs";

const LIVE_WIDGETS = {
    width: 960,
    height: 544,
    ref_max_size: 1024,
    frame_rate: 24,
    motion_context_enabled: true,
    context_length: 22,
    source_overlap_frames: 5,
    audio_context_enabled: true,
    color_reanchor_enabled: false,
    cfg: 1.0,
    steps: 14,
    sampler_name: "res_multistep",
    scheduler: "simple",
    shift_video: 12,
    shift_audio: 3,
    clear_vram_between_segments: true,
    export_source_images: false,
    pin_renorm_enabled: false,
    postprocess_config: "",
    audio_refine_enabled: false,
    audio_refine_steps: 6,
    audio_refine_denoise: 0.5,
    // Nuisance values that must never be captured.
    seed: 821096566131032,
    task_type: "r2v — Reference images to video",
    global_prompt: "a very specific project prompt",
    total_frames: 362,
    timeline_data: '{"segments":[]}',
};

const LIVE_TIMELINE = {
    output: { mode: "long_edge", continuityEnabled: true, continuityOverlapFrames: 9, width: 960, height: 544 },
    r2vCommon: { refs: [{ imageFile: "face.png" }], refAudios: [], refVideos: [] },
};

// ---------------------------------------------------------------------------
// Allowlists
// ---------------------------------------------------------------------------

assert.equal(PRESET_SCHEMA_VERSION, 1);

// Every captured name must be a real widget, and the two lists must not overlap.
assert.ok(PRESET_WIDGET_NAMES.length > 15, "the settings group should be substantial");
for (const name of PRESET_WIDGET_NAMES) {
    assert.ok(Object.prototype.hasOwnProperty.call(LIVE_WIDGETS, name), `not a live widget: ${name}`);
    assert.ok(!PRESET_EXCLUDED_WIDGETS.includes(name), `${name} is both included and excluded`);
}
for (const name of PRESET_EXCLUDED_WIDGETS) {
    assert.ok(!PRESET_WIDGET_NAMES.includes(name), `${name} must not be captured`);
}

// Dimension and export settings have no drivable control path, so a preset could
// not apply them reliably. Writing timeline.output directly is also pointless: the
// editor re-derives it from the controls on every commit.
for (const unsupported of ["width", "height", "longEdge", "megapixels", "multiple", "aspectRatio", "exportMode", "maxExportFrames", "audioMode", "mode"]) {
    assert.ok(!PRESET_OUTPUT_CONTROLS.includes(unsupported), `${unsupported} must not be applied`);
}
assert.deepEqual([...PRESET_OUTPUT_CONTROLS].sort(), ["continuityEnabled", "continuityOverlapFrames"]);

// ---------------------------------------------------------------------------
// Capture
// ---------------------------------------------------------------------------

const captured = collectPresetPayload({ widgetValues: LIVE_WIDGETS, timeline: LIVE_TIMELINE });

assert.equal(captured.version, 1);
assert.deepEqual(Object.keys(captured.widgets).sort(), [...PRESET_WIDGET_NAMES].sort());
assert.equal(captured.widgets.steps, 14);
assert.equal(captured.widgets.sampler_name, "res_multistep");

// The exclusions that matter most.
for (const forbidden of ["seed", "task_type", "global_prompt", "total_frames", "timeline_data"]) {
    assert.ok(!(forbidden in captured.widgets), `${forbidden} must never be captured`);
}

// Output: continuity is captured, dimensions are not.
assert.equal(captured.output.continuityEnabled, true);
assert.equal("width" in captured.output, false);
assert.equal("height" in captured.output, false);

// References are opt-in.
assert.equal("r2vCommon" in captured, false, "references must be opt-in");
const withRefs = collectPresetPayload({
    widgetValues: LIVE_WIDGETS,
    timeline: LIVE_TIMELINE,
    includeReferences: true,
});
assert.deepEqual(withRefs.r2vCommon, LIVE_TIMELINE.r2vCommon);

// The payload must be a detached copy, proved on throwaway probes so the fixtures
// reused below stay pristine.
const aliasingProbe = collectPresetPayload({ widgetValues: LIVE_WIDGETS, timeline: LIVE_TIMELINE });
aliasingProbe.widgets.steps = 999;
assert.equal(LIVE_WIDGETS.steps, 14, "capture must not alias the live widget values");

const refAliasingProbe = collectPresetPayload({
    widgetValues: LIVE_WIDGETS,
    timeline: LIVE_TIMELINE,
    includeReferences: true,
});
refAliasingProbe.r2vCommon.refs[0].imageFile = "mutated.png";
assert.equal(LIVE_TIMELINE.r2vCommon.refs[0].imageFile, "face.png", "references must be cloned");

// Missing widgets are simply absent, not null-filled.
const sparse = collectPresetPayload({ widgetValues: { steps: 20 }, timeline: null });
assert.deepEqual(Object.keys(sparse.widgets), ["steps"]);
assert.deepEqual(sparse.output, {});

// ---------------------------------------------------------------------------
// Apply
// ---------------------------------------------------------------------------

const target = { ...LIVE_WIDGETS, steps: 30, sampler_name: "euler" };
const plan = planPresetApply({ payload: captured, widgetValues: target, timeline: LIVE_TIMELINE });

assert.equal(plan.widgets.steps, 14, "a differing value must be applied");
assert.equal(plan.widgets.sampler_name, "res_multistep");
assert.ok(!("seed" in plan.widgets), "apply must not reach excluded widgets");
assert.ok(plan.applied.includes("steps"));
assert.ok(plan.unchanged.includes("cfg"), "already-matching values are reported, not rewritten");
assert.equal(plan.output.continuityEnabled, undefined, "unchanged output keys are skipped");
assert.ok(plan.unchanged.includes("output.continuityEnabled"));

// Applying must not touch the inputs it was given.
assert.equal(target.steps, 30, "planning must not mutate the caller's widgets");
assert.equal(LIVE_TIMELINE.output.continuityEnabled, true);

// A change to a continuity setting is applied.
const flip = planPresetApply({
    payload: { widgets: {}, output: { continuityEnabled: false, continuityOverlapFrames: 21 } },
    widgetValues: target,
    timeline: LIVE_TIMELINE,
});
assert.equal(flip.output.continuityEnabled, false);
assert.equal(flip.output.continuityOverlapFrames, 21);
assert.ok(flip.applied.includes("output.continuityOverlapFrames"));
assert.deepEqual(flip.widgets, {}, "continuity must not go through the widget group");

// Unknown widget names from a stale or hand-edited payload must be skipped.
const hostile = planPresetApply({
    payload: {
        widgets: { steps: 10, notAWidget: 1, seed: 42, __proto__: { polluted: true } },
        output: { width: 4096, exportMode: "segments" },
    },
    widgetValues: target,
    timeline: LIVE_TIMELINE,
});
assert.equal(hostile.widgets.steps, 10);
assert.ok(!("notAWidget" in hostile.widgets));
assert.ok(!("seed" in hostile.widgets));
assert.deepEqual(hostile.output, {}, "settings without a control path must be refused");
assert.deepEqual(hostile.skipped.sort(), ["notAWidget", "output.exportMode", "output.width", "seed"]);

// Nothing at all should be possible from garbage.
for (const bad of [null, undefined, 42, "payload", []]) {
    const empty = planPresetApply({ payload: bad, widgetValues: target, timeline: LIVE_TIMELINE });
    assert.deepEqual(empty.widgets, {});
    assert.deepEqual(empty.output, {});
    assert.equal(empty.r2vCommon, null);
    assert.deepEqual(empty.applied, []);
}

// References only travel when the payload carries them.
assert.equal(plan.r2vCommon, null);
const refPlan = planPresetApply({ payload: withRefs, widgetValues: target, timeline: LIVE_TIMELINE });
assert.deepEqual(refPlan.r2vCommon.refs, [{ imageFile: "face.png" }]);
refPlan.r2vCommon.refs[0].imageFile = "mutated.png";
assert.equal(withRefs.r2vCommon.refs[0].imageFile, "face.png", "apply must clone out of the payload");

// ---------------------------------------------------------------------------
// Presentation
// ---------------------------------------------------------------------------

const described = describePresetPayload(captured);
assert.equal(described.version, 1);
assert.ok(described.settings >= PRESET_WIDGET_NAMES.length);
assert.equal(described.includesReferences, false);
assert.equal(described.steps, 14);
assert.equal(described.sampler, "res_multistep");
assert.equal(described.width, 960);

const refInfo = describePresetPayload(withRefs);
assert.equal(refInfo.includesReferences, true);
assert.equal(refInfo.referenceCount, 1);

const summary = formatPresetSummary(captured);
assert.ok(summary.includes("960×544"), summary);
assert.ok(summary.includes("14 steps"), summary);
assert.ok(summary.includes("res_multistep"), summary);
assert.ok(!summary.includes("reference"), summary);

assert.ok(formatPresetSummary(withRefs).includes("1 reference(s)"));
assert.equal(formatPresetSummary(null).includes("0 settings"), true, "garbage must still describe");

console.log("minimax_director_presets.test.mjs OK");
