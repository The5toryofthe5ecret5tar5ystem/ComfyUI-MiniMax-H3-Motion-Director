import assert from "node:assert/strict";
import fs from "node:fs";

// "Start run is greyed out with nothing running, and clicking Validate changes
// nothing." The button is disabled purely by the panel's own run flag: it is raised
// when this panel queues a run and dropped by that prompt's end events. It can be
// stranded two ways, and both were seen live (2026-09-21):
//
//   1. a run that died without those events - a ComfyUI restart mid-run, a reload;
//   2. another tab whose graph shares this node's id. Exported workflows carry ids
//      like "dir", and the run manifest is keyed by that id, so the manifest's
//      "running" state can belong to somebody else's job - and the manifest-only
//      reconcile refuses to clear a flag while it says "running".
//
// Validate was innocent: clicking it in a live editor left the flag alone (proved by
// probing the running page). The cure has to come from ComfyUI's own queue, which
// says whether any queued prompt actually contains this node.

const timeline = fs.readFileSync(new URL("../minimax_timeline.js", import.meta.url), "utf8");
const modal = fs.readFileSync(new URL("../minimax_director_modal.js", import.meta.url), "utf8");
const i18n = fs.readFileSync(new URL("../minimax_i18n.js", import.meta.url), "utf8");

function functionBody(source, signature) {
    const at = source.indexOf(signature);
    assert.ok(at > 0, `${signature} must still exist`);
    const bodyStart = source.lastIndexOf("{", at + signature.length - 1);
    let depth = 0;
    for (let i = bodyStart; i < source.length; i += 1) {
        if (source[i] === "{") depth += 1;
        else if (source[i] === "}") {
            depth -= 1;
            if (depth === 0) return source.slice(bodyStart, i + 1);
        }
    }
    throw new Error(`unbalanced braces after ${signature}`);
}

function sliceBetween(source, startMarker, endMarker) {
    const start = source.indexOf(startMarker);
    assert.ok(start > 0, `missing marker: ${startMarker}`);
    const end = source.indexOf(endMarker, start + startMarker.length);
    assert.ok(end > start, `missing end marker after ${startMarker}: ${endMarker}`);
    return source.slice(start, end);
}

// --- the reconcile itself ---------------------------------------------------- //

const reconcile = functionBody(timeline, "async _reconcileRunActive() {");
assert.ok(
    reconcile.includes('api.fetchApi("/queue")'),
    "the tie-breaker must be ComfyUI's own queue, not the shared manifest",
);
assert.ok(reconcile.includes("queue_running") && reconcile.includes("queue_pending"),
    "a prompt that has not started executing yet still belongs to us");
assert.ok(
    /nodeId in graph/.test(reconcile),
    "a queue entry's prompt graph is keyed by node id - that is how 'ours' is decided",
);
assert.ok(
    reconcile.includes('String(api?.clientId ?? "")') && /entry\[3\]\?\.client_id/.test(reconcile),
    "the tab that queued the prompt is the real discriminator: another tab shares the node id",
);
assert.ok(
    /queuedAt && now - queuedAt < 4000/.test(reconcile),
    "the gap between queuePrompt() and the queue entry appearing must not clear the flag",
);
assert.ok(
    reconcile.includes("this._setRunActive(false)"),
    "the stranded flag must actually be cleared",
);
assert.ok(
    /catch \(error\)[\s\S]{0,200}return false/.test(reconcile),
    "a failed probe must keep the flag (never guess a run is over)",
);
assert.ok(reconcile.includes("console.info("),
    "clearing a stranded flag must be visible in the console");

// --- the triggers ------------------------------------------------------------ //

const refresh = functionBody(timeline, "async refreshResumeState() {");
assert.ok(
    refresh.includes("await this._reconcileRunActive();"),
    "the resume-state refresh must reconcile the flag, not just the manifest",
);
assert.ok(
    refresh.indexOf("await this._reconcileRunActive();") < refresh.indexOf("this._syncRunControls"),
    "reconcile first, then paint the buttons",
);

const queue = sliceBetween(timeline, "_queueRunWithIntent({", "resumeDirectorRun() {");
assert.ok(
    queue.includes("this._runQueuedAt = "),
    "queueing must stamp the time the grace window is measured from",
);

// --- Validate reports the run bar (the user's expectation) -------------------- //

const validate = functionBody(timeline, "async validateProject() {");
assert.ok(validate.includes("await this._reconcileRunActive();"),
    "Validate must re-check the run bar, so a stranded flag clears when the user asks");
assert.ok(validate.includes("this._withRunStateNote("),
    "Validate must say whether a run is holding Start run");

const note = functionBody(timeline, "_withRunStateNote(issues) {");
assert.ok(note.includes('t("run.stateBlocked")') && note.includes('t("run.stateIdle")'),
    "the note must distinguish running from idle");
assert.ok(/severity: "info"/.test(note), "it is a report line, not an error");

// --- a greyed button says why ------------------------------------------------- //

const controls = sliceBetween(modal, "setRunControls({", "open() {");
assert.ok(
    controls.includes('translate("run.startBlocked")'),
    "the disabled Start run must explain itself in its tooltip",
);
assert.ok(
    controls.includes("startRunButton.disabled = Boolean(running)"),
    "Start run stays disabled while a run is active",
);

// --- both locales carry the new keys ------------------------------------------ //

for (const key of ["run.startBlocked", "run.stateBlocked", "run.stateIdle"]) {
    const hits = i18n.split(`"${key}"`).length - 1;
    assert.equal(hits, 2, `${key} must exist in both locales`);
}

console.log("run state reconcile: a stranded Start run unblocks and says why");
