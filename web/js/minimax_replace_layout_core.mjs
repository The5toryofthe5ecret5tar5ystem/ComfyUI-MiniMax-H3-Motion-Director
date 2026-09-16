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
