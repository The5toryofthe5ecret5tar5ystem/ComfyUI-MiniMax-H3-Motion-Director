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
