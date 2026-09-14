/**
 * Pure helpers for Director preview-clip playback.
 *
 * The Results page plays one all-intra H.264 clip per segment, streamed from
 * ComfyUI's /view route, and the Multi Segment tab plays a playlist of them back
 * to back. The UI still presents a single global frame index - the same
 * timeline shape the legacy base64 frame array produced - so these helpers map
 * between that global index and (clip, offset within clip).
 *
 * Kept free of DOM and ComfyUI imports so the index arithmetic is unit testable;
 * it is the part of clip playback most likely to drift by one frame.
 */

/**
 * Describe a single result's preview clip.
 *
 * @param {object|null|undefined} item  a result payload from the Director
 * @param {(route: string) => string} resolveUrl  /view route resolver
 * @returns {{url: string, frames: number, fps: number}|null}
 *   null when the result has no usable clip and the caller should fall back to
 *   the legacy frame array.
 */
export function clipDescriptor(item, resolveUrl = (route) => route) {
    if (!item?.preview_url) return null;

    const frames = Number(item.preview_frame_count || 0);
    if (!(frames > 0)) return null;

    return {
        url: resolveUrl(item.preview_url),
        frames,
        fps: Number(item.fps || 24) || 24,
    };
}

/**
 * The ordered clip list for a result.
 *
 * A result either carries an explicit `clipPlaylist` (Multi Segment) or is a
 * single result with its own clip. Anything else yields an empty list.
 */
export function clipPlaylistOf(result, resolveUrl = (route) => route) {
    if (Array.isArray(result?.clipPlaylist) && result.clipPlaylist.length) {
        return result.clipPlaylist;
    }

    const clip = clipDescriptor(result, resolveUrl);
    return clip ? [clip] : [];
}

/** Total frame count across the playlist. */
export function totalClipFrames(playlist) {
    return (playlist || []).reduce(
        (sum, entry) => sum + Math.max(0, Number(entry?.frames) || 0),
        0,
    );
}

/**
 * Global frame index of the first frame in the clip at `position`.
 * Out-of-range positions clamp to the start or the end of the timeline.
 */
export function clipStartIndex(playlist, position) {
    const list = playlist || [];
    if (!list.length) return 0;

    const bounded = Math.max(0, Math.min(list.length - 1, Math.floor(Number(position) || 0)));

    let start = 0;
    for (let i = 0; i < bounded; i += 1) {
        start += Math.max(0, Number(list[i]?.frames) || 0);
    }
    return start;
}

/**
 * Map a global frame index onto the clip that holds it.
 *
 * @returns {{position: number, offset: number}}
 *   `position` is -1 for an empty playlist. `offset` is the frame within that
 *   clip, and an index past the end of the timeline clamps to the final frame so
 *   a seek can never land outside the media.
 */
export function clipPositionFor(playlist, index) {
    const list = playlist || [];
    if (!list.length) return { position: -1, offset: 0 };

    let remaining = Math.max(0, Math.floor(Number(index) || 0));

    for (let position = 0; position < list.length; position += 1) {
        const count = Math.max(0, Number(list[position]?.frames) || 0);

        // Skip unplayable entries rather than letting a zero-frame clip claim a
        // timeline slot it has no frames for.
        if (count <= 0) continue;

        if (remaining < count) {
            return { position, offset: remaining };
        }

        remaining -= count;
    }

    const last = list.length - 1;
    return {
        position: last,
        offset: Math.max(0, (Number(list[last]?.frames) || 1) - 1),
    };
}
