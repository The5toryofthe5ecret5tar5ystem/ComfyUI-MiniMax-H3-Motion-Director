import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

// Integration test for the Setup overlay: mount it in jsdom against a realistic
// server payload and require every tab to render.
//
// This exists because the pure-rules test could not catch the real bug: a row() call
// passed a translation *string* where a DOM node was expected, so renderBaselines()
// threw inside appendChild. renderAll() had already rendered Machine, and the throw
// aborted the rest - Baselines and Run & UI stayed empty forever, and the only trace
// was a status line. Nothing about the payload was wrong; the tab was simply never
// drawn.

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
globalThis.window = dom.window;
globalThis.document = dom.window.document;
Object.defineProperty(globalThis, "navigator", { value: dom.window.navigator, configurable: true });
Object.defineProperty(globalThis, "localStorage", { value: dom.window.localStorage, configurable: true });

const { mountSettingsOverlay } = await import("../minimax_settings_ui.mjs");

const machine = {
    pack_version: "1.11.0",
    comfyui_version: "0.35.0",
    python_version: "3.12.10",
    torch_version: "2.13.0+cu130",
    cuda_version: "13.0",
    platform: "Linux",
    tier: "large",
    tier_label: "Large",
    tier_note: "24-32 GB cards.",
    downgraded: false,
    downgrade_reason: "",
    device: {
        index: 0,
        name: "NVIDIA GeForce RTX 5090",
        capability: "12.0",
        total_vram_gb: 31.43,
        free_vram_gb: 29.1,
        available: true,
    },
    baselines: { megapixels: 1.0, width: 1344, height: 768, segment_frames: 243, max_segment_frames: 362, ref_max_size: 1024 },
    backends: {
        sdpa: { name: "sdpa", available: true, version: "2.13.0", detail: "SDPA", error: "" },
        sage: { name: "sage", available: false, version: null, detail: "", error: "undefined symbol" },
        comfy_kitchen: { name: "comfy_kitchen", available: true, version: "0.2.33", detail: "int8 attention available", error: "" },
        xformers: { name: "xformers", available: false, version: null, detail: "", error: "not installed" },
        flash_attn: { name: "flash_attn", available: true, version: "2.8.3", detail: "", error: "" },
        triton: { name: "triton", available: true, version: "3.7.1", detail: "", error: "" },
    },
};

const settings = {
    schema_version: 1,
    machine: { profile: "auto", device_index: 0, vram_gb_override: 0 },
    baselines: {
        aspect_ratio: "16:9",
        megapixels: 1.0,
        width: 1344,
        height: 768,
        segment_frames: 243,
        max_segment_frames: 362,
        ref_max_size: 1024,
        clear_vram_between_segments: true,
        export_mode: "all",
        continuity: true,
        continuity_overlap_frames: 9,
    },
    run: { auto_save_workflow: true, keep_models_resident: false, verbose_logging: false },
    app: { locale: "en", live_tae_preview: true, preview_audio: true },
    export: { embed_workflow: "auto" },
    cache: { warn_over_gb: 80 },
    updated_at: 1,
};

const cacheReport = {
    output_dir: "/out",
    total_gb: 40.11,
    warn_over_gb: 80,
    disk: { total_gb: 9360, free_gb: 9376.9 },
    kinds: [
        {
            id: "segments",
            label: "Segment caches",
            path: "/out/minimax_seg_cache",
            bytes: 34.48 * 1024 ** 3,
            files: 40,
            exists: true,
            nodes: [
                { node: "dir", bytes: 32 * 1024 ** 3, files: 30, segments: 8, state: "running", done: 2, segment_total: 6, updated_ms: 1 },
            ],
        },
        { id: "motion_context", label: "Motion context", path: "/out/minimax_motion_context_cache", bytes: 0, files: 0, nodes: [], exists: false },
        { id: "first_pass", label: "First-pass caches", path: "/out/minimax_first_pass_cache", bytes: 0, files: 0, nodes: [], exists: false },
    ],
};

const diagnostics = { pack: { version: "1.11.0", comfyui: "0.35.0" }, machine, settings, cache: {}, runs: [] };

const requests = [];
const applied = [];
const host = document.createElement("div");
document.body.appendChild(host);

const overlay = mountSettingsOverlay({
    host,
    api: {
        fetchApi: async (url, init = {}) => {
            const method = String(init.method || "GET");
            requests.push([method, String(url), init.body ? JSON.parse(init.body) : null]);
            if (url.includes("/cache_report")) return { ok: true, json: async () => cacheReport };
            if (url.includes("/diagnostics")) return { ok: true, json: async () => diagnostics };
            // Behave like the real route: a write is echoed back, so the panel's
            // local state after a save is the server's answer, not its own guess.
            if (method === "PATCH" || method === "POST") {
                const body = init.body ? JSON.parse(init.body) : {};
                for (const [section, values] of Object.entries(body.settings || {})) {
                    settings[section] = { ...(settings[section] || {}), ...values };
                }
            }
            return {
                ok: true,
                json: async () => ({
                    settings,
                    machine,
                    detected_baselines: machine.baselines,
                    defaults: settings,
                    export_state: { policy: settings.export.embed_workflow, embed: true, comfyui_disabled: false },
                    path: "/user/settings.json",
                }),
            };
        },
    },
    getGraphNodes: () => [
        { id: 162, type: "SageAttentionPatch", widgets: { attention_backend: "sage_attention" } },
        { id: 171, type: "ModelAttentionBackend", widgets: { attention_backend: "comfy_kitchen_int8" } },
    ],
    getProjectInfo: () => ({ taskType: "r2v", width: 1504, height: 832, segmentCount: 6, totalFrames: 1271, frameRate: 24 }),
    getLastReport: () => "=== Assembly ===",
    onApplyBaselines: undefined,
    applyBaselines: (resolved) => {
        applied.push(resolved);
        return { width: resolved.width, height: resolved.height };
    },
});

const settle = () => new Promise((resolve) => setTimeout(resolve, 60));

const pane = (name) => host.querySelector(`.pane-${name}`);
const text = (name) => (pane(name).textContent || "").trim();

overlay.open();
await settle();

// --- every tab renders, whatever the payload ---------------------------------

for (const name of ["machine", "baselines", "run", "export"]) {
    assert.ok(text(name).length > 40, `${name} must render (got ${text(name).length} chars)`);
}
assert.equal(host.querySelector(".status").textContent, "", "a clean load leaves no error on the status line");
assert.match(text("machine"), /RTX 5090/, "the machine tab names the GPU");
assert.match(text("machine"), /29\.1 GB free/, "and the live free VRAM");
assert.match(text("machine"), /int8 attention available/, "and the usable backends");
assert.match(text("machine"), /undefined symbol/, "and why sage is unusable");
assert.match(text("machine"), /SageAttention/, "and warns about the workflow's sage choice");
assert.match(text("machine"), /Node 162/, "naming the offending node");

// --- baselines tab -----------------------------------------------------------

const baselineInputs = [...pane("baselines").querySelectorAll('input[type="number"]')].map((input) => input.value);
assert.ok(baselineInputs.includes("1344") && baselineInputs.includes("768"), "the canvas widths are shown");
assert.ok(baselineInputs.includes("243") && baselineInputs.includes("362"), "the frame baselines are shown");
const aspectSelect = pane("baselines").querySelector("select");
assert.ok([...aspectSelect.options].some((option) => option.value === "16:9"), "the ratio list is populated");
assert.match(text("baselines"), /17k\+5|10\.13/, "the seconds readout explains the frame count");

// --- run & UI tab ------------------------------------------------------------

const runBoxes = pane("run").querySelectorAll('input[type="checkbox"]');
assert.ok(runBoxes.length >= 4, `run & UI renders its toggles (got ${runBoxes.length})`);
assert.ok([...pane("run").querySelectorAll("select")].length >= 2, "and its dropdowns");
assert.match(text("run"), /English|Automatic/, "including the language choice");

// --- export tab --------------------------------------------------------------

const exportSelect = pane("export").querySelector("select");
assert.deepEqual(
    [...exportSelect.options].map((option) => option.value),
    ["auto", "always", "never"],
    "the metadata choice offers all three states",
);
assert.equal(exportSelect.value, "auto", "and starts on the stored value");
assert.match(text("export"), /Embedded/, "the effective line explains what will happen");
assert.match(text("export"), /Save Video|save route/, "and names the scope (this pack's save route)");
const stripInput = pane("export").querySelector('input[type="text"]');
assert.ok(stripInput, "the strip utility has a file field");
assert.ok(
    [...pane("export").querySelectorAll("button")].some((button) => /strip/i.test(button.textContent)),
    "and a strip button",
);

const beforeExportPatch = requests.length;
exportSelect.value = "never";
exportSelect.dispatchEvent(new dom.window.Event("change"));
await new Promise((resolve) => setTimeout(resolve, 600));
const exportPatch = requests
    .slice(beforeExportPatch)
    .find(([method, url]) => method === "PATCH" && url.includes("/settings"));
assert.ok(exportPatch, "changing the policy saves it");
assert.deepEqual(exportPatch[2].settings.export, { embed_workflow: "never" });
assert.match(text("export"), /Never embedded/, "and the effective line follows immediately");

// --- tabs switch -------------------------------------------------------------

host.querySelector('button[data-tab="cache"]').click();
await settle();
assert.ok(pane("cache").classList.contains("active"), "clicking a tab activates its pane");
assert.ok(text("cache").length > 40, "the cache tab renders");
assert.match(text("cache"), /32 GB/, "with the real sizes");
assert.match(text("cache"), /rendering/, "and the run state of an active project");
assert.ok(
    [...pane("cache").querySelectorAll("button")].some((button) => /clear/i.test(button.textContent)),
    "and a clear button",
);

host.querySelector('button[data-tab="diagnostics"]').click();
await settle();
assert.match(pane("diagnostics").querySelector("pre").textContent, /MiniMax H3 Motion Director 1\.11\.0/);

// --- settings writes ---------------------------------------------------------

const framesInput = [...pane("baselines").querySelectorAll('input[type="number"]')][3];
const before = requests.length;
framesInput.value = "362";
framesInput.dispatchEvent(new dom.window.Event("change"));
await new Promise((resolve) => setTimeout(resolve, 600));
const patch = requests.slice(before).find(([method]) => method === "PATCH");
assert.ok(patch, "editing a baseline PATCHes the server");
assert.ok(patch[1].includes("/minimax/motion-director/settings"));

// --- apply to project --------------------------------------------------------

host.querySelector(".foot .btn.primary").click();
await settle();
assert.equal(applied.length, 1, "the apply button calls back once");
assert.deepEqual(
    { w: applied[0].width, h: applied[0].height, frames: applied[0].segmentFrames, mp: applied[0].megapixels },
    { w: 1344, h: 768, frames: 362, mp: 1.0 },
    "with the resolved baselines, including the edit just made",
);
assert.match(host.querySelector(".status").textContent, /362/, "and reports what it applied");

// --- a broken pane cannot blank the others -----------------------------------

overlay.reloadSettings({ ...settings, baselines: { ...settings.baselines, aspect_ratio: 12345 } }, null);
assert.ok(text("run").length > 40, "a hostile payload still leaves the other tabs rendered");

console.log("minimax_settings_overlay: OK");
