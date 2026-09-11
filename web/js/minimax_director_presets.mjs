// Portions derived from ComfyUI_MiniMaxH3_Director
// Copyright AIMixer and contributors
// Originally licensed under Apache License 2.0
// Modified for MiniMax H3 Motion Director, 2026-09-10
// This derivative project is distributed under GPL-3.0.
// See NOTICE and LICENSES/Apache-2.0-AIMixer.txt.

/**
 * Named Director presets: what a preset captures, and how it is applied.
 *
 * Pure and DOM-free so it can be unit tested; the editor only moves values between
 * here and the real widgets.
 *
 * Design rules, because a preset that silently rewrites a project is worse than no
 * preset at all:
 *
 * - A preset captures *settings*, never content. Segments and prompts are the
 *   project. `global_prompt` is excluded for the same reason.
 * - `seed` is excluded. Seeds are per-render; applying a preset should not silently
 *   change which take you get. (A "fixed look" preset is a seed+prompt job, not a
 *   preset job.)
 * - `task_type` is excluded. It reshapes the whole node UI and can invalidate
 *   existing segments, so applying it from a preset is a mode change, not a setting.
 * - Derived widgets (`total_frames`) and node inputs (`model`, `*_vae`, `clip`,
 *   `director_inputs`, `sampler`, `sigmas`) are excluded - they are graph wiring,
 *   not settings.
 * - Shared references (`r2vCommon`) are opt-in, because attaching files a project
 *   does not have is a surprise, not a convenience.
 */

export const PRESET_SCHEMA_VERSION = 1;

/**
 * Scalar settings a preset owns. Verified against the live
 * `MiniMaxH3MotionDirector` schema; keep this list explicit rather than sweeping
 * "every widget", so a future widget cannot join a preset by accident.
 */
export const PRESET_WIDGET_NAMES = [
    // Output
    "width",
    "height",
    "ref_max_size",
    "frame_rate",
    // Continuity
    "motion_context_enabled",
    "context_length",
    "source_overlap_frames",
    "audio_context_enabled",
    "color_reanchor_enabled",
    // Sampling
    "cfg",
    "steps",
    "sampler_name",
    "scheduler",
    "shift_video",
    "shift_audio",
    // Performance
    "clear_vram_between_segments",
    "export_source_images",
    // Experimental
    "pin_renorm_enabled",
    "postprocess_config",
    // Audio refine
    "audio_refine_enabled",
    "audio_refine_steps",
    "audio_refine_denoise",
];

/**
 * `timeline.output` settings that are worth preset-ing.
 *
 * Only the continuity pair qualifies, and only because it has a real control path:
 * it is driven by the output bar's own controls, and the editor re-derives
 * `timeline.output` from those on every commit. They are therefore applied *through
 * the controls*, never by writing `timeline.output` directly - a direct write is
 * overwritten by the next `commit()` and would silently do nothing.
 *
 * The other `timeline.output` keys are excluded on purpose. `width`/`height`/
 * `longEdge`/`megapixels`/`multiple`/`aspectRatio` are derived from the dimension
 * widgets, and `exportMode`/`maxExportFrames`/`audioMode`/`mode` have no control
 * path we can drive, so a preset could not apply them reliably.
 */
export const PRESET_OUTPUT_CONTROLS = ["continuityEnabled", "continuityOverlapFrames"];

/** Widgets excluded on purpose, kept here so the exclusion is reviewable. */
export const PRESET_EXCLUDED_WIDGETS = [
    "seed",
    "task_type",
    "global_prompt",
    "total_frames",
    "timeline_data",
    "director_inputs",
];

function isPlainObject(value) {
    return !!value && typeof value === "object" && !Array.isArray(value);
}

function clone(value) {
    if (value === undefined) return undefined;
    if (typeof structuredClone === "function") {
        try {
            return structuredClone(value);
        } catch {
            /* fall through to JSON */
        }
    }
    try {
        return JSON.parse(JSON.stringify(value));
    } catch {
        return value;
    }
}

/**
 * Build the stored payload for "save current settings as a preset".
 *
 * @param {object} args
 * @param {Record<string, unknown>} args.widgetValues current values by widget name
 * @param {object} [args.timeline] live timeline (for `output` / `r2vCommon`)
 * @param {boolean} [args.includeReferences] opt in to capturing `r2vCommon`
 */
export function collectPresetPayload({ widgetValues = {}, timeline = null, includeReferences = false } = {}) {
    const widgets = {};
    for (const name of PRESET_WIDGET_NAMES) {
        if (Object.prototype.hasOwnProperty.call(widgetValues, name)) {
            widgets[name] = clone(widgetValues[name]);
        }
    }

    const output = {};
    const liveOutput = isPlainObject(timeline?.output) ? timeline.output : {};
    for (const key of PRESET_OUTPUT_CONTROLS) {
        if (Object.prototype.hasOwnProperty.call(liveOutput, key)) {
            output[key] = clone(liveOutput[key]);
        }
    }

    const payload = {
        version: PRESET_SCHEMA_VERSION,
        widgets,
        output,
    };

    if (includeReferences && isPlainObject(timeline?.r2vCommon)) {
        payload.r2vCommon = clone(timeline.r2vCommon);
    }
    return payload;
}

/**
 * Decide what applying `payload` would change, without changing anything.
 *
 * Returning a plan instead of mutating keeps this testable and lets the caller
 * report "applied N settings, skipped M unknown" instead of guessing.
 */
export function planPresetApply({ payload, widgetValues = {}, timeline = null } = {}) {
    const plan = {
        widgets: {},
        output: {},
        r2vCommon: null,
        applied: [],
        skipped: [],
        unchanged: [],
    };
    if (!isPlainObject(payload)) {
        plan.skipped.push("payload");
        return plan;
    }

    // Only known names are honoured: a payload from another version, or a hand-edited
    // one, must not be able to write arbitrary widget values.
    const source = isPlainObject(payload.widgets) ? payload.widgets : {};
    for (const [name, value] of Object.entries(source)) {
        if (!PRESET_WIDGET_NAMES.includes(name)) {
            plan.skipped.push(name);
            continue;
        }
        if (Object.prototype.hasOwnProperty.call(widgetValues, name) && widgetValues[name] === value) {
            plan.unchanged.push(name);
            continue;
        }
        plan.widgets[name] = clone(value);
        plan.applied.push(name);
    }

    const outputSource = isPlainObject(payload.output) ? payload.output : {};
    for (const [key, value] of Object.entries(outputSource)) {
        if (!PRESET_OUTPUT_CONTROLS.includes(key)) {
            plan.skipped.push(`output.${key}`);
            continue;
        }
        if (isPlainObject(timeline?.output) && timeline.output[key] === value) {
            plan.unchanged.push(`output.${key}`);
            continue;
        }
        plan.output[key] = clone(value);
        plan.applied.push(`output.${key}`);
    }

    if (isPlainObject(payload.r2vCommon)) {
        plan.r2vCommon = clone(payload.r2vCommon);
        plan.applied.push("r2vCommon");
    }

    return plan;
}

/** Compact description for the preset list UI. */
export function describePresetPayload(payload) {
    const widgets = isPlainObject(payload?.widgets) ? payload.widgets : {};
    const output = isPlainObject(payload?.output) ? payload.output : {};
    const references = isPlainObject(payload?.r2vCommon) ? payload.r2vCommon : null;
    const refCount = references
        ? (Array.isArray(references.refs) ? references.refs.length : 0)
          + (Array.isArray(references.refAudios) ? references.refAudios.length : 0)
          + (Array.isArray(references.refVideos) ? references.refVideos.length : 0)
        : 0;
    return {
        version: Number(payload?.version) || 0,
        settings: Object.keys(widgets).length + Object.keys(output).length,
        includesReferences: !!references,
        referenceCount: refCount,
        sampler: typeof widgets.sampler_name === "string" ? widgets.sampler_name : "",
        steps: Number.isFinite(widgets.steps) ? Number(widgets.steps) : null,
        width: Number.isFinite(widgets.width) ? Number(widgets.width) : null,
        height: Number.isFinite(widgets.height) ? Number(widgets.height) : null,
    };
}

/** Human-readable one-liner for a preset row. */
export function formatPresetSummary(payload) {
    const info = describePresetPayload(payload);
    const parts = [];
    if (info.width && info.height) parts.push(`${info.width}×${info.height}`);
    if (info.steps != null) parts.push(`${info.steps} steps`);
    if (info.sampler) parts.push(info.sampler);
    parts.push(`${info.settings} setting${info.settings === 1 ? "" : "s"}`);
    if (info.includesReferences) parts.push(`${info.referenceCount} reference(s)`);
    return parts.join(" · ");
}
