// Wiring contract for the named-presets UI.
//
// `minimax_director_presets.mjs` is unit tested on its own. What is worth pinning
// here is the integration: that applying a preset goes through `commit()` (so it
// repaints and is undoable), that continuity is driven through its control rather
// than by writing `timeline.output` directly (which the next commit would discard),
// and that preset names cannot be injected as markup.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const source = readFileSync(join(repoRoot, "web", "js", "minimax_timeline.js"), "utf8");

function slice(startMarker, endMarker) {
    const start = source.indexOf(startMarker);
    assert.ok(start !== -1, `missing marker: ${startMarker}`);
    const end = source.indexOf(endMarker, start);
    assert.ok(end !== -1, `missing end marker after ${startMarker}: ${endMarker}`);
    return source.slice(start, end);
}

// --- imports and entry point --------------------------------------------------

assert.ok(source.includes('} from "./minimax_director_presets.mjs";'), "preset module must be imported");
assert.ok(source.includes('} from "./minimax_director_presets_api.mjs";'), "preset API client must be imported");
assert.ok(source.includes('data-a="presets"'), "output bar needs a Presets button");
assert.ok(source.includes("void this.openPresetsManager();"), "the button must open the manager");
assert.ok(source.includes("async openPresetsManager()"));
assert.ok(source.includes("async _renderPresetsManager()"));
assert.ok(source.includes("_presetRow(record)"));
assert.ok(source.includes("async _savePresetFromCurrent()"));
assert.ok(source.includes("_applyPresetRecord(record)"));

// --- applying ------------------------------------------------------------------

const applyBody = slice("    _applyPresetRecord(record) {", "    _sharedBlockStyle() {");

assert.ok(applyBody.includes("planPresetApply({"), "apply must use the tested planner");
assert.ok(applyBody.includes("this.commit();"), "apply must commit: repaint + undo entry");

// Continuity is owned by the output bar's controls, and the editor re-derives
// timeline.output from them on every commit. Writing the key directly would be
// silently discarded, so the plan must be routed through the controls.
assert.ok(
    applyBody.includes("this.segmentContinuityCb.checked"),
    "continuityEnabled must be applied through its control",
);
assert.ok(
    applyBody.includes("this.segmentContinuityOverlap.value"),
    "continuityOverlapFrames must be applied through its control",
);
assert.ok(
    !applyBody.includes("this.timeline.output ="),
    "apply must not write timeline.output directly",
);

// Widget writes must be keyed by the plan, not by the whole payload.
assert.ok(applyBody.includes("Object.entries(plan.widgets)"), "only planned widgets may be written");
assert.ok(applyBody.includes("widget.value = value;"), "widgets are written by name");
assert.ok(applyBody.includes("plan.r2vCommon"), "shared references are applied only when present");

// --- saving --------------------------------------------------------------------

const saveBody = slice("    async _savePresetFromCurrent() {", "    /**\n     * Apply a preset.");

assert.ok(saveBody.includes("collectPresetPayload({"), "save must use the tested collector");
assert.ok(
    saveBody.includes("includeReferences: !!refsEl?.checked"),
    "capturing references must stay opt-in",
);
assert.ok(saveBody.includes("await createDirectorPreset({ name, payload })"));
assert.ok(
    saveBody.includes("PRESET_WIDGET_NAMES.filter((key) => !(key in widgetValues))"),
    "a preset saved on a node missing widgets should say so",
);

// --- no markup injection -------------------------------------------------------

const rowBody = slice("    _presetRow(record) {", "    async _savePresetFromCurrent() {");
assert.ok(rowBody.includes("name.textContent ="), "preset names must not be injected as markup");
assert.ok(rowBody.includes("formatPresetSummary(record?.payload)"), "rows show the tested summary");
assert.ok(!/innerHTML\s*=\s*[^;]*record\./.test(rowBody), "record data must never reach innerHTML");

// --- delete/rename use the tested API -----------------------------------------

assert.ok(rowBody.includes("await updateDirectorPreset(record.id, { name: trimmed })"));
assert.ok(rowBody.includes("await deleteDirectorPreset(record.id)"));
assert.ok(rowBody.includes("window.confirm("), "delete must confirm");

console.log("minimax_director_presets_wiring.test.mjs OK");
