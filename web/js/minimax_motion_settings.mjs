/**
 * App-wide Motion Director settings: what they mean, and what they are allowed to do.
 *
 * Pure and DOM-free so the rules can be tested without a panel. The Setup overlay
 * (`minimax_settings_ui.mjs`) only moves values between here and the real controls.
 *
 * Three rules, each one paid for by a bug this pack already had:
 *
 * - A **baseline is a starting point for new content**, never a rewrite. Changing
 *   width/height or segment length invalidates segment caches and the run manifest's
 *   Done marks, so an existing project is only ever changed by the explicit "Apply to
 *   this project" button.
 * - **Machine facts are detected, not typed.** The stored override exists for a
 *   second GPU or a wrong driver reading; the tier always comes from the detected
 *   VRAM (and drops a tier when something else is holding the card).
 * - **Attention backends are a machine property.** The same workflow that runs on the
 *   ComfyKitchen int8 path on one box needs SageAttention on another, so the profile
 *   records which backends actually import and the panel warns about the workflow's
 *   own node values instead of letting a sampling run discover it.
 */

import { t } from "./minimax_i18n.js";

export const SETTINGS_SCHEMA_VERSION = 1;

/** Aspect ratios the server stores (locale-free) → the panel's display labels. */
export const ASPECT_RATIO_LABELS = {
    "1:1": "1:1 (方形)",
    "2:3": "2:3 (竖版照片)",
    "3:2": "3:2 (横版照片)",
    "3:4": "3:4 (竖版标准)",
    "4:3": "4:3 (标准)",
    "9:16": "9:16 (竖屏)",
    "16:9": "16:9 (宽屏)",
    "21:9": "21:9 (超宽)",
};

export const ASPECT_RATIOS = Object.keys(ASPECT_RATIO_LABELS);
export const DEFAULT_ASPECT_RATIO = "16:9";

/** H3 grids, mirrored from the server so a preview cannot promise invalid numbers. */
export const CANVAS_MULTIPLE = 32;
export const MIN_FRAMES = 5;
export const MAX_FRAMES = 512;
export const FRAME_GRID_MODULUS = 17;
export const FRAME_GRID_REMAINDER = 5;
export const H3_FPS = 24;

/** Keys a settings patch is allowed to carry, per section. */
export const SETTINGS_SECTIONS = ["machine", "baselines", "run", "app", "export", "cache"];

/**
 * Whether an exported video carries the ComfyUI workflow + prompt tags.
 *
 * `auto` follows ComfyUI (its `--disable-metadata` flag), `always` overrides that
 * flag, `never` strips - so a shared clip cannot leak the prompt text and local
 * paths that live inside the graph. Mirrors `director/video_metadata.py`.
 */
export const EMBED_POLICY_CHOICES = ["auto", "always", "never"];

export function normalizeEmbedPolicy(value) {
    const text = String(value ?? "").trim().toLowerCase();
    return EMBED_POLICY_CHOICES.includes(text) ? text : "auto";
}

/** One sentence for the panel: what happens to the next saved video, and why. */
export function metadataSummary(exportState, policy) {
    const chosen = normalizeEmbedPolicy(policy ?? exportState?.policy);
    if (chosen === "always") return t("setup.export.stateAlways");
    if (chosen === "never") return t("setup.export.stateNever");
    return exportState?.comfyui_disabled
        ? t("setup.export.stateAutoDisabled")
        : t("setup.export.stateAuto");
}

export function aspectLabelFromRatio(ratio) {
    return ASPECT_RATIO_LABELS[String(ratio || "").trim()] || ASPECT_RATIO_LABELS[DEFAULT_ASPECT_RATIO];
}

export function ratioFromAspectLabel(label) {
    const value = String(label || "").trim();
    for (const [ratio, display] of Object.entries(ASPECT_RATIO_LABELS)) {
        if (display === value) return ratio;
    }
    // The panel's custom ("自定义") and any unknown label keep their own math; the
    // stored ratio stays the default so a round-trip cannot invent a ratio.
    return DEFAULT_ASPECT_RATIO;
}

/** Mirror of the server defaults, used until the first fetch answers. */
export function defaultSettings() {
    return {
        schema_version: SETTINGS_SCHEMA_VERSION,
        machine: { profile: "auto", device_index: 0, vram_gb_override: 0 },
        baselines: {
            aspect_ratio: DEFAULT_ASPECT_RATIO,
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
        app: { locale: "auto", live_tae_preview: true, preview_audio: true },
        export: { embed_workflow: "auto" },
        cache: { warn_over_gb: 80 },
        updated_at: 0,
    };
}

function isPlainObject(value) {
    return !!value && typeof value === "object" && !Array.isArray(value);
}

export function mergeSettings(stored, defaults = defaultSettings()) {
    const merged = { ...defaults };
    if (!isPlainObject(stored)) return merged;
    for (const key of Object.keys(stored)) {
        const value = stored[key];
        merged[key] = isPlainObject(value) && isPlainObject(defaults[key])
            ? mergeSettings(value, defaults[key])
            : value;
    }
    return merged;
}

/** Frame counts on H3's 17k+5 grid, capped to what the model accepts. */
export function alignFramesToGrid(frames, maxFrames = MAX_FRAMES) {
    const cap = Math.max(MIN_FRAMES, Math.floor(Number(maxFrames) || MAX_FRAMES));
    let value = Math.min(cap, Math.max(MIN_FRAMES, Math.round(Number(frames) || MIN_FRAMES)));
    while ((value - FRAME_GRID_REMAINDER) % FRAME_GRID_MODULUS !== 0) {
        value += 1;
        if (value > cap) {
            // The cap is normally off-grid (512), so snapping up from it would hand
            // the sampler a count the model refuses: snap the cap back down instead.
            value = cap;
            while (value > MIN_FRAMES && (value - FRAME_GRID_REMAINDER) % FRAME_GRID_MODULUS !== 0) {
                value -= 1;
            }
            break;
        }
    }
    return value;
}

export function dimsFromBaselines(baselines) {
    const width = Number(baselines?.width) || 0;
    const height = Number(baselines?.height) || 0;
    return { width, height, custom: width > 0 && height > 0 };
}

/**
 * The values the panel applies: stored baselines, with the detected tier's numbers
 * shown alongside so "following the profile" stays visible instead of implied.
 */
export function resolveBaselines(settings, machine) {
    const merged = mergeSettings(settings);
    const baselines = merged.baselines;
    const detected = machine?.baselines || {};
    const frames = alignFramesToGrid(baselines.segment_frames);
    const maxFrames = Math.max(frames, alignFramesToGrid(baselines.max_segment_frames));
    return {
        aspectRatio: baselines.aspect_ratio,
        aspectLabel: aspectLabelFromRatio(baselines.aspect_ratio),
        megapixels: Number(baselines.megapixels) || 0.4,
        width: Number(baselines.width) || 0,
        height: Number(baselines.height) || 0,
        segmentFrames: frames,
        segmentSeconds: Math.round((frames / H3_FPS) * 100) / 100,
        maxSegmentFrames: maxFrames,
        refMaxSize: Number(baselines.ref_max_size) || 0,
        clearVramBetweenSegments: !!baselines.clear_vram_between_segments,
        exportMode: baselines.export_mode === "segments" ? "segments" : "all",
        continuity: !!baselines.continuity,
        continuityOverlapFrames: Number(baselines.continuity_overlap_frames) || 9,
        detectedFrames: alignFramesToGrid(detected.segment_frames ?? frames),
        detectedMegapixels: Number(detected.megapixels) || 0,
        followsDetected:
            alignFramesToGrid(detected.segment_frames ?? frames) === frames
            && Math.abs((Number(detected.megapixels) || 0) - (Number(baselines.megapixels) || 0)) < 0.01,
    };
}

/**
 * Frame count for a segment that is being created *now*.
 *
 * The task's own floor and the model cap win over the baseline, so a settings file
 * can never produce an unrenderable segment.
 */
export function baselineFrameCount(baselines, { minFrames = MIN_FRAMES, maxFrames = MAX_FRAMES } = {}) {
    const wanted = alignFramesToGrid(
        Number(baselines?.segment_frames) || defaultSettings().baselines.segment_frames,
    );
    const floor = Math.max(MIN_FRAMES, Math.floor(Number(minFrames) || MIN_FRAMES));
    const cap = Math.max(floor, Math.floor(Number(maxFrames) || MAX_FRAMES));
    return alignFramesToGrid(Math.min(cap, Math.max(floor, wanted)), cap);
}

/** Duration (seconds) that produces the baseline frame count, for card-style editors. */
export function baselineDurationSec(baselines, options) {
    const frames = baselineFrameCount(baselines, options);
    const exact = frames / H3_FPS;
    return Math.round(exact * 10) / 10;
}

// ---------------------------------------------------------------------------
// Attention backends
// ---------------------------------------------------------------------------

/**
 * Node widget values that name an attention backend, and what each one needs.
 *
 * `needs: null` means "whatever the graph already has" - a workflow that asks for the
 * built-in path cannot conflict with the machine, so it is never reported.
 */
export const BACKEND_RULES = [
    { needs: "comfy_kitchen", pattern: /kitchen/i, label: "ComfyKitchen (int8)" },
    { needs: "sage", pattern: /sage/i, label: "SageAttention" },
    { needs: "xformers", pattern: /xformers?/i, label: "xFormers" },
    { needs: "triton", pattern: /triton/i, label: "Triton" },
    { needs: null, pattern: /^(existing|inherit|auto|default|pytorch|torch|sdpa|dense|none|off)$/i, label: "built-in" },
];

/** Widget names that carry a backend choice somewhere in the pack's workflows. */
export const BACKEND_WIDGET_NAMES = new Set([
    "attention_backend",
    "dense_backend",
    "engine",
    "backend",
]);

export function backendRequirementFor(value) {
    const text = String(value ?? "").trim();
    if (!text) return null;
    for (const rule of BACKEND_RULES) {
        if (rule.pattern.test(text)) return rule;
    }
    return { needs: null, pattern: null, label: text };
}

/**
 * Backend choices found in a workflow.
 *
 * @param {Array<{id: string|number, type: string, widgets?: Record<string, unknown>}>} nodes
 * @returns {Array<{nodeId: string, type: string, widget: string, value: string, needs: string|null, label: string}>}
 */
export function collectBackendHints(nodes) {
    const hints = [];
    for (const node of nodes || []) {
        const widgets = node?.widgets || {};
        for (const [name, value] of Object.entries(widgets)) {
            if (!BACKEND_WIDGET_NAMES.has(name)) continue;
            const rule = backendRequirementFor(value);
            if (!rule || !rule.needs) continue;
            hints.push({
                nodeId: String(node.id ?? ""),
                type: String(node.type || ""),
                widget: name,
                value: String(value ?? ""),
                needs: rule.needs,
                label: rule.label,
            });
        }
    }
    return hints;
}

/** Machine-side name for a backend key (the probe payload uses these keys). */
export function backendProbeName(needs) {
    if (needs === "sage") return "sage";
    if (needs === "triton") return "triton";
    if (needs === "xformers") return "xformers";
    if (needs === "comfy_kitchen") return "comfy_kitchen";
    return null;
}

/**
 * Which of the workflow's backend choices this machine cannot run.
 *
 * @param {Array} hints from `collectBackendHints`
 * @param {Record<string, {available?: boolean, error?: string, version?: string|null}>} backends
 */
export function backendWarnings(hints, backends) {
    const warnings = [];
    for (const hint of hints || []) {
        const probeName = backendProbeName(hint.needs);
        if (!probeName) continue;
        const probe = (backends || {})[probeName];
        if (!probe) continue;
        if (probe.available) continue;
        warnings.push({
            ...hint,
            message: t("setup.backendMissing", {
                backend: hint.label,
                value: hint.value,
                node: hint.nodeId,
            }),
            error: String(probe.error || ""),
        });
    }
    return warnings;
}

// ---------------------------------------------------------------------------
// Cache + diagnostics formatting
// ---------------------------------------------------------------------------

export function formatBytes(bytes) {
    const value = Number(bytes) || 0;
    if (value < 1024) return `${value} B`;
    const units = ["KB", "MB", "GB", "TB"];
    let scaled = value / 1024;
    let index = 0;
    while (scaled >= 1024 && index < units.length - 1) {
        scaled /= 1024;
        index += 1;
    }
    return `${scaled >= 10 ? scaled.toFixed(0) : scaled.toFixed(1)} ${units[index]}`;
}

/** Flatten a cache report into display rows, biggest first. */
export function cacheRows(report) {
    const rows = [];
    for (const kind of report?.kinds || []) {
        for (const node of kind.nodes || []) {
            rows.push({
                kind: kind.id,
                kindLabel: kind.label,
                node: node.node,
                bytes: Number(node.bytes) || 0,
                size: formatBytes(node.bytes),
                files: Number(node.files) || 0,
                segments: Number(node.segments) || 0,
                state: String(node.state || "none"),
                done: Number(node.done) || 0,
                segmentTotal: Number(node.segment_total) || 0,
                updatedMs: Number(node.updated_ms) || 0,
                running: String(node.state || "") === "running",
            });
        }
    }
    rows.sort((left, right) => right.bytes - left.bytes);
    return rows;
}

/** Per-kind totals for the cache section header. */
export function cacheKindSummary(report) {
    return (report?.kinds || []).map((kind) => ({
        id: kind.id,
        label: kind.label,
        path: kind.path,
        size: formatBytes(kind.bytes),
        bytes: Number(kind.bytes) || 0,
        files: Number(kind.files) || 0,
        nodes: (kind.nodes || []).length,
        exists: !!kind.exists,
    }));
}

function runStateLabel(state) {
    if (state === "running") return t("setup.cache.stateRunning");
    if (state === "stopped") return t("setup.cache.stateStopped");
    if (state === "done") return t("setup.cache.stateDone");
    if (state === "idle") return t("setup.cache.stateIdle");
    return t("setup.cache.stateNone");
}

/** Human-readable diagnostics: the block a bug report can be pasted into. */
export function diagnosticsText({ bundle, project, lastReport, warnings } = {}) {
    const lines = [];
    const pack = bundle?.pack || {};
    const machine = bundle?.machine || {};
    const device = machine.device || {};
    lines.push(`MiniMax H3 Motion Director ${pack.version ?? "?"} (ComfyUI ${pack.comfyui ?? "?"})`);
    lines.push(`Python ${pack.python ?? "?"}; torch ${pack.torch ?? "?"}; CUDA ${pack.cuda ?? "?"}`);
    lines.push(`Platform: ${pack.platform ?? "?"}`);
    lines.push(
        `GPU: ${device.name ?? "?"} | VRAM ${device.total_vram_gb ?? "?"} GB total, `
        + `${device.free_vram_gb ?? "?"} GB free | capability ${device.capability ?? "?"}`,
    );
    lines.push(`Profile: ${machine.tier_label ?? machine.tier ?? "?"}${machine.downgraded ? " (downgraded: GPU busy)" : ""}`);
    if (machine.downgrade_reason) lines.push(`  ${machine.downgrade_reason}`);
    const backends = machine.backends || {};
    lines.push("Backends:");
    for (const name of ["sdpa", "sage", "comfy_kitchen", "xformers", "flash_attn", "triton"]) {
        const probe = backends[name];
        if (!probe) continue;
        const state = probe.available ? "ok" : "UNAVAILABLE";
        const detail = probe.detail || probe.error || "";
        lines.push(`  ${name}: ${state}${probe.version ? ` ${probe.version}` : ""}${detail ? ` - ${detail}` : ""}`);
    }
    for (const warning of warnings || []) {
        lines.push(`Warning: ${warning.message}${warning.error ? ` (${warning.error})` : ""}`);
    }
    const cache = bundle?.cache || {};
    lines.push(`Cache: ${cache.total_gb ?? 0} GB total; disk free ${cache.disk?.free_gb ?? "?"} GB`);
    for (const kind of cache.kinds || []) {
        lines.push(`  ${kind.id}: ${formatBytes(kind.bytes)} in ${kind.nodes} node(s) - ${kind.path}`);
    }
    for (const run of bundle?.runs || []) {
        lines.push(
            `Run[${run.cache}/${run.node}]: ${run.state}, ${run.done}/${run.segment_total} segment(s) done`,
        );
    }
    if (project) {
        lines.push(
            `Project: ${project.taskType ?? "?"} | ${project.width ?? "?"}x${project.height ?? "?"}`
            + ` | ${project.segmentCount ?? "?"} segment(s) | ${project.totalFrames ?? "?"} frames`
            + ` @ ${project.frameRate ?? "?"} fps`,
        );
    }
    if (lastReport) {
        lines.push("", "[Last run report]", String(lastReport).trim());
    }
    return lines.join("\n");
}

export { runStateLabel };
