/**
 * Where "Story to segments" is allowed to work, and where it writes.
 *
 * The story planner turns one brief into one beat per segment and hands them to the
 * normal enhancement path, so it needs one prompt slot per beat. That slot is not the
 * same thing in every mode:
 *
 *   - a **prompt batch** (t2v / i2v / r2v cards) *is* a list of generation segments -
 *     one card, one render - so the story may create the cards it needs. This is the
 *     mode the feature was written for and the one it was unreachable in: the cards
 *     live in a panel with no enhancer entry point of its own.
 *   - **fl2v** (Long-form) stores prompts on shots, which are flattened into segments
 *     and need their own first/last images. Beats are written to the shots that exist;
 *     nothing is invented, because a shot without images cannot render.
 *   - a **video / replace** timeline is laid out by hand - its segments address frames
 *     of a source video - so inventing one would be worse than refusing. An *empty*
 *     timeline is the exception: there is nothing there to re-time.
 *   - **mixed** has its own native editor and is out of scope until it asks.
 *
 * Kept as a pure module so the rules can be tested without a DOM, and so the timeline
 * and the enhancer panel cannot disagree about them.
 */

/** Modes where the story may grow the timeline to as many segments as it needs. */
export const STORY_GROW_MODES = new Set(["prompt_batch"]);

/** Modes where growth is allowed only while the timeline is still empty. */
export const STORY_EMPTY_GROW_MODES = new Set(["video", "gen_blank", "gen_image"]);

/** Modes whose prompts live somewhere other than `timeline.segments[i].prompt`. */
export const STORY_SHOT_MODES = new Set(["fl2v"]);

/**
 * Where a beat for segment `index` has to be written in this mode.
 *
 * `null` means "this mode does not take story beats" - the caller keeps its own
 * writer (the panel's `setPromptTextForBlock`), which is what a hand-laid timeline
 * wants anyway.
 */
export function storyTargetKind(mode) {
    if (STORY_SHOT_MODES.has(mode)) return "shots";
    if (mode === "mixed") return null;
    return "segments";
}

/** May the story create the segments it needs, or only fill the ones that exist? */
export function storyMayGrow(mode, existingCount) {
    const existing = Math.max(0, Number(existingCount) || 0);
    if (STORY_GROW_MODES.has(mode)) return true;
    return existing === 0 && STORY_EMPTY_GROW_MODES.has(mode);
}

/** The duration a created segment gets when the plan did not carry one. */
export function storySegmentSeconds(seconds, fallback = 7) {
    const value = Number(seconds);
    if (Number.isFinite(value) && value > 0) return value;
    const fallbackValue = Number(fallback);
    return Number.isFinite(fallbackValue) && fallbackValue > 0 ? fallbackValue : 7;
}
