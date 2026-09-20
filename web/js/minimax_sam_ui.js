import { app } from "../../scripts/app.js";
import { getLocale, onLocaleChange } from "./minimax_i18n.js";

const ROOT_SELECTOR = ".mmx-postprocess";
const SAM_SELECTOR = '[data-path="face_refine.sam_model"]';
//: The SAM note only ever appears inside these, so unrelated app DOM churn must
//: not trigger a scan.
const SCOPE_SELECTOR = `${ROOT_SELECTOR}, ${SAM_SELECTOR}, .mmx-director`;
//: Safety net for panels whose inner controls are built asynchronously.
const SWEEP_IDLE_MS = 2000;
const boundSelects = new WeakSet();
let documentObserver = null;
let sweepTimer = null;
let stopLocaleSync = null;
let scanScheduled = false;

const TEXT = {
    en: "No compatible SAM .pt model found. Put an Ultralytics SAM/SAM2 checkpoint in ComfyUI/models/sams.",
    zh: "未找到兼容的 SAM .pt 模型。请将 Ultralytics SAM/SAM2 checkpoint 放入 ComfyUI/models/sams。",
};

function language() {
    return getLocale?.() === "en" ? "en" : "zh";
}

function hasCompatibleModel(select) {
    return Array.from(select?.options || []).some((option) => String(option.value || "").trim());
}

function render(select) {
    const note = select?.parentElement?.querySelector?.('[data-capability="sam_model"]');
    if (!note) return;
    const ready = hasCompatibleModel(select);
    if (note.hidden !== ready) note.hidden = ready;
    note.classList.toggle("bad", !ready);
    const text = ready ? "" : TEXT[language()];
    if (note.textContent !== text) note.textContent = text;
}

function bind(select) {
    if (!select || boundSelects.has(select)) {
        if (select) render(select);
        return;
    }
    boundSelects.add(select);

    const note = document.createElement("div");
    note.className = "mmx-post-capability mmx-post-wide";
    note.dataset.capability = "sam_model";
    select.parentElement?.appendChild(note);

    if (typeof MutationObserver === "function") {
        const observer = new MutationObserver(() => render(select));
        observer.observe(select, { childList: true, subtree: true });
    }
    render(select);
}

function scan() {
    if (document.hidden) return;
    document.querySelectorAll(ROOT_SELECTOR).forEach((root) => bind(root.querySelector(SAM_SELECTOR)));
}

function scheduleScan() {
    if (scanScheduled) return;
    scanScheduled = true;
    queueMicrotask(() => {
        scanScheduled = false;
        scan();
    });
}

/** Cheap test: did this mutation batch add something the note can live in? */
function mutationAddsScope(mutation) {
    const added = mutation?.addedNodes;
    if (!added?.length) return false;
    for (const node of added) {
        if (node?.nodeType !== 1) continue;
        if (node.matches?.(SCOPE_SELECTOR) || node.querySelector?.(SCOPE_SELECTOR)) return true;
    }
    return false;
}

function ensureDocumentObserver() {
    if (documentObserver || typeof MutationObserver !== "function" || !document.body) return;
    documentObserver = new MutationObserver((mutations) => {
        for (const mutation of mutations) {
            if (mutationAddsScope(mutation)) {
                scheduleScan();
                return;
            }
        }
    });
    documentObserver.observe(document.body, { childList: true, subtree: true });
    if (sweepTimer == null) sweepTimer = setInterval(() => scheduleScan(), SWEEP_IDLE_MS);
}

function refreshAll() {
    scan();
    document.querySelectorAll(SAM_SELECTOR).forEach(render);
}

app.registerExtension({
    name: "MiniMaxH3.MotionDirector.SAMUI",
    setup() {
        ensureDocumentObserver();
        if (!stopLocaleSync) stopLocaleSync = onLocaleChange(() => queueMicrotask(refreshAll));
        scheduleScan();
    },
    nodeCreated() {
        scheduleScan();
    },
    loadedGraphNode() {
        scheduleScan();
    },
});
