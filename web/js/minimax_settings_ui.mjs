/**
 * The Setup overlay: machine profile, baselines, run/app prefs, cache, diagnostics.
 *
 * Mounted once per Director panel and opened from the top bar's gear. All maths and
 * rules live in `minimax_motion_settings.mjs`; this file only moves values between
 * that module and real controls, and talks to the pack's own routes.
 *
 * The two write paths are deliberately different from the read paths:
 *
 * - settings changes are PATCHed to the server (app-wide, one file per user);
 * - "Apply to this project" goes through the caller's own output controls, because a
 *   direct write to `timeline.output` is overwritten by the next commit().
 */

import { t } from "./minimax_i18n.js";
import {
    ASPECT_RATIOS,
    EMBED_POLICY_CHOICES,
    backendWarnings,
    cacheKindSummary,
    cacheRows,
    collectBackendHints,
    diagnosticsText,
    formatBytes,
    metadataSummary,
    normalizeEmbedPolicy,
    resolveBaselines,
    runStateLabel,
} from "./minimax_motion_settings.mjs?boot=setup_v1";

const STYLES = `
.mmx-setup{position:absolute;inset:0;z-index:40;display:none;background:rgba(0,0,0,.55);}
.mmx-setup.open{display:block}
.mmx-setup .card{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:min(880px,94%);max-height:88%;display:flex;flex-direction:column;background:#1b1b1b;border:1px solid #333;border-radius:8px;box-shadow:0 18px 48px rgba(0,0,0,.6);color:#ddd;font-size:12px}
.mmx-setup .head{display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid #2c2c2c}
.mmx-setup .head b{font-size:13px}
.mmx-setup .tabs{display:flex;gap:4px;padding:8px 12px 0}
.mmx-setup .tabs button{background:#242424;border:1px solid #333;color:#bbb;border-radius:4px 4px 0 0;padding:5px 10px;cursor:pointer;font-size:12px}
.mmx-setup .tabs button.active{background:#2f2f2f;color:#fff;border-bottom-color:#2f2f2f}
.mmx-setup .body{padding:10px 12px;overflow:auto;flex:1 1 auto;border-top:1px solid #2c2c2c;margin-top:-1px}
.mmx-setup .pane{display:none;flex-direction:column;gap:8px}
.mmx-setup .pane.active{display:flex}
.mmx-setup .row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.mmx-setup .row>label{min-width:150px;color:#aaa}
.mmx-setup .row .hint{color:#888;font-size:11px}
.mmx-setup input[type=number],.mmx-setup input[type=text],.mmx-setup select{background:#141414;border:1px solid #383838;color:#eee;border-radius:3px;padding:3px 5px;font-size:12px}
.mmx-setup input[type=number]{width:88px}
.mmx-setup .card2{border:1px solid #2c2c2c;border-radius:6px;padding:8px 10px;background:#191919;display:flex;flex-direction:column;gap:6px}
.mmx-setup .card2>h4{margin:0;font-size:12px;color:#e8e8e8}
.mmx-setup .kv{display:grid;grid-template-columns:180px 1fr;gap:2px 10px;font-size:11.5px;color:#bbb}
.mmx-setup .kv span:nth-child(odd){color:#888}
.mmx-setup table{width:100%;border-collapse:collapse;font-size:11.5px}
.mmx-setup th,.mmx-setup td{text-align:left;padding:3px 6px;border-bottom:1px solid #262626;white-space:nowrap}
.mmx-setup th{color:#888;font-weight:500}
.mmx-setup td.num{text-align:right}
.mmx-setup .ok{color:#7fd18a}
.mmx-setup .bad{color:#ef8b8b}
.mmx-setup .warn{color:#e6c07b}
.mmx-setup .btn{background:#2a2a2a;border:1px solid #3a3a3a;color:#ddd;border-radius:3px;padding:4px 9px;cursor:pointer;font-size:11.5px}
.mmx-setup .btn:hover{background:#343434}
.mmx-setup .btn.primary{background:#2f5d3a;border-color:#3d7a4c;color:#eaf7ec}
.mmx-setup .btn.danger{background:#4a2727;border-color:#6b3535;color:#f2dede}
.mmx-setup .btn[disabled]{opacity:.5;cursor:default}
.mmx-setup pre{background:#111;border:1px solid #2c2c2c;border-radius:4px;padding:8px;max-height:240px;overflow:auto;font-size:11px;line-height:1.45;white-space:pre-wrap}
.mmx-setup .status{color:#8ab4f8;font-size:11.5px;min-height:16px}
.mmx-setup .foot{display:flex;align-items:center;gap:8px;padding:8px 12px;border-top:1px solid #2c2c2c}
.mmx-setup .foot .spacer{flex:1 1 auto}
`;

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
}

function row(labelText, ...controls) {
    const wrap = el("div", "row");
    if (labelText) wrap.appendChild(el("label", "", labelText));
    for (const control of controls) wrap.appendChild(asNode(control));
    return wrap;
}

/**
 * Coerce a row control into a Node.
 *
 * A stray string here used to throw `appendChild(parameter 1 is not of type
 * 'Node')`, which the loader caught - so the tab that threw stayed empty and the
 * tab after it never rendered at all. A label is the right degradation for text
 * that was passed where a control was expected.
 */
function asNode(value) {
    const NodeType = document.defaultView?.Node ?? globalThis.Node;
    if (NodeType && value instanceof NodeType) return value;
    return el("label", "", value == null ? "" : String(value));
}

function hint(text) {
    return el("span", "hint", text);
}

function numberInput(value, { min, max, step = 1, width, onCommit } = {}) {
    const input = document.createElement("input");
    input.type = "number";
    if (min != null) input.min = String(min);
    if (max != null) input.max = String(max);
    input.step = String(step);
    if (width) input.style.width = `${width}px`;
    input.value = value == null ? "" : String(value);
    const commit = () => {
        const parsed = Number(input.value);
        if (!Number.isFinite(parsed)) {
            input.value = String(value ?? "");
            return;
        }
        onCommit?.(parsed);
    };
    input.addEventListener("change", commit);
    input.addEventListener("blur", commit);
    return input;
}

function checkbox(value, onCommit) {
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = !!value;
    input.addEventListener("change", () => onCommit?.(input.checked));
    return input;
}

function select(value, options, onCommit) {
    const node = document.createElement("select");
    for (const option of options) {
        const item = document.createElement("option");
        item.value = option.value;
        item.textContent = option.label;
        if (String(option.value) === String(value)) item.selected = true;
        node.appendChild(item);
    }
    node.addEventListener("change", () => onCommit?.(node.value));
    return node;
}

/**
 * A destructive button that needs a second click.
 *
 * Inline instead of window.confirm(): the panel lives inside a DOM widget where a
 * modal browser dialog is exactly the thing that strands a canvas interaction.
 */
function confirmButton(label, confirmLabel, onConfirm) {
    const button = el("button", "btn danger", label);
    button.type = "button";
    let armed = false;
    let timer = null;
    const disarm = () => {
        armed = false;
        button.textContent = label;
        if (timer) clearTimeout(timer);
        timer = null;
    };
    button.addEventListener("click", () => {
        if (!armed) {
            armed = true;
            button.textContent = confirmLabel;
            timer = setTimeout(disarm, 5000);
            return;
        }
        disarm();
        onConfirm?.();
    });
    return button;
}

function kv(pairs) {
    const grid = el("div", "kv");
    for (const [key, value] of pairs) {
        grid.appendChild(el("span", "", key));
        grid.appendChild(el("span", "", value == null || value === "" ? "-" : String(value)));
    }
    return grid;
}

/** Render every pane and report failures instead of blanking the panel. */
function renderSafely(label, fn) {
    try {
        fn();
    } catch (error) {
        console.error(`[MiniMax H3 Motion Director] Setup ${label} pane failed:`, error);
    }
}

export function mountSettingsOverlay({
    host,
    api,
    getGraphNodes,
    getProjectInfo,
    getLastReport,
    applyBaselines,
    onSettingsChanged,
} = {}) {
    const root = el("div", "mmx-setup");
    root.innerHTML = `<style>${STYLES}</style>`;
    const card = el("div", "card");

    const head = el("div", "head");
    const title = el("b", "", t("setup.title"));
    const statusEl = el("span", "status");
    const closeBtn = el("button", "btn", t("setup.close"));
    closeBtn.type = "button";
    const headSpacer = el("div", "spacer");
    headSpacer.style.flex = "1 1 auto";
    head.append(title, headSpacer, statusEl, closeBtn);

    const tabs = el("div", "tabs");
    const TABS = [
        ["machine", "setup.tab.machine"],
        ["baselines", "setup.tab.baselines"],
        ["run", "setup.tab.run"],
        ["export", "setup.tab.export"],
        ["cache", "setup.tab.cache"],
        ["diagnostics", "setup.tab.diagnostics"],
    ];
    const tabButtons = new Map();
    for (const [id, key] of TABS) {
        const button = el("button", "", t(key));
        button.type = "button";
        button.dataset.tab = id;
        button.addEventListener("click", () => showTab(id));
        tabs.appendChild(button);
        tabButtons.set(id, button);
    }

    const body = el("div", "body");
    const panes = {};
    for (const [id] of TABS) {
        const pane = el("div", `pane pane-${id}`);
        body.appendChild(pane);
        panes[id] = pane;
    }

    const foot = el("div", "foot");
    const refreshBtn = el("button", "btn", t("setup.refresh"));
    refreshBtn.type = "button";
    const applyBtn = el("button", "btn primary", t("setup.applyToProject"));
    applyBtn.type = "button";
    const footHint = hint(t("setup.applyHint"));
    const footSpacer = el("div", "spacer");
    foot.append(applyBtn, footHint, footSpacer, refreshBtn);

    card.append(head, tabs, body, foot);
    root.appendChild(card);
    host?.appendChild(root);

    const state = {
        settings: null,
        machine: null,
        exportState: null,
        report: null,
        bundle: null,
        backendWarnings: [],
        lastReport: "",
        saveTimer: null,
        pendingPatch: {},
        stripResult: null,
    };

    function setStatus(text, tone = "") {
        statusEl.textContent = text || "";
        statusEl.className = `status ${tone}`.trim();
    }

    function currentTab() {
        return root.dataset.tab || "machine";
    }

    function showTab(id) {
        root.dataset.tab = id;
        for (const [key, pane] of Object.entries(panes)) pane.classList.toggle("active", key === id);
        for (const [key, button] of tabButtons) button.classList.toggle("active", key === id);
        if (id === "cache" && !state.report) void refreshCache();
        if (id === "diagnostics" && !state.bundle) void refreshDiagnostics();
    }

    async function fetchJson(path, options) {
        const response = await api.fetchApi(path, options);
        let data = null;
        try {
            data = await response.json();
        } catch {
            data = null;
        }
        if (!response.ok || (data && data.error)) {
            throw new Error((data && data.error) || `${path} -> HTTP ${response.status}`);
        }
        return data || {};
    }

    async function load() {
        setStatus(t("setup.loading"));
        try {
            const payload = await fetchJson("/minimax/motion-director/settings");
            state.settings = payload.settings;
            state.machine = payload.machine;
            state.detected = payload.detected_baselines || {};
            state.defaults = payload.defaults || null;
            state.exportState = payload.export_state || null;
            state.path = payload.path || "";
            onSettingsChanged?.(state.settings);
            renderAll();
            setStatus("");
        } catch (error) {
            setStatus(String(error.message || error), "bad");
        }
    }

    function patch(section, values, { immediate = false } = {}) {
        if (!state.settings) return;
        state.settings = {
            ...state.settings,
            [section]: { ...(state.settings[section] || {}), ...values },
        };
        state.pendingPatch[section] = { ...(state.pendingPatch[section] || {}), ...values };
        onSettingsChanged?.(state.settings);
        if (state.saveTimer) clearTimeout(state.saveTimer);
        const flush = async () => {
            const body = { settings: state.pendingPatch };
            state.pendingPatch = {};
            try {
                const payload = await fetchJson("/minimax/motion-director/settings", {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(body),
                });
                state.settings = payload.settings;
                state.machine = payload.machine;
                onSettingsChanged?.(state.settings);
                renderAll();
                setStatus(t("setup.saved"), "ok");
            } catch (error) {
                setStatus(String(error.message || error), "bad");
            }
        };
        if (immediate) void flush();
        else state.saveTimer = setTimeout(() => void flush(), 450);
    }

    // -- machine ---------------------------------------------------------------

    function renderMachine() {
        const pane = panes.machine;
        pane.replaceChildren();
        const machine = state.machine || {};
        const settings = state.settings || {};
        const device = machine.device || {};

        const facts = el("div", "card2");
        facts.appendChild(el("h4", "", t("setup.machine.card")));
        facts.appendChild(kv([
            [t("setup.machine.device"), device.name],
            [t("setup.machine.vram"), device.total_vram_gb != null
                ? t("setup.machine.vramValue", { total: device.total_vram_gb, free: device.free_vram_gb ?? "?" })
                : "-"],
            [t("setup.machine.capability"), device.capability],
            [t("setup.machine.profile"), `${machine.tier_label || machine.tier || "?"}${machine.downgraded ? " *" : ""}`],
            [t("setup.machine.pack"), `${machine.pack_version ?? "?"} / ComfyUI ${machine.comfyui_version ?? "?"}`],
            [t("setup.machine.runtime"), `Python ${machine.python_version ?? "?"} / torch ${machine.torch_version ?? "?"} / CUDA ${machine.cuda_version ?? "?"}`],
        ]));
        if (machine.tier_note) facts.appendChild(hint(machine.tier_note));
        if (machine.downgrade_reason) facts.appendChild(el("div", "warn", machine.downgrade_reason));
        pane.appendChild(facts);

        const override = el("div", "card2");
        override.appendChild(el("h4", "", t("setup.machine.override")));
        override.appendChild(row(
            t("setup.machine.deviceIndex"),
            numberInput(settings.machine?.device_index ?? 0, {
                min: 0,
                max: 16,
                onCommit: (value) => patch("machine", { device_index: value }, { immediate: true }),
            }),
            hint(t("setup.machine.deviceIndexHint")),
        ));
        override.appendChild(row(
            t("setup.machine.vramOverride"),
            numberInput(settings.machine?.vram_gb_override ?? 0, {
                min: 0,
                max: 1024,
                step: 0.5,
                onCommit: (value) => patch("machine", { vram_gb_override: value }, { immediate: true }),
            }),
            hint(t("setup.machine.vramOverrideHint")),
        ));
        override.appendChild(row(
            t("setup.machine.profile"),
            select(settings.machine?.profile || "auto", [
                { value: "auto", label: t("setup.machine.profileAuto") },
                { value: "custom", label: t("setup.machine.profileCustom") },
                ...["small", "medium", "large", "xl"].map((id) => ({ value: id, label: id })),
            ], (value) => patch("machine", { profile: value }, { immediate: true })),
        ));
        pane.appendChild(override);

        const backends = el("div", "card2");
        backends.appendChild(el("h4", "", t("setup.machine.backends")));
        const table = document.createElement("table");
        table.innerHTML = `<thead><tr><th>${t("setup.machine.backendName")}</th><th>${t("setup.machine.backendState")}</th><th>${t("setup.machine.backendDetail")}</th></tr></thead>`;
        const tbody = document.createElement("tbody");
        for (const [name, probe] of Object.entries(machine.backends || {})) {
            const tr = document.createElement("tr");
            const stateCell = el("td", probe.available ? "ok" : "bad", probe.available ? t("setup.machine.available") : t("setup.machine.unavailable"));
            tr.append(
                el("td", "", `${name}${probe.version ? ` ${probe.version}` : ""}`),
                stateCell,
                el("td", "", probe.detail || probe.error || ""),
            );
            tbody.appendChild(tr);
        }
        table.appendChild(tbody);
        backends.appendChild(table);

        if (state.backendWarnings.length) {
            const warnBox = el("div", "card2");
            warnBox.appendChild(el("h4", "warn", t("setup.machine.workflowWarnings")));
            for (const warning of state.backendWarnings) {
                warnBox.appendChild(el("div", "warn", warning.message));
                if (warning.error) warnBox.appendChild(hint(warning.error));
            }
            backends.appendChild(warnBox);
        }
        pane.appendChild(backends);

        const actions = el("div", "row");
        const detectBtn = el("button", "btn", t("setup.machine.redetect"));
        detectBtn.type = "button";
        detectBtn.addEventListener("click", async () => {
            setStatus(t("setup.loading"));
            try {
                const data = await fetchJson("/minimax/motion-director/machine?refresh=1");
                state.machine = data.machine;
                renderAll();
                setStatus(t("setup.saved"), "ok");
            } catch (error) {
                setStatus(String(error.message || error), "bad");
            }
        });
        const resetBtn = el("button", "btn", t("setup.machine.resetBaselines"));
        resetBtn.type = "button";
        resetBtn.addEventListener("click", async () => {
            try {
                const payload = await fetchJson("/minimax/motion-director/settings", {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ reset_baselines: true }),
                });
                state.settings = payload.settings;
                state.machine = payload.machine;
                onSettingsChanged?.(state.settings);
                renderAll();
                setStatus(t("setup.saved"), "ok");
            } catch (error) {
                setStatus(String(error.message || error), "bad");
            }
        });
        actions.append(detectBtn, resetBtn);
        pane.appendChild(actions);

        if (state.path) pane.appendChild(hint(t("setup.filePath", { path: state.path })));
    }

    // -- baselines -------------------------------------------------------------

    function renderBaselines() {
        const pane = panes.baselines;
        pane.replaceChildren();
        const settings = state.settings;
        if (!settings) return;
        const resolved = resolveBaselines(settings, state.machine);

        const card = el("div", "card2");
        card.appendChild(el("h4", "", t("setup.baselines.card")));
        card.appendChild(hint(t("setup.baselines.intro")));
        card.appendChild(row(
            t("setup.baselines.aspect"),
            select(settings.baselines.aspect_ratio, ASPECT_RATIOS.map((ratio) => ({
                value: ratio,
                label: ratio,
            })), (value) => patch("baselines", { aspect_ratio: value })),
        ));
        card.appendChild(row(
            t("setup.baselines.megapixels"),
            numberInput(settings.baselines.megapixels, {
                min: 0.1,
                max: 16,
                step: 0.1,
                onCommit: (value) => patch("baselines", { megapixels: value }),
            }),
            hint(t("setup.baselines.megapixelsHint")),
        ));
        card.appendChild(row(
            t("setup.baselines.width"),
            numberInput(settings.baselines.width, {
                min: 0,
                max: 8192,
                step: 32,
                onCommit: (value) => patch("baselines", { width: value }),
            }),
            el("label", "", t("setup.baselines.height")),
            numberInput(settings.baselines.height, {
                min: 0,
                max: 8192,
                step: 32,
                onCommit: (value) => patch("baselines", { height: value }),
            }),
            hint(t("setup.baselines.dimsHint")),
        ));
        card.appendChild(row(
            t("setup.baselines.segmentFrames"),
            numberInput(settings.baselines.segment_frames, {
                min: 5,
                max: 512,
                step: 17,
                onCommit: (value) => patch("baselines", { segment_frames: value }),
            }),
            hint(t("setup.baselines.segmentFramesHint", { seconds: resolved.segmentSeconds })),
        ));
        card.appendChild(row(
            t("setup.baselines.maxFrames"),
            numberInput(settings.baselines.max_segment_frames, {
                min: 5,
                max: 512,
                step: 17,
                onCommit: (value) => patch("baselines", { max_segment_frames: value }),
            }),
            hint(t("setup.baselines.maxFramesHint")),
        ));
        card.appendChild(row(
            t("setup.baselines.refMaxSize"),
            numberInput(settings.baselines.ref_max_size, {
                min: 0,
                max: 4096,
                step: 32,
                onCommit: (value) => patch("baselines", { ref_max_size: value }),
            }),
            hint(t("setup.baselines.refMaxSizeHint")),
        ));
        pane.appendChild(card);

        const continuity = el("div", "card2");
        continuity.appendChild(el("h4", "", t("setup.baselines.continuityCard")));
        continuity.appendChild(row(
            t("setup.baselines.continuity"),
            checkbox(settings.baselines.continuity, (value) => patch("baselines", { continuity: value })),
        ));
        continuity.appendChild(row(
            t("setup.baselines.overlap"),
            numberInput(settings.baselines.continuity_overlap_frames, {
                min: 1,
                max: 81,
                step: 4,
                onCommit: (value) => patch("baselines", { continuity_overlap_frames: value }),
            }),
        ));
        continuity.appendChild(row(
            t("setup.baselines.detected"),
            el("span", resolved.followsDetected ? "ok" : "warn",
                t("setup.baselines.detectedValue", {
                    frames: resolved.detectedFrames,
                    megapixels: resolved.detectedMegapixels || "-",
                })),
        ));
        pane.appendChild(continuity);
    }

    // -- run + app -------------------------------------------------------------

    function renderRun() {
        const pane = panes.run;
        pane.replaceChildren();
        const settings = state.settings;
        if (!settings) return;

        const run = el("div", "card2");
        run.appendChild(el("h4", "", t("setup.run.card")));
        run.appendChild(row(
            t("setup.run.autoSave"),
            checkbox(settings.run.auto_save_workflow, (value) => patch("run", { auto_save_workflow: value })),
            hint(t("setup.run.autoSaveHint")),
        ));
        run.appendChild(row(
            t("setup.run.keepModels"),
            checkbox(settings.run.keep_models_resident, (value) => patch("run", { keep_models_resident: value })),
            hint(t("setup.run.keepModelsHint")),
        ));
        run.appendChild(row(
            t("setup.run.verbose"),
            checkbox(settings.run.verbose_logging, (value) => patch("run", { verbose_logging: value })),
            hint(t("setup.run.verboseHint")),
        ));
        run.appendChild(row(
            t("setup.run.clearVram"),
            checkbox(settings.baselines.clear_vram_between_segments, (value) => patch("baselines", { clear_vram_between_segments: value })),
            hint(t("setup.run.clearVramHint")),
        ));
        run.appendChild(row(
            t("setup.run.exportMode"),
            select(settings.baselines.export_mode, [
                { value: "all", label: t("setup.run.exportAll") },
                { value: "segments", label: t("setup.run.exportSegments") },
            ], (value) => patch("baselines", { export_mode: value })),
        ));
        pane.appendChild(run);

        const app = el("div", "card2");
        app.appendChild(el("h4", "", t("setup.app.card")));
        app.appendChild(row(
            t("setup.app.locale"),
            select(settings.app.locale, [
                { value: "auto", label: t("setup.app.localeAuto") },
                { value: "zh", label: "中文" },
                { value: "en", label: "English" },
            ], (value) => patch("app", { locale: value })),
            hint(t("setup.app.localeHint")),
        ));
        app.appendChild(row(
            t("setup.app.livePreview"),
            checkbox(settings.app.live_tae_preview, (value) => patch("app", { live_tae_preview: value })),
        ));
        app.appendChild(row(
            t("setup.app.previewAudio"),
            checkbox(settings.app.preview_audio, (value) => patch("app", { preview_audio: value })),
        ));
        app.appendChild(row(
            t("setup.app.cacheWarn"),
            numberInput(settings.cache.warn_over_gb, {
                min: 0,
                max: 10000,
                step: 10,
                onCommit: (value) => patch("cache", { warn_over_gb: value }),
            }),
            hint(t("setup.app.cacheWarnHint")),
        ));
        pane.appendChild(app);
    }

    // -- cache -----------------------------------------------------------------

    async function refreshCache() {
        try {
            state.report = await fetchJson("/minimax/motion-director/cache_report");
            renderCache();
        } catch (error) {
            setStatus(String(error.message || error), "bad");
        }
    }

    function renderCache() {
        const pane = panes.cache;
        pane.replaceChildren();
        const report = state.report;
        if (!report) {
            pane.appendChild(hint(t("setup.loading")));
            return;
        }
        const summary = el("div", "card2");
        summary.appendChild(el("h4", "", t("setup.cache.card")));
        summary.appendChild(kv([
            [t("setup.cache.total"), `${report.total_gb} GB`],
            [t("setup.cache.disk"), report.disk?.free_gb != null
                ? t("setup.cache.diskValue", { free: report.disk.free_gb, total: report.disk.total_gb })
                : "-"],
            [t("setup.cache.location"), report.output_dir],
        ]));
        if (report.warn_over_gb > 0 && report.total_gb >= report.warn_over_gb) {
            summary.appendChild(el("div", "warn", t("setup.cache.overWarn", { limit: report.warn_over_gb })));
        }
        const actions = el("div", "row");
        for (const kind of cacheKindSummary(report)) {
            const clearAll = confirmButton(
                t("setup.cache.clearKind", { kind: kind.label, size: kind.size }),
                t("setup.cache.confirm"),
                async () => {
                    try {
                        const result = await fetchJson("/minimax/motion-director/cache_clear", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ kind: kind.id, all: true }),
                        });
                        setStatus(t("setup.cache.cleared", { size: `${result.gb} GB` }), "ok");
                        await refreshCache();
                    } catch (error) {
                        setStatus(String(error.message || error), "bad");
                    }
                },
            );
            actions.appendChild(clearAll);
        }
        const refresh = el("button", "btn", t("setup.refresh"));
        refresh.type = "button";
        refresh.addEventListener("click", () => void refreshCache());
        actions.appendChild(refresh);
        summary.appendChild(actions);
        pane.appendChild(summary);

        const rows = cacheRows(report);
        if (!rows.length) {
            pane.appendChild(hint(t("setup.cache.empty")));
            return;
        }
        const table = document.createElement("table");
        table.innerHTML = `<thead><tr>
            <th>${t("setup.cache.node")}</th>
            <th>${t("setup.cache.kind")}</th>
            <th class="num">${t("setup.cache.size")}</th>
            <th class="num">${t("setup.cache.segments")}</th>
            <th>${t("setup.cache.runState")}</th>
            <th></th>
        </tr></thead>`;
        const tbody = document.createElement("tbody");
        for (const rowData of rows.slice(0, 60)) {
            const tr = document.createElement("tr");
            const stateCell = el("td", rowData.running ? "warn" : "", runStateLabel(rowData.state)
                + (rowData.segmentTotal ? ` ${rowData.done}/${rowData.segmentTotal}` : ""));
            const clear = confirmButton(t("setup.cache.clearOne"), t("setup.cache.confirm"), async () => {
                try {
                    const result = await fetchJson("/minimax/motion-director/cache_clear", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ kind: rowData.kind, node: rowData.node }),
                    });
                    setStatus(t("setup.cache.cleared", { size: `${result.gb} GB` }), "ok");
                    await refreshCache();
                } catch (error) {
                    setStatus(String(error.message || error), "bad");
                }
            });
            const cell = document.createElement("td");
            cell.appendChild(clear);
            tr.append(
                el("td", "", rowData.node),
                el("td", "", rowData.kind),
                el("td", "num", rowData.size),
                el("td", "num", String(rowData.segments)),
                stateCell,
                cell,
            );
            tbody.appendChild(tr);
        }
        table.appendChild(tbody);
        pane.appendChild(table);
        pane.appendChild(hint(t("setup.cache.note")));
    }

    // -- diagnostics -----------------------------------------------------------

    async function refreshDiagnostics() {
        try {
            state.bundle = await fetchJson("/minimax/motion-director/diagnostics");
            state.lastReport = String(getLastReport?.() || "");
            renderDiagnostics();
        } catch (error) {
            setStatus(String(error.message || error), "bad");
        }
    }

    function diagnosticsBody() {
        const text = diagnosticsText({
            bundle: state.bundle,
            project: getProjectInfo?.() || null,
            lastReport: state.lastReport,
            warnings: state.backendWarnings,
        });
        const browser = typeof navigator !== "undefined" ? navigator.userAgent : "";
        return browser ? `${text}\nBrowser: ${browser}` : text;
    }

    function renderDiagnostics() {
        const pane = panes.diagnostics;
        pane.replaceChildren();
        if (!state.bundle) {
            pane.appendChild(hint(t("setup.loading")));
            return;
        }
        const card = el("div", "card2");
        card.appendChild(el("h4", "", t("setup.diag.card")));
        card.appendChild(hint(t("setup.diag.intro")));
        const actions = el("div", "row");
        const copy = el("button", "btn primary", t("setup.diag.copy"));
        copy.type = "button";
        copy.addEventListener("click", async () => {
            const text = diagnosticsBody();
            try {
                await navigator.clipboard.writeText(text);
                setStatus(t("setup.diag.copied"), "ok");
            } catch {
                preview.textContent = text;
                setStatus(t("setup.diag.copyFailed"), "warn");
            }
        });
        const download = el("button", "btn", t("setup.diag.download"));
        download.type = "button";
        download.addEventListener("click", () => {
            const payload = {
                ...state.bundle,
                project: getProjectInfo?.() || null,
                browser: typeof navigator !== "undefined" ? navigator.userAgent : "",
                report: state.lastReport,
            };
            const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
            const url = URL.createObjectURL(blob);
            const link = document.createElement("a");
            const stamp = new Date().toISOString().replace(/[:.]/g, "-");
            link.href = url;
            link.download = `mmx-motion-director-diagnostics-${stamp}.json`;
            document.body.appendChild(link);
            link.click();
            link.remove();
            setTimeout(() => URL.revokeObjectURL(url), 4000);
            setStatus(t("setup.diag.downloaded"), "ok");
        });
        const refresh = el("button", "btn", t("setup.refresh"));
        refresh.type = "button";
        refresh.addEventListener("click", () => {
            state.bundle = null;
            state.lastReport = "";
            void refreshDiagnostics();
        });
        actions.append(copy, download, refresh);
        card.appendChild(actions);
        const preview = document.createElement("pre");
        preview.textContent = diagnosticsBody();
        card.appendChild(preview);
        pane.appendChild(card);
    }

    // -- export ----------------------------------------------------------------

    function renderExport() {
        const pane = panes.export;
        pane.replaceChildren();
        const settings = state.settings;
        if (!settings) return;
        const policy = normalizeEmbedPolicy(settings.export?.embed_workflow);

        const card = el("div", "card2");
        card.appendChild(el("h4", "", t("setup.export.card")));
        card.appendChild(hint(t("setup.export.intro")));
        card.appendChild(row(
            t("setup.export.policy"),
            select(policy, [
                { value: "auto", label: t("setup.export.auto") },
                { value: "always", label: t("setup.export.always") },
                { value: "never", label: t("setup.export.never") },
            ], (value) => patch("export", { embed_workflow: normalizeEmbedPolicy(value) })),
        ));
        card.appendChild(row(
            t("setup.export.effective"),
            el("span", policy === "never" ? "warn" : "ok", metadataSummary(state.exportState, policy)),
        ));
        card.appendChild(hint(t("setup.export.scope")));
        pane.appendChild(card);

        const strip = el("div", "card2");
        strip.appendChild(el("h4", "", t("setup.export.stripCard")));
        strip.appendChild(hint(t("setup.export.stripIntro")));
        const input = document.createElement("input");
        input.type = "text";
        input.style.width = "420px";
        input.placeholder = t("setup.export.stripPlaceholder");
        const button = el("button", "btn", t("setup.export.stripButton"));
        button.type = "button";
        button.addEventListener("click", async () => {
            const filename = String(input.value || "").trim();
            if (!filename) {
                setStatus(t("setup.export.stripNeedsName"), "warn");
                return;
            }
            button.disabled = true;
            setStatus(t("setup.export.stripping"));
            try {
                const result = await fetchJson("/minimax/motion-director/strip_metadata", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ filename }),
                });
                state.stripResult = result;
                setStatus(t("setup.export.stripped", {
                    name: result.filename,
                    size: formatBytes(result.after_bytes),
                    tags: (result.removed_tags || []).length,
                }), "ok");
                renderExport();
            } catch (error) {
                setStatus(String(error.message || error), "bad");
            } finally {
                button.disabled = false;
            }
        });
        strip.appendChild(row(t("setup.export.stripFile"), input, button));
        if (state.stripResult) {
            strip.appendChild(kv([
                [t("setup.export.stripResult"), state.stripResult.path],
                [t("setup.export.stripTags"), (state.stripResult.removed_tags || []).join(", ") || "-"],
            ]));
        }
        pane.appendChild(strip);
    }

    // -- shared ----------------------------------------------------------------

    function renderAll() {
        if (!state.settings) return;
        // The graph gives raw node summaries; the rules module owns which widget
        // values name a backend and what each of them needs.
        const nodes = typeof getGraphNodes === "function" ? getGraphNodes() : [];
        state.backendHints = collectBackendHints(nodes);
        state.backendWarnings = backendWarnings(state.backendHints, state.machine?.backends || {});
        // One pane failing must not take the rest of the tabs down with it.
        renderSafely("machine", renderMachine);
        renderSafely("baselines", renderBaselines);
        renderSafely("run", renderRun);
        renderSafely("export", renderExport);
        if (state.report) renderSafely("cache", renderCache);
        if (state.bundle) renderSafely("diagnostics", renderDiagnostics);
        showTab(currentTab());
    }

    applyBtn.addEventListener("click", () => {
        if (!state.settings) return;
        const resolved = resolveBaselines(state.settings, state.machine);
        const result = applyBaselines?.(resolved, state.settings);
        setStatus(t("setup.applyStatus", {
            width: result?.width ?? resolved.width,
            height: result?.height ?? resolved.height,
            frames: resolved.segmentFrames,
        }), "ok");
    });

    refreshBtn.addEventListener("click", () => void load());
    closeBtn.addEventListener("click", () => close());
    root.addEventListener("click", (event) => {
        if (event.target === root) close();
    });
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && root.classList.contains("open")) close();
    });

    function open() {
        root.classList.add("open");
        showTab(currentTab());
        if (!state.settings) void load();
    }

    function close() {
        root.classList.remove("open");
    }

    return {
        root,
        open,
        close,
        refresh: load,
        reloadSettings: (settings, machine) => {
            if (settings) state.settings = settings;
            if (machine) state.machine = machine;
            renderAll();
        },
        getSettings: () => state.settings,
        render: renderAll,
        formatBytes,
    };
}
