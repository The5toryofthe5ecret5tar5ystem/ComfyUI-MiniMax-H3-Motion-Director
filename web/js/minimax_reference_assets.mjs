/** Stable R2V asset identity and per-segment official tag compilation. */

export const SEMANTIC_REFERENCE_RE = /\{\{mmx-ref:(picture|video|audio):([A-Za-z0-9_.:-]+)\}\}/gi;

function defaultIdFactory(kind = "asset") {
    if (globalThis.crypto?.randomUUID) return `${kind}-${globalThis.crypto.randomUUID()}`;
    return `${kind}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function semanticReferenceToken(kind, assetId) {
    const normalized = String(kind || "").trim().toLowerCase();
    const identity = String(assetId || "").trim();
    if (!["picture", "video", "audio"].includes(normalized)) {
        throw new Error("Reference kind must be picture, video, or audio");
    }
    if (!identity || !/^[A-Za-z0-9_.:-]+$/.test(identity)) {
        throw new Error("Reference asset ID is empty or unsafe");
    }
    return `{{mmx-ref:${normalized}:${identity}}}`;
}

function referenceKindField(kind) {
    if (kind === "video") return "refVideos";
    if (kind === "audio") return "refAudios";
    return "refs";
}

function referenceHash(input) {
    let h1 = 0x811c9dc5;
    let h2 = 5381;
    const str = String(input || "");
    for (let i = 0; i < str.length; i += 1) {
        const code = str.charCodeAt(i);
        h1 ^= code;
        h1 = Math.imul(h1, 0x01000193) >>> 0;
        h2 = (Math.imul(h2, 33) + code) >>> 0;
    }
    return h1.toString(16).padStart(8, "0") + h2.toString(16).padStart(8, "0");
}

/** Deterministic asset id derived from the uploaded file, so removing and
 * re-adding the same file keeps its prompt mentions bound. Empty when no
 * usable file identity is available (callers fall back to a generated id). */
export function fileStableReferenceAssetId(kind, fileRef) {
    const raw = String(fileRef && typeof fileRef === "object"
        ? (fileRef.imageFile || fileRef.fileName || fileRef.videoFile
            || fileRef.audioFile || "")
        : String(fileRef || "")).trim();
    const normalized = raw.replace(/\\/g, "/");
    if (!normalized) return "";
    return `f-${referenceHash(`${kind}:${normalized}`)}`;
}

/** Every asset id of a kind currently assigned anywhere in the timeline. */
export function timelineKnownAssetIds(timeline, kind) {
    const field = referenceKindField(kind);
    const ids = new Set();
    const scan = (block) => {
        for (const item of (block?.[field]) || []) {
            if (item?.assetId) ids.add(String(item.assetId));
        }
    };
    scan(timeline?.global);
    scan(timeline?.r2vCommon);
    for (const segment of (timeline?.segments) || []) scan(segment);
    return ids;
}

/** {{mmx-ref:<kind>:<id>}} ids present in a prompt whose asset is not in
 * knownIds, in document order. These are the mentions left dangling when a
 * reference was removed. */
export function danglingReferenceTokenIds(promptText, kind, knownIds) {
    const used = knownIds instanceof Set
        ? knownIds
        : new Set((knownIds || []).map(String));
    const re = new RegExp(
        `\\{\\{mmx-ref:${kind}:([A-Za-z0-9_.:-]+)\\}\\}`,
        "gi",
    );
    const out = [];
    const text = String(promptText || "");
    let match;
    while ((match = re.exec(text))) {
        const id = match[1];
        if (!used.has(id) && !out.includes(id)) out.push(id);
    }
    return out;
}

/** Choose the asset id to use when a reference is (re-)added from a file.
 *
 * 1. If one of `referencingPrompts` still mentions a removed asset of this
 *    kind (a dangling "missing asset" chip), reuse that id so the existing
 *    prompt mention reconnects to the re-added reference.
 * 2. Otherwise derive a stable id from the uploaded file so removing and
 *    re-adding the same file keeps mentions bound.
 * 3. Otherwise return "" so the schema assigns a fresh id.
 */
export function resolveReferenceAssetId(timeline, kind, referencingPrompts, fileRef) {
    const knownIds = timelineKnownAssetIds(timeline, kind);
    for (const promptText of referencingPrompts || []) {
        const dangling = danglingReferenceTokenIds(promptText, kind, knownIds);
        if (dangling.length) return dangling[0];
    }
    return fileStableReferenceAssetId(kind, fileRef);
}

function arraysFor(container) {
    if (!container || typeof container !== "object") return [];
    container.refs = Array.isArray(container.refs) ? container.refs : [];
    container.refVideos = Array.isArray(container.refVideos)
        ? container.refVideos : (Array.isArray(container.ref_videos) ? container.ref_videos : []);
    container.refAudios = Array.isArray(container.refAudios)
        ? container.refAudios : (Array.isArray(container.ref_audios) ? container.ref_audios : []);
    return [
        ["picture", container.refs],
        ["video", container.refVideos],
        ["audio", container.refAudios],
    ];
}

function hasMedia(kind, item) {
    if (!item) return false;
    if (kind === "picture") return !!(item.imageFile || item.imageB64);
    if (kind === "video") return !!(
        item.videoFile || item.fileName || item.previewImageFile || item.previewImageUrl || item.linked
    );
    return !!(item.audioFile || item.fileName);
}

export function replaceReferenceAssetAtSlot(container, field, slot, nextItem) {
    if (!container || !["refs", "refVideos", "refAudios"].includes(field)) return null;
    const items = Array.isArray(container[field]) ? container[field] : [];
    const current = items.find((item) => Number(item.index ?? item.slot) === Number(slot));
    const replacement = {
        ...nextItem,
        index: Number(slot),
        assetId: current?.assetId || current?.asset_id || nextItem?.assetId || nextItem?.asset_id || "",
    };
    container[field] = items.filter((item) => Number(item.index ?? item.slot) !== Number(slot));
    container[field].push(replacement);
    return replacement;
}

export function moveReferenceAssetSlot(container, field, fromSlot, toSlot) {
    if (!container || !["refs", "refVideos", "refAudios"].includes(field)) return false;
    const items = Array.isArray(container[field]) ? container[field] : [];
    const from = items.find((item) => Number(item.index ?? item.slot) === Number(fromSlot));
    if (!from || Number(fromSlot) === Number(toSlot)) return false;
    const to = items.find((item) => Number(item.index ?? item.slot) === Number(toSlot));
    container[field] = items.filter((item) => {
        const index = Number(item.index ?? item.slot);
        return index !== Number(fromSlot) && index !== Number(toSlot);
    });
    container[field].push({ ...from, index: Number(toSlot), slot: undefined });
    if (to) container[field].push({ ...to, index: Number(fromSlot), slot: undefined });
    return true;
}

export function setCommonAssetEnabled(segment, allAssetIds, assetId, enabled) {
    if (!segment) return false;
    const knownIds = [...new Set((allAssetIds || []).map(String))];
    const excluded = new Set(
        segment.useCommonAssets === false
            ? knownIds
            : (segment.excludedCommonAssetIds || []).map(String),
    );
    const identity = String(assetId || "");
    if (!identity) return false;
    if (enabled) excluded.delete(identity);
    else excluded.add(identity);
    segment.useCommonAssets = true;
    segment.excludedCommonAssetIds = [
        ...knownIds.filter((id) => excluded.has(id)),
        ...[...excluded].filter((id) => !knownIds.includes(id)),
    ];
    return true;
}

function ensureIds(container, scope, idFactory, used) {
    for (const [kind, items] of arraysFor(container)) {
        for (const item of items) {
            if (!item || typeof item !== "object") continue;
            let assetId = String(item.assetId || item.asset_id || "").trim();
            if (!assetId || used.has(assetId)) {
                do {
                    assetId = String(idFactory(`${scope}-${kind}`));
                } while (!assetId || used.has(assetId));
            }
            item.assetId = assetId;
            delete item.asset_id;
            used.add(assetId);
        }
    }
}

export function referenceAssetIds(globalBlock) {
    const ids = [];
    for (const [kind, items] of arraysFor(globalBlock)) {
        for (const item of items) {
            if (hasMedia(kind, item) && item.assetId) ids.push(String(item.assetId));
        }
    }
    return ids;
}

function emptyReferenceContainer() {
    return { refs: [], refVideos: [], refAudios: [] };
}

export function ensureR2vReferenceAssetSchema(timeline, idFactory = defaultIdFactory) {
    const data = timeline || {};
    data.global = data.global || {};
    data.segments = Array.isArray(data.segments) ? data.segments : [];
    if ((!data.r2vCommon || typeof data.r2vCommon !== "object")
        && data.r2v_common && typeof data.r2v_common === "object") {
        data.r2vCommon = data.r2v_common;
    }
    delete data.r2v_common;
    if (!data.r2vCommon || typeof data.r2vCommon !== "object") {
        // Legacy R2V used global as Common. Only migrate when old R2V selection
        // fields prove that these assets belonged to the old Common pool.
        const legacyR2v = data.segments.some((segment) => (
            Array.isArray(segment?.commonAssetIds)
            || Array.isArray(segment?.common_asset_ids)
            || segment?.useCommonPrompt != null
            || segment?.use_common_prompt != null
        ));
        if (legacyR2v) {
            data.r2vCommon = {
                refs: data.global.refs || [],
                refVideos: data.global.refVideos || data.global.ref_videos || [],
                refAudios: data.global.refAudios || data.global.ref_audios || [],
            };
            data.global.refs = [];
            data.global.refVideos = [];
            data.global.refAudios = [];
            delete data.global.ref_videos;
            delete data.global.ref_audios;
        } else {
            data.r2vCommon = emptyReferenceContainer();
        }
    }
    const used = new Set();
    ensureIds(data.global, "global", idFactory, used);
    ensureIds(data.r2vCommon, "r2v-common", idFactory, used);
    delete data.global.ref_videos;
    delete data.global.ref_audios;
    delete data.r2vCommon.ref_videos;
    delete data.r2vCommon.ref_audios;
    const allCommon = referenceAssetIds(data.r2vCommon);
    for (let index = 0; index < data.segments.length; index += 1) {
        const segment = data.segments[index] || (data.segments[index] = {});
        ensureIds(segment, `segment-${segment.id || index}`, idFactory, used);
        const storedExclusions = Array.isArray(segment.excludedCommonAssetIds)
            ? segment.excludedCommonAssetIds
            : segment.excluded_common_asset_ids;
        if (!Array.isArray(storedExclusions)) {
            const legacySelection = Array.isArray(segment.commonAssetIds)
                ? segment.commonAssetIds
                : segment.common_asset_ids;
            if (Array.isArray(legacySelection)) {
                const selected = new Set(legacySelection.map(String));
                segment.excludedCommonAssetIds = allCommon.filter((id) => !selected.has(id));
            } else {
                segment.excludedCommonAssetIds = [];
            }
        } else {
            segment.excludedCommonAssetIds = [...new Set(storedExclusions.map(String))];
        }
        const storedUseCommon = segment.useCommonAssets ?? segment.use_common_assets;
        segment.useCommonAssets = storedUseCommon == null ? true : !!storedUseCommon;
        delete segment.commonAssetIds;
        delete segment.common_asset_ids;
        delete segment.excluded_common_asset_ids;
        delete segment.useCommonPrompt;
        delete segment.use_common_prompt;
        delete segment.use_common_assets;
    }
    return data;
}

export function ensureReferenceAssetSchema(timeline, idFactory = defaultIdFactory) {
    const data = timeline || {};
    data.global = data.global || {};
    data.segments = Array.isArray(data.segments) ? data.segments : [];
    const used = new Set();
    ensureIds(data.global, "global", idFactory, used);
    if (data.r2vCommon) ensureIds(data.r2vCommon, "r2v-common", idFactory, used);
    for (let index = 0; index < data.segments.length; index += 1) {
        const segment = data.segments[index] || (data.segments[index] = {});
        ensureIds(segment, `segment-${segment.id || index}`, idFactory, used);
    }
    return data;
}

function assetDescriptor(kind, item, source) {
    const assetId = String(item.assetId || "");
    const path = kind === "picture"
        ? (item.imageFile || "")
        : kind === "video"
            ? (item.videoFile || item.fileName || item.previewImageFile || "")
            : (item.audioFile || item.fileName || "");
    return {
        kind,
        assetId,
        source,
        item,
        label: String(item.name || item.label || path.split(/[\\/]/).pop() || assetId),
        authoringTag: "",
        effectiveTag: "",
        officialTag: "",
        paired: false,
    };
}

function orderedMediaItems(items) {
    return [...(items || [])]
        .map((item, position) => ({ item, position }))
        .sort((left, right) => {
            const leftSlot = Number(left.item?.index ?? left.item?.slot ?? left.position);
            const rightSlot = Number(right.item?.index ?? right.item?.slot ?? right.position);
            return leftSlot - rightSlot || left.position - right.position;
        })
        .map(({ item }) => item);
}

export function allKnownReferenceAssets(globalBlock, segment = null) {
    const out = [];
    for (const [kind, items] of arraysFor(globalBlock)) {
        for (const item of orderedMediaItems(items)) {
            if (hasMedia(kind, item)) out.push(assetDescriptor(kind, item, "common"));
        }
    }
    if (segment) {
        for (const [kind, items] of arraysFor(segment)) {
            for (const item of orderedMediaItems(items)) {
                if (hasMedia(kind, item)) out.push(assetDescriptor(kind, item, "local"));
            }
        }
    }
    return out;
}

function assignReferenceTags(items, kind, field) {
    items.forEach((item, index) => { item[field] = `<${kind} ${index + 1}>`; });
}

function pairedAudioAssets(videos) {
    return videos
        .filter((asset) => !!(asset.item.pairedAudioFile || asset.item.paired_audio_file))
        .map((asset) => ({
            ...asset,
            kind: "audio",
            paired: true,
            label: `${asset.label} soundtrack`,
            authoringTag: "",
            effectiveTag: "",
            officialTag: "",
        }));
}

export function authoringReferenceAssets(commonBlock, segment) {
    const all = [
        ...allKnownReferenceAssets(commonBlock),
        ...allKnownReferenceAssets({}, segment),
    ];
    const pictures = all.filter((asset) => asset.kind === "picture");
    const videos = all.filter((asset) => asset.kind === "video");
    const standaloneAudios = all.filter((asset) => asset.kind === "audio");
    const audios = [...pairedAudioAssets(videos), ...standaloneAudios];
    assignReferenceTags(pictures, "Picture", "authoringTag");
    assignReferenceTags(videos, "Video", "authoringTag");
    assignReferenceTags(audios, "Audio", "authoringTag");
    return [...pictures, ...videos, ...audios];
}

export function effectiveReferenceAssets(globalBlock, segment) {
    const excluded = new Set((segment?.excludedCommonAssetIds || []).map(String));
    const common = segment?.useCommonAssets === false
        ? []
        : allKnownReferenceAssets(globalBlock).filter((x) => !excluded.has(x.assetId));
    const local = allKnownReferenceAssets({}, segment);
    const pictures = [...common, ...local].filter((x) => x.kind === "picture");
    const videos = [...common, ...local].filter((x) => x.kind === "video");
    const standaloneAudios = [...common, ...local].filter((x) => x.kind === "audio");

    assignReferenceTags(pictures, "Picture", "effectiveTag");
    assignReferenceTags(videos, "Video", "effectiveTag");

    const pairedAudios = pairedAudioAssets(videos);
    const audios = [...pairedAudios, ...standaloneAudios];
    assignReferenceTags(audios, "Audio", "effectiveTag");
    for (const asset of [...pictures, ...videos, ...audios]) {
        asset.officialTag = asset.effectiveTag;
    }
    return [...pictures, ...videos, ...audios];
}

export function referenceAssetStates(commonBlock, segment) {
    const authoring = authoringReferenceAssets(commonBlock, segment);
    const effectiveByKey = new Map(
        effectiveReferenceAssets(commonBlock, segment)
            .map((asset) => [`${asset.kind}:${asset.assetId}`, asset]),
    );
    return authoring.map((asset) => {
        const effective = effectiveByKey.get(`${asset.kind}:${asset.assetId}`);
        const effectiveTag = effective?.effectiveTag || "";
        return {
            ...asset,
            effectiveTag,
            officialTag: effectiveTag,
            status: effective ? "active" : "disabled",
        };
    });
}

export function hydrateOfficialReferenceTags(prompt, authoringAssets) {
    let value = String(prompt || "");
    for (const asset of authoringAssets || []) {
        if (!asset?.assetId || !asset?.authoringTag) continue;
        value = value.split(asset.authoringTag)
            .join(semanticReferenceToken(asset.kind, asset.assetId));
    }
    return value;
}

export function compileSemanticPrompt(prompt, effectiveAssets, options = {}) {
    const mapping = new Map(
        (effectiveAssets || [])
            .filter((asset) => asset.status !== "disabled" && (asset.effectiveTag || asset.officialTag))
            .map((asset) => [
                `${asset.kind}:${asset.assetId}`,
                asset.effectiveTag || asset.officialTag,
            ]),
    );
    const known = new Map(
        (options.knownAssets || []).map((asset) => [
            `${asset.kind}:${asset.assetId}`,
            asset,
        ]),
    );
    const segmentLabel = options.segmentLabel || "Segment";
    return String(prompt || "").replace(SEMANTIC_REFERENCE_RE, (_whole, rawKind, assetId) => {
        const kind = String(rawKind).toLowerCase();
        const key = `${kind}:${assetId}`;
        if (mapping.has(key)) return mapping.get(key);
        const asset = known.get(key);
        const pretty = kind[0].toUpperCase() + kind.slice(1);
        if (asset) {
            throw new Error(
                `${segmentLabel} prompt references ${pretty} "${asset.label || assetId}", `
                + "but that asset is disabled for this segment.",
            );
        }
        throw new Error(`${segmentLabel} prompt references unknown ${pretty} asset "${assetId}".`);
    });
}
