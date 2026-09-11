// Wiring contract for the multi-seed sweep.
//
// `minimax_seed_sweep.mjs` is unit tested on its own. The integration risks are:
// that a sweep fails to force `resume: false` (every take would then reuse take 1's
// caches and come out identical, at full GPU cost), that the user's seed is left
// clobbered by the last take, and that the queueing path is duplicated instead of
// shared with the normal run.

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

// --- module + UI ---------------------------------------------------------------

assert.ok(source.includes('} from "./minimax_seed_sweep.mjs";'), "sweep module must be imported");
assert.ok(source.includes('data-r="sweep-takes"'), "output bar needs a take-count control");
assert.ok(source.includes('data-r="sweep-seeds"'), "output bar needs a seed-list control");
assert.ok(source.includes('data-a="sweep-run"'), "output bar needs a Sweep button");
assert.ok(source.includes("bind('[data-a=\"sweep-run\"]', () => this.startSeedSweepRun());"));
assert.ok(i18n.includes('"sweep.takes"'), "the take label needs both languages");
assert.equal((i18n.match(/"sweep\.takes"/g) || []).length, 2, "zh + en");

// --- the sweep must not be a no-op -----------------------------------------------

const sweepBody = slice("    _startSeedSweep(seeds) {", "    _queueRunWithIntent({");

// The single most important line in this feature: without resume: false every take
// reuses take 1's segment caches and the sweep renders N identical videos.
assert.ok(
    sweepBody.includes("this._queueOnce({ resume: false, from: null })"),
    "every take must force resume: false or the sweep is a no-op",
);
assert.ok(
    !/resume:\s*true/.test(sweepBody),
    "a sweep must never resume",
);

// One queue call per seed, and the seed is stamped immediately before it.
assert.ok(sweepBody.includes("for (const seed of seeds)"), "one take per seed");
assert.ok(
    sweepBody.indexOf("seedWidget.value = seed;") < sweepBody.indexOf("this._queueOnce({"),
    "the seed must be stamped before the queue call",
);

// The user's seed must survive the sweep.
assert.ok(sweepBody.includes("const originalSeed = seedWidget.value;"), "capture the user's seed");
assert.ok(sweepBody.includes("seedWidget.value = originalSeed;"), "restore the user's seed");

// --- queueing is shared, not duplicated ------------------------------------------

const onceBody = slice("    _queueOnce({ resume = false, from = null } = {}) {", "    /**\n     * Read the sweep controls");
assert.ok(onceBody.includes("app.queuePrompt();"), "_queueOnce owns the queue call");
assert.ok(
    onceBody.includes("this.commit(true, { syncTimeline: false });"),
    "_queueOnce flushes the timeline before queueing",
);
// The normal path must still queue exactly once, through the same helper contract.
const runBody = slice("    _queueRunWithIntent({", "    resumeDirectorRun() {");
assert.equal(
    (runBody.match(/app\.queuePrompt\(\)/g) || []).length,
    1,
    "the normal path still queues exactly once",
);
assert.ok(runBody.includes("const sweepSeeds = Array.isArray(sweep) ? sweep : null;"));
assert.ok(runBody.includes("isSweepActive(sweepSeeds.length)"), "a one-take sweep stays a normal run");

// --- UI guards -------------------------------------------------------------------

const uiBody = slice("    startSeedSweepRun() {", "    _queueRunWithIntent({");
assert.ok(uiBody.includes("this._isRunActive()"), "must not sweep while a run is active");
assert.ok(uiBody.includes("parseSeedList(rawList)"), "seed lists go through the tested parser");
assert.ok(uiBody.includes("expandSeedSweep({"), "expansion goes through the tested function");
assert.ok(
    uiBody.includes("!parsed.seeds.length"),
    "an unusable seed list must be reported, not silently replaced with derived seeds",
);
assert.ok(uiBody.includes("this._queueRunWithIntent({ sweep: expansion.seeds });"));

// --- lifecycle -------------------------------------------------------------------

const inactiveBody = slice("    _onRunInactive() {", "    setRunProgress(detail) {");
assert.ok(inactiveBody.includes("this._sweepQueued = null;"), "sweep state must clear when a run ends");

console.log("minimax_seed_sweep_wiring.test.mjs OK");
