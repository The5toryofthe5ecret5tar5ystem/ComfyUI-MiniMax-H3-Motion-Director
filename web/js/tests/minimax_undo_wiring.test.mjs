// Wiring contract for timeline undo/redo + the mirror-integrity guard.
//
// `minimax_undo_buffer.mjs` is unit tested on its own. These assertions guard the
// integration into the 12k-line editor, where the risk is that a future edit
// quietly drops the recording hook or lets the keyboard handler steal Ctrl+Z from
// a text field.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const source = readFileSync(join(repoRoot, "web", "js", "minimax_timeline.js"), "utf8");
const i18n = readFileSync(join(repoRoot, "web", "js", "minimax_i18n.js"), "utf8");

function slice(startMarker, endMarker) {
    const start = source.indexOf(startMarker);
    assert.ok(start !== -1, `missing marker: ${startMarker}`);
    const end = source.indexOf(endMarker, start);
    assert.ok(end !== -1, `missing end marker after ${startMarker}: ${endMarker}`);
    return source.slice(start, end);
}

// --- commit() is the single recording funnel ---------------------------------

assert.ok(
    source.includes('} from "./minimax_undo_buffer.mjs";'),
    "undo buffer module must be imported",
);

// Both commit branches (mixed and classic) must record.
assert.equal(
    (source.match(/this\._recordUndoSnapshot\(\);/g) || []).length,
    2,
    "commit must record in the mixed AND classic branches",
);

const commitBody = slice("    commit(skipRender = false, { syncTimeline = true } = {}) {", "\n    normalizeSegments() {");
assert.ok(
    commitBody.includes("this._recordUndoSnapshot();"),
    "commit must record a snapshot",
);
assert.ok(
    commitBody.lastIndexOf("this._recordUndoSnapshot();")
        > commitBody.lastIndexOf("refreshDirectorContinuityUi(this.node, this);"),
    "the classic path must record last, after the timeline is normalised",
);

// --- restore must not create history ----------------------------------------

const applyBody = slice("    _applyUndoSnapshot(snapshot) {", "    /** Reflect history availability");
assert.ok(applyBody.includes("buffer.suppress(() =>"), "applying a snapshot must be suppressed");
assert.ok(applyBody.includes("this.commit(true, { syncTimeline: true });"), "restore repaints without re-sampling");

// --- keyboard -----------------------------------------------------------------

const keysBody = slice("    installUndoTimelineKeys() {", "    disposeUndoTimelineKeys() {");
assert.ok(keysBody.includes("isTextEntryTarget(target)"), "must not fight text-field undo");
assert.ok(keysBody.includes("isUndoShortcut(event)"), "must share the shortcut rules with the tests");
assert.ok(
    keysBody.includes("this.root.contains?.(target)") && keysBody.includes("this.container.contains?.(target)"),
    "must be scoped to events inside this editor, not global",
);
assert.ok(
    source.includes("this.installUndoTimelineKeys();"),
    "the keyboard handler must be installed during init",
);
assert.ok(
    source.includes("disposeUndoTimelineKeys()"),
    "there must be a way to unbind the window listener",
);
assert.ok(
    source.includes("window.removeEventListener(\"keydown\", this._undoKeyHandler, true)"),
    "dispose must actually remove the listener",
);

// --- toolbar discoverability --------------------------------------------------

assert.ok(source.includes('data-a="undo"'), "toolbar needs an undo button");
assert.ok(source.includes('data-a="redo"'), "toolbar needs a redo button");
assert.ok(source.includes("bind('[data-a=\"undo\"]', () => this.undoTimeline());"));
assert.ok(source.includes("bind('[data-a=\"redo\"]', () => this.redoTimeline());"));
assert.ok(source.includes("_syncUndoControls()"), "button state must follow history availability");

for (const key of ["toolbar.undo", "toolbar.redo", "tooltip.undo", "tooltip.redo", "undo.nothingToUndo", "undo.nothingToRedo"]) {
    assert.ok(i18n.includes(`"${key}"`), `missing i18n key: ${key}`);
}

// --- mirror integrity guard ---------------------------------------------------

const writeBody = slice("    _writeTimelineWidget() {", "    _markNodeDirtyLight() {");
assert.ok(
    !writeBody.includes("_checkTimelineMirrorIntegrity"),
    "the guard must NOT run on write: the live widget always lags the saved mirrors",
);
assert.ok(
    /setTimeout\(\(\) => \{ this\._checkTimelineMirrorIntegrity\(\); \}, 0\);/.test(source),
    "the guard must run once at load, after configure has restored the mirrors",
);

const guardBody = slice("    _checkTimelineMirrorIntegrity() {", "    commit(skipRender = false");
assert.ok(guardBody.includes("compareTimelineMirrors({"), "guard must use the tested comparison");
assert.ok(guardBody.includes("widgets_values_named?.timeline_data"), "guard must read the named mirror");
assert.ok(guardBody.includes("state.timeline_data"), "guard must read the properties mirror");
assert.ok(
    !guardBody.includes("live:"),
    "the live widget must never be compared as a mirror (false-positive regression)",
);
assert.ok(guardBody.includes('severity: "error"'), "drift must surface as a visible issue, not a silent warn");
assert.ok(guardBody.includes("this._lastMirrorWarning"), "drift must be de-duplicated");

// A guard that fires on a missing property bag would spam every old workflow.
assert.ok(
    guardBody.includes("if (!state || typeof state !== \"object\") return null;"),
    "guard must no-op when the mirror was never written",
);

console.log("minimax_undo_wiring.test.mjs OK");
