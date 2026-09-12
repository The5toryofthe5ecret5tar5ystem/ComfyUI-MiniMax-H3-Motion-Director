// Never-spoken guard for the shared prompt block.
//
// H3 generates video AND audio from the same text. The shared block is reference
// material - subject_definitions, Camera, Scene, Audio rules - but nothing in it
// is marked as non-voiceable, so a bare trigger token or a quoted phrase sitting
// there is a shape the audio path can read aloud. TALK-CONTROL only governs the
// shot's own <d> lines, which sit after the block.
//
// The guard is a marker line appended to the block, plus a warning for content
// that is especially likely to be voiced.
//
// The helper methods are self-contained, so rather than asserting on source text
// this lifts them into a harness and exercises the real behaviour.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const source = readFileSync(join(repoRoot, "web", "js", "minimax_timeline.js"), "utf8");

/** A class method body, found structurally (class members sit at 4 spaces). */
function methodSource(signature) {
    const start = source.indexOf(signature);
    assert.ok(start !== -1, `missing method: ${signature}`);
    const rest = source.slice(start);
    const boundary = rest.slice(1).search(/\n {4}[A-Za-z_$#]/);
    assert.ok(boundary !== -1, `no following member after ${signature}`);
    return rest.slice(0, boundary + 1);
}

/** Evaluate a top-level `const NAME = ...;` and return its value. */
function constValue(name) {
    const start = source.indexOf(`const ${name} =`);
    assert.ok(start !== -1, `missing const ${name}`);
    const end = source.indexOf(";", start);
    assert.ok(end !== -1, `unterminated const ${name}`);
    return new Function(`${source.slice(start, end + 1)}\nreturn ${name};`)();
}

const MARKER = constValue("SHARED_SILENCE_MARKER");

// --- a harness built from the real methods -----------------------------------

const Harness = new Function("SHARED_SILENCE_MARKER", `
    return class SharedBlockHarness {
        ${methodSource("_sharedBlockHasMarker(text) {")}
        ${methodSource("_withSilenceMarker(text) {")}
        ${methodSource("_sharedBlockVoiceRisks(text) {")}
        ${methodSource("_splitPromptSharedShot(prompt) {")}
    };
`)(MARKER);

const h = new Harness();

// --- the marker --------------------------------------------------------------

assert.ok(/SHARED-BLOCK-CONTROL:/.test(MARKER), "marker must carry its control label");
assert.ok(/never\b.*\bvoiced/i.test(MARKER), "marker must state the content is not voiced");
assert.ok(/<d>/.test(MARKER), "marker must point at the only voiced content");

assert.equal(h._sharedBlockHasMarker("no marker here"), false);
assert.equal(h._sharedBlockHasMarker(MARKER), true);

// appended once, at the end
const guarded = h._withSilenceMarker("subject_definitions:\n<Picture 1> is her face.");
assert.ok(guarded.endsWith(MARKER), "marker should be appended at the end");
assert.ok(guarded.startsWith("subject_definitions:"), "original text must be preserved");

// idempotent - applying twice must not double the marker
const twice = h._withSilenceMarker(guarded);
assert.equal(twice, guarded, "marker must not be appended twice");
assert.equal(guarded.split("SHARED-BLOCK-CONTROL:").length - 1, 1, "exactly one marker");

// never add a marker to an empty block
assert.equal(h._withSilenceMarker(""), "");
assert.equal(h._withSilenceMarker("   \n  "), "");

// --- voiceable-content detection ---------------------------------------------

assert.deepEqual(h._sharedBlockVoiceRisks("subject_definitions:\n<Picture 1> is her face."), [],
    "plain reference text should be clean");

assert.ok(h._sharedBlockVoiceRisks('trigger: "say my name"').length > 0, "quoted phrase flagged");
assert.ok(h._sharedBlockVoiceRisks("she says: welcome in").length > 0, "speech verb flagged");
assert.ok(h._sharedBlockVoiceRisks("<d>hello</d>").length > 0, "<d> block flagged");
assert.ok(h._sharedBlockVoiceRisks("she whispers: come here").length > 0, "whispers flagged");

// the marker itself must not be reported as a risk
assert.deepEqual(h._sharedBlockVoiceRisks(guarded),
    h._sharedBlockVoiceRisks(guarded.replace(MARKER, "").trim()),
    "the appended marker must not raise a risk by itself");

// --- the split the guard depends on ------------------------------------------

const withSummary = h._splitPromptSharedShot("subject_definitions:\nX\nsummary:\nshot body");
assert.equal(withSummary.shared, "subject_definitions:\nX");
assert.equal(withSummary.shot, "summary:\nshot body");

const noSummary = h._splitPromptSharedShot("just a body with no summary line");
assert.equal(noSummary.shared, "", "no bare summary: line means no shared block");
assert.equal(noSummary.shot, "just a body with no summary line");

// `summary:` must be a bare line - one with trailing text is not the boundary
const inline = h._splitPromptSharedShot("summary: same line text");
assert.equal(inline.shared, "", "an inline summary: must not split the prompt");

// --- wiring ------------------------------------------------------------------

const apply = methodSource("_applySharedBlock(newShared, segments, matching, appendGuard) {");
assert.ok(/appendGuard !== false/.test(apply),
    "guarding must be the default when the flag is absent");
assert.ok(/_withSilenceMarker\(next\)/.test(apply),
    "the guard must be applied to the block being written");

const editor = methodSource("_renderSharedBlockEditor(shared, segments) {");
assert.ok(/guard\.checked = true/.test(editor), "the guard checkbox must default to on");
assert.ok(/guard\.checked\)/.test(editor), "the checkbox state must reach _applySharedBlock");
assert.ok(/mmx-sb-guard/.test(editor), "the checkbox must be rendered into the dialog");
assert.ok(/_sharedBlockVoiceRisks/.test(editor), "risks must be surfaced in the dialog");

const css = source.slice(source.indexOf(".mmx-sb-guard{"));
assert.ok(css.startsWith(".mmx-sb-guard{"), "guard styles must be defined");
assert.ok(/\.mmx-sb-risk\{/.test(css), "risk styles must be defined");

console.log("OK  never-spoken shared block guard");
