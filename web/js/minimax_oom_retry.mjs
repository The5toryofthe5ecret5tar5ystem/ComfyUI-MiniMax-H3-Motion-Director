/** Turn the engine's VRAM failure report into the retries the run panel offers.
 *
 * The backend emits a structured `minimax_motion_director_oom` payload (stage,
 * failing segment, shape, free memory, and the same suggestions the pre-flight
 * check would print). This module is the pure half: it decides which of those
 * suggestions is actionable from the UI, and what each button should say. Kept
 * apart from the editor so it can be tested without a DOM - the parsing is the
 * part that silently rots when the wording of a suggestion changes.
 */

/** Suggestion text -> the retry it enables. Order matters: the first frames
 * suggestion is the tier's cap, which is the one worth offering. */
const FRAMES_PATTERNS = [
    /at most (\d+) frames/,
    /default is (\d+) frames/,
];
const REF_SIZE_PATTERN = /reference size to (\d+) px/;

/**
 * @param {object|null} info  the engine payload (`shape`, `suggestions`, segment indices)
 * @param {(key: string, values?: object) => string} t  translator
 * @returns {{title: string, index: number, label: string, actions: Array<object>}|null}
 */
export function oomRetryActions(info, t) {
    if (!info || typeof info !== "object") return null;
    const shape = info.shape && typeof info.shape === "object" ? info.shape : {};
    const rawIndex = info.timeline_segment_index ?? info.segment_index;
    const index = Number(rawIndex);
    const label = Number.isFinite(index) && index >= 0
        ? `S${index + 1}`
        : String(shape.label || "");
    const actions = [];
    let framesOffered = false;

    for (const suggestion of Array.isArray(info.suggestions) ? info.suggestions : []) {
        const text = String(suggestion || "");
        if (!framesOffered && Number.isFinite(index) && index >= 0) {
            for (const pattern of FRAMES_PATTERNS) {
                const match = pattern.exec(text);
                const frames = Number(match?.[1]);
                if (match && Number.isFinite(frames) && frames > 0) {
                    actions.push({
                        kind: "frames",
                        index,
                        value: frames,
                        label: t("run.oomRetryFrames", { segment: label, frames: match[1] }),
                        note: "",
                    });
                    framesOffered = true;
                    break;
                }
            }
        }
        const edge = REF_SIZE_PATTERN.exec(text);
        const edgePx = Number(edge?.[1]);
        if (edge && Number.isFinite(edgePx) && edgePx > 0) {
            actions.push({
                kind: "ref_size",
                value: edgePx,
                label: t("run.oomRetryRefSize", { px: edge[1] }),
                note: t("run.oomProjectWide"),
            });
        }
    }

    if (!label && !actions.length) return null;
    // The engine lists its advice in order of how little it changes the picture,
    // which puts the reference size first. For retry buttons the *local* change
    // belongs first instead: an edited segment length touches the failed row,
    // while the reference size is a node-level setting. Stable sort, so multiple
    // suggestions of the same kind keep the engine's order.
    actions.sort((left, right) => {
        if (left.kind === right.kind) return 0;
        return left.kind === "frames" ? -1 : 1;
    });
    return {
        title: t("run.oomTitle", { segment: label || "?" }),
        index: Number.isFinite(index) ? index : -1,
        label,
        actions,
    };
}
