/**
 * Content preservation for the Director's replace-window re-cut.
 *
 * "Long-form replace - cover whole clip" rebuilds `timeline.segments` from
 * scratch in order to lay the clip out in equal windows. Laying out is all it
 * should do. Every window used to be built by the plain new-window factory, so
 * every window came back blank: the generation prompt the user had just written
 * for the clip, and the character references sitting next to it, were gone the
 * moment the clip was covered. The prompt box reads the selected window, so it
 * emptied out in front of them.
 *
 * These helpers keep the two concerns apart. A window's position in the clip
 * (start/length) is the layout and is always replaced; everything else belongs
 * to the window and is carried over.
 */

import { isGeneratedRow } from "./minimax_segment_kind.mjs?boot=generated_rows_v1";

/**
 * What a window owns, as opposed to where it sits in the clip. Mirrors the
 * payload the new-window factory initialises: anything it blanks out is content
 * by definition, otherwise a window would have no field to hold it.
 */
export const SEGMENT_CONTENT_KEYS = Object.freeze([
    "prompt",
    "negativePrompt",
    "taskType",
    "refs",
    "refAudios",
    "refVideos",
    "referenceVideo",
    "genImage",
    "contextLink",
]);

/** Deep copy a payload value so sibling windows never share one array. */
function cloneSegmentValue(value) {
    if (value === null || typeof value !== "object") return value;
    if (typeof structuredClone === "function") {
        try {
            return structuredClone(value);
        } catch (_err) {
            // Segment payloads are plain data, but a live handle can sneak into
            // one. Fall through rather than losing the field entirely.
        }
    }
    try {
        return JSON.parse(JSON.stringify(value));
    } catch (_err) {
        return value;
    }
}

/**
 * Copy `source`'s content onto `target`. Layout (id/start/length/frameCount) and
 * the replace recipe are left alone - the caller owns those.
 *
 * Values are cloned per window on purpose: the per-window editors mutate
 * `seg.refs` and friends in place, and shared arrays would make one window's
 * edit silently rewrite its siblings.
 *
 * @returns {boolean} whether anything was carried.
 */
export function carrySegmentContent(target, source) {
    if (!target || !source) return false;
    let carried = false;
    for (const key of SEGMENT_CONTENT_KEYS) {
        if (!Object.prototype.hasOwnProperty.call(source, key)) continue;
        target[key] = cloneSegmentValue(source[key]);
        carried = true;
    }
    return carried;
}

/**
 * Which existing window a rebuilt window inherits its content from.
 *
 * Re-cutting to the same number of windows is the same windows laid out again,
 * so each one keeps what it had. Any other count is a different cut - there is
 * no positional mapping left, and the clip collapses to a single recipe taken
 * from the first window, which is the window the replace config already
 * templates from.
 *
 * @returns {object|null} the window to inherit from, or null when there is none.
 */
export function contentSourceForWindow(previous, index, windowCount) {
    if (!Array.isArray(previous) || previous.length === 0) return null;
    if (previous.length === windowCount) return previous[index] || null;
    return previous[0] || null;
}

/**
 * Which mask source a window should actually use.
 *
 * The per-window selector stores `frames` for anything that is not `sam3`, so a
 * window that never touched the control read back as "PNG mask folder" with no
 * folder set. That is not a preference, it is a guaranteed fallback:
 * `prepare_replace_window` cannot load a mask, so Character Replace quietly
 * degrades to plain video-to-video and only says so at the very end of the run,
 * after every segment has been paid for.
 *
 * A missing kind is therefore read from what is actually configured. A folder
 * means the user meant the file route; no folder at all means the file-free
 * SAM3 route is the only one that can work. An explicit `frames` is left alone -
 * that is a real choice, and the pre-flight validator reports the empty folder.
 *
 * @param {object|null|undefined} mask a replace mask (or a flat cfg with
 *     `kind` / `dir`, which is what the per-window editor hands over).
 * @returns {"frames"|"sam3"}
 */
export function normalizeMaskKind(mask) {
    const raw = String((mask && mask.kind) || "").trim().toLowerCase();
    if (raw === "sam3") return "sam3";
    if (raw === "frames") return "frames";
    return String((mask && mask.dir) || "").trim() ? "frames" : "sam3";
}

/**
 * How many windows will actually run Character Replace.
 *
 * The panel header reports coverage (do the windows tile the clip?), which is a
 * different question. Coverage can read 100% while every window has the
 * per-window switch off, in which case the engine never engages and the run is
 * plain video-to-video. Counting the switches is what the badge needs.
 *
 * @returns {{on: number, total: number, all: boolean, none: boolean}}
 */
export function replaceEnabledCount(segments) {
    const list = Array.isArray(segments) ? segments : [];
    let on = 0;
    for (const seg of list) {
        if (seg && seg.replace && seg.replace.enabled) on += 1;
    }
    return {
        on,
        total: list.length,
        all: list.length > 0 && on === list.length,
        none: list.length > 0 && on === 0,
    };
}

/**
 * Split a replace job's rows into the two kinds it can hold.
 *
 * A *window* edits a range of the source video. A *generated* row has no source
 * range at all and renders from its prompt and references (the H3 source-free
 * tasks), which is how a chain continues past the end of the footage or breaks
 * away from it in the middle.
 *
 * Every count and readout in the panel has to go through this: "how many
 * windows" and "how much of the source is covered" are questions about the
 * windows alone, and answered over the whole list they over-report by exactly
 * the generated rows.
 *
 * @returns {{windows: object[], generated: object[]}}
 */
export function splitReplaceRows(segments) {
    const windows = [];
    const generated = [];
    for (const seg of Array.isArray(segments) ? segments : []) {
        if (!seg || typeof seg !== "object") continue;
        (isGeneratedRow(seg) ? generated : windows).push(seg);
    }
    return { windows, generated };
}

/** Frames of the source the replace windows actually cover (windows only). */
export function coverageFrames(segments, total) {
    const limit = Math.max(0, parseInt(total, 10) || 0);
    let sum = 0;
    for (const seg of splitReplaceRows(segments).windows) {
        const start = Math.max(0, parseInt(seg.start, 10) || 0);
        const length = Math.max(0, parseInt(seg.length ?? seg.frameCount, 10) || 0);
        sum += limit > 0 ? Math.min(Math.max(0, limit - start), length) : length;
    }
    return sum;
}

/**
 * Frames the generated rows add to the export.
 *
 * They are additive: the output is the rows in list order, so a generated row
 * makes the finished clip longer than the source instead of replacing part of it.
 */
export function generatedFrames(segments) {
    let sum = 0;
    for (const seg of splitReplaceRows(segments).generated) {
        sum += Math.max(0, parseInt(seg.length ?? seg.frameCount, 10) || 0);
    }
    return sum;
}

/**
 * Put the generated rows back where they were after a long-form re-cut.
 *
 * "Long-form replace - cover whole clip" rebuilds the window list from the plan,
 * so a generated row - which is not part of the window layout and cannot be
 * derived from it - was simply gone. Each one is remembered by how many windows
 * preceded it, which survives a window count change (the row stays in the same
 * relative place, and lands at the end when the new cut is shorter).
 *
 * @param {object[]} newWindows the re-cut window list, in order
 * @param {object[]} previous the row list before the re-cut
 * @returns {object[]} the rows to store, in order
 */
export function reinsertGeneratedRows(newWindows, previous) {
    const windows = Array.isArray(newWindows) ? newWindows : [];
    const byWindowIndex = new Map();
    let seen = 0;
    for (const seg of Array.isArray(previous) ? previous : []) {
        if (!seg || typeof seg !== "object") continue;
        if (!isGeneratedRow(seg)) {
            seen += 1;
            continue;
        }
        const at = Math.min(seen, windows.length);
        if (!byWindowIndex.has(at)) byWindowIndex.set(at, []);
        byWindowIndex.get(at).push(seg);
    }
    const rows = [];
    for (let i = 0; i <= windows.length; i += 1) {
        for (const seg of byWindowIndex.get(i) || []) rows.push(seg);
        if (i < windows.length) rows.push(windows[i]);
    }
    return rows;
}
