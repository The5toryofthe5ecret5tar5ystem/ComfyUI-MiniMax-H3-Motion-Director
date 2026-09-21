// MiniMax H3 Motion Director — anchor ladder HTTP client (P2 anchor strip).
//
// Mirrors the house style of minimax_director_presets_api.mjs: every call goes
// through checked()/responseError() so the strip can show one readable message
// instead of an "HTTP 500" toast.

import { api } from "../../scripts/api.js";

const BASE = "/minimax/motion-director/anchors";

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

export function anchorsApiUrl(path = "") {
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

/** Anchors currently on disk for this node (thumbnails, status, seeds). */
export async function listAnchors(nodeId) {
    const data = await checked(
        await api.fetchApi(anchorsApiUrl(`?node_id=${encodeURIComponent(nodeId ?? "")}`)),
    );
    return {
        items: Array.isArray(data?.items) ? data.items : [],
        counts: data?.counts || { items: 0, boundaries: 0, approved: 0, rejected: 0 },
        available: Boolean(data?.available),
        root: data?.root || "",
    };
}

/** approve | reject | pending | delete | clear | approve_all | prune */
export async function anchorAction(nodeId, action, index = null) {
    const body = { node_id: nodeId, action };
    if (index !== null && index !== undefined) body.index = index;
    const data = await checked(await api.fetchApi(anchorsApiUrl("/action"), jsonInit("POST", body)));
    return {
        items: Array.isArray(data?.items) ? data.items : [],
        counts: data?.counts || { items: 0, boundaries: 0, approved: 0, rejected: 0 },
        available: Boolean(data?.available),
        removed: Number(data?.removed || 0),
        sidecarsWritten: Number(data?.sidecarsWritten || 0),
    };
}

/** Preflight numbers for the current timeline (pass cost, missing boundaries). */
export async function planAnchors(nodeId, { timelineData, width, height, refLongEdge = 768, contextFrames = 22 } = {}) {
    return checked(
        await api.fetchApi(
            anchorsApiUrl("/plan"),
            jsonInit("POST", {
                node_id: nodeId,
                timeline_data: timelineData,
                width: Math.max(0, Math.round(Number(width) || 0)),
                height: Math.max(0, Math.round(Number(height) || 0)),
                ref_long_edge: Math.max(64, Math.round(Number(refLongEdge) || 768)),
                context_frames: Math.max(0, Math.round(Number(contextFrames) || 22)),
            }),
        ),
    );
}

/** Thumbnail URL for an item returned by listAnchors (already cache-busted). */
export function anchorThumbUrl(item) {
    const raw = String(item?.url || "");
    if (!raw) return "";
    if (typeof api.apiURL === "function") return api.apiURL(raw);
    return raw;
}

/**
 * A new anchor seed that never repeats the previous one.
 *
 * Seeds are authored client-side (the boundary owns its seed in the timeline),
 * so the strip only needs a fresh, stable-looking integer - not a distribution.
 */
export function nextAnchorSeed(previous, { min = 1000, max = 99999999 } = {}) {
    const span = Math.max(1, max - min);
    let candidate = min + Math.floor(Math.random() * span);
    if (Number.isFinite(Number(previous)) && Math.trunc(Number(previous)) === candidate) {
        candidate = min + ((candidate - min + 1) % span);
    }
    return candidate;
}
