// Mechanical check of the prompt enhancer's model control, using the real
// payload shape the backend returns (captured from the live ComfyUI instance).
//
// Verifies: the scan feeds a <select>, installed entries sort first and are
// tagged, the resolved default is selected automatically (no typing needed),
// picking an entry writes the id that gets sent, the custom escape hatch opens
// and closes, a typed value keeps a truthful entry in the list, and an empty
// scan (remote backend) falls back to the text field.
import assert from "node:assert/strict";
import fs from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { JSDOM } from "jsdom";

const here = new URL("./", import.meta.url);

const dom = new JSDOM("<!doctype html><html><head></head><body></body></html>", {
    url: "http://localhost/",
});
Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    Node: dom.window.Node,
    HTMLElement: dom.window.HTMLElement,
    HTMLCanvasElement: dom.window.HTMLCanvasElement,
    Event: dom.window.Event,
    CustomEvent: dom.window.CustomEvent,
    FormData: dom.window.FormData,
    File: dom.window.File,
    MouseEvent: dom.window.MouseEvent,
    MutationObserver: dom.window.MutationObserver,
});
Object.defineProperty(globalThis, "navigator", {
    value: dom.window.navigator,
    configurable: true,
});
Object.defineProperty(globalThis, "localStorage", {
    value: dom.window.localStorage,
    configurable: true,
});
globalThis.ResizeObserver = globalThis.ResizeObserver || class {
    observe() {}
    unobserve() {}
    disconnect() {}
};
// Skip the module's recovery import of the full timeline module.
globalThis.__MMX_MOTION_DIRECTOR_EXTENSION_REGISTERED__ = true;

const payload = JSON.parse(fs.readFileSync(fileURLToPath(new URL("scan.json", here)), "utf8"));
const { api } = await import("./api-stub.mjs");
api.scanPayload = payload;

const repoRoot = fileURLToPath(new URL("../../", here));
const { mountPromptEnhancerPanel } = await import(pathToFileURL(`${repoRoot}web/js/minimax_prompt_enhancer.js`).href);

const editor = {
    node: { id: 42 },
    widget: () => undefined,
    timeline: { segments: [], global: {} },
    selectedIndex: 0,
    getTaskKey: () => "rv2v",
    isGlobalMode: () => false,
    getDirectorMode: () => "video",
    commit: () => {},
    updateSelectionUI: () => {},
    updateDomWidgetHeight: () => {},
    _markNodeDirtyLight: () => {},
};

const pe = mountPromptEnhancerPanel(editor, document.createElement("div"));
assert.equal(pe.apiSelect.value, "Local (ComfyUI)", "defaults to the local backend");
await pe.fetchModels(true);

// --- the scan becomes a visible dropdown ------------------------------------
assert.equal(pe.modelSelect.style.display, "", "select is the default control after a scan");
assert.equal(pe.modelInput.style.display, "none", "text field is hidden while the list is active");
assert.equal(pe.modelBackBtn.style.display, "none", "no back button in list mode");

const options = [...pe.modelSelect.options];
assert.equal(options[0].value, "", "first entry is the automatic pick");
assert.match(options[0].textContent, /Automatic/);
assert.equal(options[options.length - 1].value, "__custom__", "custom entry is last");
assert.equal(document.querySelector("datalist"), null, "the datalist is gone");

const ids = options.map((option) => option.value);
const firstInstalled = ids.indexOf(payload.resolved_default);
const firstDownload = ids.indexOf("qwen3.8-27b-abl-ud-iq3-xxs");
assert.ok(firstInstalled > 0, "the resolved default is among the options");
assert.ok(firstDownload > 0, "downloadable catalog entries are offered too");
assert.ok(firstInstalled < firstDownload, "installed entries sort before downloadable ones");
assert.match(options[firstInstalled].textContent, /installed/, "entries carry their install state");
assert.match(options[firstDownload].textContent, /to download/, "downloadable entries say so");

// --- no typing needed: the resolved default is selected ---------------------
assert.equal(pe.modelInput.value, payload.resolved_default, "empty value self-heals to the resolved default");
assert.equal(pe.modelSelect.value, payload.resolved_default, "and the select shows it");

// --- picking an entry writes the id that gets sent ---------------------------
pe.modelSelect.value = "qwen3.8-27b-abl-q3-k";
pe.modelSelect.dispatchEvent(new dom.window.Event("change"));
assert.equal(pe.modelInput.value, "qwen3.8-27b-abl-q3-k");
assert.equal(pe.resolveModelForSend(), "qwen3.8-27b-abl-q3-k");
assert.equal(
    JSON.parse(localStorage.getItem("mmx_motion_director_pe_settings")).model,
    "qwen3.8-27b-abl-q3-k",
    "the pick persists like a typed name did",
);

// --- custom escape hatch -----------------------------------------------------
pe.modelSelect.value = "__custom__";
pe.modelSelect.dispatchEvent(new dom.window.Event("change"));
assert.equal(pe.modelInput.style.display, "", "custom mode reveals the text field");
assert.equal(pe.modelSelect.style.display, "none");
assert.equal(pe.modelBackBtn.style.display, "", "and the way back is offered");

pe.modelInput.value = "my-own-model.gguf";
pe.modelInput.dispatchEvent(new dom.window.Event("input"));
assert.equal(pe.resolveModelForSend(), "my-own-model.gguf");

// --- going back keeps the typed value visible and truthfully labelled --------
pe.modelBackBtn.click();
assert.equal(pe.modelSelect.style.display, "", "back button returns to the list");
assert.equal(pe.modelInput.style.display, "none");
assert.equal(pe.modelSelect.value, "my-own-model.gguf", "typed value keeps its own entry");
assert.match(pe.modelSelect.selectedOptions[0].textContent, /Custom: my-own-model\.gguf/);

// --- a backend with no list still gets the text field ------------------------
pe.modelChoices = [];
pe.refreshModelRow();
assert.equal(pe.modelInput.style.display, "", "no scan result -> text field");
assert.equal(pe.modelSelect.style.display, "none");

// --- H3 rules toggle ---------------------------------------------------------
assert.equal(pe.h3RulesCheck.checked, true, "H3 engine rules are on by default");
assert.equal(
    JSON.parse(localStorage.getItem("mmx_motion_director_pe_settings")).h3Rules,
    undefined,
    "an untouched toggle writes nothing",
);

pe.h3RulesCheck.checked = false;
pe.h3RulesCheck.dispatchEvent(new dom.window.Event("change"));
assert.equal(
    JSON.parse(localStorage.getItem("mmx_motion_director_pe_settings")).h3Rules,
    false,
    "turning the rules off persists",
);
pe.h3RulesCheck.checked = true;
pe.h3RulesCheck.dispatchEvent(new dom.window.Event("change"));
assert.equal(
    JSON.parse(localStorage.getItem("mmx_motion_director_pe_settings")).h3Rules,
    true,
    "and so does turning them back on",
);

// --- the toggle reaches the enhance request -----------------------------------
api.calls.length = 0;
await pe.callEnhanceApi("some window prompt", "rv2v", { index: 0 }, {
    model: payload.resolved_default,
    skipVision: true,
    llmUrl: "",
    apiFormat: "Local (ComfyUI)",
});
const enhanceCall = api.calls.find((call) => call.url.endsWith("/minimax/motion-director/enhance"));
assert.ok(enhanceCall, "the enhance endpoint was called");
assert.equal(
    JSON.parse(enhanceCall.options.body).h3_rules,
    true,
    "h3_rules is sent with the enhancement",
);
pe.h3RulesCheck.checked = false;
api.calls.length = 0;
await pe.callEnhanceApi("some window prompt", "rv2v", { index: 0 }, {
    model: payload.resolved_default,
    skipVision: true,
    llmUrl: "",
    apiFormat: "Local (ComfyUI)",
});
assert.equal(
    JSON.parse(api.calls.find((call) => call.url.endsWith("/enhance")).options.body).h3_rules,
    false,
    "turning the toggle off sends false",
);
pe.h3RulesCheck.checked = true;

// --- model download progress -------------------------------------------------
// A 20 GB pull used to sit on one static line. The bar is fed by the server's
// byte count, which is polled because the download request itself blocks.
api.downloadStatus = {
    active: true, done: false, fallback: false, model_id: "qwen3.8-27b-abl-q5-k",
    label: "Qwen3.8 27B abliterated - Q5_K (19.5 GB)", phase: "vision",
    bytes: 8.4e9, expected_bytes: 20.4e9, percent: 41.2, rate_bps: 2.0e7,
    eta_seconds: 600, error: "",
};
assert.notEqual(pe.dlBar.style.display, "block", "the bar is not shown before any download");

await pe.pollDownloadStatus();
assert.equal(pe.dlBar.style.display, "block", "the bar appears while a download runs");
assert.equal(pe.dlFill.style.width, "41.2%", "the fill tracks the reported percentage");
assert.match(pe.statusEl.textContent, /41%/, "the status line shows the percentage");
assert.match(pe.statusEl.textContent, /8\.4 GB \/ 20\.4 GB/, "and the byte progress");
assert.match(pe.statusEl.textContent, /vision projector/, "the vision phase is named");
assert.match(pe.statusEl.textContent, /10m/, "and the ETA is shown");

// An unknown total (download started before this page loaded) must not show 0%.
api.downloadStatus = {
    active: true, done: false, fallback: true, model_id: "", label: "", phase: "unknown",
    bytes: 3.0e9, expected_bytes: 0, percent: null, rate_bps: 0, eta_seconds: null, error: "",
};
await pe.pollDownloadStatus();
assert.equal(pe.dlFill.style.width, "", "the stale percentage is cleared when the total is unknown");
assert.match(pe.statusEl.textContent, /3\.0 GB/, "but the received bytes are still reported");
assert.ok(pe.dlFill.classList.contains("minimax-pe-loading"), "the fill pulses while unknown");

api.downloadStatus = {
    active: false, done: true, fallback: false, model_id: "", label: "", phase: "done",
    bytes: 0, expected_bytes: 0, percent: 100, rate_bps: 0, eta_seconds: null, error: "",
};
await pe.pollDownloadStatus();
assert.equal(pe.dlBar.style.display, "none", "the bar hides once the download ends");
assert.equal(pe.dlFill.style.width, "0%", "and the fill resets");

// --- prompt recipe dropdown --------------------------------------------------
// The dropdown is populated from the pack's own list (GET /enhance_recipes) so a
// new recipe needs no frontend change, and the chosen key travels with the request.
await pe.loadRecipes();
const recipeValues = [...pe.recipeSelect.options].map((option) => option.value);
assert.equal(recipeValues[0], "auto", "Auto is the default and comes first");
assert.ok(recipeValues.includes("character_replace"), "pack recipes are offered");
assert.ok(recipeValues.includes("character_replace_refmod"), "including the RefMod variant");
assert.equal(pe.recipeSelect.value, "auto", "nothing is overridden by default");
assert.ok(pe.recipeNote.textContent.length > 0, "the Auto note explains itself");

pe.recipeSelect.value = "character_replace_refmod";
pe.recipeSelect.dispatchEvent(new dom.window.Event("change"));
assert.equal(
    JSON.parse(localStorage.getItem("mmx_motion_director_pe_settings")).h3Recipe,
    "character_replace_refmod",
    "the recipe choice persists",
);
assert.match(pe.recipeNote.textContent, /appearance prose/, "and its summary is shown");

api.calls.length = 0;
await pe.callEnhanceApi("some window prompt", "rv2v", { index: 0 }, {
    model: payload.resolved_default,
    skipVision: true,
    llmUrl: "",
    apiFormat: "Local (ComfyUI)",
});
assert.equal(
    JSON.parse(api.calls.find((call) => call.url.endsWith("/enhance")).options.body).h3_recipe,
    "character_replace_refmod",
    "the recipe is sent with the enhancement",
);

// --- build from images (caption mode) ----------------------------------------
// Port of the Character Remake + QwenVL workflow: the pack assembles the block
// from two vision captions instead of asking the model to rewrite a prompt.
assert.equal(pe.fromImagesCheck.checked, false, "caption mode is off by default");
pe.fromImagesCheck.checked = true;
pe.fromImagesCheck.dispatchEvent(new dom.window.Event("change"));
assert.equal(
    JSON.parse(localStorage.getItem("mmx_motion_director_pe_settings")).fromImages,
    true,
    "the choice persists",
);

api.calls.length = 0;
await pe.callEnhanceApi("some window prompt", "rv2v", { index: 0, replace: { audio_policy: "generate" } }, {
    model: payload.resolved_default,
    skipVision: true,
    llmUrl: "",
    apiFormat: "Local (ComfyUI)",
});
const captioned = JSON.parse(
    api.calls.find((call) => call.url.endsWith("/enhance")).options.body,
);
assert.equal(captioned.prompt_mode, "captions", "caption mode travels with the request");
assert.equal(
    captioned.audio_policy,
    "generate",
    "and the window's audio policy comes from the replace spec instead of being guessed",
);

pe.fromImagesCheck.checked = false;
api.calls.length = 0;
await pe.callEnhanceApi("some window prompt", "rv2v", { index: 0 }, {
    model: payload.resolved_default,
    skipVision: true,
    llmUrl: "",
    apiFormat: "Local (ComfyUI)",
});
const plain = JSON.parse(api.calls.find((call) => call.url.endsWith("/enhance")).options.body);
assert.equal(plain.prompt_mode, "rewrite", "off means the rewrite path");
assert.equal(plain.audio_policy, "", "no replace spec -> no policy claimed");

// --- polish mode (wording only) ------------------------------------------------
// The one mode that must NOT reshape the prompt: exclusive with caption mode, it
// parks the controls that only apply to a rewrite, collects no frames and travels
// as prompt_mode "polish".
assert.equal(pe.polishCheck.checked, false, "polish is off by default");
pe.polishCheck.checked = true;
pe.polishCheck.dispatchEvent(new dom.window.Event("change"));
assert.equal(
    JSON.parse(localStorage.getItem("mmx_motion_director_pe_settings")).polish,
    true,
    "the choice persists",
);
assert.equal(pe.recipeSelect.disabled, true, "a recipe only shapes a rewrite");
assert.equal(pe.detailCheck.disabled, true, "so does character detail");
assert.equal(pe.h3CompactCheck.disabled, true, "and the compact-rules switch");
assert.equal(pe.hidePerformerCheck.disabled, true, "hiding the performer is a caption-mode job");

pe.fromImagesCheck.checked = true;
pe.fromImagesCheck.dispatchEvent(new dom.window.Event("change"));
assert.equal(pe.polishCheck.checked, false, "the two modes clear each other");
assert.equal(pe.recipeSelect.disabled, false, "and the shape controls come back");

pe.polishCheck.checked = true;
pe.polishCheck.dispatchEvent(new dom.window.Event("change"));
let visionCollects = 0;
const realCollect = pe.collectVisionImagesForBlock;
pe.collectVisionImagesForBlock = async (...args) => {
    visionCollects += 1;
    return realCollect(...args);
};
api.calls.length = 0;
await pe.callEnhanceApi("subject_definitions:\n<Subject 1> is the woman.", "rv2v", { index: 0 }, {
    model: payload.resolved_default,
    llmUrl: "",
    apiFormat: "Local (ComfyUI)",
});
pe.collectVisionImagesForBlock = realCollect;
const polished = JSON.parse(api.calls.find((call) => call.url.endsWith("/enhance")).options.body);
assert.equal(polished.prompt_mode, "polish", "the wording pass travels with the request");
assert.equal(visionCollects, 0, "a wording pass gathers no frames: the server ignores them");
assert.deepEqual(polished.images, [], "so the payload carries none");
assert.equal(
    polished.h3_rules,
    true,
    "the panel still reports the switch as set; the server decides what a polish pass uses",
);
pe.polishCheck.checked = false;
pe.polishCheck.dispatchEvent(new dom.window.Event("change"));
assert.equal(pe.recipeSelect.disabled, false, "switching back restores the shape controls");

// --- compact rules + hiding the source performer ------------------------------
// Both are opt-in switches on the same request; the panel must persist them and
// send them, and the RefMod character field must only be offered where it applies.
assert.equal(pe.h3CompactCheck.checked, false, "compact rules are opt-in");
pe.h3CompactCheck.checked = true;
pe.h3CompactCheck.dispatchEvent(new dom.window.Event("change"));
assert.equal(
    JSON.parse(localStorage.getItem("mmx_motion_director_pe_settings")).h3Compact,
    true,
    "the compact choice persists",
);

assert.equal(pe.hidePerformerCheck.checked, false, "hiding the performer is opt-in");
pe.hidePerformerCheck.checked = true;
pe.hidePerformerCheck.dispatchEvent(new dom.window.Event("change"));

api.calls.length = 0;
await pe.callEnhanceApi("some window prompt", "rv2v", { index: 0 }, {
    model: payload.resolved_default,
    skipVision: true,
    llmUrl: "",
    apiFormat: "Local (ComfyUI)",
});
const toggled = JSON.parse(api.calls.find((call) => call.url.endsWith("/enhance")).options.body);
assert.equal(toggled.h3_rules_compact, true, "the compact flag travels with the request");
assert.equal(toggled.hide_performer, true, "so does the performer-hiding flag");
assert.deepEqual(toggled.frame_images, [], "and no endpoint frames when the segment has none");

// The RefMod character field only makes sense for the recipe that uses it.
pe.recipeSelect.value = "auto";
pe.recipeSelect.dispatchEvent(new dom.window.Event("change"));
assert.equal(pe.refmodRow.style.display, "none", "no RefMod character field on Auto");
pe.recipeSelect.value = "character_replace_refmod";
pe.recipeSelect.dispatchEvent(new dom.window.Event("change"));
assert.notEqual(pe.refmodRow.style.display, "none", "and it appears for the RefMod recipe");
pe.refmodInput.value = "people/elf_girl";
pe.refmodInput.dispatchEvent(new dom.window.Event("change"));
api.calls.length = 0;
await pe.callEnhanceApi("some window prompt", "rv2v", { index: 0 }, {
    model: payload.resolved_default,
    skipVision: true,
    llmUrl: "",
    apiFormat: "Local (ComfyUI)",
});
const refmodded = JSON.parse(api.calls.find((call) => call.url.endsWith("/enhance")).options.body);
assert.equal(refmodded.refmod_character, "people/elf_girl", "the character source is sent");

console.log("prompt enhancer model picker: all checks passed");
