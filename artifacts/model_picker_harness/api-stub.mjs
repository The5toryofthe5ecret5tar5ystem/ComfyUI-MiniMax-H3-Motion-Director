// Stub for ComfyUI's frontend `scripts/api.js`, used only by the
// prompt-enhancer model-picker harness in /tmp. The harness assigns
// api.scanPayload / api.downloadStatus before mounting the panel.
export const api = {
    scanPayload: { models: [] },
    downloadStatus: {
        active: false, done: false, fallback: false, model_id: "", label: "", phase: "",
        bytes: 0, expected_bytes: 0, percent: null, rate_bps: 0, eta_seconds: null, error: "",
    },
    // Mirrors GET /enhance_recipes: keys + English labels + summaries.
    recipePayload: {
        recipes: [
            { key: "auto", label: "Auto (from the task)", summary: "Pick by task.", tasks: [], needs_source: false },
            { key: "character_replace", label: "Character replace window (reference images)", summary: "Discard sentence, role lines.", tasks: ["rv2v", "v2v"], needs_source: true },
            { key: "character_replace_refmod", label: "Character replace window (RefMod identity)", summary: "No appearance prose.", tasks: [], needs_source: true },
            { key: "official", label: "Official MiniMax template", summary: "Previous behaviour.", tasks: [], needs_source: false },
        ],
    },
    calls: [],
    async fetchApi(url, options = {}) {
        api.calls.push({ url, options });
        if (url === "/minimax/motion-director/enhance_models") {
            return { ok: true, status: 200, json: async () => api.scanPayload };
        }
        if (url === "/minimax/motion-director/download_status") {
            return { ok: true, status: 200, json: async () => api.downloadStatus };
        }
        if (url === "/minimax/motion-director/enhance_recipes") {
            return { ok: true, status: 200, json: async () => api.recipePayload };
        }
        return { ok: true, status: 200, json: async () => ({}) };
    },
    addEventListener() {},
    removeEventListener() {},
};
