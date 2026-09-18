// Portions derived from ComfyUI_MiniMaxH3_Director
// Copyright AIMixer and contributors
// Originally licensed under Apache License 2.0
// Modified for MiniMax H3 Motion Director, 2026-08-09
// This derivative project is distributed under GPL-3.0.
// See NOTICE and LICENSES/Apache-2.0-AIMixer.txt.

/** LLM prompt enhancer panel for MiniMax H3 Motion Director (Ollama / Zhipu). */

import { api } from "../../scripts/api.js";
import { resolveTaskKey, taskUsesReferenceImages, taskUsesReferenceVideo } from "./minimax_gen_timeline.js";
import { stripFl2vPromptBody } from "./minimax_fl2v.js";
// Panel copy follows the Director's UI locale. These strings used to be
// hardcoded Chinese, so switching the interface to English left this whole panel
// untranslated.
import { t } from "./minimax_i18n.js";

export const PE_PANEL_COLLAPSED_H = 34;
export const PE_PANEL_EXPANDED_H = 348;

const DEFAULT_LLM_URL = "http://127.0.0.1:11434/v1";
const DEFAULT_LLM_MODEL = "qwen3.5";
const DEFAULT_ZHIPU_URL = "https://open.bigmodel.cn/api/paas/v4";
const DEFAULT_ZHIPU_MODEL = "glm-4.6v-flash";
const DEFAULT_OPENAI_COMPAT_URL = "http://127.0.0.1:8080/v1";
const DEFAULT_API_FORMAT = "Local (ComfyUI)";
const API_OLLAMA = "Ollama";
// Enum value, NOT display text: stored in settings and sent to the backend as
// the api_format identifier. Translating it silently deselects the Zhipu
// backend (the stored value stops matching). The visible dropdown label is
// the separate pe.apiZhipu string.
const API_ZHIPU = "智谱 GLM";
const API_OPENAI_COMPAT = "OpenAI Compatible";
// Runs a GGUF model from ComfyUI's own models/LLM tree inside ComfyUI. No
// server, no API key, no URL - so it is the out-of-the-box default.
const API_LOCAL = "Local (ComfyUI)";
const NON_URL_FORMATS = [API_LOCAL];
const PE_SETTINGS_KEY = "mmx_motion_director_pe_settings";
// Enum value, NOT display text: persisted in settings and compared in
// normalizeOpenAiCompatMode(). The visible dropdown label is the separate
// pe.compatStandard string.
const OPENAI_COMPAT_STANDARD = "标准";
const OPENAI_COMPAT_LLAMA_SWAP = "llama-swap";
const DEFAULT_OUTPUT_LANGUAGE = "English";
// Enum value, NOT display text: the literal that requests Chinese output. It is
// sent as output_language to the enhancer backend, so translating it silently
// switches the request back to the server default. Visible label: pe.langZh.
const OUTPUT_LANGUAGE_ZH = "中文";
// Legacy value vocabulary from the old character-detail dropdown, NOT display
// text. These strings survive in stored settings and drive the migration check
// in coerceFeatureEnhanceValue(); only "详尽" counts as enabled. The visible
// checkbox label is pe.characterDetail.
const CHARACTER_DETAIL_NORMAL = "一般";
const CHARACTER_DETAIL_DETAILED = "详尽";
const LEGACY_OPENAI_FORMAT = "OpenAI / vLLM";
// Sentinel value for the "type a custom name" entry in the model select.
const MODEL_CUSTOM_OPTION = "__custom__";

const STATUS_COLORS = {
    info: "#9aa3b5",
    loading: "#fbbf24",
    success: "#4ade80",
    error: "#f87171",
};

function coerceLlmUrl(value, defaultUrl = DEFAULT_LLM_URL) {
    const s = String(value ?? "").trim();
    if (/^https?:\/\//i.test(s)) return s.replace(/\/+$/, "");
    return defaultUrl;
}

function coerceLlmModel(value) {
    const s = String(value ?? "").trim();
    if (!s || s === "true" || s === "false") return DEFAULT_LLM_MODEL;
    return s;
}

function normalizeApiFormat(fmt) {
    if (fmt === LEGACY_OPENAI_FORMAT) return API_OPENAI_COMPAT;
    if (
        fmt === API_ZHIPU
        || fmt === API_OLLAMA
        || fmt === API_OPENAI_COMPAT
        || fmt === API_LOCAL
    ) return fmt;
    return DEFAULT_API_FORMAT;
}

function inferApiFormat(url, explicit) {
    const fmt = normalizeApiFormat(explicit);
    // Local wins outright: a leftover llm_url from a previous Ollama setup must
    // not drag the user back onto that server through the URL sniff below.
    if (fmt === API_LOCAL) return API_LOCAL;
    if (fmt === API_ZHIPU || fmt === API_OLLAMA || fmt === API_OPENAI_COMPAT) return fmt;
    const u = coerceLlmUrl(url);
    if (/bigmodel\.cn/i.test(u)) return API_ZHIPU;
    return DEFAULT_API_FORMAT;
}

/** Local mode has no server, so its URL/API-key rows are meaningless. */
function formatUsesUrl(fmt) {
    return !NON_URL_FORMATS.includes(normalizeApiFormat(fmt));
}

/**
 * Enhancer settings, persisted per browser.
 *
 * The panel used to read and write named llm_* node widgets that were never
 * declared, so every read returned undefined and every write was dropped: the
 * model reset to a hardcoded name on each reload. localStorage keeps the
 * selection without changing the node's widget tail, which is a tested contract
 * (see DIRECTOR_WIDGET_TAIL). Per-workflow persistence would need a real widget.
 */
function loadPeSettings() {
    try {
        const raw = localStorage.getItem(PE_SETTINGS_KEY);
        return raw ? JSON.parse(raw) || {} : {};
    } catch (e) {
        return {};
    }
}

function savePeSettings(patch) {
    try {
        const merged = { ...loadPeSettings(), ...patch };
        localStorage.setItem(PE_SETTINGS_KEY, JSON.stringify(merged));
    } catch (e) {
        /* private mode or quota; settings simply do not persist */
    }
}

function defaultsForApiFormat(fmt) {
    if (fmt === API_ZHIPU) return { url: DEFAULT_ZHIPU_URL, model: DEFAULT_ZHIPU_MODEL };
    if (fmt === API_OPENAI_COMPAT) return { url: DEFAULT_OPENAI_COMPAT_URL, model: DEFAULT_LLM_MODEL };
    if (fmt === API_LOCAL) return { url: "", model: "" };
    return { url: "http://127.0.0.1:11434", model: DEFAULT_LLM_MODEL };
}

function normalizeOpenAiCompatMode(mode) {
    return String(mode || "").trim().toLowerCase() === OPENAI_COMPAT_LLAMA_SWAP
        ? OPENAI_COMPAT_LLAMA_SWAP
        : OPENAI_COMPAT_STANDARD;
}

function ensurePeStyles() {
    if (document.getElementById("minimax-pe-styles")) return;
    const style = document.createElement("style");
    style.id = "minimax-pe-styles";
    style.textContent = `
@keyframes minimax-pe-pulse { 0%,100%{opacity:1} 50%{opacity:.65} }
.minimax-pe-loading { animation: minimax-pe-pulse 1.2s ease-in-out infinite !important; }
.minimax-pe-label { font-size: 11px; color: #b8c0d0; flex-shrink: 0; white-space: nowrap; }
.minimax-pe-input, .minimax-pe-select {
    font-size: 11px; line-height: 1.35; min-height: 28px; box-sizing: border-box;
    background: #12151b; color: #e8ecf4; border: 1px solid #2a3140; border-radius: 4px;
}
.minimax-pe-input { padding: 5px 8px; }
.minimax-pe-select { padding: 4px 8px; cursor: pointer; }
.minimax-pe-btn-sm {
    font-size: 11px; line-height: 1.35; min-height: 28px; box-sizing: border-box;
    background: #252a34; color: #e8ecf4; border: 1px solid #2a3140; border-radius: 4px;
    padding: 4px 10px; cursor: pointer; flex-shrink: 0; white-space: nowrap;
}
.minimax-pe-api-row { display: flex; gap: 6px; align-items: center; flex-wrap: nowrap; }
.minimax-pe-api-row .minimax-pe-select { flex: 0 1 38%; min-width: 132px; max-width: 220px; }
.minimax-pe-api-row .minimax-pe-input { flex: 1 1 120px; min-width: 0; }
.minimax-pe-options-row { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; }
.minimax-pe-check-item { display: flex; gap: 4px; align-items: center; }
.minimax-pe-check-item span { font-size: 11px; color: #b8c0d0; }
/* Model download: a 20 GB pull with no feedback looked like a hung panel. */
.minimax-pe-dlbar {
    height: 6px; background: #12151b; border: 1px solid #2a3140; border-radius: 3px;
    overflow: hidden; display: none;
}
.minimax-pe-dlfill { height: 100%; width: 0%; background: #3b82f6; transition: width .3s ease-out; }
.minimax-pe-dlfill.minimax-pe-loading { width: 100%; background: #6366f1; }
`;
    document.head.appendChild(style);
}

function el(style, text, tag = "div") {
    const node = document.createElement(tag);
    if (style) Object.assign(node.style, style);
    if (text != null) node.textContent = text;
    return node;
}

function swallowKeys(input) {
    input.addEventListener("keydown", (e) => e.stopPropagation());
    input.addEventListener("keyup", (e) => e.stopPropagation());
}

async function fetchImageB64(imageFile) {
    const resp = await api.fetchApi("/minimax/motion-director/image_b64", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ imageFile }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || resp.statusText);
    return data.image;
}

function resolveOutputLanguage(pe) {
    const widgetLang = pe.widget?.("llm_output_language")?.value;
    if (widgetLang) {
        if (pe.langSelect) pe.langSelect.value = widgetLang;
        return widgetLang;
    }
    return pe.langSelect?.value || DEFAULT_OUTPUT_LANGUAGE;
}

function coerceFeatureEnhanceValue(value) {
    if (value === true || value === 1) return true;
    if (value === false || value === 0 || value == null || value === "") return false;
    const v = String(value).trim().toLowerCase();
    if (v === "true" || v === "yes" || v === "on") return true;
    // The old dropdown could survive the BOOLEAN migration with its legacy
    // values ("一般"/"详尽"); only "详尽" (detailed) counts as enabled.
    if (v.includes("详尽") || v === "detailed" || v === "verbose" || v === "full") return true;
    return false;
}

function resolveCharacterFeatureEnhance(pe, { preferWidget = false } = {}) {
    const enhanceWidget = pe.widget?.("llm_character_feature_enhance");
    const fromWidgetEnhance = enhanceWidget?.value;
    const fromCheck = pe.detailCheck?.checked;
    if (preferWidget && enhanceWidget) {
        return coerceFeatureEnhanceValue(fromWidgetEnhance);
    }
    if (fromCheck != null) return !!fromCheck;
    if (enhanceWidget) return coerceFeatureEnhanceValue(fromWidgetEnhance);
    return false;
}

function formatEnhanceSuccessStatus(taskKey, result) {
    let msg = t("pe.statusEnhancedOk", { task: taskKey, count: result.text?.length ?? 0 });
    if (result.detailedMode) {
        // The backend measures Chinese characters for a Chinese answer and plain
        // characters for any other language; showing the wrong one made every
        // English answer look short of the target.
        const measured = result.detailMeasure ?? 0;
        const target = result.detailTargetHan ?? 300;
        const unit = result.detailUnit === "han" ? t("pe.detailUnitHan") : t("pe.detailUnitChars");
        msg += t("pe.statusEnhancedDetail", { count: measured, target, unit });
        if (measured < target) {
            msg += t("pe.statusEnhancedShort");
        }
    }
    return msg;
}

function resolveCharacterDetailLevel(pe, opts) {
    return resolveCharacterFeatureEnhance(pe, opts) ? CHARACTER_DETAIL_DETAILED : CHARACTER_DETAIL_NORMAL;
}

export function mountPromptEnhancerPanel(editor, parentEl) {
    ensurePeStyles();
    const pe = {
        editor, open: false, _currentDefaultTemplate: "", _busy: false,
        modelChoices: [], _modelCustomMode: false,
    };

    pe.setStatus = (text, kind = "info") => {
        pe.statusEl.textContent = text || "";
        pe.statusEl.style.color = STATUS_COLORS[kind] || STATUS_COLORS.info;
        pe.statusEl.style.fontWeight = kind === "error" ? "600" : "400";
        pe.statusEl.style.whiteSpace = "pre-wrap";
        pe.statusEl.style.lineHeight = "1.35";
    };

    /**
     * Report one enhancement result, including how it was produced.
     * The server may decline "build from images" (wrong recipe, no images) and say
     * so in `note`; silently doing something else is how the panel loses trust.
     */
    pe.reportEnhanceResult = (taskKey, result) => {
        const modeNote = result.promptMode === "captions"
            ? t("pe.statusBuiltFromImages")
            : (result.note ? ` ${result.note}` : "");
        pe.setStatus(formatEnhanceSuccessStatus(taskKey, result) + modeNote, "success");
    };

    pe.setEnhanceLoading = (loading, activeBtn = null, label = t("pe.statusEnhancing")) => {
        pe._busy = loading;
        pe.enhanceCurrentBtn.disabled = loading;
        pe.enhanceAllBtn.disabled = loading;
        pe.refreshBtn.disabled = loading;
        pe.unloadBtn.disabled = loading;
        if (loading && activeBtn) {
            activeBtn.textContent = label;
            activeBtn.style.background = "#d97706";
            activeBtn.style.cursor = "wait";
            activeBtn.classList.add("minimax-pe-loading");
        } else {
            pe.enhanceCurrentBtn.textContent = t("pe.enhanceCurrent");
            pe.enhanceAllBtn.textContent = t("pe.enhanceAll");
            pe.enhanceCurrentBtn.style.background = "#3b82f6";
            pe.enhanceAllBtn.style.background = "#6366f1";
            pe.enhanceCurrentBtn.style.cursor = "pointer";
            pe.enhanceAllBtn.style.cursor = "pointer";
            pe.enhanceCurrentBtn.classList.remove("minimax-pe-loading");
            pe.enhanceAllBtn.classList.remove("minimax-pe-loading");
        }
    };

    const header = el({
        display: "flex", justifyContent: "space-between", alignItems: "center",
        background: "#1a1d24", border: "1px solid #2a3140", borderRadius: "4px",
        padding: "6px 8px", cursor: "pointer", userSelect: "none", marginTop: "6px",
    });
    header.appendChild(el({ fontWeight: "600", fontSize: "10px", color: "#9aa3b5", textTransform: "uppercase" }, t("pe.title")));
    pe.arrow = el({ fontSize: "10px", color: "#9aa3b5" }, "\u25B6");
    header.appendChild(pe.arrow);

    pe.body = el({
        background: "#1a1d24", border: "1px solid #2a3140", borderTop: "none",
        borderRadius: "0 0 4px 4px", padding: "8px", display: "none",
        flexDirection: "column", gap: "6px", marginTop: "-5px",
    });
    pe.body.appendChild(el({ fontSize: "9px", color: "#7d8698", lineHeight: "1.4" },
        t("pe.panelDesc")));

    const fmtRow = el({});
    fmtRow.className = "minimax-pe-api-row";
    fmtRow.appendChild(el({}, "API:", "span")).className = "minimax-pe-label";
    pe.apiSelect = document.createElement("select");
    pe.apiSelect.className = "minimax-pe-select";
    for (const [val, label] of [
        [API_LOCAL, "Local (ComfyUI models)"],
        [API_OLLAMA, "Ollama (/api/chat)"],
        // The option value stays the API_ZHIPU enum; only the label translates.
        [API_ZHIPU, t("pe.apiZhipu")],
        [API_OPENAI_COMPAT, "OpenAI Compatible (/v1/chat/completions)"],
    ]) {
        const o = document.createElement("option");
        o.value = val; o.textContent = label;
        pe.apiSelect.appendChild(o);
    }
    pe.urlInput = document.createElement("input");
    pe.urlInput.type = "text";
    pe.urlInput.placeholder = DEFAULT_LLM_URL;
    pe.urlInput.className = "minimax-pe-input";
    pe.urlInput.oninput = () => {
        pe.apiSelect.value = inferApiFormat(pe.urlInput.value, pe.apiSelect.value);
        pe.updateApiFormatUI();
        pe.syncToWidgets();
    };
    swallowKeys(pe.urlInput);
    pe.apiSelect.onchange = () => {
        const d = defaultsForApiFormat(pe.apiSelect.value);
        pe.urlInput.value = d.url;
        if (!pe.modelInput.value.trim() || pe._lastApiFormat !== pe.apiSelect.value) {
            pe.modelInput.value = d.model;
        }
        pe._lastApiFormat = pe.apiSelect.value;
        pe.updateApiFormatUI();
        pe.syncToWidgets();
        pe.fetchModels();
    };
    fmtRow.appendChild(pe.apiSelect);
    fmtRow.appendChild(pe.urlInput);
    pe.refreshBtn = el({}, t("pe.refreshModels"), "button");
    pe.refreshBtn.className = "minimax-pe-btn-sm";
    pe.refreshBtn.onclick = () => pe.fetchModels();
    fmtRow.appendChild(pe.refreshBtn);
    pe.visionBadge = el({ fontSize: "9px", color: "#4ade80", flexShrink: "0", display: "none" });
    fmtRow.appendChild(pe.visionBadge);
    pe.body.appendChild(fmtRow);

    const compatRow = el({ display: "none", gap: "6px", alignItems: "center" });
    compatRow.appendChild(el({}, t("pe.compatLabel"), "span")).className = "minimax-pe-label";
    pe.compatSelect = document.createElement("select");
    pe.compatSelect.className = "minimax-pe-select";
    Object.assign(pe.compatSelect.style, { flex: "1" });
    for (const [val, label] of [
        // Values stay the stored literals; only the visible label is translated.
        [OPENAI_COMPAT_STANDARD, t("pe.compatStandard")],
        [OPENAI_COMPAT_LLAMA_SWAP, "llama-swap"],
    ]) {
        const o = document.createElement("option");
        o.value = val; o.textContent = label;
        pe.compatSelect.appendChild(o);
    }
    pe.compatSelect.title = t("pe.compatTip");
    pe.compatSelect.onchange = () => {
        pe.updateApiFormatUI();
        pe.syncToWidgets();
    };
    compatRow.appendChild(pe.compatSelect);
    pe.compatRow = compatRow;
    pe.body.appendChild(compatRow);

    const keyRow = el({ display: "flex", gap: "6px", alignItems: "center" });
    keyRow.dataset.r = "pe-key-row";
    keyRow.appendChild(el({}, "API Key:", "span")).className = "minimax-pe-label";
    pe.apiKeyInput = document.createElement("input");
    pe.apiKeyInput.type = "password";
    pe.apiKeyInput.placeholder = t("pe.keyPlaceholderZhipu");
    pe.apiKeyInput.autocomplete = "off";
    pe.apiKeyInput.className = "minimax-pe-input";
    Object.assign(pe.apiKeyInput.style, { flex: "1" });
    pe.apiKeyInput.oninput = () => pe.syncToWidgets();
    swallowKeys(pe.apiKeyInput);
    keyRow.appendChild(pe.apiKeyInput);
    pe.keyRow = keyRow;
    pe.body.appendChild(keyRow);

    const modelRow = el({ display: "flex", gap: "6px", alignItems: "center" });
    modelRow.appendChild(el({}, t("pe.modelLabel"), "span")).className = "minimax-pe-label";
    // The scan result goes into a real <select>, not a <datalist>.
    //
    // A datalist was the first attempt and it looked like a plain text box: its
    // suggestions only appear while typing, so the panel seemed to demand a
    // model name even though the scan had already found every local model. The
    // select makes the list the primary control and tags each entry with its
    // install state.
    pe.modelSelect = document.createElement("select");
    pe.modelSelect.className = "minimax-pe-select";
    Object.assign(pe.modelSelect.style, { flex: "1", display: "none" });
    pe.modelSelect.onchange = () => {
        if (pe.modelSelect.value === MODEL_CUSTOM_OPTION) {
            pe.setModelCustomMode(true);
            return;
        }
        pe.modelInput.value = pe.modelSelect.value;
        pe.syncToWidgets();
    };
    modelRow.appendChild(pe.modelSelect);
    // Escape hatch for names the scan cannot know: a remote backend, a server
    // that is not answering, or a GGUF outside the scanned folders.
    pe.modelInput = document.createElement("input");
    pe.modelInput.type = "text";
    pe.modelInput.placeholder = DEFAULT_LLM_MODEL;
    pe.modelInput.className = "minimax-pe-input";
    Object.assign(pe.modelInput.style, { flex: "1" });
    pe.modelInput.oninput = () => pe.syncToWidgets();
    swallowKeys(pe.modelInput);
    modelRow.appendChild(pe.modelInput);
    // Only visible while the text field is active; returns to the scanned list.
    pe.modelBackBtn = el({
        background: "#252a34", color: "#e8ecf4", border: "1px solid #2a3140",
        borderRadius: "4px", padding: "4px 8px", fontSize: "11px", cursor: "pointer",
        flexShrink: "0", display: "none",
    }, "\u25BE", "button");
    pe.modelBackBtn.title = t("pe.modelBackToList");
    pe.modelBackBtn.onclick = () => pe.setModelCustomMode(false);
    modelRow.appendChild(pe.modelBackBtn);
    pe.body.appendChild(modelRow);
    // Engine status (local format only). llama.cpp silently falls back to the
    // CPU when its GPU backend cannot load - typically a wheel built for a
    // different CUDA major - and that difference is 10-50x in speed, so it is
    // shown instead of left to the user to notice.
    pe.engineNote = el({ fontSize: "9px", color: "#7d8698", lineHeight: "1.4", display: "none" });
    pe.body.appendChild(pe.engineNote);

    const langRow = el({ display: "flex", gap: "6px", alignItems: "center" });
    langRow.appendChild(el({}, t("pe.outputLanguageLabel"), "span")).className = "minimax-pe-label";
    pe.langSelect = document.createElement("select");
    pe.langSelect.className = "minimax-pe-select";
    Object.assign(pe.langSelect.style, { flex: "1" });
    for (const [val, label] of [
        // Values are the literals the backend expects; only labels translate.
        ["English", t("pe.langEnglish")],
        [OUTPUT_LANGUAGE_ZH, t("pe.langZh")],
    ]) {
        const o = document.createElement("option");
        o.value = val; o.textContent = label;
        pe.langSelect.appendChild(o);
    }
    pe.langSelect.title = t("pe.outputLanguageTip");
    pe.langSelect.onchange = () => {
        pe._lastOutputLanguage = pe.langSelect.value || DEFAULT_OUTPUT_LANGUAGE;
        pe.syncToWidgets();
        pe.fetchTemplate(true);
    };
    langRow.appendChild(pe.langSelect);
    pe.body.appendChild(langRow);

    const AUTO_ENHANCE_TIP = t("pe.autoEnhanceTip");

    const optionsRow = el({});
    optionsRow.className = "minimax-pe-options-row";
    const detailItem = el({});
    detailItem.className = "minimax-pe-check-item";
    pe.detailCheck = document.createElement("input");
    pe.detailCheck.type = "checkbox";
    pe.detailCheck.checked = false;
    pe.detailCheck.title = t("pe.characterDetailTip");
    pe.detailCheck.onchange = () => pe.syncToWidgets();
    detailItem.appendChild(pe.detailCheck);
    const detailLabel = el({ cursor: "help" }, t("pe.characterDetail"), "span");
    detailLabel.title = pe.detailCheck.title;
    detailItem.appendChild(detailLabel);
    optionsRow.appendChild(detailItem);

    const autoItem = el({ cursor: "help" });
    autoItem.className = "minimax-pe-check-item";
    autoItem.title = AUTO_ENHANCE_TIP;
    pe.autoCheck = document.createElement("input");
    pe.autoCheck.type = "checkbox";
    pe.autoCheck.checked = false;
    pe.autoCheck.title = AUTO_ENHANCE_TIP;
    pe.autoCheck.onchange = () => pe.syncToWidgets();
    autoItem.appendChild(pe.autoCheck);
    const autoLabel = el({ cursor: "help" }, t("pe.autoEnhance"), "span");
    autoLabel.title = AUTO_ENHANCE_TIP;
    autoItem.appendChild(autoLabel);
    optionsRow.appendChild(autoItem);

    pe.unloadWrap = el({});
    pe.unloadWrap.className = "minimax-pe-check-item";
    pe.unloadCheck = document.createElement("input");
    pe.unloadCheck.type = "checkbox";
    pe.unloadCheck.onchange = () => pe.syncToWidgets();
    pe.unloadWrap.appendChild(pe.unloadCheck);
    pe.unloadCheckLabel = el({}, t("pe.unloadAfter"), "span");
    pe.unloadWrap.appendChild(pe.unloadCheckLabel);
    optionsRow.appendChild(pe.unloadWrap);

    // The enhancer is a general-purpose model: without these rules it will happily
    // write a beat into a line that repeats in every segment, or quote a word
    // outside a <d> block so the video model reads the whole prompt aloud. On by
    // default because "enhance correctly for this node" is the whole point.
    const H3_RULES_TIP = t("pe.h3RulesTip");
    const rulesItem = el({ cursor: "help" });
    rulesItem.className = "minimax-pe-check-item";
    rulesItem.title = H3_RULES_TIP;
    pe.h3RulesCheck = document.createElement("input");
    pe.h3RulesCheck.type = "checkbox";
    pe.h3RulesCheck.checked = true;
    pe.h3RulesCheck.title = H3_RULES_TIP;
    pe.h3RulesCheck.onchange = () => {
        savePeSettings({ h3Rules: !!pe.h3RulesCheck.checked });
        pe.setStatus(
            t("pe.statusH3Rules", {
                state: pe.h3RulesCheck.checked ? t("pe.h3RulesOn") : t("pe.h3RulesOff"),
            }),
            "info",
        );
    };
    rulesItem.appendChild(pe.h3RulesCheck);
    const rulesLabel = el({ cursor: "help" }, t("pe.h3Rules"), "span");
    rulesLabel.title = H3_RULES_TIP;
    rulesItem.appendChild(rulesLabel);
    optionsRow.appendChild(rulesItem);

    // The full contract is ~9k characters (~14k with a recipe). That is a lot of
    // prefill for a partially offloaded local model, and it is re-read on every
    // retry pass, so the same invariants ship in a condensed form too.
    const COMPACT_TIP = t("pe.h3CompactTip");
    const compactItem = el({ cursor: "help" });
    compactItem.className = "minimax-pe-check-item";
    compactItem.title = COMPACT_TIP;
    pe.h3CompactCheck = document.createElement("input");
    pe.h3CompactCheck.type = "checkbox";
    pe.h3CompactCheck.checked = false;
    pe.h3CompactCheck.title = COMPACT_TIP;
    pe.h3CompactCheck.onchange = () => {
        savePeSettings({ h3Compact: !!pe.h3CompactCheck.checked });
    };
    compactItem.appendChild(pe.h3CompactCheck);
    const compactLabel = el({ cursor: "help" }, t("pe.h3Compact"), "span");
    compactLabel.title = COMPACT_TIP;
    compactItem.appendChild(compactLabel);
    optionsRow.appendChild(compactItem);

    // Port of the Character Remake workflow: two vision captions (identity from the
    // reference images, action from the source frames) assembled into the block by
    // the pack itself. Structure stops being the model's job, which is what made
    // that workflow reliable where prompt rewriting was not.
    const IMAGES_TIP = t("pe.fromImagesTip");
    const imagesItem = el({ cursor: "help" });
    imagesItem.className = "minimax-pe-check-item";
    imagesItem.title = IMAGES_TIP;
    pe.fromImagesCheck = document.createElement("input");
    pe.fromImagesCheck.type = "checkbox";
    pe.fromImagesCheck.checked = false;
    pe.fromImagesCheck.title = IMAGES_TIP;
    pe.fromImagesCheck.onchange = () => {
        savePeSettings({ fromImages: !!pe.fromImagesCheck.checked });
        pe.setStatus(
            t("pe.statusFromImages", {
                state: pe.fromImagesCheck.checked ? t("pe.h3RulesOn") : t("pe.h3RulesOff"),
            }),
            "info",
        );
    };
    imagesItem.appendChild(pe.fromImagesCheck);
    const imagesLabel = el({ cursor: "help" }, t("pe.fromImages"), "span");
    imagesLabel.title = IMAGES_TIP;
    imagesItem.appendChild(imagesLabel);
    optionsRow.appendChild(imagesItem);

    // The action caption reads the raw source window, so a caption model can still
    // describe the performer being replaced. The original Character Remake workflow
    // inverted the subject region before captioning so there was no identity left to
    // describe; this does the same with a foreground mask.
    const HIDE_TIP = t("pe.hidePerformerTip");
    const hideItem = el({ cursor: "help" });
    hideItem.className = "minimax-pe-check-item";
    hideItem.title = HIDE_TIP;
    pe.hidePerformerCheck = document.createElement("input");
    pe.hidePerformerCheck.type = "checkbox";
    pe.hidePerformerCheck.checked = false;
    pe.hidePerformerCheck.title = HIDE_TIP;
    pe.hidePerformerCheck.onchange = () => {
        savePeSettings({ hidePerformer: !!pe.hidePerformerCheck.checked });
    };
    hideItem.appendChild(pe.hidePerformerCheck);
    const hideLabel = el({ cursor: "help" }, t("pe.hidePerformer"), "span");
    hideLabel.title = HIDE_TIP;
    hideItem.appendChild(hideLabel);
    optionsRow.appendChild(hideItem);
    pe.body.appendChild(optionsRow);

    // Which target shape the enhanced prompt must take. The official MiniMax
    // template always returns "instruction + description, one paragraph", which is
    // wrong for a replace window (no discard sentence, no role lines) - the recipe
    // says what this node actually needs. Auto keeps the previous behaviour for
    // anyone who never touches it.
    const recipeRow = el({ display: "flex", gap: "6px", alignItems: "center" });
    recipeRow.appendChild(el({}, t("pe.recipeLabel"), "span")).className = "minimax-pe-label";
    pe.recipeSelect = document.createElement("select");
    pe.recipeSelect.className = "minimax-pe-select";
    Object.assign(pe.recipeSelect.style, { flex: "1" });
    pe.recipeSelect.title = t("pe.recipeTip");
    const autoOption = document.createElement("option");
    autoOption.value = "auto";
    autoOption.textContent = t("pe.recipeAuto");
    pe.recipeSelect.appendChild(autoOption);
    pe.recipeSelect.onchange = () => {
        savePeSettings({ h3Recipe: pe.recipeSelect.value || "auto" });
        pe.updateRecipeNote();
    };
    recipeRow.appendChild(pe.recipeSelect);
    pe.body.appendChild(recipeRow);
    pe.recipeNote = el({ fontSize: "9px", color: "#7d8698", lineHeight: "1.4" });
    pe.body.appendChild(pe.recipeNote);
    pe.recipeOptions = [];

    // A RefMod window has no <Picture N> slots - its identity is appended after text
    // encoding - so "build from images" has nothing to caption unless the panel can
    // find the character itself. The mod file stores what it was built from, so the
    // backend decodes member 0 with the H3 video VAE; a folder or image path works
    // too. Only shown for the RefMod recipe, because only that one needs it.
    const refmodRow = el({ display: "none", gap: "6px", alignItems: "center" });
    refmodRow.appendChild(el({}, t("pe.refmodLabel"), "span")).className = "minimax-pe-label";
    pe.refmodInput = document.createElement("input");
    pe.refmodInput.className = "minimax-pe-input";
    Object.assign(pe.refmodInput.style, { flex: "1" });
    pe.refmodInput.placeholder = t("pe.refmodPlaceholder");
    pe.refmodInput.title = t("pe.refmodTip");
    pe.refmodInput.setAttribute("list", "minimax-pe-refmod-list");
    swallowKeys(pe.refmodInput);
    const refmodList = document.createElement("datalist");
    refmodList.id = "minimax-pe-refmod-list";
    // The datalist belongs to the document, not inside the input: an <input> is a
    // void element, so children appended to it are not a reliable place for it.
    pe.body.appendChild(refmodList);
    pe.refmodInput.onchange = () => {
        savePeSettings({ refmodCharacter: pe.refmodInput.value || "" });
    };
    refmodRow.appendChild(pe.refmodInput);
    pe.body.appendChild(refmodRow);
    pe.refmodRow = refmodRow;
    pe.refmodList = refmodList;

    /** RefMod names for the picker. Metadata only, so this stays cheap. */
    pe.loadRefmods = async () => {
        try {
            const resp = await api.fetchApi("/minimax/motion-director/refmod_list");
            if (!resp.ok) return;                       // older server: type the path
            const data = await resp.json();
            while (pe.refmodList.firstChild) pe.refmodList.removeChild(pe.refmodList.firstChild);
            for (const mod of data.mods || []) {
                if (!mod || !mod.id) continue;
                const option = document.createElement("option");
                option.value = mod.id;
                option.label = mod.pooled
                    ? t("pe.refmodPooled")
                    : (mod.description || mod.summary || "");
                pe.refmodList.appendChild(option);
            }
        } catch (e) {
            /* the field still accepts a typed name or path */
        }
    };

    /** Rebuild the dropdown from the pack's recipe list (server-owned keys). */
    pe.loadRecipes = async () => {
        if (!pe.recipeSelect) return;
        try {
            const resp = await api.fetchApi("/minimax/motion-director/enhance_recipes");
            if (!resp.ok) return;                       // older server: Auto only
            const data = await resp.json();
            const items = (data.recipes || []).filter((r) => r && r.key && r.key !== "auto");
            pe.recipeOptions = items;
            const keep = pe.recipeSelect.value || "auto";
            while (pe.recipeSelect.options.length > 1) pe.recipeSelect.remove(1);
            for (const item of items) {
                const option = document.createElement("option");
                option.value = item.key;
                // Locale label when one exists, else the pack's own English text
                // (t() returns the key unchanged when a translation is missing).
                const i18nKey = `pe.recipe.${item.key}`;
                const translated = t(i18nKey);
                option.textContent = translated === i18nKey ? item.label : translated;
                option.title = item.summary || "";
                pe.recipeSelect.appendChild(option);
            }
            pe.recipeSelect.value = keep;
            if (pe.recipeSelect.value !== keep) pe.recipeSelect.value = "auto";
            pe.updateRecipeNote();
        } catch (e) {
            /* the dropdown stays on Auto; enhancement is unaffected */
        }
    };

    pe.updateRecipeNote = () => {
        if (!pe.recipeNote) return;
        const key = pe.recipeSelect?.value || "auto";
        const item = pe.recipeOptions.find((r) => r.key === key);
        // The character field belongs to the RefMod recipe only: showing it for a
        // recipe that cannot use it would imply it does something.
        if (pe.refmodRow) pe.refmodRow.style.display = key === "character_replace_refmod" ? "flex" : "none";
        if (key === "auto") {
            pe.recipeNote.textContent = t("pe.recipeAutoTip");
            return;
        }
        // Summaries are pack-side English; translate when the locale has them.
        const i18nKey = `pe.recipe.${key}.summary`;
        const translated = t(i18nKey);
        pe.recipeNote.textContent = translated === i18nKey
            ? (item?.summary || "")
            : translated;
    };

    const btnRow = el({ display: "flex", gap: "6px", flexDirection: "column" });
    const enhanceRow = el({ display: "flex", gap: "6px" });
    pe.enhanceCurrentBtn = el({
        flex: "1", background: "#3b82f6", color: "#fff", border: "none", borderRadius: "4px",
        padding: "6px", fontWeight: "600", fontSize: "10px", cursor: "pointer",
    }, t("pe.enhanceCurrent"), "button");
    pe.enhanceCurrentBtn.onclick = () => pe.enhancePrompt("current");
    enhanceRow.appendChild(pe.enhanceCurrentBtn);
    pe.enhanceAllBtn = el({
        flex: "1", background: "#6366f1", color: "#fff", border: "none", borderRadius: "4px",
        padding: "6px", fontWeight: "600", fontSize: "10px", cursor: "pointer",
    }, t("pe.enhanceAll"), "button");
    pe.enhanceAllBtn.onclick = () => pe.enhancePrompt("all");
    enhanceRow.appendChild(pe.enhanceAllBtn);
    btnRow.appendChild(enhanceRow);
    const utilRow = el({ display: "flex", gap: "6px" });
    pe.unloadBtn = el({ background: "#252a34", color: "#e8ecf4", border: "1px solid #2a3140", borderRadius: "4px", padding: "6px 10px", fontSize: "10px", cursor: "pointer" }, t("pe.unloadNow"), "button");
    pe.unloadBtn.onclick = () => pe.unloadOllama();
    utilRow.appendChild(pe.unloadBtn);
    pe.unloadBtnRow = utilRow;
    btnRow.appendChild(utilRow);
    pe.body.appendChild(btnRow);

    pe.statusEl = el({ fontSize: "10px", color: STATUS_COLORS.info, minHeight: "16px", padding: "2px 0" });
    pe.body.appendChild(pe.statusEl);

    pe.dlBar = el({});
    pe.dlBar.className = "minimax-pe-dlbar";
    pe.dlFill = el({});
    pe.dlFill.className = "minimax-pe-dlfill";
    pe.dlBar.appendChild(pe.dlFill);
    pe.body.appendChild(pe.dlBar);

    pe.templateArea = document.createElement("textarea");
    pe.templateArea.rows = 4;
    Object.assign(pe.templateArea.style, { width: "100%", fontSize: "9px", display: "none", background: "#12151b", color: "#d6dbe6", border: "1px solid #2a3140", borderRadius: "3px" });
    pe.templateArea.oninput = () => pe.syncToWidgets();
    swallowKeys(pe.templateArea);
    pe.body.appendChild(pe.templateArea);

    header.onclick = () => {
        pe.open = !pe.open;
        pe.body.style.display = pe.open ? "flex" : "none";
        pe.arrow.style.transform = pe.open ? "rotate(90deg)" : "";
        editor.updateDomWidgetHeight?.();
        if (pe.open && !pe.modelChoices.length) pe.fetchModels(true);
    };

    parentEl.appendChild(header);
    parentEl.appendChild(pe.body);

    pe.widget = (name) => editor.widget(name);

    /**
     * The model control: a select of everything the last scan found, plus a text
     * field for names the scan cannot know.
     *
     * One control is visible at a time. The select is the default - it is how
     * the user learns what is installed and what a missing model would cost to
     * download - and the text field is reached through the trailing entry, then
     * left again with the small arrow button. Showing a select that disagrees
     * with the value actually being sent would be worse than either one alone.
     */
    pe.modelEntryId = (item) => (typeof item === "string" ? item : (item?.id || ""));

    pe.modelEntryLabel = (item) => {
        if (typeof item === "string") return item;
        const tags = [];
        if (item.installed) tags.push(t("pe.modelInstalledTag"));
        else if (item.downloadable) tags.push(t("pe.modelDownloadTag"));
        const base = item.label || item.filename || item.id || "";
        return tags.length ? `${base} · ${tags.join(" · ")}` : base;
    };

    pe.refreshModelRow = () => {
        const select = pe.modelSelect;
        const input = pe.modelInput;
        if (!select || !input) return;
        const choices = pe.modelChoices || [];
        if (pe._modelCustomMode || !choices.length) {
            // No scan yet (or a remote backend returned nothing): the text field
            // is the only control that can hold a name.
            select.style.display = "none";
            input.style.display = "";
            pe.modelBackBtn.style.display = pe._modelCustomMode && choices.length ? "" : "none";
            return;
        }
        // Installed entries first - that is what a render can use right now. The
        // sort is stable, so the backend's ordering survives inside each group.
        const ordered = [...choices].sort(
            (a, b) => Number(!a?.installed) - Number(!b?.installed),
        );
        select.innerHTML = "";
        const addOption = (value, label) => {
            const option = document.createElement("option");
            option.value = value;
            option.textContent = label;
            select.appendChild(option);
        };
        addOption("", t("pe.modelAutoOption"));
        for (const item of ordered) addOption(pe.modelEntryId(item), pe.modelEntryLabel(item));
        // A stored value the scan does not list (typed earlier, or known only to
        // the backend) keeps its own entry, so the select never shows a
        // different model than the one that will be sent.
        const value = (input.value || "").trim();
        if (value && !ordered.some((item) => pe.modelEntryId(item) === value)) {
            addOption(value, t("pe.modelCustomEntry", { name: value }));
        }
        addOption(MODEL_CUSTOM_OPTION, t("pe.modelCustomOption"));
        select.value = value || "";
        select.style.display = "";
        input.style.display = "none";
        pe.modelBackBtn.style.display = "none";
    };

    pe.setModelCustomMode = (on) => {
        pe._modelCustomMode = !!on;
        pe.refreshModelRow();
        if (on) pe.modelInput.focus();
    };

    pe.updateEngineNote = () => {
        const note = pe.engineNote;
        if (!note) return;
        const engine = pe._engineInfo;
        if (pe.apiSelect?.value !== API_LOCAL || !engine) {
            note.style.display = "none";
            return;
        }
        let text = "";
        let color = "#7d8698";
        let withLink = false;
        if (pe._runtimeAvailable === false) {
            text = t("pe.engineMissing");
            color = STATUS_COLORS.error;
            withLink = true;
        } else if (engine.gpu === true) {
            text = t("pe.engineGpu", { backend: String(engine.backend || "").toUpperCase() });
            color = STATUS_COLORS.success;
        } else if (engine.gpu === false || !(engine.shipped || []).length) {
            text = t("pe.engineCpu");
            color = "#fbbf24";
            withLink = true;
        } else {
            // GPU build present but no load has happened yet: nothing to claim.
            note.style.display = "none";
            return;
        }
        note.replaceChildren();
        note.appendChild(el({}, text, "span"));
        if (withLink) {
            const anchor = el(
                { marginLeft: "4px", color: "#8ab4f8", textDecoration: "underline", cursor: "pointer" },
                t("pe.engineSetupLink"),
                "a",
            );
            anchor.href = engine.doc_url || "#";
            anchor.target = "_blank";
            anchor.rel = "noreferrer";
            note.appendChild(anchor);
            note.title = t("pe.engineTip");
        } else {
            note.title = "";
        }
        note.style.color = color;
        note.style.display = "";
    };

    pe.supportsUnload = () => {
        const fmt = pe.apiSelect.value;
        // Local models are resident in ComfyUI's process, so unloading is
        // meaningful for them too - it is how VRAM is handed back to the render.
        return fmt === API_OLLAMA
            || fmt === API_LOCAL
            || (fmt === API_OPENAI_COMPAT && normalizeOpenAiCompatMode(pe.compatSelect?.value) === OPENAI_COMPAT_LLAMA_SWAP);
    };

    pe.updateApiFormatUI = () => {
        const fmt = pe.apiSelect.value;
        const isOpenAi = fmt === API_OPENAI_COMPAT;
        const isLocal = fmt === API_LOCAL;
        const showKey = fmt === API_ZHIPU || isOpenAi;
        const supportsUnload = pe.supportsUnload();
        // Local mode talks to no server, so the URL row would be a lie. Hide it
        // rather than leave a field that silently does nothing.
        if (pe.urlInput) pe.urlInput.style.display = isLocal ? "none" : "";
        if (pe.compatRow) pe.compatRow.style.display = isOpenAi ? "flex" : "none";
        if (pe.keyRow) pe.keyRow.style.display = showKey ? "flex" : "none";
        if (pe.apiKeyInput) {
            pe.apiKeyInput.placeholder = fmt === API_ZHIPU
                ? t("pe.keyPlaceholderZhipu")
                : t("pe.keyPlaceholderOpenAi");
        }
        if (pe.unloadWrap) pe.unloadWrap.style.display = supportsUnload ? "flex" : "none";
        if (pe.unloadBtnRow) pe.unloadBtnRow.style.display = supportsUnload ? "flex" : "none";
        // The unload labels no longer vary by backend: one wording each is set at
        // creation time, and the active backend is already visible in the API
        // dropdown. Nothing here to re-word per format.
        pe.urlInput.placeholder = defaultsForApiFormat(fmt).url;
        pe.modelInput.placeholder = defaultsForApiFormat(fmt).model;
        pe.refreshModelRow();
        pe.updateEngineNote();
    };

    pe.syncFromWidgets = () => {
        const w = (n) => pe.widget(n);
        // Stored settings win; the named widgets are read as a fallback so this
        // keeps working if llm_* widgets are ever declared on the node.
        const stored = loadPeSettings();
        const explicitFmt = stored.apiFormat || w("llm_api_format")?.value || DEFAULT_API_FORMAT;
        const fmt = inferApiFormat(stored.url || w("llm_url")?.value, explicitFmt);
        const url = coerceLlmUrl(stored.url || w("llm_url")?.value, defaultsForApiFormat(fmt).url);
        pe.urlInput.value = url;
        pe.apiSelect.value = fmt;
        pe._lastApiFormat = pe.apiSelect.value;
        if (pe.compatSelect) {
            pe.compatSelect.value = normalizeOpenAiCompatMode(
                stored.openaiCompatMode || w("llm_openai_compat_mode")?.value,
            );
        }
        // Leave the field empty when nothing is stored: for local mode the real
        // default comes from the catalog, and coerceLlmModel would otherwise
        // substitute the stale remote default name.
        const storedModel = stored.model || w("llm_model")?.value;
        pe.modelInput.value = storedModel ? coerceLlmModel(storedModel) : "";
        if (w("llm_api_key")) pe.apiKeyInput.value = w("llm_api_key").value || "";
        if (w("llm_auto_enhance")) pe.autoCheck.checked = !!w("llm_auto_enhance").value;
        else pe.autoCheck.checked = false;
        if (w("llm_unload_after")) pe.unloadCheck.checked = !!w("llm_unload_after").value;
        // Multi-line safety rules for the H3 engine; on unless the user turned them
        // off (stored `false`), so a fresh install gets them without a click.
        if (pe.h3RulesCheck) {
            pe.h3RulesCheck.checked = stored.h3Rules === undefined ? true : !!stored.h3Rules;
        }
        if (pe.fromImagesCheck) {
            pe.fromImagesCheck.checked = !!stored.fromImages;
        }
        if (pe.h3CompactCheck) {
            pe.h3CompactCheck.checked = !!stored.h3Compact;
        }
        if (pe.hidePerformerCheck) {
            pe.hidePerformerCheck.checked = !!stored.hidePerformer;
        }
        if (pe.refmodInput) pe.refmodInput.value = stored.refmodCharacter || "";
        if (pe.recipeSelect) {
            pe.recipeSelect.value = stored.h3Recipe || "auto";
            if (!stored.h3Recipe && pe.recipeSelect.options.length === 1) {
                // Options not loaded yet; Auto is already selected by construction.
                pe.recipeSelect.value = "auto";
            }
            pe.updateRecipeNote?.();
        }
        const lang = resolveOutputLanguage(pe);
        const prevLang = pe._lastOutputLanguage;
        pe._lastOutputLanguage = lang;
        if (pe.detailCheck) {
            pe.detailCheck.checked = resolveCharacterFeatureEnhance(pe, { preferWidget: true });
        }
        if (w("llm_custom_template")) pe.templateArea.value = w("llm_custom_template").value || "";
        pe.updateApiFormatUI();
        if (prevLang !== null && lang !== prevLang) pe.fetchTemplate(true);
    };

    pe.syncToWidgets = () => {
        const set = (n, v) => { const w = pe.widget(n); if (w) w.value = v; };
        const url = coerceLlmUrl(pe.urlInput.value, defaultsForApiFormat(pe.apiSelect.value).url);
        set("llm_api_format", pe.apiSelect.value);
        set("llm_openai_compat_mode", normalizeOpenAiCompatMode(pe.compatSelect?.value));
        set("llm_url", url);
        set("llm_api_key", pe.apiKeyInput.value || "");
        set("llm_model", pe.resolveModelForSend());
        set("llm_output_language", pe.langSelect.value || DEFAULT_OUTPUT_LANGUAGE);
        set("llm_character_feature_enhance", !!pe.detailCheck?.checked);
        set("llm_auto_enhance", !!pe.autoCheck.checked);
        set("llm_unload_after", pe.supportsUnload() && !!pe.unloadCheck.checked);
        const custom = pe.templateArea.value.trim();
        set("llm_custom_template", custom !== pe._currentDefaultTemplate ? custom : "");
        savePeSettings({
            apiFormat: pe.apiSelect.value,
            url: pe.urlInput.value || "",
            model: pe.resolveModelForSend(),
            openaiCompatMode: normalizeOpenAiCompatMode(pe.compatSelect?.value),
            outputLanguage: pe.langSelect.value || DEFAULT_OUTPUT_LANGUAGE,
        });
        editor._markNodeDirtyLight?.();
    };

    pe.fetchModels = async (silent = false) => {
        if (pe._busy) return;
        try {
            const llmUrl = coerceLlmUrl(pe.urlInput.value, defaultsForApiFormat(pe.apiSelect.value).url);
            pe.urlInput.value = llmUrl;
            pe.apiSelect.value = inferApiFormat(llmUrl, pe.apiSelect.value);
            pe.updateApiFormatUI();
            if (!silent) pe.setStatus(t("pe.statusFetchingModels"), "loading");
            const resp = await api.fetchApi("/minimax/motion-director/enhance_models", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    llm_url: llmUrl, api_format: pe.apiSelect.value,
                    openai_compat_mode: normalizeOpenAiCompatMode(pe.compatSelect?.value),
                    api_key: pe.apiKeyInput.value || "",
                }),
            });
            const data = await resp.json();
            if (!resp.ok) {
                if (!silent) pe.setStatus(data.error || t("pe.statusFetchModelsFailed"), "error");
                return;
            }
            // The local backend returns objects (with install state and download
            // size); remote backends return plain names. Both feed the select;
            // entries without a usable id would render as an empty option.
            const entries = (data.models || []).filter((item) => pe.modelEntryId(item));
            pe.modelChoices = entries;
            pe._localModels = entries.length && typeof entries[0] === "object" ? entries : null;
            if (data.resolved_default) pe._localDefaultModel = data.resolved_default;
            // Self-heal a stored value that no longer exists locally. An earlier
            // build persisted the remote default ("qwen3.5") for local mode, and
            // that name is not a file on disk - so a persisted-but-bogus model
            // must be replaced, not merely ignored, or it survives every reload.
            if (pe._localModels) {
                const current = (pe.modelInput.value || "").trim();
                const known = !current || pe._localModels.some(
                    (m) => m.id === current || m.filename === current || m.path === current || m.label === current,
                );
                if (!known) pe.modelInput.value = data.resolved_default || "";
            }
            if (!pe.modelInput.value.trim() && data.resolved_default) {
                pe.modelInput.value = data.resolved_default;
            }
            if (!pe.modelInput.value.trim()) {
                pe.modelInput.value = defaultsForApiFormat(pe.apiSelect.value).model;
            }
            pe.refreshModelRow();
            pe._runtimeAvailable = data.runtime_available !== false;
            pe._engineInfo = data.engine || null;
            pe.updateEngineNote();
            // A 20 GB pull survives a page reload (it runs server-side), so the bar
            // has to come back on its own rather than only for a click in this tab.
            if (pe._localModels) void pe.adoptRunningDownload();
            // Recipe options are served by the pack, so the dropdown and the
            // backend list cannot drift apart.
            void pe.loadRecipes();
            void pe.loadRefmods();
            const count = entries.length;
            const localNote = pe._localModels
                ? ` · ${data.installed_count || 0} installed${data.runtime_available ? "" : " · llama.cpp missing"}`
                : "";
            if (!silent) pe.setStatus(t("pe.statusModelCount", { count, note: localNote }), "success");
            pe.syncToWidgets();
        } catch (e) {
            if (!silent) pe.setStatus(t("pe.statusConnectFailed", { error: e.message }), "error");
        }
    };

    pe.fetchTemplate = async (resetIfDefault = false) => {
        const task = resolveTaskKey(editor.getTaskKey?.() || "rv2v");
        const outputLanguage = resolveOutputLanguage(pe);
        try {
            const resp = await api.fetchApi("/minimax/motion-director/get_template", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ task_type: task, output_language: outputLanguage }),
            });
            const data = await resp.json();
            if (data.template) {
                pe._currentDefaultTemplate = data.template;
                if (resetIfDefault || !pe.templateArea.value || pe.templateArea.value === pe._lastFetchedTemplate) {
                    pe.templateArea.value = data.template;
                }
                pe._lastFetchedTemplate = data.template;
            }
        } catch (e) { /* ignore */ }
    };

    pe.getPromptBlock = (segmentIndex = null) => {
        if (editor.isGlobalMode?.()) {
            editor.timeline.global = editor.timeline.global || {};
            return { block: editor.timeline.global, taskKey: resolveTaskKey(editor.getTaskKey?.() || "rv2v"), isGlobal: true };
        }
        const idx = segmentIndex ?? editor.selectedIndex ?? 0;
        const seg = editor.timeline.segments?.[idx];
        const global = editor.timeline.global || {};
        const taskKey = resolveTaskKey(seg?.taskType || global.taskType || editor.getTaskKey?.() || "rv2v");
        return { block: seg || global, taskKey, isGlobal: false, segmentIndex: idx };
    };

    pe.getPromptTextForBlock = (segmentIndex = null) => {
        if (editor.isGlobalMode?.()) {
            return (editor.globalPrompt?.value || editor.timeline.global?.prompt || editor.globalPromptWidget?.value || "").trim();
        }
        const idx = segmentIndex ?? editor.selectedIndex ?? 0;
        const seg = editor.timeline.segments?.[idx];
        const globalPrompt = (editor.timeline.global?.prompt || editor.globalPrompt?.value || "").trim();
        return (seg?.prompt || globalPrompt || "").trim();
    };

    /**
     * Push the editor's displayed prompt textarea to `text`, through whatever owns it.
     *
     * Both prompt textareas are wrapped by a mention controller
     * (`minimax_prompt_mentions.js`), which keeps its own rich state and re-renders the
     * textarea from it. Writing `.value` directly leaves that state stale, so the next
     * `getValue()` / `refresh()` puts the OLD text back over the enhancement - a
     * finished enhancement that appears to do nothing, with no error anywhere. The
     * controller's `setValue` updates both sides at once.
     */
    pe.setDisplayedPromptText = (textarea, text) => {
        const controller = textarea?._mmxMentionController;
        if (controller?.setValue) controller.setValue(text);
        else if (textarea) textarea.value = text;
    };

    pe.setPromptTextForBlock = (text, segmentIndex = null) => {
        if (editor.isGlobalMode?.()) {
            editor.timeline.global = editor.timeline.global || {};
            editor.timeline.global.prompt = text;
            pe.setDisplayedPromptText(editor.globalPrompt, text);
            if (editor.globalPromptWidget) editor.globalPromptWidget.value = text;
            return;
        }
        const idx = segmentIndex ?? editor.selectedIndex ?? 0;
        const seg = editor.timeline.segments?.[idx];
        if (seg) seg.prompt = text;
        if (idx === editor.selectedIndex && editor.segPrompt) {
            pe.setDisplayedPromptText(editor.segPrompt, text);
        }
    };

    pe.getActivePromptText = () => pe.getPromptTextForBlock();

    pe.setActivePromptText = (text) => {
        pe.setPromptTextForBlock(text);
        editor.commit?.(false, { syncTimeline: true });
    };

    /**
     * The model value to send for the current backend.
     *
     * Local mode must not fall back to coerceLlmModel(): that substitutes the
     * remote default ("qwen3.5"), which is not a file on disk, so an untouched
     * field produced "Local model 'qwen3.5' is not on disk" for every request.
     * An empty value is correct here - the server resolves it from the catalog,
     * preferring an installed model over one that would need downloading.
     */
    pe.resolveModelForSend = () => {
        const typed = (pe.modelInput?.value || "").trim();
        if (typed) return typed;
        if (pe.apiSelect?.value === API_LOCAL) {
            return (pe._localDefaultModel || "").trim();
        }
        return coerceLlmModel(typed);
    };

    pe.getLlmConfig = () => {
        if (pe.detailCheck) {
            pe.detailCheck.checked = resolveCharacterFeatureEnhance(pe, { preferWidget: true });
        }
        pe.syncToWidgets();
        const llmUrl = coerceLlmUrl(pe.urlInput.value, defaultsForApiFormat(pe.apiSelect.value).url);
        pe.urlInput.value = llmUrl;
        pe.apiSelect.value = inferApiFormat(llmUrl, pe.apiSelect.value);
        pe.updateApiFormatUI();
        const model = pe.resolveModelForSend();
        if (model) pe.modelInput.value = model;
        pe.refreshModelRow();
        const outputLanguage = resolveOutputLanguage(pe);
        const characterFeatureEnhance = resolveCharacterFeatureEnhance(pe, { preferWidget: true });
        const customTemplate = pe.templateArea.value.trim() !== pe._currentDefaultTemplate ? pe.templateArea.value.trim() : "";
        return {
            llmUrl, model, apiFormat: pe.apiSelect.value,
            openaiCompatMode: normalizeOpenAiCompatMode(pe.compatSelect?.value),
            apiKey: pe.apiKeyInput.value || "",
            outputLanguage,
            characterFeatureEnhance,
            customTemplate,
        };
    };

    pe.collectVisionImagesForBlock = async (block, taskKey) => {
        const images = [];
        let sourceCount = 0;
        let refCount = 0;
        const refSlots = [];
        const video = editor.timeline?.video || {};
        const videoFile = video.videoFile || video.fileName;
        const isOllama = pe.apiSelect?.value === API_OLLAMA;
        const sourceFrameCount = isOllama ? 2 : 3;
        if (videoFile && editor.getDirectorMode?.() === "video") {
            const resp = await api.fetchApi("/minimax/motion-director/extract_frames", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    filename: videoFile,
                    subfolder: video.subfolder || "",
                    num_frames: sourceFrameCount,
                }),
            });
            const data = await resp.json();
            if (data.frames?.length) { sourceCount = data.frames.length; images.push(...data.frames); }
        }
        const global = editor.timeline.global || {};
        const refsBlock = block || global;
        if (taskUsesReferenceImages(taskKey) && refsBlock?.refs?.length) {
            const sortedRefs = [...refsBlock.refs]
                .filter((r) => r.imageFile || r.imageB64)
                .sort((a, b) => Number(a.index ?? a.slot ?? 0) - Number(b.index ?? b.slot ?? 0));
            for (const ref of sortedRefs) {
                const slot = Number(ref.index ?? ref.slot ?? 0);
                if (ref.imageFile) {
                    const b64 = await fetchImageB64(ref.imageFile);
                    if (b64) { images.push(b64); refCount += 1; refSlots.push(slot); }
                } else if (ref.imageB64) {
                    images.push(ref.imageB64.startsWith("data:") ? ref.imageB64.split(",", 2)[1] : ref.imageB64);
                    refCount += 1;
                    refSlots.push(slot);
                }
            }
        }
        let refVideoCount = 0;
        if (taskUsesReferenceVideo(taskKey)) {
            const rv = refsBlock?.referenceVideo || global.referenceVideo || {};
            const refVid = rv.videoFile || rv.fileName;
            if (refVid) {
                const resp = await api.fetchApi("/minimax/motion-director/extract_frames", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        filename: refVid,
                        subfolder: rv.subfolder || "",
                        num_frames: isOllama ? 1 : 2,
                    }),
                });
                const data = await resp.json();
                if (data.frames?.length) {
                    refVideoCount = data.frames.length;
                    images.push(...data.frames);
                }
            }
        }
        // i2v and fl2v supply their frames as the segment's own endpoint images
        // rather than as reference slots, so nothing above sends them. They travel in
        // their own list: appending them to `images` would put them in the reference
        // slice and leak the start frame into a caption that must not see it.
        const frameImages = await pe.collectEndpointFrames(refsBlock, taskKey);
        return { images, sourceCount, refCount, refSlots, refVideoCount, frameImages };
    };

    /** The fixed endpoint frames of an i2v / fl2v segment, as base64 JPEG. */
    pe.collectEndpointFrames = async (block, taskKey) => {
        const out = [];
        const pick = async (ref) => {
            const file = ref?.imageFile || ref?.fileName || (typeof ref === "string" ? ref : "");
            const inline = ref?.imageB64 || "";
            if (inline) {
                return inline.startsWith("data:") ? inline.split(",", 2)[1] : inline;
            }
            if (!file) return "";
            try {
                return (await fetchImageB64(file)) || "";
            } catch (e) {
                return "";
            }
        };
        const wanted = [];
        if (taskKey === "i2v") {
            // The image batch keeps the start frame on the segment as `genImage`,
            // with `imageFile` as the legacy spelling.
            wanted.push(block?.genImage || block?.imageFile ? (block.genImage || { imageFile: block.imageFile }) : null);
        } else if (taskKey === "fl2v") {
            wanted.push(block?.startImage || (block?.firstImageFile ? { imageFile: block.firstImageFile } : null));
            wanted.push(block?.endImage || (block?.lastImageFile ? { imageFile: block.lastImageFile } : null));
        }
        for (const ref of wanted) {
            if (!ref) continue;
            const b64 = await pick(ref);
            if (b64) out.push(b64);
            else out.push("");   // keep start/end positions aligned
        }
        // Drop a wholly empty result so the server sees "no frames" rather than a
        // list of empty strings.
        return out.some((item) => item) ? out : [];
    };

    const DOWNLOAD_POLL_MS = 1000;

    const formatDownloadBytes = (value) => {
        const bytes = Number(value) || 0;
        if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
        if (bytes >= 1e6) return `${Math.round(bytes / 1e6)} MB`;
        return `${Math.max(0, Math.round(bytes / 1e3))} KB`;
    };

    const formatDownloadEta = (seconds) => {
        const total = Math.max(1, Math.round(Number(seconds) || 0));
        if (total < 60) return `${total}s`;
        const minutes = Math.floor(total / 60);
        const rest = total % 60;
        return rest ? `${minutes}m ${rest}s` : `${minutes}m`;
    };

    pe.hideDownloadProgress = () => {
        pe.dlBar.style.display = "none";
        pe.dlFill.classList.remove("minimax-pe-loading");
        pe.dlFill.style.width = "0%";
    };

    /** Paint one /download_status payload; also decides when to stop polling. */
    pe.renderDownloadProgress = (data) => {
        if (!data || !data.active) {
            pe.hideDownloadProgress();
            return false;
        }
        const percent = typeof data.percent === "number" ? data.percent : null;
        const label = data.label || pe._downloadEntryLabel || "";
        pe.dlBar.style.display = "block";
        // Unknown total (a download that started before this page loaded) gets the
        // pulsing full-width fill instead of a stale or fake percentage. The inline
        // width has to be cleared, not set to 0, or it beats the class rule.
        pe.dlFill.classList.toggle("minimax-pe-loading", percent == null);
        if (percent == null) {
            pe.dlFill.style.removeProperty("width");
        } else {
            pe.dlFill.style.width = `${Math.max(0, Math.min(100, percent))}%`;
        }
        const phase = data.phase === "vision" ? t("pe.downloadVisionPhase") : "";
        const eta = data.eta_seconds ? t("pe.downloadEta", { eta: formatDownloadEta(data.eta_seconds) }) : "";
        if (percent == null) {
            pe.setStatus(t("pe.statusDownloadUnknown", { done: formatDownloadBytes(data.bytes) }) + phase, "loading");
        } else {
            pe.setStatus(
                t("pe.statusDownloadProgress", {
                    label,
                    percent: Math.round(percent),
                    done: formatDownloadBytes(data.bytes),
                    total: formatDownloadBytes(data.expected_bytes),
                }) + phase + eta,
                "loading",
            );
        }
        return true;
    };

    /** Fetch, paint, and return one progress payload (null when unavailable). */
    pe.pollDownloadStatus = async () => {
        try {
            const resp = await api.fetchApi("/minimax/motion-director/download_status");
            // An older ComfyUI (route not registered yet) answers 404: keep the
            // plain "Downloading ..." text instead of failing the download flow.
            if (!resp.ok) return null;
            const data = await resp.json();
            pe.renderDownloadProgress(data);
            return data;
        } catch (e) {
            // A dropped poll must not hide a running bar: the transfer lives in a
            // server thread and is unaffected by one failed request.
            return null;
        }
    };

    /**
     * Poll the download progress until told to stop.
     *
     * `selfStop` is for a download this panel did not start (page reloaded while
     * one was running): there is no request to await, so the first inactive status
     * is the end of it. When the panel owns the request, the caller stops the
     * monitor itself - the poll can legitimately see "nothing yet" before the
     * server has registered the transfer.
     */
    pe.startDownloadMonitor = (entry, { selfStop = false } = {}) => {
        pe._downloadEntryLabel = entry?.label || "";
        pe._downloadMonitor = true;
        pe._downloadSelfStop = !!selfStop;
        clearTimeout(pe._downloadTimer);
        const tick = async () => {
            if (!pe._downloadMonitor) return;
            const data = await pe.pollDownloadStatus();
            if (!pe._downloadMonitor) return;
            if (pe._downloadSelfStop && data && !data.active) {
                pe.stopDownloadMonitor();
                return;
            }
            pe._downloadTimer = setTimeout(tick, DOWNLOAD_POLL_MS);
        };
        void tick();
    };

    pe.stopDownloadMonitor = () => {
        pe._downloadMonitor = false;
        pe._downloadSelfStop = false;
        clearTimeout(pe._downloadTimer);
        pe.hideDownloadProgress();
    };

    /** Adopt a download that was already running when this page loaded. */
    pe.adoptRunningDownload = async () => {
        if (pe._downloadMonitor) return;
        const data = await pe.pollDownloadStatus();
        if (!data?.active) return;
        pe.startDownloadMonitor({ label: data.label || "" }, { selfStop: true });
    };

    /**
     * Make sure the selected local model is on disk, offering to fetch it.
     *
     * Returns true when the caller may proceed. The size is always shown before
     * anything is downloaded: pulling 13 GB without consent is not a reasonable
     * thing to do on someone's connection, and the server refuses an
     * unconfirmed request for the same reason.
     */
    pe.ensureLocalModel = async (modelId) => {
        const entries = pe._localModels;
        if (!entries) return true; // remote backend: nothing to download
        const entry = entries.find(
            (m) => m.id === modelId || m.filename === modelId || (m.path && m.path === modelId),
        );
        if (!entry || entry.installed || !entry.downloadable) return true;

        const totalGb = ((entry.size_bytes || 0) + (entry.vision ? entry.mmproj_size_bytes || 0 : 0)) / 1e9;
        const pretty = totalGb ? `${totalGb.toFixed(1)} GB` : "an unknown size";
        const ok = window.confirm(
            `${entry.label}\n\nThis model is not on disk yet.\n`
            + `Download ${pretty} into ComfyUI's models/LLM folder now?\n\n`
            + "The first download can take a while.",
        );
        if (!ok) {
            pe.setStatus(t("pe.statusDownloadCancelled"), "info");
            return false;
        }

        pe.setStatus(t("pe.statusDownloading", { label: entry.label }), "loading");
        let resp = null;
        let data = {};
        try {
            // The download route blocks for the whole transfer, so the request is
            // started without awaiting it while the monitor polls the server-side
            // byte count; the bar would show nothing otherwise.
            const started = api.fetchApi("/minimax/motion-director/download_model", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ model: entry.id, confirm: true }),
            });
            pe.startDownloadMonitor(entry);
            resp = await started;
            data = await resp.json();
            if (!resp.ok || data.error) {
                pe.setStatus(t("pe.statusDownloadFailed", { error: data.error || resp.status }), "error");
                return false;
            }
            pe.setStatus(t("pe.statusDownloaded", { label: entry.label }), "success");
            // Re-list so the entry flips to installed and the default resolves.
            await pe.fetchModels(true);
            return true;
        } catch (e) {
            pe.setStatus(t("pe.statusDownloadFailed", { error: e.message }), "error");
            return false;
        } finally {
            pe.stopDownloadMonitor();
        }
    };

    pe.callEnhanceApi = async (prompt, taskKey, block, cfg) => {
        let images = []; let refCount = 0; let sourceCount = 0; let refSlots = []; let refVideoCount = 0;
        let frameImages = [];
        // The window's audio policy lives in the segment's replace spec; passing it
        // saves the model from guessing between "keep the source track" (no <d>
        // lines) and "generate the audio" (full cue block).
        const audioPolicy = String(block?.replace?.audio_policy || "").trim();
        // Fetch the model before paying for vision frame extraction.
        if (!(await pe.ensureLocalModel(cfg.model))) {
            return null;
        }
        // Batch runs set skipVision: gathering reference frames per block is slow
        // and would dominate a multi-segment run. Single-prompt enhancement keeps
        // the full vision path.
        try {
            if (!cfg?.skipVision) {
                ({
                    images, refCount, sourceCount, refSlots, refVideoCount, frameImages,
                } = await pe.collectVisionImagesForBlock(block, taskKey));
            }
        } catch (e) {
            console.warn("[MiniMax H3 PE] vision collect failed:", e);
        }
        const resp = await api.fetchApi("/minimax/motion-director/enhance", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    llm_url: cfg.llmUrl, model: cfg.model, prompt, task_type: taskKey,
                    image_num: Math.max(1, refCount), images, api_format: cfg.apiFormat,
                    openai_compat_mode: cfg.openaiCompatMode,
                    api_key: cfg.apiKey, output_language: cfg.outputLanguage,
                    character_feature_enhance: cfg.characterFeatureEnhance,
                    source_count: sourceCount, ref_slots: refSlots, ref_video_count: refVideoCount,
                    llm_unload_after: pe.supportsUnload() && !!pe.unloadCheck.checked, custom_template: cfg.customTemplate,
                    h3_rules: !!pe.h3RulesCheck?.checked,
                    h3_rules_compact: !!pe.h3CompactCheck?.checked,
                    hide_performer: !!pe.hidePerformerCheck?.checked,
                    frame_images: frameImages,
                    h3_recipe: pe.recipeSelect?.value || "auto",
                    prompt_mode: pe.fromImagesCheck?.checked ? "captions" : "rewrite",
                    audio_policy: audioPolicy,
                    // Only meaningful for the RefMod recipe, and only a hint: the
                    // server resolves it and says so in the note when it cannot.
                    refmod_character: pe.refmodInput?.value || "",
                }),
        });
        let data = {};
        try { data = await resp.json(); } catch { data = {}; }
        return {
            ok: resp.ok && !!data.response,
            text: data.response || "",
            error: data.error || (resp.ok ? t("pe.errorEmptyResponse") : `HTTP ${resp.status}`),
            hanCount: data.han_count,
            detailedMode: !!data.detailed_mode,
            detailTargetHan: data.detail_target_han,
            detailMeasure: data.detail_measure,
            detailUnit: data.detail_unit,
            // "captions" when the pack assembled the block from image captions, plus
            // any explanation for why a requested mode was not used.
            promptMode: data.prompt_mode || "rewrite",
            note: data.note || "",
            refmod: data.refmod || null,
            vision: { images, sourceCount, refCount },
        };
    };

    pe.enhanceOneTarget = async (segmentIndex, cfg, activeBtn, label) => {
        const { block, taskKey } = pe.getPromptBlock(segmentIndex);
        const prompt = pe.getPromptTextForBlock(segmentIndex);
        if (!prompt) return { ok: false, skipped: true, reason: "empty" };
        pe.setEnhanceLoading(true, activeBtn, label);
        pe.setStatus(t("pe.statusEnhancingTarget", { label }), "loading");
        const result = await pe.callEnhanceApi(prompt, taskKey, block, cfg);
        if (result.ok) {
            const text = taskKey === "fl2v" ? stripFl2vPromptBody(result.text) : result.text;
            pe.setPromptTextForBlock(text, segmentIndex);
            return { ok: true, chars: text.length, taskKey, result: { ...result, text } };
        }
        return { ok: false, error: result.error, taskKey };
    };

    pe.enhancePrompt = async (scope = "current") => {
        if (pe._busy) return;
        const cfg = pe.getLlmConfig();
        if (!cfg.model) { pe.setStatus(t("pe.errorModelRequired"), "error"); return; }
        if ((cfg.apiFormat === API_ZHIPU) && !cfg.apiKey) {
            pe.setStatus(t("pe.errorApiKeyRequired"), "error");
            return;
        }

        const activeBtn = scope === "all" ? pe.enhanceAllBtn : pe.enhanceCurrentBtn;

        if (scope === "current") {
            const prompt = pe.getActivePromptText();
            if (!prompt) { pe.setStatus(t("pe.errorPromptRequired"), "error"); return; }
            pe.setEnhanceLoading(true, activeBtn, t("pe.statusPreparing"));
            try {
                const { block, taskKey } = pe.getPromptBlock();
                pe.setEnhanceLoading(true, activeBtn, t("pe.statusCollecting"));
                const result = await pe.callEnhanceApi(prompt, taskKey, block, cfg);
                const v = result.vision || {};
                if (v.images?.length) {
                    // Badge reads like "3 video frames + 2 reference images".
                    const frames = v.sourceCount ? t("pe.badgeVideoFrames", { n: v.sourceCount }) : "";
                    const refs = v.refCount ? t("pe.badgeRefImages", { n: v.refCount }) : "";
                    pe.visionBadge.textContent = `${frames}${frames && refs ? " + " : ""}${refs}`;
                    pe.visionBadge.style.display = "inline";
                } else {
                    pe.visionBadge.style.display = "none";
                }
                if (result.ok) {
                    const text = taskKey === "fl2v" ? stripFl2vPromptBody(result.text) : result.text;
                    pe.setActivePromptText(text);
                    pe.reportEnhanceResult(taskKey, { ...result, text });
                } else {
                    pe.setStatus(result.error, "error");
                }
            } catch (e) {
                pe.setStatus(t("pe.statusRequestFailed", { error: e.message }), "error");
            } finally {
                pe.setEnhanceLoading(false);
            }
            return;
        }

        // scope === "all"
        if (editor.isGlobalMode?.()) {
            const prompt = pe.getActivePromptText();
            if (!prompt) { pe.setStatus(t("pe.errorGlobalPromptRequired"), "error"); return; }
            try {
                const r = await pe.enhanceOneTarget(null, cfg, activeBtn, t("panel.globalPromptOnly"));
                if (r.ok) {
                    editor.commit?.(false, { syncTimeline: true });
                    pe.setStatus(formatEnhanceSuccessStatus(r.taskKey, r.result || {}), "success");
                } else if (!r.skipped) {
                    pe.setStatus(r.error || t("pe.errorEnhanceFailed"), "error");
                }
            } catch (e) {
                pe.setStatus(t("pe.statusRequestFailed", { error: e.message }), "error");
            } finally {
                pe.setEnhanceLoading(false);
            }
            return;
        }

        const segments = editor.timeline.segments || [];
        const targets = segments.map((_, i) => i).filter((i) => pe.getPromptTextForBlock(i));
        if (!targets.length) {
            pe.setStatus(t("pe.errorNoSegmentPrompts"), "error");
            return;
        }

        let okCount = 0;
        let lastError = "";
        try {
            for (let n = 0; n < targets.length; n++) {
                const idx = targets[n];
                const label = t("pe.segmentLabel", { n: idx + 1, total: segments.length });
                const r = await pe.enhanceOneTarget(idx, cfg, activeBtn, label);
                if (r.ok) {
                    okCount += 1;
                    pe.setStatus(t("pe.statusSegmentOk", { label, done: okCount, total: targets.length }), "loading");
                } else if (!r.skipped) {
                    lastError = r.error || t("pe.errorUnknown");
                    pe.setStatus(t("pe.statusSegmentFailed", { label, error: lastError }), "error");
                    break;
                }
            }
            editor.commit?.(false, { syncTimeline: true });
            editor.updateSelectionUI?.();
            if (okCount === targets.length) {
                pe.setStatus(t("pe.statusAllDone", { count: okCount }), "success");
            } else if (okCount > 0 && lastError) {
                pe.setStatus(t("pe.statusPartial", { done: okCount, total: targets.length, error: lastError }), "error");
            }
        } catch (e) {
            pe.setStatus(t("pe.statusRequestFailed", { error: e.message }), "error");
        } finally {
            pe.setEnhanceLoading(false);
        }
    };

    pe.unloadModel = async () => {
        const llmUrl = coerceLlmUrl(pe.urlInput.value, defaultsForApiFormat(pe.apiSelect.value).url);
        const apiFormat = pe.apiSelect.value;
        const openaiCompatMode = normalizeOpenAiCompatMode(pe.compatSelect?.value);
        const model = pe.resolveModelForSend();
        if (!model) { pe.setStatus(t("pe.errorModelRequired"), "error"); return; }
        if (!pe.supportsUnload()) {
            pe.setStatus(t("pe.errorUnloadUnsupported"), "error");
            return;
        }
        pe.setStatus(t("pe.statusUnloading"), "loading");
        try {
            const resp = await api.fetchApi("/minimax/motion-director/unload_model", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    llm_url: llmUrl,
                    model,
                    api_format: apiFormat,
                    openai_compat_mode: openaiCompatMode,
                    api_key: pe.apiKeyInput.value || "",
                }),
            });
            const data = await resp.json();
            if (resp.ok && data.status === "unloaded") {
                // The local backend answers with how many resident models it dropped.
                // Zero is a real answer, and "unloaded" would overstate it.
                if (data.released === 0) {
                    pe.setStatus(t("pe.statusNothingToUnload", { provider: data.provider || "Local (ComfyUI)" }), "success");
                } else {
                    pe.setStatus(t("pe.statusUnloaded", { provider: data.provider || "LLM" }), "success");
                }
            } else {
                pe.setStatus(data.error || t("pe.errorUnloadFailed"), "error");
            }
        } catch (e) {
            pe.setStatus(t("pe.statusUnloadFailed", { error: e.message }), "error");
        }
    };
    pe.unloadOllama = pe.unloadModel;

    pe.onTaskTypeChanged = () => pe.fetchTemplate();
    pe.handleServerEnhanced = (payload) => {
        if (!payload || String(payload.node) !== String(editor.node.id)) return;
        let text = payload.text || "";
        if (editor.isFl2vMode?.() || resolveTaskKey(editor.getTaskKey?.() || "") === "fl2v") {
            text = stripFl2vPromptBody(text);
        }
        pe.setActivePromptText(text);
        pe.setStatus(t("pe.statusAutoApplied", { count: text.length }), "success");
    };

    pe._lastOutputLanguage = null;
    pe.syncFromWidgets();
    editor._promptEnhancer = pe;
    // Local mode starts with an empty model field and no list, and the server only
    // reports what is installed when asked. Fetch once on mount so the field
    // resolves to an installed model instead of staying blank.
    if (pe.apiSelect.value === API_LOCAL) void pe.fetchModels(true);

    // Open by default. The collapse header exists because this panel used to be
    // an inline strip competing for vertical space in the modal; as an on-demand
    // settings dialog, opening to a bare title bar just makes the user click twice
    // to see the thing they asked for.
    pe.open = true;
    if (pe.body) pe.body.style.display = "flex";
    if (pe.arrow) pe.arrow.style.transform = "rotate(90deg)";

    pe.fetchTemplate(true);
    return pe;
}

export function getPromptEnhancerPanelHeight(editor) {
    const pe = editor?._promptEnhancer;
    if (!pe?.open) return PE_PANEL_COLLAPSED_H;
    return PE_PANEL_COLLAPSED_H + PE_PANEL_EXPANDED_H;
}

export function registerDirectorPromptEnhancerEvents(findDirectorNode) {
    api.addEventListener("minimax_motion_director_enhanced", ({ detail }) => {
        findDirectorNode(detail?.node)?._minimaxEditor?._promptEnhancer?.handleServerEnhanced?.(detail);
    });
}

// ComfyUI can keep a rejected ES module in the current page's module map.
// Recover through a versioned URL so the Director cannot silently remain as
// raw backend widgets after one stale/failed entry import.
setTimeout(async () => {
    if (globalThis.__MMX_MOTION_DIRECTOR_EXTENSION_REGISTERED__) return;
    try {
        await import("./minimax_timeline.js?boot=director_ui_recovery_v16");
        if (!globalThis.__MMX_MOTION_DIRECTOR_EXTENSION_REGISTERED__) {
            throw new Error("Director extension did not register after recovery import.");
        }
    } catch (error) {
        console.error("[MiniMax H3 Motion Director] UI recovery import failed:", error);
    }
}, 0);
