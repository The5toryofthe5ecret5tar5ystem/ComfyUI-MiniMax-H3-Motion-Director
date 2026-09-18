import assert from "node:assert/strict";
import fs from "node:fs";

import {
    normalizeMaskKind,
    replaceEnabledCount,
} from "../minimax_replace_layout_core.mjs";

// Two traps these helpers exist to close.
//
// 1. Mask source. The per-window selector wrote `frames` for anything that was
//    not `sam3`, so a window that never touched the control came back claiming a
//    PNG mask folder with no folder set. `prepare_replace_window` cannot load a
//    mask from that, returns None, and the window silently renders as plain
//    rv2v - reported only at the end of the run, after every segment was paid
//    for. A missing kind must therefore be read from what is configured.
//
// 2. Enabled count. The header badge reported coverage, which stays at 100% with
//    every window switched off, so the panel read as engaged while the backend
//    never engaged at all. Counting the switches is a different question.

// --- normalizeMaskKind ---------------------------------------------------

assert.equal(normalizeMaskKind({ kind: "sam3" }), "sam3", "explicit sam3 is kept");
assert.equal(normalizeMaskKind({ kind: "frames" }), "frames", "explicit frames is kept");

// An explicit `frames` with no folder is a real (broken) choice, not something to
// silently reinterpret - the pre-flight validator reports it instead.
assert.equal(
    normalizeMaskKind({ kind: "frames", dir: "" }),
    "frames",
    "an explicit frames kind is never reinterpreted",
);

// The regression: no kind at all, nothing configured.
assert.equal(normalizeMaskKind({}), "sam3", "no kind and no folder falls back to sam3");
assert.equal(normalizeMaskKind(null), "sam3", "a missing mask falls back to sam3");
assert.equal(normalizeMaskKind(undefined), "sam3", "an undefined mask falls back to sam3");

// But a folder means the file route was the intent, even without an explicit kind.
assert.equal(
    normalizeMaskKind({ dir: "/mnt/masks/scene-1" }),
    "frames",
    "a configured folder keeps legacy frames behaviour",
);
assert.equal(
    normalizeMaskKind({ kind: "frames", dir: "/mnt/masks/scene-1" }),
    "frames",
    "kind and folder together stay on the file route",
);

// Whitespace is not configuration.
assert.equal(
    normalizeMaskKind({ dir: "   " }),
    "sam3",
    "a blank folder is not a configured folder",
);
assert.equal(normalizeMaskKind({ kind: "  SAM3  " }), "sam3", "kind is case and space tolerant");
assert.equal(normalizeMaskKind({ kind: "none" }), "sam3", "an unknown kind is not frames");
assert.equal(
    normalizeMaskKind({ kind: "none", dir: "/tmp/x" }),
    "frames",
    "an unknown kind with a folder resolves to frames",
);

// --- replaceEnabledCount -------------------------------------------------

const on = { replace: { enabled: true } };
const off = { replace: { enabled: false } };

assert.deepEqual(
    replaceEnabledCount([on, on, on]),
    { on: 3, total: 3, all: true, none: false },
    "every window on reads as all",
);
assert.deepEqual(
    replaceEnabledCount([on, off]),
    { on: 1, total: 2, all: false, none: false },
    "a partial list is neither all nor none",
);
assert.deepEqual(
    replaceEnabledCount([off, off]),
    { on: 0, total: 2, all: false, none: true },
    "no window on must be reported as none so the badge can say so",
);
assert.deepEqual(
    replaceEnabledCount([]),
    { on: 0, total: 0, all: false, none: false },
    "an empty timeline is not 'none enabled', it is nothing to report",
);
assert.deepEqual(
    replaceEnabledCount(null),
    { on: 0, total: 0, all: false, none: false },
    "a missing timeline must not throw",
);

// Windows without a replace block at all are simply off, not a crash.
assert.deepEqual(
    replaceEnabledCount([{}, { replace: null }, { replace: { enabled: true } }]),
    { on: 1, total: 3, all: false, none: false },
    "windows with no replace block count as off",
);

// Truthiness, not strict identity, so the badge agrees with the engine: the
// backend gate is `getattr(replace_spec, "enabled", False)` in a Python `and`,
// which is true for 1 as well. A badge that disagreed with the gate would be
// worse than no badge.
assert.deepEqual(
    replaceEnabledCount([{ replace: { enabled: 1 } }, { replace: { enabled: true } }]),
    { on: 2, total: 2, all: true, none: false },
    "a truthy enabled value must count, matching the engine's read",
);

// --- the sam3 default prompt, and the window that has none -------------------
// A window with no explicit prompt used to be written as `sam_prompts: []`, so
// the engine fell back to its own default and could ground nothing at all. Since
// normalizeMaskKind() now defaults an unconfigured window to sam3, that path is
// the common one rather than an edge case.

const timelineSrc = fs.readFileSync(new URL("../minimax_timeline.js", import.meta.url), "utf8");

const defaultDecl = timelineSrc.match(/const DEFAULT_SAM3_PROMPT = "([^"]*)";/);
assert.ok(defaultDecl, "DEFAULT_SAM3_PROMPT must still be declared");
const defaultPrompt = defaultDecl[1];
assert.equal(defaultPrompt, "the woman", "the default must match the proven standalone tool");
assert.ok(
    defaultPrompt.split(/\s+/).length <= 3,
    "the default must stay a short noun phrase; a long descriptive clause can describe "
    + "a configuration the subject is not in, which grounds nothing",
);
for (const clause of ["full body", "head to toe", "every strand"]) {
    assert.ok(
        !defaultPrompt.includes(clause),
        `the default must not demand "${clause}" - that is what broke it`,
    );
}

assert.match(
    timelineSrc,
    /sam_prompts: kind === "sam3" \? \[prompt \|\| DEFAULT_SAM3_PROMPT\] : \[\],/,
    "a sam3 window must never carry an empty prompt list",
);

console.log("replace mask-source and enabled-count tests passed");
