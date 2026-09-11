// MiniMax H3 Motion Director — named preset HTTP client.

import { api } from "../../scripts/api.js";

const BASE = "/minimax/motion-director/presets";

async function responseError(resp) {
    try {
        const data = await resp.json();
        return data?.error || data?.message || `HTTP ${resp.status}`;
    } catch {
        try { return (await resp.text()) || `HTTP ${resp.status}`; }
        catch { return `HTTP ${resp.status}`; }
    }
}

async function checked(resp) {
    if (!resp.ok) throw new Error(await responseError(resp));
    return resp.json();
}

export function presetsApiUrl(path = "") {
    const url = `${BASE}${path}`;
    if (typeof api.apiURL === "function") return api.apiURL(url);
    return url;
}

function jsonInit(method, body) {
    return {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body ?? {}),
    };
}

/** Metadata only - payloads are fetched per preset. */
export async function listDirectorPresets() {
    const data = await checked(await api.fetchApi(presetsApiUrl()));
    return Array.isArray(data?.presets) ? data.presets : [];
}

export async function getDirectorPreset(presetId) {
    const data = await checked(await api.fetchApi(presetsApiUrl(`/${encodeURIComponent(presetId)}`)));
    return data?.preset || null;
}

export async function createDirectorPreset({ name, description = "", payload = {} }) {
    const data = await checked(await api.fetchApi(presetsApiUrl(), jsonInit("POST", { name, description, payload })));
    return data?.preset || null;
}

export async function updateDirectorPreset(presetId, patch) {
    const data = await checked(
        await api.fetchApi(presetsApiUrl(`/${encodeURIComponent(presetId)}`), jsonInit("PATCH", patch)),
    );
    return data?.preset || null;
}

export async function deleteDirectorPreset(presetId) {
    return checked(await api.fetchApi(presetsApiUrl(`/${encodeURIComponent(presetId)}`), { method: "DELETE" }));
}
