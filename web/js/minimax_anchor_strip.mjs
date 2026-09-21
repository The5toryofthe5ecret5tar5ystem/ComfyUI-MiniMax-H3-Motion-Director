// MiniMax H3 Motion Director — anchor ladder strip (P2).
//
// One cell per segment BOUNDARY (N segments => N+1 boundaries: the opening
// pose, every cut, and the closing pose). A cell shows the rendered anchor
// thumbnail, its seed/status, an editable "beat" (the pose that boundary must
// hold) and two actions: approve / re-roll.
//
// The strip is a view over `timeline.anchors` (parsed by
// director/anchor_ladder.py) plus the PNGs on disk (served by
// director/anchor_routes.py). It never renders anything itself: the executor's
// anchor pass fills the missing cells on the next run, reusing whatever is
// already approved on disk.
//
// Mounted above the timeline canvas by `installAnchorStrip(ed)`.

import { t, applyI18nDom, onLocaleChange } from "./minimax_i18n.js";
import {
    anchorAction,
    anchorThumbUrl,
    listAnchors,
    nextAnchorSeed,
    planAnchors,
} from "./minimax_anchor_api.mjs?boot=anchor_ladder_v1";

const DEFAULT_ANCHORS = {
    mode: "off",
    chunkFrames: 22,
    candidates: 1,
    seedBase: 4242,
    renderPass: true,
    preRollOnly: false,
    // Draft = the final canvas, few steps (a cheap preview whose framing is the
    // real one). The 100 % scale is what makes the draft judgeable early; the
    // steps are what make it cheap.
    draft: { enabled: false, scale: 1, steps: 8 },
    placement: "boundary",
    leadFrames: 24,
    leadHard: false,
    promptSource: "auto",
    beats: [],
    seeds: [],
    prompts: [],
    promptSources: [],
};

const MODES = ["off", "soft", "hard"];
/** Where a boundary pose sits: at the cut, or one second before it. */
const PLACEMENTS = ["boundary", "lead"];
/** What a boundary anchor's prompt is built from (director/anchor_ladder.py). */
const PROMPT_SOURCES = ["auto", "template", "from", "to", "both"];
const PLAN_DEBOUNCE_MS = 420;

const STYLES = `
.mmxa-strip{margin:6px 8px 2px;border:1px solid rgba(255,255,255,.10);border-radius:8px;background:rgba(255,255,255,.03);font-size:12px;color:#d8d8d8}
.mmxa-strip[data-busy="1"]{opacity:.72}
.mmxa-bar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:6px 8px;border-bottom:1px solid rgba(255,255,255,.07)}
.mmxa-title{font-weight:700;letter-spacing:.02em}
.mmxa-fold{background:none;border:none;color:#d8d8d8;font-size:12px;cursor:pointer;padding:0 2px;line-height:1}
.mmxa-summary{display:none;opacity:.8;font-size:11px}
.mmxa-lead{color:#e0b45c;font-size:10px}
.mmxa-lbl[data-off="1"]{opacity:.45}
.mmxa-strip[data-collapsed="1"] .mmxa-bar>*{display:none}
.mmxa-strip[data-collapsed="1"] .mmxa-fold,
.mmxa-strip[data-collapsed="1"] .mmxa-title,
.mmxa-strip[data-collapsed="1"] .mmxa-summary{display:inline-block}
.mmxa-strip[data-collapsed="1"] .mmxa-bar{border-bottom:none;padding:4px 8px}
.mmxa-strip[data-collapsed="1"] .mmxa-cells,
.mmxa-strip[data-collapsed="1"] .mmxa-foot{display:none}
.mmxa-thumb{cursor:pointer}
.mmxa-lbl{display:flex;align-items:center;gap:4px;opacity:.85}
.mmxa-select,.mmxa-num,.mmxa-beat{background:#1b1b1f;color:#dcdcdc;border:1px solid rgba(255,255,255,.14);border-radius:5px;padding:2px 5px;font-size:12px}
.mmxa-num{width:60px}
.mmxa-beat{width:100%;box-sizing:border-box;padding:3px 5px}
.mmxa-btn{background:rgba(255,255,255,.06);color:#dcdcdc;border:1px solid rgba(255,255,255,.14);border-radius:5px;padding:3px 8px;cursor:pointer;font-size:12px}
.mmxa-btn:hover:not(:disabled){background:rgba(255,255,255,.12)}
.mmxa-btn:disabled{opacity:.45;cursor:default}
.mmxa-btn-ok{border-color:rgba(90,200,120,.5)}
.mmxa-btn-warn{border-color:rgba(200,140,80,.5)}
.mmxa-spacer{flex:1 1 auto}
.mmxa-cells{display:flex;gap:6px;overflow-x:auto;padding:7px 8px}
.mmxa-cell{flex:0 0 auto;width:126px;border:1px solid rgba(255,255,255,.10);border-radius:7px;padding:5px;display:flex;flex-direction:column;gap:4px;background:rgba(0,0,0,.18)}
.mmxa-cell[data-stale="1"]{border-color:rgba(214,150,74,.65)}
.mmxa-thumb{display:flex;align-items:center;justify-content:center;height:70px;border-radius:5px;overflow:hidden;background:rgba(255,255,255,.05);border:1px dashed rgba(255,255,255,.14)}
.mmxa-thumb img{width:100%;height:100%;object-fit:cover;display:block}
.mmxa-thumb-empty{font-size:11px;opacity:.5}
.mmxa-row{display:flex;align-items:center;gap:5px;font-size:11px}
.mmxa-idx{font-weight:700}
.mmxa-seed{opacity:.65;font-variant-numeric:tabular-nums}
.mmxa-actions{display:flex;gap:4px}
.mmxa-actions .mmxa-btn{flex:1 1 auto;text-align:center;padding:2px 4px}
.mmxa-dot{width:7px;height:7px;border-radius:50%;background:#8a8a8a;flex:0 0 auto}
.mmxa-cell[data-status="ready"] .mmxa-dot{background:#5ac8c8}
.mmxa-cell[data-status="approved"] .mmxa-dot{background:#5ac878}
.mmxa-cell[data-status="rejected"] .mmxa-dot{background:#d05a5a}
.mmxa-cell[data-status="empty"] .mmxa-dot{background:#5a5a5a}
.mmxa-foot{display:flex;align-items:flex-start;gap:8px;padding:0 8px 7px;font-size:11px;opacity:.78;line-height:1.45}
.mmxa-foot-text{flex:1 1 auto;min-width:0}
.mmxa-stop{flex:0 0 auto;border-color:rgba(255,90,90,.85);color:#ffd9d9;padding:1px 8px;font-size:11px}
.mmxa-stop:hover:not(:disabled){background:rgba(255,90,90,.18)}
.mmxa-foot .mmxa-err{color:#ff9a9a;opacity:1}
.mmxa-cell[data-rendering="1"]{border-color:rgba(224,178,90,.85);box-shadow:0 0 0 1px rgba(224,178,90,.35)}
.mmxa-cell[data-selected="0"]{opacity:.48}
.mmxa-btn-eye{min-width:24px;padding:3px 4px}
.mmxa-btn-go{border-color:rgba(120,190,230,.55)}
/* Pre-roll wears the timeline's clip yellow (CLIP_SEGMENT_COLORS[0] in
   minimax_timeline.js) so "fill every missing pose" stands out from the rest. */
.mmxa-btn[data-t="preRoll"]{border-color:rgba(255,200,50,.9)}
.mmxa-btn[data-t="preRoll"]:hover:not(:disabled){background:rgba(255,200,50,.16)}
.mmxa-foot .mmxa-sel{color:#9fd0a8}
.mmxa-foot .mmxa-hint{color:#e8c98a;opacity:1}
.mmxa-foot .mmxa-preroll{color:#e0b25a;font-weight:600}
.mmxa-prompt{border-top:1px solid rgba(255,255,255,.07);padding:7px 8px;display:flex;flex-direction:column;gap:6px}
.mmxa-prompt[hidden]{display:none}
.mmxa-prompt-head{display:flex;align-items:center;gap:6px;font-size:11px;flex-wrap:wrap}
.mmxa-prompt-head b{font-size:12px}
.mmxa-prompt-shots{opacity:.8}
.mmxa-badge{border-radius:9px;padding:1px 7px;font-size:10px;border:1px solid rgba(255,255,255,.16);opacity:.85}
.mmxa-badge[data-on="1"]{border-color:rgba(224,178,90,.7);color:#e8c98a;opacity:1}
.mmxa-prompt textarea{background:#1b1b1f;color:#dcdcdc;border:1px solid rgba(255,255,255,.14);border-radius:5px;padding:5px;font-size:11px;min-height:104px;resize:vertical;font-family:inherit;line-height:1.45}
.mmxa-prompt-actions{display:flex;gap:5px;align-items:center;flex-wrap:wrap}
.mmxa-chips{display:flex;gap:4px;flex-wrap:wrap}
.mmxa-chip{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.12);border-radius:9px;padding:1px 7px;font-size:10px;cursor:pointer;max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mmxa-chip:hover{background:rgba(255,255,255,.13)}
.mmxa-chip[data-empty="1"]{opacity:.45}
.mmxa-strip[data-busy="1"] .mmxa-chip{pointer-events:none;opacity:.5}
.mmxa-rendered{font-size:10px;opacity:.62;white-space:pre-wrap;max-height:92px;overflow:auto;border-left:2px solid rgba(255,255,255,.12);padding-left:6px;line-height:1.45}
.mmxa-cell[data-prompt="1"] [data-cell="prompt"]{border-color:rgba(224,178,90,.75);color:#e8c98a}
`;

function cn(value) {
    return String(value ?? "").trim();
}

function clampInt(value, min, max, fallback) {
    const num = Math.round(Number(value));
    if (!Number.isFinite(num)) return fallback;
    return Math.min(max, Math.max(min, num));
}

function clampFloat(value, min, max, fallback) {
    const num = Number(value);
    if (!Number.isFinite(num)) return fallback;
    return Math.min(max, Math.max(min, num));
}

/** The `anchors` block, created/normalised in place on first use. */
function anchorsBlock(ed) {
    if (!ed?.timeline) return { ...DEFAULT_ANCHORS };
    const raw = ed.timeline.anchors;
    const block = raw && typeof raw === "object" ? raw : {};
    for (const [key, value] of Object.entries(DEFAULT_ANCHORS)) {
        if (key === "beats" || key === "seeds") {
            if (!Array.isArray(block[key])) block[key] = [];
            continue;
        }
        if (block[key] === undefined || block[key] === null) block[key] = value;
    }
    for (const key of ["beats", "seeds", "prompts", "promptSources"]) {
        if (!Array.isArray(block[key])) block[key] = [];
    }
    block.promptSource = PROMPT_SOURCES.includes(String(block.promptSource).toLowerCase())
        ? String(block.promptSource).toLowerCase()
        : DEFAULT_ANCHORS.promptSource;
    block.mode = MODES.includes(String(block.mode).toLowerCase()) ? String(block.mode).toLowerCase() : "off";
    block.chunkFrames = clampInt(block.chunkFrames, 5, 425, DEFAULT_ANCHORS.chunkFrames);
    block.candidates = clampInt(block.candidates, 1, 4, 1);
    block.renderPass = block.renderPass !== false;
    block.preRollOnly = block.preRollOnly === true;
    block.placement = PLACEMENTS.includes(String(block.placement).toLowerCase())
        ? String(block.placement).toLowerCase()
        : "boundary";
    block.leadFrames = Math.max(4, Math.round(clampInt(block.leadFrames, 4, 120, DEFAULT_ANCHORS.leadFrames) / 4) * 4);
    block.leadHard = block.leadHard === true;
    const draft = block.draft && typeof block.draft === "object" ? block.draft : {};
    draft.enabled = draft.enabled === true;
    draft.scale = clampFloat(draft.scale, 0.1, 1, DEFAULT_ANCHORS.draft.scale);
    draft.steps = clampInt(draft.steps, 0, 64, DEFAULT_ANCHORS.draft.steps);
    block.draft = draft;
    // ``boundaries`` is either absent (all), an explicit index list, or one of the
    // string presets. The strip normalizes it to an explicit list so the eye
    // toggles always describe exactly what the fills will use (strict selection).
    const selection = block.boundaries;
    if (typeof selection === "string") {
        const text = selection.trim().toLowerCase();
        if (["bookends", "bookend", "ends", "first-last"].includes(text)) {
            block.boundaries = [0, Math.max(0, boundaryCount(ed) - 1)];
        } else if (["none", "off", "no"].includes(text)) {
            block.boundaries = [];
        } else {
            delete block.boundaries;
        }
    } else if (Array.isArray(selection)) {
        block.boundaries = [...new Set(
            selection.map(Number).filter((value) => Number.isFinite(value) && value >= 0),
        )].sort((a, b) => a - b);
    } else if (selection !== undefined) {
        delete block.boundaries;
    }
    ed.timeline.anchors = block;
    return block;
}

function selectionSet(block) {
    return Array.isArray(block.boundaries) ? new Set(block.boundaries.map(Number)) : null;
}

function boundarySelected(block, index) {
    const set = selectionSet(block);
    return set === null || set.has(Number(index));
}

function boundaryList(block, count) {
    const set = selectionSet(block);
    if (set === null) return Array.from({ length: count }, (_, index) => index);
    return [...set].filter((index) => index >= 0 && index < count).sort((a, b) => a - b);
}

function boundaryCount(ed) {
    const segments = ed?.timeline?.segments;
    return Math.max(1, (Array.isArray(segments) ? segments.length : 0) + 1);
}

function outputSize(ed) {
    const out = ed?.timeline?.output || {};
    return {
        width: clampInt(out.width, 0, 8192, 0),
        height: clampInt(out.height, 0, 8192, 0),
        refLongEdge: clampInt(out.refLongEdge ?? out.refSize ?? ed?.timeline?.refImageSize, 64, 2048, 768),
    };
}

function nodeIdOf(ed) {
    return String(ed?.node?.id ?? "");
}

/** Persist the in-memory timeline to the node widget (same path as context links). */
function persistTimeline(ed) {
    try {
        const widget = ed?.timelineWidget;
        if (!widget) return false;
        const before = String(widget.value || "");
        if (typeof ed._writeTimelineWidget === "function") ed._writeTimelineWidget();
        else widget.value = JSON.stringify(ed.buildTimelinePayload());
        const after = String(widget.value || "");
        if (after === before) return false;
        ed.node?.onWidgetChanged?.("timeline_data", after, before, widget);
        ed.node?.graph?.change?.();
        return true;
    } catch (err) {
        console.warn("[MiniMax H3 Motion Director] anchor state write failed:", err);
        return false;
    }
}

export function installAnchorStrip(ed) {
    if (!ed || !ed.mainBody || ed._anchorStrip) return ed?._anchorStrip || null;

    const el = document.createElement("div");
    el.className = "mmxa-strip";
    el.innerHTML = `<style>${STYLES}</style>
        <div class="mmxa-bar">
            <button type="button" class="mmxa-fold" data-t="fold" data-i18n-title="anchor.foldTitle">▾</button>
            <span class="mmxa-title" data-i18n="anchor.title">Anchors</span>
            <span class="mmxa-summary" data-t="summary"></span>
            <label class="mmxa-lbl"><span data-i18n="anchor.mode">Mode</span>
                <select class="mmxa-select" data-t="mode"></select>
            </label>
            <label class="mmxa-lbl"><span data-i18n="anchor.chunk">Chunk</span>
                <input class="mmxa-num" type="number" min="5" max="425" step="1" data-t="chunk">
            </label>
            <label class="mmxa-lbl" data-i18n-title="anchor.placementTitle"><span data-i18n="anchor.placement">Placement</span>
                <select class="mmxa-select" data-t="placement"></select>
            </label>
            <label class="mmxa-lbl" data-i18n-title="anchor.promptSourceTitle"><span data-i18n="anchor.promptSource">Prompt</span>
                <select class="mmxa-select" data-t="promptSource"></select>
            </label>
            <label class="mmxa-lbl" data-i18n-title="anchor.leadPinTitle">
                <input type="checkbox" data-t="leadHard"> <span data-i18n="anchor.leadPin">Pin pose</span>
            </label>
            <label class="mmxa-lbl" data-i18n-title="anchor.renderPass">
                <input type="checkbox" data-t="renderPass"> <span data-i18n="anchor.renderPass">Render anchors</span>
            </label>
            <label class="mmxa-lbl" data-i18n-title="anchor.renderFillTitle">
                <input type="checkbox" data-t="renderFill" disabled> <span data-i18n="anchor.renderFill">Render fill pieces</span>
            </label>
            <span class="mmxa-spacer"></span>
            <button type="button" class="mmxa-btn" data-t="presetAll" data-i18n-title="anchor.presetAllTitle" data-i18n="anchor.presetAll">All</button>
            <button type="button" class="mmxa-btn" data-t="presetBookends" data-i18n-title="anchor.presetBookendsTitle" data-i18n="anchor.presetBookends">Bookends</button>
            <button type="button" class="mmxa-btn" data-t="presetRendered" data-i18n-title="anchor.presetRenderedTitle" data-i18n="anchor.presetRendered">Rendered</button>
            <button type="button" class="mmxa-btn mmxa-btn-go" data-t="preRoll" data-i18n-title="anchor.preRollTitle" data-i18n="anchor.preRollBtn">Pre-roll</button>
            <button type="button" class="mmxa-btn mmxa-btn-draft" data-t="draft" data-i18n-title="anchor.draftTitle" data-i18n="anchor.draftBtn">Draft</button>
            <label class="mmxa-lbl" data-i18n-title="anchor.draftScaleTitle"><span data-i18n="anchor.draftScale">Scale</span>
                <input class="mmxa-num" type="number" min="10" max="100" step="5" data-t="draftScale">
            </label>
            <label class="mmxa-lbl" data-i18n-title="anchor.draftStepsTitle"><span data-i18n="anchor.draftSteps">Steps</span>
                <input class="mmxa-num" type="number" min="0" max="64" step="1" data-t="draftSteps">
            </label>
            <button type="button" class="mmxa-btn mmxa-btn-ok" data-t="approveAll" data-i18n="anchor.approveAll">Approve all</button>
            <button type="button" class="mmxa-btn mmxa-btn-warn" data-t="clear" data-i18n="anchor.clear">Clear</button>
        </div>
        <div class="mmxa-cells" data-t="cells"></div>
        <div class="mmxa-prompt" data-t="promptPanel" hidden>
            <div class="mmxa-prompt-head">
                <b data-t="promptTitle"></b>
                <span class="mmxa-prompt-shots" data-t="promptShots"></span>
                <span class="mmxa-badge" data-t="promptBadge"></span>
                <span class="mmxa-spacer"></span>
                <span data-i18n="anchor.promptMaterial"></span>
                <span class="mmxa-chips" data-t="promptChips"></span>
            </div>
            <textarea data-t="promptBody" spellcheck="false" data-i18n-placeholder="anchor.promptBodyHint"></textarea>
            <div class="mmxa-prompt-actions">
                <button type="button" class="mmxa-btn mmxa-btn-ok" data-t="promptSave" data-i18n="anchor.promptSave">Save</button>
                <button type="button" class="mmxa-btn mmxa-btn-warn" data-t="promptClear" data-i18n="anchor.promptClear">Back to auto</button>
                <button type="button" class="mmxa-btn" data-t="promptClose" data-i18n="anchor.promptClose">Close</button>
                <span class="mmxa-spacer"></span>
                <span data-i18n="anchor.promptRendered"></span>
            </div>
            <div class="mmxa-rendered" data-t="promptRendered"></div>
        </div>
        <div class="mmxa-foot" data-t="foot">
            <button type="button" class="mmxa-btn mmxa-stop" data-t="stop" data-i18n-title="anchor.stopTitle" data-i18n="anchor.stop" hidden>■ Stop</button>
            <span class="mmxa-foot-text" data-t="footText"></span>
        </div>`;

    const modeSelect = el.querySelector('[data-t="mode"]');
    for (const mode of MODES) {
        const option = document.createElement("option");
        option.value = mode;
        option.dataset.i18n = mode === "off" ? "anchor.modeOff" : mode === "soft" ? "anchor.modeSoft" : "anchor.modeHard";
        option.disabled = mode === "hard";
        option.textContent = t(option.dataset.i18n);
        modeSelect.appendChild(option);
    }
    const chunkInput = el.querySelector('[data-t="chunk"]');
    const placementSelect = el.querySelector('[data-t="placement"]');
    for (const placement of PLACEMENTS) {
        const option = document.createElement("option");
        option.value = placement;
        option.dataset.i18n = placement === "lead" ? "anchor.placementLead" : "anchor.placementBoundary";
        option.textContent = t(option.dataset.i18n);
        placementSelect.appendChild(option);
    }
    const leadHardBox = el.querySelector('[data-t="leadHard"]');
    const promptSourceSelect = el.querySelector('[data-t="promptSource"]');
    for (const source of PROMPT_SOURCES) {
        const option = document.createElement("option");
        option.value = source;
        option.textContent = t(sourceKey(source));
        promptSourceSelect.appendChild(option);
    }
    const promptPanel = el.querySelector('[data-t="promptPanel"]');
    const promptTitleEl = el.querySelector('[data-t="promptTitle"]');
    const promptShotsEl = el.querySelector('[data-t="promptShots"]');
    const promptBadgeEl = el.querySelector('[data-t="promptBadge"]');
    const promptBodyEl = el.querySelector('[data-t="promptBody"]');
    const promptChipsEl = el.querySelector('[data-t="promptChips"]');
    const promptRenderedEl = el.querySelector('[data-t="promptRendered"]');
    const promptSaveBtn = el.querySelector('[data-t="promptSave"]');
    const promptClearBtn = el.querySelector('[data-t="promptClear"]');
    const promptCloseBtn = el.querySelector('[data-t="promptClose"]');
    const renderPassBox = el.querySelector('[data-t="renderPass"]');
    const renderFillBox = el.querySelector('[data-t="renderFill"]');
    const approveAllBtn = el.querySelector('[data-t="approveAll"]');
    const preRollBtn = el.querySelector('[data-t="preRoll"]');
    const presetAllBtn = el.querySelector('[data-t="presetAll"]');
    const presetBookendsBtn = el.querySelector('[data-t="presetBookends"]');
    const presetRenderedBtn = el.querySelector('[data-t="presetRendered"]');
    const foldBtn = el.querySelector('[data-t="fold"]');
    const summaryEl = el.querySelector('[data-t="summary"]');
    const draftBtn = el.querySelector('[data-t="draft"]');
    const draftScaleInput = el.querySelector('[data-t="draftScale"]');
    const draftStepsInput = el.querySelector('[data-t="draftSteps"]');
    const clearBtn = el.querySelector('[data-t="clear"]');
    const cellsEl = el.querySelector('[data-t="cells"]');
    const footEl = el.querySelector('[data-t="foot"]');
    const footTextEl = el.querySelector('[data-t="footText"]');
    const stopBtn = el.querySelector('[data-t="stop"]');

    let cells = [];
    let lastSignature = "";
    let busy = false;
    let planTimer = 0;
    let refreshTimer = 0;
    let planToken = 0;
    let diskItems = new Map();
    let lastEstimate = null;
    let hint = "";
    let error = "";
    let stopRequested = false;

    // ---- small helpers ---------------------------------------------------- //
    function setBusy(value) {
        busy = Boolean(value);
        el.dataset.busy = busy ? "1" : "0";
        for (const button of el.querySelectorAll("button")) {
            // Stop is the one control that must stay live while a run is in
            // flight - every other control locks.
            if (button === stopBtn) continue;
            button.disabled = busy;
        }
        renderFillBox.disabled = busy;
        renderPassBox.disabled = busy;
        placementSelect.disabled = busy;
        leadHardBox.disabled = busy;
        promptSourceSelect.disabled = busy;
        stopBtn.hidden = !busy;
        stopBtn.disabled = !busy || stopRequested;
    }

    function setFoot() {
        if (error) {
            footTextEl.innerHTML = `<span class="mmxa-err"></span>`;
            footTextEl.firstChild.textContent = t("anchor.error", { message: error });
            return;
        }
        const parts = [];
        if (hint) parts.push(`<span class="mmxa-hint"></span>`);
        parts.push(`<span class="mmxa-est"></span>`);
        const block = anchorsBlock(ed);
        const preRoll = block.mode !== "off" && block.preRollOnly === true;
        const selection = selectionSet(block);
        if (preRoll) parts.push(`<span class="mmxa-preroll"></span>`);
        if (block.mode !== "off" && block.placement === "lead") {
            parts.push(`<span class="mmxa-leadfoot"></span>`);
        }
        if (block.mode !== "off" && selection !== null) parts.push(`<span class="mmxa-sel"></span>`);
        footTextEl.innerHTML = parts.join(" ");
        if (hint) footTextEl.querySelector(".mmxa-hint").textContent = hint;
        footTextEl.querySelector(".mmxa-est").textContent = lastEstimate || t("anchor.loading");
        if (preRoll) footTextEl.querySelector(".mmxa-preroll").textContent = t("anchor.preRollFoot");
        if (block.mode !== "off" && block.placement === "lead") {
            const seconds = (leadFramesOf(block) / 24).toFixed(2).replace(/\.?0+$/, "");
            footTextEl.querySelector(".mmxa-leadfoot").textContent = t("anchor.leadFoot", {
                seconds,
                pinned: block.leadHard ? t("anchor.leadFootPinned") : "",
            });
        }
        if (block.mode !== "off" && selection !== null) {
            footTextEl.querySelector(".mmxa-sel").textContent = t("anchor.activeCount", {
                active: selection.size, total: boundaryCount(ed),
            });
        }
    }

    function fail(err) {
        error = String(err?.message || err || "unknown error");
        console.warn("[MiniMax H3 Motion Director] anchors:", err);
        setFoot();
    }

    function clearFailure() {
        if (!error) return;
        error = "";
        setFoot();
    }

    async function withBusy(fn) {
        if (busy) return;
        setBusy(true);
        try {
            await fn();
        } catch (err) {
            fail(err);
        } finally {
            stopRequested = false;
            setBusy(false);
            // Re-apply the per-cell disabled rules: refresh() ran while the
            // strip was busy, so every action button is still disabled.
            updateCells();
        }
    }

    // ---- in-strip run control -------------------------------------------- //
    // The strip owns the "render anchors" workflow: it sets the transient flags
    // on this node's timeline, queues the graph itself, waits for the PNGs to
    // land, then puts the flags back. No "uncheck something and hit Run" dance.
    function sleep(ms) {
        return new Promise((resolve) => setTimeout(resolve, ms));
    }

    async function queueDirectorRun() {
        const comfy = window.app || window.comfyAPI?.app?.app;
        if (!comfy?.queuePrompt) throw new Error(t("anchor.noApp"));
        const response = await comfy.queuePrompt(0);
        // The prompt id lets the strip wait for *its own* run. Waiting for the
        // history count to grow instead was wrong whenever another prompt
        // finished in the meantime: Pre-roll then reported "N still missing"
        // while its own run was still rendering.
        return String(response?.prompt_id || response?.promptId || "");
    }

    async function promptFinished(promptId) {
        if (!promptId) return null;
        try {
            const response = await fetch(`/history/${encodeURIComponent(promptId)}`);
            if (!response.ok) return null;
            const data = await response.json();
            return data && typeof data === "object" && Object.keys(data).length ? data : null;
        } catch (err) {
            return null;
        }
    }

    /** Interrupt the running prompt - the anchor pass stops where it is.
     *
     * Every anchor writes its PNG as soon as it settles, so the poses finished
     * before the click are on disk and stay there; only the ones still to render
     * are lost. (The node's own graceful Stop only takes effect inside the fill
     * loop, i.e. after the whole anchor pass - useless for stopping anchors.)
     */
    async function interruptRun() {
        const response = await fetch("/interrupt", { method: "POST" });
        if (!response.ok) throw new Error(t("anchor.stopFailed", { status: response.status }));
    }

    stopBtn.addEventListener("click", () => {
        if (!busy || stopRequested) return;
        stopRequested = true;
        stopBtn.disabled = true;
        hint = t("anchor.stopping");
        setFoot();
        interruptRun().catch((err) => fail(err));
    });

    async function historyCount() {
        try {
            const response = await fetch("/history");
            const data = await response.json();
            return Object.keys(data || {}).length;
        } catch (err) {
            return -1;
        }
    }

    async function waitForHistory(before, timeoutMs, promptId = "") {
        if (!promptId && before < 0) return false;
        const deadline = Date.now() + timeoutMs;
        do {
            await sleep(5000);
            if (stopRequested) return false;
            if (promptId) {
                if (await promptFinished(promptId)) return true;
                continue;
            }
            const now = await historyCount();
            if (now > before) return true;
        } while (Date.now() < deadline);
        return false;
    }

    async function anchorMtime(index) {
        try {
            const listing = await listAnchors(nodeIdOf(ed));
            const item = listing.items.find((entry) => Number(entry.index) === Number(index));
            return item ? Number(item.mtime) || 0 : 0;
        } catch (err) {
            return 0;
        }
    }

    async function waitForAnchors(indices, timeoutMs, historyBefore, promptId = "") {
        const wanted = (indices || []).map(Number);
        const before = new Map();
        for (const index of wanted) before.set(index, await anchorMtime(index));
        const deadline = Date.now() + timeoutMs;
        do {
            await sleep(3000);
            if (stopRequested) {
                // Stop pressed: report what landed instead of waiting out the
                // timeout - the callers say "stopped" and keep the PNGs.
                return { settled: false, stopped: true, changed: await anchorChanged(wanted, before) };
            }
            if (promptId) {
                // Our own prompt finished: every anchor it rendered is on disk.
                if (await promptFinished(promptId)) {
                    return { settled: true, changed: await anchorChanged(wanted, before) };
                }
                // Live progress, so a ten-pose pass does not look like a hang.
                hint = t("anchor.progressAnchors", {
                    done: await anchorLanded(wanted, before), total: wanted.length,
                });
                setFoot();
                continue;
            }
            // Legacy fallback (no prompt id from the frontend): the queued run
            // finishing is enough, because a boundary that was already on disk is
            // reused and its PNG never changes.
            if (historyBefore >= 0 && (await historyCount()) > historyBefore) {
                return { settled: true, changed: await anchorChanged(wanted, before) };
            }
            let ready = wanted.length === 0;
            for (const index of wanted) {
                const mtime = await anchorMtime(index);
                if (mtime && mtime !== before.get(index)) ready = true;
            }
            if (ready) return { settled: true, changed: await anchorChanged(wanted, before) };
        } while (Date.now() < deadline);
        return { settled: false, stopped: stopRequested, changed: false };
    }

    async function anchorLanded(indices, before) {
        let count = 0;
        for (const index of indices) {
            const mtime = await anchorMtime(index);
            if (mtime && mtime !== before.get(index)) count += 1;
        }
        return count;
    }

    async function anchorChanged(indices, before) {
        for (const index of indices) {
            const mtime = await anchorMtime(index);
            if (mtime && mtime !== before.get(index)) return true;
        }
        return false;
    }

    function boundariesMissing() {
        const block = anchorsBlock(ed);
        const count = boundaryCount(ed);
        return boundaryList(block, count).filter((index) => !diskItems.has(index));
    }

    // Timeline frame a boundary sits on: the opening frame of the segment that
    // starts there, or the final frame for the closing boundary.
    function boundaryFrame(index) {
        const segments = ed?.timeline?.segments || [];
        if (!segments.length) return null;
        const frameOf = (seg) => Math.max(0, Math.round(Number(seg?.start ?? seg?.startFrame ?? 0) || 0));
        if (index < segments.length) return frameOf(segments[index]);
        const last = segments[segments.length - 1];
        const frames = Math.round(Number(last?.frameCount ?? last?.length ?? 0) || 0);
        const total = Math.round(Number(ed?.timeline?.totalFrames ?? 0) || 0);
        const frame = frameOf(last) + frames;
        return total > 0 ? Math.min(frame, Math.max(0, total - 1)) : frame;
    }

    /** In lead placement the pose sits inside the shot that ends on the boundary. */
    function leadFramesOf(block = anchorsBlock(ed)) {
        const value = clampInt(block.leadFrames, 4, 120, DEFAULT_ANCHORS.leadFrames);
        return Math.max(4, Math.round(value / 4) * 4);
    }

    function seekToBoundary(index) {
        const block = anchorsBlock(ed);
        const base = boundaryFrame(index);
        if (base === null || typeof ed.seekToFrame !== "function") return;
        const lead = block.placement === "lead" && index > 0;
        const frame = lead ? Math.max(0, base - leadFramesOf(block)) : base;
        ed.seekToFrame(frame, { fromUi: true });
        hint = lead
            ? t("anchor.seekHintLead", {
                index: index + 1, frame: frame + 1, seconds: leadFramesOf(block) / 24,
            })
            : t("anchor.seekHint", { index: index + 1, frame: frame + 1 });
        setFoot();
    }

    // ---- collapse --------------------------------------------------------- //
    let collapsed = ed.node?.properties?.mmxa_collapsed === true;

    function applyCollapsed() {
        el.dataset.collapsed = collapsed ? "1" : "0";
        foldBtn.textContent = collapsed ? "▸" : "▾";
        if (!collapsed) return;
        const block = anchorsBlock(ed);
        const count = boundaryCount(ed);
        const list = boundaryList(block, count);
        const mode = block.mode === "off"
            ? t("anchor.modeOff")
            : (block.mode === "soft" ? t("anchor.modeSoft") : t("anchor.modeHard"));
        summaryEl.textContent = t("anchor.summary", {
            mode,
            active: list.length,
            total: count,
            rendered: list.filter((index) => diskItems.has(index)).length,
        });
    }

    foldBtn.addEventListener("click", () => {
        collapsed = !collapsed;
        if (ed.node?.properties) ed.node.properties.mmxa_collapsed = collapsed;
        applyCollapsed();
    });

    async function runAnchors(onlyIndices, options = {}) {
        const force = options.force === true;
        const block = anchorsBlock(ed);
        let promptId = "";
        const previous = {
            preRollOnly: block.preRollOnly === true,
            forceRender: block.forceRender === true,
            renderPass: block.renderPass !== false,
            onlyIndices: Array.isArray(block.onlyIndices) ? block.onlyIndices.slice() : null,
            mode: String(block.mode || "off").toLowerCase(),
        };
        // "Mode: off" means the project has no anchors at all - and the engine drops
        // the ENTIRE anchor block for such a run, so onlyIndices, preRollOnly and
        // renderPass are never even parsed. That is why ▶ on a boundary used to
        // render the whole timeline: the request was thrown away and the run fell
        // through to the fills. A render action arms the mode for its own run.
        const armed = previous.mode === "off";
        const historyBefore = await historyCount();
        const targets = onlyIndices && onlyIndices.length ? onlyIndices : boundariesMissing();
        try {
            if (armed) block.mode = "soft";
            block.preRollOnly = true;
            block.forceRender = force;
            // Every strip action that says "render" means it: the "Render anchors"
            // checkbox governs what a normal Start run does automatically, not
            // whether this button works. (With it off, ▶ used to load the anchors
            // that already existed, render nothing, and report "reused".)
            block.renderPass = true;
            // A fresh nonce changes the payload, so ComfyUI's node-output cache
            // cannot short-circuit a repeat click into a 0.01s no-op run.
            block.nonce = String(Date.now());
            if (onlyIndices && onlyIndices.length) block.onlyIndices = onlyIndices.slice();
            else delete block.onlyIndices;
            persistTimeline(ed);
            setFoot();
            promptId = await queueDirectorRun();
        } finally {
            // Restore immediately: the queued prompt is already a snapshot, and
            // leaving these flags armed would make the next manual "Start run"
            // skip the fills (instant completion, no render).
            const current = anchorsBlock(ed);
            current.preRollOnly = previous.preRollOnly;
            current.forceRender = previous.forceRender;
            current.renderPass = previous.renderPass;
            current.mode = previous.mode;
            if (previous.onlyIndices === null) delete current.onlyIndices;
            else current.onlyIndices = previous.onlyIndices;
            persistTimeline(ed);
        }
        const result = await waitForAnchors(targets, 1500000, historyBefore, promptId);
        return { ...result, armed };
    }

    // ---- prompt material: source policy + the per-boundary editor ---------- //
    let promptInfo = [];
    let promptIndex = null;
    let promptDirty = false;

    function sourceKey(source) {
        const value = String(source || "auto").toLowerCase();
        return `anchor.source${value.charAt(0).toUpperCase()}${value.slice(1)}`;
    }

    function promptEntry(index) {
        return promptInfo.find((entry) => Number(entry?.index) === Number(index)) || null;
    }

    function promptShotsText(index) {
        const entry = promptEntry(index);
        if (!entry) return "";
        const from = String(entry.fromLabel || "");
        const to = String(entry.toLabel || "");
        if (from && to) return t("anchor.promptShots", { from, to });
        return from || to || t("anchor.promptNoNeighbours");
    }

    function promptIsOverridden(index) {
        const block = anchorsBlock(ed);
        return Boolean(String(block.prompts?.[index] ?? "").trim());
    }

    function insertToken(token) {
        const value = promptBodyEl.value;
        const start = promptBodyEl.selectionStart ?? value.length;
        const end = promptBodyEl.selectionEnd ?? start;
        const head = value.slice(0, start);
        const glue = head.trim() && !/\s$/.test(head) ? " " : "";
        promptBodyEl.value = `${head}${glue}${token}${value.slice(end)}`;
        const caret = start + glue.length + token.length;
        promptBodyEl.selectionStart = caret;
        promptBodyEl.selectionEnd = caret;
        promptDirty = true;
        promptBodyEl.focus();
    }

    function paintPromptEditor() {
        if (promptIndex === null) return;
        const entry = promptEntry(promptIndex);
        const overridden = promptIsOverridden(promptIndex);
        promptTitleEl.textContent = `#${promptIndex + 1}`;
        promptShotsEl.textContent = promptShotsText(promptIndex);
        promptBadgeEl.textContent = overridden
            ? t("anchor.promptOverride")
            : t("anchor.promptDerived", { source: t(sourceKey(entry?.source)) });
        promptBadgeEl.dataset.on = overridden ? "1" : "0";
        promptChipsEl.innerHTML = "";
        const material = [
            ["{{from_tail}}", entry?.fromTail],
            ["{{to_head}}", entry?.toHead],
            ["{{camera}}", entry?.camera],
            ["{{beat}}", ""],
            ["{{subject}}", ""],
        ];
        for (const [token, text] of material) {
            const chip = document.createElement("span");
            chip.className = "mmxa-chip";
            chip.textContent = token;
            chip.title = text ? `${token} \u2192 ${text}` : token;
            chip.dataset.empty = text ? "0" : "1";
            chip.addEventListener("click", () => insertToken(token));
            promptChipsEl.appendChild(chip);
        }
        promptRenderedEl.textContent = String(entry?.prompt || "");
        if (!promptDirty) promptBodyEl.value = String(entry?.body || "");
    }

    function openPromptEditor(index) {
        promptIndex = index;
        promptDirty = false;
        const stored = String(anchorsBlock(ed).prompts?.[index] ?? "");
        if (stored.trim()) promptBodyEl.value = stored;
        promptPanel.hidden = false;
        paintPromptEditor();
        schedulePlan();
    }

    promptBodyEl.addEventListener("input", () => {
        promptDirty = true;
    });
    promptSaveBtn.addEventListener("click", () => {
        if (promptIndex === null) return;
        const block = anchorsBlock(ed);
        if (!Array.isArray(block.prompts)) block.prompts = [];
        block.prompts[promptIndex] = promptBodyEl.value;
        persistTimeline(ed);
        promptDirty = false;
        hint = t("anchor.promptSaved", { index: promptIndex + 1 });
        setFoot();
        paintPromptEditor();
        schedulePlan();
        refresh();
    });
    promptClearBtn.addEventListener("click", () => {
        if (promptIndex === null) return;
        const block = anchorsBlock(ed);
        if (Array.isArray(block.prompts)) {
            block.prompts[promptIndex] = "";
            if (!block.prompts.some((entry) => String(entry || "").trim())) delete block.prompts;
        }
        persistTimeline(ed);
        promptDirty = false;
        promptBodyEl.value = "";
        hint = t("anchor.promptCleared", { index: promptIndex + 1 });
        setFoot();
        paintPromptEditor();
        schedulePlan();
        refresh();
    });
    promptCloseBtn.addEventListener("click", () => {
        promptPanel.hidden = true;
        promptIndex = null;
        promptDirty = false;
    });

    // ---- cells ------------------------------------------------------------ //
    function buildCells() {
        cellsEl.innerHTML = "";
        cells = [];
        const count = boundaryCount(ed);
        for (let index = 0; index < count; index += 1) {
            const cell = document.createElement("div");
            cell.className = "mmxa-cell";
            cell.dataset.index = String(index);
            cell.innerHTML = `
                <a class="mmxa-thumb" target="_blank" rel="noopener" data-i18n-title="anchor.thumbTitle"><span class="mmxa-thumb-empty"></span></a>
                <div class="mmxa-row"><span class="mmxa-idx"></span><span class="mmxa-lead"></span><span class="mmxa-seed"></span></div>
                <div class="mmxa-row mmxa-status"><i class="mmxa-dot"></i><span class="mmxa-status-txt"></span></div>
                <input class="mmxa-beat" type="text" data-i18n-placeholder="anchor.beatPlaceholder">
                <div class="mmxa-actions">
                    <button type="button" class="mmxa-btn mmxa-btn-eye" data-cell="toggle" data-i18n-title="anchor.toggleTitle">◉</button>
                    <button type="button" class="mmxa-btn mmxa-btn-go" data-cell="render" data-i18n-title="anchor.renderTitle">▶</button>
                    <button type="button" class="mmxa-btn mmxa-btn-ok" data-cell="approve" data-i18n-title="anchor.approve">✓</button>
                    <button type="button" class="mmxa-btn" data-cell="reroll" data-i18n-title="anchor.reroll">↻</button>
                    <button type="button" class="mmxa-btn" data-cell="prompt" data-i18n-title="anchor.promptEditTitle">✎</button>
                </div>`;
            const beatInput = cell.querySelector(".mmxa-beat");
            beatInput.addEventListener("change", () => {
                const block = anchorsBlock(ed);
                block.beats[index] = beatInput.value;
                persistTimeline(ed);
                refresh();
            });
            cell.querySelector('[data-cell="approve"]').addEventListener("click", () => {
                withBusy(async () => {
                    const item = diskItems.get(index);
                    if (!item) return;
                    const action = item.approved ? "pending" : "approve";
                    await anchorAction(nodeIdOf(ed), action, index);
                    clearFailure();
                    await refresh();
                });
            });
            cell.querySelector('[data-cell="reroll"]').addEventListener("click", () => {
                withBusy(async () => {
                    const block = anchorsBlock(ed);
                    const previous = Number(block.seeds[index]) || 0;
                    await anchorAction(nodeIdOf(ed), "delete", index);
                    block.seeds[index] = nextAnchorSeed(previous);
                    persistTimeline(ed);
                    hint = t("anchor.rerollPending", { index: index + 1 });
                    clearFailure();
                    await refresh();
                });
            });
            cell.querySelector('[data-cell="toggle"]').addEventListener("click", () => {
                const block = anchorsBlock(ed);
                const list = boundaryList(block, boundaryCount(ed));
                const set = new Set(list);
                if (set.has(index)) set.delete(index);
                else set.add(index);
                block.boundaries = [...set].sort((a, b) => a - b);
                persistTimeline(ed);
                refresh();
            });            cell.querySelector(".mmxa-thumb").addEventListener("click", (event) => {
                // Plain click = park the timeline playhead on this boundary;
                // Ctrl/Cmd/Shift+click keeps the browser default (open the image).
                if (event.ctrlKey || event.metaKey || event.shiftKey) return;
                event.preventDefault();
                seekToBoundary(index);
            });
            cell.querySelector('[data-cell="prompt"]').addEventListener("click", () => {
                if (promptIndex === index && !promptPanel.hidden) {
                    promptPanel.hidden = true;
                    promptIndex = null;
                    return;
                }
                openPromptEditor(index);
            });            cell.querySelector('[data-cell="render"]').addEventListener("click", () => {
                if (busy) return;
                cell.dataset.rendering = "1";
                hint = t("anchor.rendering", { index: index + 1 });
                setFoot();
                withBusy(async () => {
                    let result = { settled: true, changed: false };
                    try {
                        result = await runAnchors([index], { force: true });
                        clearFailure();
                    } finally {
                        delete cell.dataset.rendering;
                        // Decide the message on the listing, not on the run: a
                        // boundary that produced no PNG is a failure, never a
                        // "it was already there and got reused".
                        await refresh();
                        const onDisk = diskItems.has(index);
                        if (result.stopped) hint = t("anchor.stoppedHint", { index: index + 1 });
                        else if (!result.settled) hint = t("anchor.renderTimeout");
                        else if (result.changed) hint = t("anchor.renderedHint", { index: index + 1 });
                        else if (!onDisk) hint = t("anchor.renderNothing", { index: index + 1 });
                        else hint = t("anchor.renderedReused", { index: index + 1 });
                        if (result.armed) hint = `${hint} · ${t("anchor.modeArmed")}`;
                        setFoot();
                    }
                });
            });
            applyI18nDom(cell);
            cells.push(cell);
            cellsEl.appendChild(cell);
        }
        lastSignature = `${anchorsBlock(ed).mode}|${count}`;
    }

    function updateCells() {
        const block = anchorsBlock(ed);
        const count = boundaryCount(ed);
        if (cells.length !== count) return; // buildCells() owns the shape
        for (let index = 0; index < cells.length; index += 1) {
            const cell = cells[index];
            const wanted = Number(block.seeds[index]) || DEFAULT_ANCHORS.seedBase + index;
            const item = diskItems.get(index);
            const fresh = item && Number(item.seed) === Number(wanted);
            const status = !item ? "empty" : (fresh ? item.status : "pending");
            const stale = Boolean(item) && !fresh;
            cell.dataset.status = status;
            cell.dataset.stale = stale ? "1" : "0";
            cell.dataset.prompt = promptIsOverridden(index) ? "1" : "0";
            cell.querySelector(".mmxa-idx").textContent = `#${index + 1}`;
            const leadMode = block.placement === "lead";
            const leadFrame = leadMode && index > 0 ? leadFramesOf(block) : 0;
            cell.dataset.lead = leadFrame ? "1" : "0";
            const leadBadge = cell.querySelector(".mmxa-lead");
            if (leadBadge) {
                leadBadge.textContent = leadFrame
                    ? t("anchor.leadBadge", { seconds: (leadFrame / 24).toFixed(2).replace(/\.?0+$/, "") })
                    : "";
            }
            cell.querySelector(".mmxa-seed").textContent = `s${wanted}`;
            cell.querySelector(".mmxa-status-txt").textContent = item
                ? `${t(`anchor.status.${status}`)}${stale ? " · ↻" : ""}`
                : t("anchor.cellEmpty");
            const selected = boundarySelected(block, index);
            cell.dataset.selected = selected ? "1" : "0";
            const toggleBtn = cell.querySelector('[data-cell="toggle"]');
            if (toggleBtn) toggleBtn.textContent = selected ? "◉" : "○";
            const renderBtn = cell.querySelector('[data-cell="render"]');
            if (renderBtn) renderBtn.disabled = busy || !selected;
            const thumb = cell.querySelector(".mmxa-thumb");
            const existing = thumb.querySelector("img");
            const empty = thumb.querySelector(".mmxa-thumb-empty");
            if (item?.url) {
                const url = anchorThumbUrl(item);
                thumb.href = url;
                if (existing) {
                    if (existing.dataset.src !== url) {
                        existing.dataset.src = url;
                        existing.src = url;
                    }
                } else {
                    const img = document.createElement("img");
                    img.dataset.src = url;
                    img.src = url;
                    img.loading = "lazy";
                    img.alt = `anchor ${index + 1}`;
                    thumb.innerHTML = "";
                    thumb.appendChild(img);
                }
                empty?.remove();
            } else if (!existing) {
                if (!empty) {
                    const span = document.createElement("span");
                    span.className = "mmxa-thumb-empty";
                    span.textContent = t("anchor.cellEmpty");
                    thumb.appendChild(span);
                }
                const span = thumb.querySelector(".mmxa-thumb-empty");
                if (span) span.textContent = t("anchor.cellEmpty");
            }
            const beatInput = cell.querySelector(".mmxa-beat");
            const beat = String(block.beats[index] || "");
            if (document.activeElement !== beatInput && beatInput.value !== beat) beatInput.value = beat;
            const approveBtn = cell.querySelector('[data-cell="approve"]');
            approveBtn.disabled = busy || !item || stale;
            approveBtn.title = item?.approved ? t("anchor.unapprove") : t("anchor.approve");
            cell.querySelector('[data-cell="reroll"]').disabled = busy;
        }
    }

    // ---- preflight -------------------------------------------------------- //
    function schedulePlan() {
        if (planTimer) clearTimeout(planTimer);
        planTimer = setTimeout(() => {
            planTimer = 0;
            runPlan();
        }, PLAN_DEBOUNCE_MS);
    }

    async function runPlan() {
        if (!ed?.node || el.dataset.hidden === "1") return;
        const token = (planToken += 1);
        const { width, height, refLongEdge } = outputSize(ed);
        try {
            const data = await planAnchors(nodeIdOf(ed), {
                timelineData: String(ed.timelineWidget?.value || ""),
                width,
                height,
                refLongEdge,
            });
            if (token !== planToken) return;
            promptInfo = Array.isArray(data.boundaryText) ? data.boundaryText : [];
            if (promptIndex !== null) paintPromptEditor();
            lastEstimate = t("anchor.estimate", {
                mode: data.enabled ? t(`anchor.mode${data.mode === "soft" ? "Soft" : "Hard"}`) : t("anchor.modeOff"),
                boundaries: data.boundaries,
                chunk: data.chunkFrames,
                onDisk: data.boundariesOnDisk,
                anchor: (data.anchorWorkspaceGb ?? 0).toFixed(2),
                fill: (data.worstFillWorkspaceGb ?? 0).toFixed(2),
            });
            if (Array.isArray(data.missing) && data.missing.length && data.enabled) {
                lastEstimate += data.renderPass === false
                    ? ` · ${t("anchor.missingOff", { count: data.missing.length })}`
                    : ` · ${t("anchor.missing", { count: data.missing.length })}`;
            }
            if (Number(data.chunkFrames) && document.activeElement !== chunkInput) {
                chunkInput.value = String(data.chunkFrames);
            }
            setFoot();
        } catch (err) {
            if (token === planToken) fail(err);
        }
    }

    // ---- refresh ---------------------------------------------------------- //
    async function refresh() {
        if (!ed?.root?.isConnected) return;
        if (typeof ed.isMixedMode === "function" && ed.isMixedMode()) {
            el.style.display = "none";
            return;
        }
        el.style.display = "";
        const block = anchorsBlock(ed);
        if (!ed.timeline?.segments?.length) {
            el.dataset.hidden = "1";
            el.style.display = "none";
            return;
        }
        el.dataset.hidden = "0";

        // Self-heal transient preview flags left behind by an interrupted strip
        // action: if they stay armed, the next manual "Start run" silently skips
        // the fills (instant completion, no render).
        if (!busy) {
            const stale = anchorsBlock(ed);
            let healed = false;
            if (stale.preRollOnly === true) { stale.preRollOnly = false; healed = true; }
            if (stale.forceRender === true) { stale.forceRender = false; healed = true; }
            if (Array.isArray(stale.onlyIndices) && stale.onlyIndices.length) { delete stale.onlyIndices; healed = true; }
            if (stale.draft?.enabled === true) { stale.draft.enabled = false; healed = true; }
            if (healed) {
                persistTimeline(ed);
                hint = t("anchor.flagsCleared");
            }
        }

        if (document.activeElement !== modeSelect) modeSelect.value = block.mode;
        if (document.activeElement !== chunkInput) chunkInput.value = String(block.chunkFrames);
        if (document.activeElement !== draftScaleInput) draftScaleInput.value = String(Math.round((block.draft?.scale ?? DEFAULT_ANCHORS.draft.scale) * 100));
        if (document.activeElement !== draftStepsInput) draftStepsInput.value = String(block.draft?.steps ?? DEFAULT_ANCHORS.draft.steps);
        if (renderPassBox.checked !== block.renderPass) renderPassBox.checked = block.renderPass;
        if (placementSelect.value !== block.placement) placementSelect.value = block.placement;
        if (promptSourceSelect.value !== block.promptSource) promptSourceSelect.value = block.promptSource;
        if (leadHardBox.checked !== block.leadHard) leadHardBox.checked = block.leadHard;
        // "Pin pose" is the hard variant of lead placement: without lead there is
        // no interior frame to pin, so the box follows the placement.
        leadHardBox.disabled = busy || block.placement !== "lead";
        leadHardBox.parentElement.dataset.off = block.placement === "lead" ? "0" : "1";
        if (renderFillBox.checked !== !block.preRollOnly) renderFillBox.checked = !block.preRollOnly;
        approveAllBtn.disabled = busy;
        clearBtn.disabled = busy;

        const signature = `${block.mode}|${boundaryCount(ed)}`;
        if (signature !== lastSignature || cells.length !== boundaryCount(ed)) buildCells();

        try {
            const listing = await listAnchors(nodeIdOf(ed));
            // A boundary can have several PNGs on disk (re-rolled seeds, older
            // runs). Prefer the one matching this boundary's current seed so the
            // cell never shows a stale pose; fall back to the newest file.
            const pick = new Map();
            for (const item of listing.items) {
                const key = Number(item.index);
                const wanted = Number(block.seeds[key]) || DEFAULT_ANCHORS.seedBase + key;
                const current = pick.get(key);
                if (!current) {
                    pick.set(key, item);
                    continue;
                }
                const itemMatch = Number(item.seed) === wanted;
                const currentMatch = Number(current.seed) === wanted;
                if (itemMatch !== currentMatch) {
                    if (itemMatch) pick.set(key, item);
                    continue;
                }
                if (Number(item.mtime) >= Number(current.mtime)) pick.set(key, item);
            }
            diskItems = pick;
            clearFailure();
        } catch (err) {
            diskItems = new Map();
            fail(err);
        }
        updateCells();
        applyCollapsed();
        schedulePlan();
    }

    // ---- toolbar wiring --------------------------------------------------- //
    modeSelect.addEventListener("change", () => {
        const block = anchorsBlock(ed);
        block.mode = modeSelect.value;
        if (block.mode !== "off") {
            if (!block.beats.length) block.beats = new Array(boundaryCount(ed)).fill("");
            for (let index = 0; index < boundaryCount(ed); index += 1) {
                if (!block.seeds[index]) block.seeds[index] = DEFAULT_ANCHORS.seedBase + index;
            }
        }
        hint = block.mode === "off" ? t("anchor.offHint") : t("anchor.onHint");
        persistTimeline(ed);
        refresh();
    });

    chunkInput.addEventListener("change", () => {
        const block = anchorsBlock(ed);
        block.chunkFrames = clampInt(chunkInput.value, 5, 425, DEFAULT_ANCHORS.chunkFrames);
        chunkInput.value = String(block.chunkFrames);
        persistTimeline(ed);
        refresh();
    });

    draftScaleInput.addEventListener("change", () => {
        const block = anchorsBlock(ed);
        block.draft.scale = clampFloat(
            Number(draftScaleInput.value) / 100, 0.1, 1, DEFAULT_ANCHORS.draft.scale,
        );
        draftScaleInput.value = String(Math.round(block.draft.scale * 100));
        persistTimeline(ed);
        setFoot();
    });

    draftStepsInput.addEventListener("change", () => {
        const block = anchorsBlock(ed);
        block.draft.steps = clampInt(draftStepsInput.value, 0, 64, DEFAULT_ANCHORS.draft.steps);
        draftStepsInput.value = String(block.draft.steps);
        persistTimeline(ed);
        setFoot();
    });

    // Draft pass: preview the whole story cheaply (the draft scale/steps - by
    // default the final canvas at 8 steps) and stop. The flag is only true for
    // the queued snapshot, so the next Run is a normal full-quality pass again.
    draftBtn.addEventListener("click", () => {
        if (busy) return;
        withBusy(async () => {
            const block = anchorsBlock(ed);
            const before = await historyCount();
            block.draft.enabled = true;
            block.nonce = String(Date.now());
            persistTimeline(ed);
            hint = t("anchor.draftRunning", { scale: Math.round(block.draft.scale * 100) });
            setFoot();
            let promptId = "";
            try {
                promptId = await queueDirectorRun();
            } finally {
                block.draft.enabled = false;
                persistTimeline(ed);
            }
            const settled = await waitForHistory(before, 1800000, promptId);
            hint = stopRequested
                ? t("anchor.draftStopped")
                : settled ? t("anchor.draftDone") : t("anchor.draftTimeout");
            setFoot();
        });
    });

    renderPassBox.addEventListener("change", () => {
        anchorsBlock(ed).renderPass = Boolean(renderPassBox.checked);
        persistTimeline(ed);
        schedulePlan();
    });

    placementSelect.addEventListener("change", () => {
        const block = anchorsBlock(ed);
        block.placement = PLACEMENTS.includes(placementSelect.value) ? placementSelect.value : "boundary";
        persistTimeline(ed);
        hint = block.placement === "lead"
            ? t("anchor.placementLeadHint", { seconds: leadFramesOf(block) / 24 })
            : t("anchor.placementBoundaryHint");
        refresh();
    });

    promptSourceSelect.addEventListener("change", () => {
        const block = anchorsBlock(ed);
        block.promptSource = PROMPT_SOURCES.includes(promptSourceSelect.value)
            ? promptSourceSelect.value
            : DEFAULT_ANCHORS.promptSource;
        persistTimeline(ed);
        hint = t("anchor.promptSourceHint");
        if (promptIndex !== null) {
            promptDirty = false;
            promptBodyEl.value = "";
        }
        schedulePlan();
        refresh();
    });

    leadHardBox.addEventListener("change", () => {
        anchorsBlock(ed).leadHard = Boolean(leadHardBox.checked);
        persistTimeline(ed);
        schedulePlan();
        setFoot();
    });

    // "Render fill pieces" unchecked = pre-roll: render the boundary anchors,
    // write the storyboard, stop. Checking it again runs the normal pass, which
    // reuses the anchors already on disk.
    renderFillBox.addEventListener("change", () => {
        const block = anchorsBlock(ed);
        block.preRollOnly = !renderFillBox.checked;
        persistTimeline(ed);
        schedulePlan();
        setFoot();
    });

    approveAllBtn.addEventListener("click", () => {
        withBusy(async () => {
            await anchorAction(nodeIdOf(ed), "approve_all");
            clearFailure();
            hint = "";
            await refresh();
        });
    });

    preRollBtn.addEventListener("click", () => {
        if (busy) return;
        withBusy(async () => {
            const missing = boundaryList(anchorsBlock(ed), boundaryCount(ed)).filter((index) => !diskItems.has(index));
            hint = missing.length
                ? t("anchor.preRollRunning")
                : t("anchor.preRollNothing", { count: diskItems.size });
            setFoot();
            let settled = true;
            let armed = false;
            let stopped = false;
            try {
                const result = await runAnchors(missing);
                clearFailure();
                settled = result.settled;
                armed = result.armed === true;
                stopped = result.stopped === true;
            } finally {
                await refresh();
                const still = missing.filter((index) => !diskItems.has(index));
                if (stopped) {
                    hint = t("anchor.preRollStopped", {
                        done: Math.max(0, missing.length - still.length), total: missing.length,
                    });
                } else if (!settled) hint = t("anchor.renderTimeout");
                else if (still.length) hint = t("anchor.preRollPartial", { count: still.length });
                else hint = t("anchor.preRollDone");
                if (armed) hint = `${hint} · ${t("anchor.modeArmed")}`;
                setFoot();
            }
        });
    });

    presetAllBtn.addEventListener("click", () => {
        const block = anchorsBlock(ed);
        delete block.boundaries;
        persistTimeline(ed);
        hint = t("anchor.presetAllHint");
        refresh();
    });

    presetBookendsBtn.addEventListener("click", () => {
        const block = anchorsBlock(ed);
        const last = Math.max(0, boundaryCount(ed) - 1);
        block.boundaries = [0, last];
        persistTimeline(ed);
        hint = t("anchor.presetBookendsHint", { first: 1, last: last + 1 });
        refresh();
    });

    presetRenderedBtn.addEventListener("click", () => {
        const block = anchorsBlock(ed);
        const list = boundaryList(block, boundaryCount(ed)).filter((index) => diskItems.has(index));
        block.boundaries = list;
        persistTimeline(ed);
        hint = t("anchor.presetRenderedHint", { count: list.length });
        refresh();
    });

    clearBtn.addEventListener("click", () => {
        if (!window.confirm(t("anchor.clearConfirm"))) return;
        withBusy(async () => {
            await anchorAction(nodeIdOf(ed), "clear");
            clearFailure();
            hint = "";
            await refresh();
        });
    });

    // ---- mount ------------------------------------------------------------ //
    if (ed.viewport && ed.viewport.parentElement === ed.mainBody) {
        ed.mainBody.insertBefore(el, ed.viewport);
    } else {
        ed.mainBody.appendChild(el);
    }
    applyI18nDom(el);
    hint = anchorsBlock(ed).mode === "off" ? t("anchor.offHint") : t("anchor.onHint");

    const offLocale = onLocaleChange?.(() => {
        applyI18nDom(el);
        for (const option of modeSelect.options) {
            if (option.dataset.i18n) option.textContent = t(option.dataset.i18n);
        }
        updateCells();
        setFoot();
    });

    const api = {
        el,
        refresh: () => refresh(),
        // Debounced entry point for the editor's commit() hook: commits are
        // frequent (every drag), listings are not free.
        requestRefresh: () => {
            if (refreshTimer) clearTimeout(refreshTimer);
            refreshTimer = setTimeout(() => {
                refreshTimer = 0;
                refresh();
            }, 250);
        },
        destroy: () => {
            if (planTimer) clearTimeout(planTimer);
            if (refreshTimer) clearTimeout(refreshTimer);
            if (typeof offLocale === "function") offLocale();
            el.remove();
            if (ed._anchorStrip === api) ed._anchorStrip = null;
        },
    };

    ed._anchorStrip = api;
    refresh();
    return api;
}

export default installAnchorStrip;
