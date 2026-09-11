// Resume intent — the `resumeRun` block the frontend attaches to the timeline
// and the engine reads back in director/plan.py::_resume_from_index.
//
// `from` is a 0-BASED segment index. Both values are meaningful and they are
// easy to confuse:
//
//   from: 0     -> "re-render from segment 1 (S1)" — an explicit choice
//   from: null  -> "no explicit choice, let the engine pick the resume point
//                  from the on-disk segment caches"
//
// That ambiguity is why this module exists. A <select> whose value matches no
// <option> reports "" (not null), and `Number("")` is 0 (not NaN), so the
// obvious inline coercion quietly turns "no explicit choice" into "re-render
// from S1". Every parse here keeps a genuine 0 and rejects a blank.
//
// Reported symptom (2026-09-11): the resume dialog's cache check reported the
// prefix as usable, but the queued prompt carried
// `resumeRun {enabled: true, from: 0}` and the run restarted at segment 1.

/** The <option> that means "clear the caches and start over". */
export const RESUME_START_FRESH = "fresh";

/**
 * Coerce a UI value into a resume index.
 *
 * @returns {number|null} a non-negative integer, or null for "engine decides".
 */
export function parseResumeIndex(value) {
    // Only primitives are accepted. `Number()` is far too eager for this job:
    // it turns "" into 0, [] into 0 and true into 1, and each of those would
    // otherwise be read as a deliberate start segment.
    if (typeof value === "number") {
        return Number.isFinite(value) && value >= 0 ? Math.floor(value) : null;
    }
    if (typeof value !== "string") return null;
    const text = value.trim();
    // A blank string is an *absent* choice, not segment 0.
    if (text === "" || text === RESUME_START_FRESH) return null;
    const parsed = Number(text);
    return Number.isFinite(parsed) && parsed >= 0 ? Math.floor(parsed) : null;
}

/**
 * Build the `resumeRun` payload written onto `timeline`.
 *
 * @param {{resume?: boolean, from?: unknown}} intent
 */
export function buildResumeRun({ resume = false, from = null } = {}) {
    if (!resume) return { enabled: false, from: null };
    return { enabled: true, from: parseResumeIndex(from) };
}

/**
 * Choose a value a <select> will actually accept.
 *
 * Assigning `.value` on a <select> is a no-op when no <option> carries that
 * value; the element then reports "" and the UI silently disagrees with the
 * state it is showing. This picks a value that is guaranteed to be present.
 *
 * @param {unknown} desired   what we would like to select
 * @param {unknown[]} choices the values actually rendered as options
 * @param {unknown} fallback  preferred stand-in when `desired` is unavailable
 * @returns {string} a member of `choices` (or "" when there are none)
 */
export function resolveSelectChoice(desired, choices, fallback = null) {
    const list = Array.isArray(choices) ? choices.map((entry) => String(entry)) : [];
    if (list.length === 0) return "";
    const wanted = desired == null ? null : String(desired);
    if (wanted != null && list.includes(wanted)) return wanted;
    const spare = fallback == null ? null : String(fallback);
    if (spare != null && list.includes(spare)) return spare;
    return list[0];
}
