import assert from "node:assert/strict";
import fs from "node:fs";

// The Setup panel's rules: baselines are starting points, machine facts come from
// detection, and a workflow that asks for a backend this machine cannot run is
// reported before a render discovers it. Every rule here is pure, so it is pinned
// without a DOM.

const settings = await import("../minimax_motion_settings.mjs");
const i18n = fs.readFileSync(new URL("../minimax_i18n.js", import.meta.url), "utf8");
const ui = fs.readFileSync(new URL("../minimax_settings_ui.mjs", import.meta.url), "utf8");
const timeline = fs.readFileSync(new URL("../minimax_timeline.js", import.meta.url), "utf8");

// --- settings merge ---------------------------------------------------------

const merged = settings.mergeSettings({ baselines: { segment_frames: 362 }, app: { locale: "en" } });
assert.equal(merged.baselines.segment_frames, 362, "a stored value wins");
assert.equal(
    merged.baselines.megapixels,
    settings.defaultSettings().baselines.megapixels,
    "an unstored field keeps the default",
);
assert.equal(merged.app.locale, "en", "nested sections merge independently");
assert.equal(merged.app.preview_audio, true, "and keep their own defaults");
assert.equal(settings.mergeSettings(null).baselines.segment_frames, 243, "no stored file = defaults");

// --- H3 grids ---------------------------------------------------------------

for (const value of [1, 5, 100, 124, 243, 361, 511, 999]) {
    const aligned = settings.alignFramesToGrid(value);
    assert.equal((aligned - 5) % 17, 0, `${value} -> ${aligned} must be on the 17k+5 grid`);
    assert.ok(aligned >= 5 && aligned <= 512, `${value} -> ${aligned} must stay renderable`);
}
assert.equal(settings.alignFramesToGrid(124), 124, "an aligned value is untouched");
assert.equal(settings.alignFramesToGrid(125), 141, "an off-grid value snaps up");
assert.equal(settings.alignFramesToGrid(5000), 498, "past the cap it snaps down to the largest grid value");

// --- baselines --------------------------------------------------------------

const machine = {
    tier: "medium",
    baselines: { megapixels: 0.6, width: 1024, height: 576, segment_frames: 175, max_segment_frames: 243, ref_max_size: 768 },
};
const resolved = settings.resolveBaselines(settings.defaultSettings(), machine);
assert.deepEqual(
    { aspect: resolved.aspectRatio, frames: resolved.segmentFrames, mp: resolved.megapixels },
    { aspect: "16:9", frames: 243, mp: 1.0 },
    "the stored baselines are what run, not the detected ones",
);
assert.equal(resolved.detectedFrames, 175, "the detected tier stays visible for comparison");
assert.equal(resolved.followsDetected, false, "and the difference is reported");

const followDetected = settings.resolveBaselines(
    { baselines: { ...settings.defaultSettings().baselines, segment_frames: 175, megapixels: 0.6 } },
    machine,
);
assert.equal(followDetected.followsDetected, true, "matching the tier reads as following the profile");
assert.equal(followDetected.segmentSeconds, 7.29, "seconds are derived from the frames at 24 fps");

// A baseline can never produce an unrenderable segment.
assert.equal(settings.baselineFrameCount({ segment_frames: 4000 }), 498, "over-long baselines are capped");
assert.equal(settings.baselineFrameCount({ segment_frames: 400 }, { minFrames: 124, maxFrames: 243 }), 243, "the task cap wins");
assert.equal(settings.baselineFrameCount({ segment_frames: 1 }, { minFrames: 124 }), 124, "the task floor wins");
assert.equal(settings.baselineDurationSec({ segment_frames: 243 }), 10.1, "durations follow the frames");

// Aspect labels round-trip through the panel's own label list.
for (const ratio of settings.ASPECT_RATIOS) {
    const label = settings.aspectLabelFromRatio(ratio);
    assert.equal(settings.ratioFromAspectLabel(label), ratio, `${ratio} must round-trip`);
}
assert.equal(settings.ratioFromAspectLabel("自定义"), "16:9", "a custom canvas stores the default ratio");

// The stored ratio list must match the panel's ResolutionSelector list.
const aspectBlock = timeline.slice(0, 0) + fs.readFileSync(new URL("../minimax_gen_timeline.js", import.meta.url), "utf8");
for (const ratio of settings.ASPECT_RATIOS) {
    const label = settings.aspectLabelFromRatio(ratio);
    assert.ok(aspectBlock.includes(`"${label}"`), `${label} must exist in RESOLUTION_ASPECTS`);
}

// --- attention backends -----------------------------------------------------

const nodeSummaries = [
    { id: 171, type: "ModelAttentionBackend", widgets: { attention_backend: "comfy_kitchen_int8" } },
    { id: 162, type: "SageAttentionPatch", widgets: { attention_backend: "sage_attention" } },
    { id: 174, type: "SpectrumApplyMiniMaxH3", widgets: { attention_backend: "existing" } },
    { id: 180, type: "SLA", widgets: { engine: "triton", dense_backend: "comfy_kitchen" } },
    { id: 10, type: "KSampler", widgets: { sampler_name: "res_multistep", steps: 25 } },
];
const hints = settings.collectBackendHints(nodeSummaries);
assert.deepEqual(
    hints.map((hint) => [hint.nodeId, hint.needs]),
    [["171", "comfy_kitchen"], ["162", "sage"], ["180", "triton"], ["180", "comfy_kitchen"]],
    "only backend-bearing widgets are collected, and 'existing' needs nothing",
);

const backends = {
    comfy_kitchen: { available: true },
    sage: { available: false, error: "ImportError: undefined symbol _ZN3c104impl..." },
    triton: { available: true },
    xformers: { available: false },
};
const warnings = settings.backendWarnings(hints, backends);
assert.equal(warnings.length, 1, "exactly the unsupported choice is reported");
assert.equal(warnings[0].nodeId, "162");
assert.match(warnings[0].message, /162/);
assert.match(warnings[0].error, /undefined symbol/);
assert.equal(
    settings.backendWarnings(hints, { comfy_kitchen: { available: true }, sage: { available: true }, triton: { available: true } }).length,
    0,
    "a fully capable machine warns about nothing",
);
assert.equal(
    settings.backendWarnings(hints, {}).length,
    0,
    "an unknown machine (no probe payload) stays quiet instead of guessing",
);

// --- export metadata policy -------------------------------------------------

assert.equal(settings.defaultSettings().export.embed_workflow, "auto", "the pack follows ComfyUI by default");
assert.equal(settings.normalizeEmbedPolicy("NEVER "), "never");
assert.equal(settings.normalizeEmbedPolicy("sometimes"), "auto", "junk falls back to auto, never to strip");
assert.equal(settings.normalizeEmbedPolicy(undefined), "auto");
assert.deepEqual(settings.EMBED_POLICY_CHOICES, ["auto", "always", "never"]);
assert.match(settings.metadataSummary({ comfyui_disabled: false }, "auto"), /Embedded/);
assert.match(settings.metadataSummary({ comfyui_disabled: true }, "auto"), /Not embedded/);
assert.match(settings.metadataSummary({ comfyui_disabled: true }, "always"), /Always embedded/);
assert.match(settings.metadataSummary({ comfyui_disabled: false }, "never"), /Never embedded/);

// --- cache + diagnostics ----------------------------------------------------

assert.equal(settings.formatBytes(0), "0 B");
assert.equal(settings.formatBytes(2048), "2.0 KB");
assert.equal(settings.formatBytes(32 * 1024 ** 3), "32 GB");

const report = {
    total_gb: 32.4,
    disk: { free_gb: 100, total_gb: 900 },
    kinds: [
        {
            id: "segments",
            label: "Segment caches",
            path: "/out/minimax_seg_cache",
            bytes: 34_000_000_000,
            files: 12,
            exists: true,
            nodes: [
                { node: "dir", bytes: 32 * 1024 ** 3, files: 9, segments: 3, state: "running", done: 1, segment_total: 6, updated_ms: 1 },
                { node: "probe", bytes: 1024, files: 1, segments: 0, state: "none", done: 0, segment_total: 0, updated_ms: 2 },
            ],
        },
        { id: "first_pass", label: "First-pass caches", path: "/out/minimax_first_pass_cache", bytes: 0, files: 0, nodes: [], exists: false },
    ],
};
const rows = settings.cacheRows(report);
assert.deepEqual(rows.map((row) => row.node), ["dir", "probe"], "biggest cache first");
assert.equal(rows[0].size, "32 GB");
assert.equal(rows[0].running, true, "an active run is flagged for the guard");
const kindSummary = settings.cacheKindSummary(report);
assert.equal(kindSummary[0].nodes, 2);
assert.equal(kindSummary[1].exists, false);
assert.equal(settings.runStateLabel("stopped"), "stopped");

const bundle = {
    pack: { version: "1.11.0", comfyui: "0.35.0", python: "3.12", torch: "2.13.0", cuda: "13.0", platform: "Linux" },
    machine: {
        tier: "large",
        tier_label: "Large",
        device: { name: "RTX 5090", total_vram_gb: 32, free_vram_gb: 30, capability: "12.0" },
        backends,
    },
    cache: { total_gb: 32.4, disk: { free_gb: 100 }, kinds: [{ id: "segments", bytes: 34_000_000_000, files: 12, nodes: 2, path: "/out/minimax_seg_cache" }] },
    runs: [{ cache: "segments", node: "dir", state: "stopped", done: 1, segment_total: 6 }],
};
const text = settings.diagnosticsText({
    bundle,
    project: { taskType: "r2v", width: 1504, height: 832, segmentCount: 6, totalFrames: 1271, frameRate: 24 },
    lastReport: "=== Assembly ===",
    warnings,
});
assert.match(text, /MiniMax H3 Motion Director 1\.11\.0 \(ComfyUI 0\.35\.0\)/);
assert.match(text, /RTX 5090 \| VRAM 32 GB total, 30 GB free/);
assert.match(text, /sage: UNAVAILABLE/, "an unusable backend is spelled out");
assert.match(text, /Run\[segments\/dir\]: stopped, 1\/6 segment\(s\) done/);
assert.match(text, /Project: r2v \| 1504x832 \| 6 segment\(s\)/);
assert.match(text, /\[Last run report\]/);
assert.match(text, /Node 162 uses SageAttention/, "the workflow warning travels with the report");

// --- panel wiring -----------------------------------------------------------

assert.match(ui, /\/minimax\/motion-director\/settings/, "the overlay reads the stored settings");
assert.match(ui, /\/minimax\/motion-director\/cache_clear/, "and clears caches through the server");
assert.match(ui, /\/minimax\/motion-director\/diagnostics/, "and fetches the diagnostics bundle");
assert.match(ui, /confirmButton\(/, "destructive cache clears need a second click");
assert.match(ui, /PATCH/, "settings are saved with a PATCH");

assert.match(timeline, /data-a="setup"/, "the panel's top bar has the gear");
assert.match(timeline, /forward\('\[data-a="setup"\]'/, "and the gear is wired");
assert.match(timeline, /setBaselineFrameProvider\(baselineFramesForTask\)/, "the baseline provider is installed");
assert.match(timeline, /_applySetupBaselines\(/, "'Apply to this project' has a real path");
assert.match(
    timeline,
    /applyResolutionSelector\(\s*\n\s*aspectLabelFromRatio\(resolved\.aspectRatio\)/,
    "applying baselines goes through the panel's own output controls",
);
assert.match(
    timeline,
    /applyCustomResolution\(resolved\.width, resolved\.height\)/,
    "and can set explicit dimensions",
);

const gen = fs.readFileSync(new URL("../minimax_gen_timeline.js", import.meta.url), "utf8");
assert.match(gen, /export function baselineFrameCount\(taskKey\)/, "creation-time frames have one entry point");
assert.match(gen, /typeof _baselineProvider !== "function"/, "and fall back cleanly with no settings");
assert.match(gen, /catch \{\s*\n\s*return fallback;/, "a broken provider cannot break segment creation");

// The enhancer button had to stop being called "Settings" now that a real
// app-wide Settings button exists.
//
// Split on the block boundary rather than at half the file length: the packs
// add strings to both dictionaries, and a byte-count midpoint silently drifts
// into whichever block grew more (it cut the English block's first keys off
// the moment the anchor strip was added).
const enStart = i18n.indexOf("const EN = {");
assert.ok(enStart > 0, "the i18n module declares an EN dictionary");
const zhBlock = i18n.slice(0, enStart);
const enBlock = i18n.slice(enStart);
assert.match(zhBlock, /"panel.enhanceSettings": "扩写设置"/);
assert.match(enBlock, /"panel.enhanceSettings": "Enhancer…"/);
for (const block of [zhBlock, enBlock]) {
    assert.match(block, /"panel\.setup"/, "both locales name the gear");
    assert.match(block, /"setup\.title"/, "and both translate the overlay");
}

// Every key the overlay can ask for must exist in both locales.
const keys = new Set();
for (const match of ui.matchAll(/\bt\("([a-zA-Z0-9_.]+)"/g)) keys.add(match[1]);
for (const match of fs.readFileSync(new URL("../minimax_motion_settings.mjs", import.meta.url), "utf8").matchAll(/\bt\("([a-zA-Z0-9_.]+)"/g)) {
    keys.add(match[1]);
}
assert.ok(keys.size > 50, `expected the overlay to ask for its own strings (${keys.size})`);
for (const key of keys) {
    assert.ok(zhBlock.includes(`"${key}"`), `zh is missing ${key}`);
    assert.ok(enBlock.includes(`"${key}"`), `en is missing ${key}`);
}
assert.ok(!keys.has("panel.enhanceSettings"), "the overlay never reuses the enhancer's label");

console.log(`minimax_motion_settings: OK (${keys.size} translated keys)`);
