// Undo/redo history + timeline mirror integrity for the Director editor.
//
// `timeline_data` is mirrored into three places and they can silently drift, which
// has caused real project corruption. The buffer and the mirror comparison are
// pure so they are tested here rather than through the 12k-line editor.

import assert from "node:assert/strict";
import {
    canonical,
    compareTimelineMirrors,
    createUndoBuffer,
    isTextEntryTarget,
    isUndoShortcut,
    parseMirror,
} from "../minimax_undo_buffer.mjs";

// ---------------------------------------------------------------------------
// canonical / parseMirror
// ---------------------------------------------------------------------------

assert.equal(canonical({ b: 1, a: 2 }), canonical({ a: 2, b: 1 }), "key order must not matter");
assert.notEqual(canonical({ a: 1 }), canonical({ a: 2 }));
assert.equal(canonical([1, { x: true }]), '[1,{"x":true}]');
assert.equal(canonical(null), "null");
assert.equal(parseMirror("").present, false, "empty string is absent");
assert.equal(parseMirror(null).present, false);
assert.equal(parseMirror(undefined).present, false);
assert.deepEqual(parseMirror('{"a":1}').value, { a: 1 });
assert.equal(parseMirror("{oops").present, true, "present but unparseable");
assert.ok(parseMirror("{oops").error, "unparseable JSON reports an error");

// ---------------------------------------------------------------------------
// Undo buffer
// ---------------------------------------------------------------------------

const buf = createUndoBuffer({ limit: 50 });
buf.reset("A");
assert.equal(buf.canUndo, false);
assert.equal(buf.canRedo, false);

// An identical commit must not create a history entry.
assert.equal(buf.record("A").changed, false);
assert.equal(buf.canUndo, false, "no-op commit must not push history");

assert.equal(buf.record("B").changed, true);
assert.equal(buf.record("C").changed, true);
assert.equal(buf.depth, 2);

assert.equal(buf.undo(), "B");
assert.equal(buf.undo(), "A");
assert.equal(buf.canUndo, false);
assert.equal(buf.undo(), null, "undo past the start is a no-op");

assert.equal(buf.redo(), "B");
assert.equal(buf.redo(), "C");
assert.equal(buf.canRedo, false);
assert.equal(buf.redo(), null, "redo past the end is a no-op");

// A new edit after undoing must drop the redo branch.
buf.record("D");
assert.equal(buf.undo(), "C");
assert.equal(buf.canRedo, true);
buf.record("E");
assert.equal(buf.canRedo, false, "a new edit clears the redo stack");
assert.equal(buf.undo(), "C");

// ---------------------------------------------------------------------------
// Bounding
// ---------------------------------------------------------------------------

const tiny = createUndoBuffer({ limit: 3 });
tiny.reset("0");
for (const value of ["1", "2", "3", "4"]) tiny.record(value);
assert.equal(tiny.depth, 3, "history is bounded by limit");
// Oldest entries are dropped, so undoing 3 times cannot reach "0".
assert.equal(tiny.undo(), "3");
assert.equal(tiny.undo(), "2");
assert.equal(tiny.undo(), "1");
assert.equal(tiny.canUndo, false);

const single = createUndoBuffer({ limit: 0 });
single.reset("a");
single.record("b");
assert.equal(single.depth, 1, "limit below 1 clamps to 1");

// ---------------------------------------------------------------------------
// Suppression (applying a snapshot must not record it)
// ---------------------------------------------------------------------------

const sup = createUndoBuffer();
sup.reset("A");
sup.record("B");
sup.suppress(() => {
    const result = sup.record("A");
    assert.equal(result.suspended, true);
    assert.equal(result.changed, false);
});
assert.equal(sup.depth, 1, "suppressed records must not grow history");
assert.equal(sup.suspended, false, "suppression ends after the callback");
assert.throws(
    () =>
        sup.suppress(() => {
            throw new Error("boom");
        }),
    /boom/,
);
assert.equal(sup.suspended, false, "suppression is released even on throw");

// ---------------------------------------------------------------------------
// reset / clear
// ---------------------------------------------------------------------------

const reset = createUndoBuffer();
reset.reset("A");
reset.record("B");
reset.reset("X");
assert.equal(reset.canUndo, false, "reset clears history");
assert.equal(reset.canRedo, false);
assert.equal(reset.record("X").changed, false, "reset seeds the current value");

const cleared = createUndoBuffer();
cleared.reset("A");
cleared.record("B");
cleared.clear();
assert.equal(cleared.depth, 0);
assert.equal(cleared.current, null);

// ---------------------------------------------------------------------------
// Mirror integrity
// ---------------------------------------------------------------------------

const payload = { segments: [{ start: 0, length: 124 }], replaceMode: false };

// A single mirror cannot disagree with itself.
assert.equal(compareTimelineMirrors({ named: payload }).ok, true);
assert.equal(compareTimelineMirrors({}).ok, true);

// The two persisted copies agreeing is healthy, including when key order differs.
const healthy = compareTimelineMirrors({
    named: payload,
    properties: JSON.stringify({ replaceMode: false, segments: [{ length: 124, start: 0 }] }),
});
assert.equal(healthy.ok, true);
assert.equal(healthy.compared, 2);
assert.equal(healthy.message, "");

// REGRESSION: the live widget is not a mirror. The editor rewrites it during load
// normalisation and on every commit, so a freshly opened healthy workflow always
// has live != the saved snapshots. Treating that as corruption made every reload
// report drift that was not there.
const afterLoadNormalisation = compareTimelineMirrors({
    live: JSON.stringify({ segments: [{ start: 0, length: 141 }], replaceMode: false }),
    named: payload,
    properties: payload,
});
assert.equal(afterLoadNormalisation.ok, true, "live drift between saves is normal");
assert.equal(afterLoadNormalisation.message, "");

// The two persisted copies disagreeing is the real corruption case.
const drifted = compareTimelineMirrors({
    named: payload,
    properties: JSON.stringify({ segments: [{ start: 0, length: 243 }], replaceMode: false }),
});
assert.equal(drifted.ok, false);
assert.deepEqual(drifted.mismatches, ["properties"]);
assert.ok(drifted.message.includes("timeline_data mirrors disagree"));
assert.ok(drifted.message.includes("Save the workflow"), "actionable advice");

// A single persisted mirror is normal on older workflows.
const partial = compareTimelineMirrors({ named: null, properties: payload });
assert.equal(partial.ok, true, "missing mirrors are not a mismatch");
assert.equal(partial.compared, 1);

// Unparseable JSON is reported rather than silently equal.
const broken = compareTimelineMirrors({ named: "{not json", properties: payload });
assert.equal(broken.ok, false);
assert.deepEqual(broken.unreadable, ["named"]);

// ---------------------------------------------------------------------------
// Shortcut handling
// ---------------------------------------------------------------------------

const ev = (over) => ({ key: "z", ctrlKey: false, metaKey: false, shiftKey: false, ...over });
assert.deepEqual(isUndoShortcut(ev({ ctrlKey: true })), { undo: true, redo: false });
assert.deepEqual(isUndoShortcut(ev({ ctrlKey: true, shiftKey: true })), { undo: false, redo: true });
assert.deepEqual(isUndoShortcut(ev({ ctrlKey: true, key: "y" })), { undo: false, redo: true });
assert.deepEqual(isUndoShortcut(ev({ metaKey: true })), { undo: true, redo: false });
assert.deepEqual(isUndoShortcut(ev({})), { undo: false, redo: false }, "bare z is typing");
assert.deepEqual(isUndoShortcut(ev({ ctrlKey: true, key: "a" })), { undo: false, redo: false });
assert.deepEqual(isUndoShortcut(null), { undo: false, redo: false });
assert.deepEqual(
    isUndoShortcut(ev({ ctrlKey: true }), { requireMeta: true }),
    { undo: false, redo: false },
    "macOS-only mode ignores ctrl",
);

assert.equal(isTextEntryTarget({ tagName: "INPUT" }), true);
assert.equal(isTextEntryTarget({ tagName: "textarea" }), true);
assert.equal(isTextEntryTarget({ tagName: "SELECT" }), true);
assert.equal(isTextEntryTarget({ isContentEditable: true }), true);
assert.equal(isTextEntryTarget({ tagName: "DIV" }), false);
assert.equal(isTextEntryTarget(null), false);

console.log("minimax_undo_buffer.test.mjs OK");
