/**
 * Row kinds on a Director timeline - the frontend twin of lib/segment_kind.py.
 *
 * A replace job's rows are either *replace windows* (a masked edit of a source
 * range) or *generated rows* (no source range at all, rendered from their own
 * prompt and references). Rows written before this existed carry no kind and are
 * replace windows, so nothing needs migrating.
 *
 * Both sides must agree: a row the plan renders source-free must not be clamped
 * to the source total by the UI first, and a row the UI shows as a window must
 * not be planned as source-free.
 */

export const SEGMENT_KIND_REPLACE = "replace";
export const SEGMENT_KIND_GENERATE = "generate";

const GENERATE_VALUES = new Set([
    "generate",
    "generated",
    "gen",
    "generated_segment",
    "generatedsegment",
    // The generated row renders as a source-free reference segment, so the task
    // names are accepted as kind aliases too.
    "ref2va",
    "r2v",
    "r2flv",
    "t2v",
]);

const REPLACE_VALUES = new Set([
    "replace",
    "replace_window",
    "replacewindow",
    "window",
    "masked",
]);

const KIND_KEYS = [
    "kind",
    "segmentKind",
    "segment_kind",
    "rowKind",
    "row_kind",
    "segmentType",
    "segment_type",
];

const GENERATE_FLAGS = ["generate", "generated", "isGenerated", "is_generated"];

/** Kind of a timeline row. Anything unrecognised is a replace window. */
export function segmentKind(raw) {
    if (!raw || typeof raw !== "object") return SEGMENT_KIND_REPLACE;
    for (const key of KIND_KEYS) {
        const value = raw[key];
        if (value === undefined || value === null) continue;
        if (typeof value === "boolean") {
            if (value) return SEGMENT_KIND_GENERATE;
            continue;
        }
        const text = String(value).trim().toLowerCase();
        if (!text) continue;
        if (GENERATE_VALUES.has(text)) return SEGMENT_KIND_GENERATE;
        if (REPLACE_VALUES.has(text)) return SEGMENT_KIND_REPLACE;
    }
    for (const flag of GENERATE_FLAGS) {
        if (raw[flag] === true) return SEGMENT_KIND_GENERATE;
    }
    return SEGMENT_KIND_REPLACE;
}

/** True when a row renders without consuming source pixels. */
export function isGeneratedRow(raw) {
    return segmentKind(raw) === SEGMENT_KIND_GENERATE;
}

/** Un-snapped requested length of a generated row (0 when it has none). */
export function generatedRowLength(raw) {
    if (!raw || typeof raw !== "object") return 0;
    const start = parseInt(raw.start, 10);
    if (raw.end !== undefined && raw.end !== null) {
        const end = parseInt(raw.end, 10);
        if (!Number.isFinite(end)) return 0;
        return Math.max(0, end - (Number.isFinite(start) ? start : 0));
    }
    const raw_length = raw.length !== undefined && raw.length !== null ? raw.length : raw.frameCount;
    const length = parseInt(raw_length, 10);
    return Number.isFinite(length) ? Math.max(0, length) : 0;
}
