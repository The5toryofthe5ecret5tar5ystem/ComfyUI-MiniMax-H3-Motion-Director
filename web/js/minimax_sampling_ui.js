const INTERNAL_SAMPLING_WIDGETS = Object.freeze([
    "steps",
    "sampler_name",
    "scheduler",
    "shift_video",
    "shift_audio",
]);

const SEED_CONTROL_MODES = new Set(["fixed", "increment", "decrement", "randomize"]);

export function normalizeSeedControlMode(value) {
    const mode = String(value || "").trim().toLowerCase();
    return SEED_CONTROL_MODES.has(mode) ? mode : "unknown";
}

export function seedControlModeFromWidgets(widgets = []) {
    const seed = widgets.find((widget) => widget?.name === "seed");
    const control = seed?.linkedWidgets?.find((widget) => (
        /control[_\s]?after[_\s]?generate/i.test(String(widget?.name || widget?.label || ""))
    ));
    return normalizeSeedControlMode(control?.value);
}

function hasLink(input) {
    return input?.link !== null && input?.link !== undefined;
}

export function getSamplingConnectionState(inputs = []) {
    const sampler = inputs.find((input) => input?.name === "sampler");
    const sigmas = inputs.find((input) => input?.name === "sigmas");
    const hasSampler = hasLink(sampler);
    const hasSigmas = hasLink(sigmas);
    if (hasSampler && hasSigmas) return "external";
    if (!hasSampler && !hasSigmas) return "internal";
    return "incomplete";
}

function setWidgetVisible(widget, visible) {
    if (!widget) return;
    if (!widget._mmxSamplingVisibility) {
        widget._mmxSamplingVisibility = {
            computeSize: widget.computeSize,
            hidden: widget.hidden,
            optionHidden: widget.options?.hidden,
            display: widget.element?.style?.display ?? "",
        };
    }
    const saved = widget._mmxSamplingVisibility;
    if (visible) {
        widget.computeSize = saved.computeSize;
        widget.hidden = saved.hidden;
        if (!widget.options) widget.options = {};
        if (saved.optionHidden === undefined) delete widget.options.hidden;
        else widget.options.hidden = saved.optionHidden;
        if (widget.element?.style) widget.element.style.display = saved.display;
        return;
    }
    widget.hidden = true;
    if (!widget.options) widget.options = {};
    widget.options.hidden = true;
    widget.computeSize = () => [0, 0];
    if (widget.element?.style) widget.element.style.display = "none";
}

export function applySamplingWidgetVisibility(node) {
    const state = getSamplingConnectionState(node?.inputs || []);
    const showInternal = state !== "external";
    for (const name of INTERNAL_SAMPLING_WIDGETS) {
        setWidgetVisible(node?.widgets?.find((widget) => widget?.name === name), showInternal);
    }
    return state;
}

function widgetIndexBefore(inputs, inputIndex) {
    let index = 0;
    for (let i = 0; i < inputIndex; i += 1) {
        if (inputs[i]?.widget) index += 1;
    }
    return index;
}

const DIRECTOR_GROUP_INPUT_NAMES = new Set([
    "bd_grp_sample",
    "bd_grp_motion",
    "bd_grp_advanced",
    "bd_grp_perf",
    "bd_grp_experimental",
]);

// Current Director widget serialization order. BDBROUP widgets are real widgets
// when the frontend extension is loaded. If the extension fails during a graph
// load, ComfyUI can persist them as input sockets instead, shifting every later
// widget value by one slot. Repair that graph shape before node construction.
const DIRECTOR_GROUP_WIDGET_LAYOUT = Object.freeze([
    [2, "采样设置"],
    [12, "Motion Context"],
    [18, "高级采样"],
    [24, "性能"],
    [27, "Experimental"],
]);

function isDirectorWorkflowNode(node) {
    return String(node?.type || node?.comfyClass || "") === "MiniMaxH3MotionDirector";
}

function removePersistedDirectorGroupInputs(node) {
    if (!Array.isArray(node?.inputs)) return [];
    const removed = [];
    node.inputs.forEach((input, index) => {
        if (DIRECTOR_GROUP_INPUT_NAMES.has(String(input?.name || ""))) removed.push(index);
    });
    if (!removed.length) return removed;
    const removeSet = new Set(removed);
    node.inputs = node.inputs.filter((_, index) => !removeSet.has(index));
    return removed;
}

function restoreMissingDirectorGroupWidgetValues(node) {
    const values = node?.widgets_values;
    if (!Array.isArray(values)) return 0;
    let inserted = 0;
    for (const [index, fallback] of DIRECTOR_GROUP_WIDGET_LAYOUT) {
        // Every BDBROUP value is a string; the widget immediately following each
        // group is numeric/boolean. This makes a missing group slot unambiguous.
        if (index <= values.length && typeof values[index] !== "string") {
            values.splice(index, 0, fallback);
            inserted += 1;
        }
    }
    return inserted;
}

export function repairDirectorGroupWidgetWorkflow(graphData) {
    if (!graphData || !Array.isArray(graphData.nodes)) return 0;
    const removedByNode = new Map();
    let repaired = 0;
    for (const node of graphData.nodes) {
        if (!isDirectorWorkflowNode(node)) continue;
        const removed = removePersistedDirectorGroupInputs(node);
        if (removed.length) {
            removedByNode.set(String(node.id), removed);
            repaired += removed.length;
        }
        repaired += restoreMissingDirectorGroupWidgetValues(node);
    }
    if (!removedByNode.size || !Array.isArray(graphData.links)) return repaired;

    const adjustedSlot = (nodeId, slot) => {
        const removed = removedByNode.get(String(nodeId));
        if (!removed?.length) return slot;
        const original = Number(slot);
        if (!Number.isFinite(original)) return slot;
        return original - removed.filter((index) => index < original).length;
    };

    for (const link of graphData.links) {
        if (Array.isArray(link)) {
            link[4] = adjustedSlot(link[3], link[4]);
            continue;
        }
        if (!link || typeof link !== "object") continue;
        const targetIdKey = "target_id" in link ? "target_id" : "targetId";
        const targetSlotKey = "target_slot" in link ? "target_slot" : "targetSlot";
        link[targetSlotKey] = adjustedSlot(link[targetIdKey], link[targetSlotKey]);
    }
    return repaired;
}

// Declaration tail of MiniMaxH3MotionDirector, in order: [name, kind, default].
// KEEP IN STEP with TAIL_AFTER_POSTPROCESS / LEGACY_TAIL_AFTER_POSTPROCESS in
// tests/test_example_workflow_widgets.py - tests/test_director_widget_tail_parity.py
// fails if the two drift.
//
// ComfyUI coerces each slot by declaration type, so int(None) / float(None) raise
// while str(None) / bool(None) do not. That is why a null in a numeric slot makes
// the workflow unqueueable:
//
//     Failed to convert an input value to a FLOAT value: audio_refine_denoise, None
//
// This is recurring, not a one-off: saving a workflow that predates a widget makes
// the frontend append the new slots with null, because it has no saved value to
// restore them from. verbose_logging was inserted mid-tail that way, and one file
// was seen with the `bd_grp_advanced` section header written into the boolean slot
// it belongs to.
const DIRECTOR_WIDGET_TAIL = [
    ["bd_grp_audio_refine", "str", "Audio Refine"],
    ["audio_refine_enabled", "bool", false],
    ["audio_refine_steps", "int", 6],
    ["audio_refine_denoise", "float", 0.5],
    ["latent_continuation_enabled", "bool", false],
    ["verbose_logging", "bool", false],
    ["minimax_motion_director_ui", "str", ""],
];

// Files saved before verbose_logging was declared end one slot earlier.
const LEGACY_DIRECTOR_WIDGET_TAIL = DIRECTOR_WIDGET_TAIL.filter(
    ([name]) => name !== "verbose_logging",
);

function tailValueIsValid(kind, value) {
    switch (kind) {
        case "int":
            return typeof value === "number" && Number.isInteger(value);
        case "float":
            return typeof value === "number" && Number.isFinite(value);
        case "bool":
            return typeof value === "boolean";
        default:
            return typeof value === "string";
    }
}

/** Index of the postprocess_config widget: the anchor the tail hangs off. */
function directorTailAnchor(values) {
    return values.findIndex((value) => typeof value === "string"
        && value.startsWith('{"version":')
        && value.includes('"global_refine"'));
}

/**
 * Replace null / wrongly-typed values in the Director's declaration tail.
 *
 * Anchored on postprocess_config rather than measured from the end of the array:
 * a file saved before a widget existed is simply shorter, and counting backwards
 * would line the table up against the wrong slots and overwrite live values.
 */
function repairDirectorWidgetTail(node) {
    const values = node?.widgets_values;
    if (!Array.isArray(values)) return 0;
    const anchor = directorTailAnchor(values);
    if (anchor < 0) return 0;

    const tail = values.slice(anchor + 1);
    // Only the two shapes the node has actually shipped. Anything else is
    // unfamiliar and is left for the guard test to report rather than guessed at.
    let spec = null;
    if (tail.length >= DIRECTOR_WIDGET_TAIL.length) spec = DIRECTOR_WIDGET_TAIL;
    else if (tail.length === LEGACY_DIRECTOR_WIDGET_TAIL.length) spec = LEGACY_DIRECTOR_WIDGET_TAIL;
    if (!spec) return 0;

    const mirrors = [node.widgets_values_named, node?.properties?.mmx_director_widget_state]
        .filter((mirror) => mirror && typeof mirror === "object");

    let repaired = 0;
    spec.forEach(([name, kind, fallback], offset) => {
        const index = anchor + 1 + offset;
        if (!tailValueIsValid(kind, values[index])) {
            values[index] = fallback;
            repaired += 1;
        }
        for (const mirror of mirrors) {
            // Mirrors are loosely typed (some files store '6' / 'false'), so only
            // fill a genuine gap; never rewrite a value the user set.
            if (Object.prototype.hasOwnProperty.call(mirror, name) && mirror[name] == null) {
                mirror[name] = fallback;
                repaired += 1;
            }
        }
    });
    return repaired;
}

export function repairDirectorWidgetTailWorkflow(graphData) {
    if (!graphData || !Array.isArray(graphData.nodes)) return 0;
    let repaired = 0;
    for (const node of graphData.nodes) {
        if (!isDirectorWorkflowNode(node)) continue;
        repaired += repairDirectorWidgetTail(node);
    }
    return repaired;
}

export function migrateLegacySamplingControlNode(node) {
    if (!node || node.type !== "MiniMaxH3MotionDirector" || !Array.isArray(node.inputs)) {
        return false;
    }
    const inputIndex = node.inputs.findIndex((input) => input?.name === "sampling_control");
    if (inputIndex < 0) return false;
    const explicitValueIndex = Array.isArray(node.widgets_values)
        ? node.widgets_values.findIndex((value) => value === "internal" || value === "external")
        : -1;
    // ComfyUI serializes seed's linked control_after_generate widget even though
    // it has no matching node.inputs entry, so prefer the distinctive legacy value.
    const widgetIndex = explicitValueIndex >= 0
        ? explicitValueIndex
        : widgetIndexBefore(node.inputs, inputIndex);
    node.inputs.splice(inputIndex, 1);
    if (Array.isArray(node.widgets_values) && widgetIndex < node.widgets_values.length) {
        node.widgets_values.splice(widgetIndex, 1);
    }
    return { inputIndex };
}

export function migrateLegacySamplingControlWorkflow(graphData) {
    if (!graphData || !Array.isArray(graphData.nodes)) return 0;
    const removedSlots = new Map();
    for (const node of graphData.nodes) {
        const result = migrateLegacySamplingControlNode(node);
        if (result) removedSlots.set(String(node.id), result.inputIndex);
    }
    if (!removedSlots.size || !Array.isArray(graphData.links)) return removedSlots.size;

    for (const link of graphData.links) {
        if (Array.isArray(link)) {
            const removed = removedSlots.get(String(link[3]));
            if (removed !== undefined && Number(link[4]) > removed) link[4] -= 1;
            continue;
        }
        if (!link || typeof link !== "object") continue;
        const targetIdKey = "target_id" in link ? "target_id" : "targetId";
        const targetSlotKey = "target_slot" in link ? "target_slot" : "targetSlot";
        const removed = removedSlots.get(String(link[targetIdKey]));
        if (removed !== undefined && Number(link[targetSlotKey]) > removed) {
            link[targetSlotKey] -= 1;
        }
    }
    return removedSlots.size;
}

export { INTERNAL_SAMPLING_WIDGETS };
