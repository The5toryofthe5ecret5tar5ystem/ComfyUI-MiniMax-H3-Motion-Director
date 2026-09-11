// Portions derived from ComfyUI_MiniMaxH3_Director
// Copyright AIMixer and contributors
// Originally licensed under Apache License 2.0
// Modified for MiniMax H3 Motion Director, 2026-09-07
// This derivative project is distributed under GPL-3.0.
// See NOTICE and LICENSES/Apache-2.0-AIMixer.txt.

/**
 * Undo/redo history and mirror-integrity checks for the Director timeline.
 *
 * Kept free of DOM and ComfyUI imports so it can be unit tested directly, and so
 * the 12k-line `minimax_timeline.js` only has to call into it.
 *
 * Two independent concerns live here:
 *
 * 1. `createUndoBuffer` - a bounded history of serialized timeline snapshots.
 *    Every timeline mutation funnels through the editor's `commit()`, which
 *    records a snapshot; nothing else may push. Snapshots are opaque strings, so
 *    the buffer never has to know the timeline's shape.
 *
 * 2. `compareTimelineMirrors` - the guard for this project's top corruption
 *    vector. `timeline_data` is persisted twice (`widgets_values_named` and
 *    `properties.mmx_director_widget_state`) and the two copies can silently
 *    drift, which is what produced real project breakage twice during the
 *    Tier 0-1 work. This just reports whether they still agree. Only the
 *    *persisted* copies are compared - never the live widget, which is expected
 *    to differ from the saved state between saves.
 */

/** Stable stringify so key order alone never reports a mismatch. */
export function canonical(value) {
    if (value === null || value === undefined) return "null";
    if (typeof value !== "object") return JSON.stringify(value) ?? "null";
    if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
    const keys = Object.keys(value).sort();
    return `{${keys.map((k) => `${JSON.stringify(k)}:${canonical(value[k])}`).join(",")}}`;
}

/** Accepts an already-parsed object or a JSON string; null/"" means "absent". */
export function parseMirror(value) {
    if (value === null || value === undefined) return { present: false, value: null };
    if (typeof value === "object") return { present: true, value };
    if (typeof value !== "string") return { present: false, value: null };
    const text = value.trim();
    if (!text) return { present: false, value: null };
    try {
        return { present: true, value: JSON.parse(text) };
    } catch (error) {
        return { present: true, value: null, error: String(error?.message || error) };
    }
}

/**
 * Compare the two *persisted* `timeline_data` mirrors.
 *
 * Only save-time snapshots belong here. `widgets_values_named` and
 * `properties.mmx_director_widget_state` are both written during `onSerialize`
 * from the same widget values, so a healthy file has them identical. When they
 * disagree the file carries two conflicting copies and the loader's precedence
 * order (`widgets_values_named` wins) silently decides which one you get - that is
 * the corruption this guards against.
 *
 * The *live* widget value is deliberately NOT accepted. The editor normalises the
 * timeline on load and rewrites the widget on every commit, so between saves the
 * live value is expected to differ from the persisted copies. Comparing it made
 * every freshly opened workflow report drift that was not there.
 *
 * A missing mirror is not a mismatch - older files legitimately carry only one.
 */
export function compareTimelineMirrors({ named, properties } = {}) {
    const sources = {
        named: parseMirror(named),
        properties: parseMirror(properties),
    };

    const unreadable = Object.entries(sources)
        .filter(([, entry]) => entry.error)
        .map(([name]) => name);

    const present = Object.entries(sources).filter(([, entry]) => entry.present);
    if (present.length < 2) {
        // Nothing to compare against; a single mirror cannot disagree with itself.
        return { ok: true, compared: present.length, mismatches: [], unreadable, message: "" };
    }

    const [[firstName, firstEntry], ...rest] = present;
    const baseline = canonical(firstEntry.value);
    const mismatches = rest
        .filter(([, entry]) => canonical(entry.value) !== baseline)
        .map(([name]) => name);

    if (!mismatches.length && !unreadable.length) {
        return { ok: true, compared: present.length, mismatches: [], unreadable, message: "" };
    }

    const parts = [];
    if (mismatches.length) {
        parts.push(
            `timeline_data mirrors disagree: ${firstName} differs from ${mismatches.join(", ")}.`,
        );
    }
    if (unreadable.length) {
        parts.push(`unreadable: ${unreadable.join(", ")}.`);
    }
    parts.push("Save the workflow and reload the node before editing further.");

    return {
        ok: false,
        compared: present.length,
        mismatches,
        unreadable,
        baseline: firstName,
        message: parts.join(" "),
    };
}

/**
 * Bounded undo/redo history over opaque snapshots.
 *
 * `record()` is called after every commit with the state that resulted from it.
 * The buffer keeps the *previous* state so `undo()` always returns something to
 * apply. New edits clear the redo stack, which is standard editor behaviour.
 */
export function createUndoBuffer({ limit = 50, isEqual = (a, b) => a === b } = {}) {
    const maxDepth = Math.max(1, Number(limit) || 1);
    let undoStack = [];
    let redoStack = [];
    let current = null;
    let hasCurrent = false;
    let suspended = 0;

    function pushUndo(snapshot) {
        undoStack.push(snapshot);
        // Bound the history: drop the oldest entries.
        while (undoStack.length > maxDepth) undoStack.shift();
    }

    return {
        /** True while `suppress()` is applying a snapshot (so it is not recorded). */
        get suspended() {
            return suspended > 0;
        },

        get canUndo() {
            return undoStack.length > 0;
        },

        get canRedo() {
            return redoStack.length > 0;
        },

        get depth() {
            return undoStack.length;
        },

        get redoDepth() {
            return redoStack.length;
        },

        get current() {
            return current;
        },

        /** Seed the buffer without creating history (load / project open). */
        reset(snapshot = null) {
            undoStack = [];
            redoStack = [];
            current = snapshot;
            hasCurrent = snapshot !== null && snapshot !== undefined;
        },

        /**
         * Record the state produced by a commit.
         * Returns `{ changed, pushed }` so the caller can skip redraws.
         */
        record(snapshot) {
            if (suspended > 0) return { changed: false, pushed: false, suspended: true };
            if (!hasCurrent) {
                current = snapshot;
                hasCurrent = true;
                return { changed: false, pushed: false, seeded: true };
            }
            if (isEqual(snapshot, current)) return { changed: false, pushed: false };
            pushUndo(current);
            current = snapshot;
            redoStack = [];
            return { changed: true, pushed: true, depth: undoStack.length };
        },

        /** Returns the snapshot to apply, or null when there is nothing to undo. */
        undo() {
            if (!undoStack.length) return null;
            const target = undoStack.pop();
            if (hasCurrent) redoStack.push(current);
            current = target;
            hasCurrent = true;
            return target;
        },

        /** Returns the snapshot to apply, or null when there is nothing to redo. */
        redo() {
            if (!redoStack.length) return null;
            const target = redoStack.pop();
            if (hasCurrent) pushUndo(current);
            current = target;
            hasCurrent = true;
            return target;
        },

        /**
         * Run `fn` (typically "apply this snapshot") without recording it, so an
         * undo does not push a new history entry for its own edit.
         */
        suppress(fn) {
            suspended += 1;
            try {
                return fn();
            } finally {
                suspended -= 1;
            }
        },

        clear() {
            undoStack = [];
            redoStack = [];
            current = null;
            hasCurrent = false;
        },
    };
}

/**
 * True when a keyboard event should trigger timeline undo/redo.
 *
 * Ctrl+Z is a global browser/textarea affordance, so this deliberately refuses to
 * fire while the user is typing in a field: undoing someone's text edit is worse
 * than not undoing at all.
 */
export function isUndoShortcut(event, { requireMeta = false } = {}) {
    if (!event) return { undo: false, redo: false };
    const key = String(event.key || "").toLowerCase();
    if (key !== "z" && key !== "y") return { undo: false, redo: false };
    if (!(event.ctrlKey || event.metaKey)) return { undo: false, redo: false };
    if (requireMeta && !event.metaKey) return { undo: false, redo: false };
    const redo = key === "y" || (key === "z" && !!event.shiftKey);
    const undo = !redo && key === "z";
    return { undo, redo };
}

/** Whether a DOM node is a text-entry field that owns Ctrl+Z. */
export function isTextEntryTarget(target) {
    if (!target || typeof target !== "object") return false;
    const tag = String(target.tagName || "").toUpperCase();
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
    return !!target.isContentEditable;
}
