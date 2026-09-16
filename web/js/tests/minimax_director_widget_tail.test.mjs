#!/usr/bin/env node
// Unit tests for repairDirectorWidgetTailWorkflow.
//
// The bug it repairs is recurring: saving a workflow that predates a widget makes
// the frontend append the new slots with null, and ComfyUI coerces widget values by
// declaration type, so int(None) / float(None) raise and the workflow becomes
// unqueueable. One real file also had a BDBROUP section header written into a
// boolean slot instead of null.

import assert from "node:assert/strict";
import { repairDirectorWidgetTailWorkflow } from "../minimax_sampling_ui.js";

const POSTPROCESS = '{"version":11,"global_refine":{"enabled":false}}';

// Offsets from the postprocess_config slot, i.e. what `anchor + N` selects.
const OFF = {
    bd_grp_audio_refine: 1,
    audio_refine_enabled: 2,
    audio_refine_steps: 3,
    audio_refine_denoise: 4,
    latent_continuation_enabled: 5,
    verbose_logging: 6,
    minimax_motion_director_ui: 7,
};

function directorNode(values, { named = {}, state = null } = {}) {
    const node = {
        id: "dir",
        type: "MiniMaxH3MotionDirector",
        widgets_values: values,
        widgets_values_named: named,
    };
    if (state) node.properties = { mmx_director_widget_state: state };
    return node;
}

/** `lead` plus a valid 7-slot tail; returns { values, anchor }. */
function withTail(lead) {
    const values = [
        ...lead,
        POSTPROCESS,
        "Audio Refine",
        false,
        6,
        0.5,
        false,
        false,
        "",
    ];
    return { values, anchor: values.length - 8 };
}

// ---------------------------------------------------------------- 1. the null case
{
    const { values, anchor } = withTail([1, "x"]);
    values[anchor + OFF.latent_continuation_enabled] = null;
    values[anchor + OFF.verbose_logging] = null;
    const named = { latent_continuation_enabled: null, verbose_logging: null };
    const state = { latent_continuation_enabled: null, verbose_logging: null };
    const graph = { nodes: [directorNode(values, { named, state })] };

    const repaired = repairDirectorWidgetTailWorkflow(graph);

    assert.equal(values[anchor + OFF.latent_continuation_enabled], false);
    assert.equal(values[anchor + OFF.verbose_logging], false);
    assert.equal(named.latent_continuation_enabled, false, "named mirror repaired");
    assert.equal(state.verbose_logging, false, "state mirror repaired");
    assert.equal(repaired, 6, "counts widget slots and mirror fills");
    console.log("null slots and their mirrors are repaired");
}

// ------------------------------------------------- 2. the misplaced section header
{
    const { values, anchor } = withTail([1]);
    values[anchor + OFF.latent_continuation_enabled] = null;
    values[anchor + OFF.verbose_logging] = "Advanced sampling · Sampling: external";
    const graph = { nodes: [directorNode(values)] };

    repairDirectorWidgetTailWorkflow(graph);

    assert.equal(values[anchor + OFF.latent_continuation_enabled], false);
    assert.equal(values[anchor + OFF.verbose_logging], false,
        "a header string in a bool slot is replaced");
    console.log("a section header in a boolean slot is replaced");
}

// ----------------------------------------------- 3. a numeric slot holding a string
{
    const { values, anchor } = withTail([1]);
    values[anchor + OFF.audio_refine_denoise] = "0.5";
    const graph = { nodes: [directorNode(values)] };

    repairDirectorWidgetTailWorkflow(graph);

    assert.equal(values[anchor + OFF.audio_refine_denoise], 0.5,
        "a stringified float is replaced by the default");
    console.log("a wrongly-typed numeric slot is replaced");
}

// ------------------------------------------------------- 4. valid values untouched
{
    const { values, anchor } = withTail([1]);
    values[anchor + OFF.latent_continuation_enabled] = true;
    values[anchor + OFF.verbose_logging] = true;
    const named = { latent_continuation_enabled: true, verbose_logging: "true" };
    const graph = { nodes: [directorNode(values, { named })] };
    const before = JSON.stringify(values);

    const repaired = repairDirectorWidgetTailWorkflow(graph);

    assert.equal(repaired, 0, "nothing to repair");
    assert.equal(JSON.stringify(values), before, "array untouched");
    assert.equal(values[anchor + OFF.latent_continuation_enabled], true,
        "a user's true is not reset to the default");
    assert.equal(named.verbose_logging, "true", "a loosely-typed mirror value is kept");
    console.log("valid values, including user-set ones, are left alone");
}

// --------------------------------------------------- 5. the legacy 6-slot shape
{
    const values = [1, POSTPROCESS, "Audio Refine", false, 6, 0.5, null, ""];
    const graph = { nodes: [directorNode(values)] };

    repairDirectorWidgetTailWorkflow(graph);

    assert.equal(values[6], false, "legacy latent_continuation_enabled repaired");
    assert.equal(values[7], "", "the trailing ui string is not mapped onto verbose_logging");
    console.log("the legacy 6-slot tail is not misaligned against the 7-slot table");
}

// --------------------------------------------------- 6. no anchor, no guessing
{
    const values = [1, "no postprocess config here", null, null, null];
    const before = JSON.stringify(values);
    const graph = { nodes: [directorNode(values)] };

    const repaired = repairDirectorWidgetTailWorkflow(graph);

    assert.equal(repaired, 0);
    assert.equal(JSON.stringify(values), before, "an unrecognised array is left alone");
    console.log("an array without the anchor is left alone");
}

// --------------------------------------------------- 7. other node types are skipped
{
    const other = {
        id: 3,
        type: "SomeOtherNode",
        widgets_values: [POSTPROCESS, "Audio Refine", false, 6, 0.5, null, null, ""],
    };
    const graph = { nodes: [other] };
    const before = JSON.stringify(other.widgets_values);

    const repaired = repairDirectorWidgetTailWorkflow(graph);

    assert.equal(repaired, 0);
    assert.equal(JSON.stringify(other.widgets_values), before, "non-director node untouched");
    console.log("non-director nodes are skipped");
}

// ----------------------------------- 8. a mirror without the key is not given one
{
    const { values, anchor } = withTail([1]);
    values[anchor + OFF.verbose_logging] = null;
    const named = {}; // verbose_logging absent entirely
    const graph = { nodes: [directorNode(values, { named })] };

    repairDirectorWidgetTailWorkflow(graph);

    assert.equal(values[anchor + OFF.verbose_logging], false, "the widget slot is still repaired");
    assert.equal("verbose_logging" in named, false, "a missing mirror key is not invented");
    console.log("a mirror missing the key is not given one");
}

// ------------------------------------------------- 9. malformed input does not throw
{
    assert.equal(repairDirectorWidgetTailWorkflow(null), 0);
    assert.equal(repairDirectorWidgetTailWorkflow({}), 0);
    assert.equal(repairDirectorWidgetTailWorkflow({ nodes: "nope" }), 0);
    assert.equal(
        repairDirectorWidgetTailWorkflow({ nodes: [{ type: "MiniMaxH3MotionDirector" }] }),
        0,
    );
    console.log("malformed input returns 0 instead of throwing");
}

console.log("\nminimax director widget tail repair tests passed");
