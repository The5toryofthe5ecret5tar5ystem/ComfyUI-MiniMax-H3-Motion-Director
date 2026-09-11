// Portions derived from ComfyUI_MiniMaxH3_Director
// Copyright AIMixer and contributors
// Originally licensed under Apache License 2.0
// Modified for MiniMax H3 Motion Director, 2026-09-10
// This derivative project is distributed under GPL-3.0.
// See NOTICE and LICENSES/Apache-2.0-AIMixer.txt.

/**
 * Multi-seed sweep: working out which seeds a sweep run should use.
 *
 * "Give me three takes of this segment" is a manual loop today - change the seed,
 * re-run, compare by eye. A sweep queues the same project N times with N different
 * seeds so the takes land as separate runs you can compare afterwards.
 *
 * Pure and DOM-free so it is unit tested; the editor only supplies the current seed
 * and queues the results.
 *
 * Two decisions worth stating:
 *
 * - Derived seeds are *hashed*, not `base + i`. Consecutive seeds can produce
 *   visibly correlated takes on some samplers, which defeats the point of a sweep.
 * - Seeds stay inside 32 bits. They are valid ComfyUI INT values, they are exact in
 *   JavaScript, and nothing has to reason about float precision near 2^53.
 */

export const SWEEP_MIN_TAKES = 1;
export const SWEEP_MAX_TAKES = 12;

/** Seed space. 32-bit keeps every derived seed an exact JS integer. */
export const SEED_SPACE = 0x100000000;

/**
 * splitmix32-style finalizer.
 *
 * The avalanche is the point: it turns a base seed into well-separated take seeds
 * instead of a near-arithmetic progression.
 */
function mixSeed(value) {
    let x = Number(value) >>> 0;
    x = (x + 0x9e3779b9) >>> 0;
    x = Math.imul(x ^ (x >>> 16), 0x21f0aaad) >>> 0;
    x = Math.imul(x ^ (x >>> 15), 0x735a2d97) >>> 0;
    x = (x ^ (x >>> 15)) >>> 0;
    return x >>> 0;
}

function isSeed(value) {
    return Number.isInteger(value) && value >= 0 && value < SEED_SPACE;
}

/**
 * Parse a user-entered seed list: "1, 2, 3", "10 20", newline separated, anything.
 * Returns the valid seeds plus the tokens that could not be used, so the UI can say
 * why nothing happened instead of silently dropping input.
 */
export function parseSeedList(text) {
    const seeds = [];
    const invalid = [];
    for (const token of String(text ?? "").split(/[\s,;]+/)) {
        const trimmed = token.trim();
        if (!trimmed) continue;
        // Number() rather than parseInt: "12abc" must be invalid, not 12.
        const value = Number(trimmed);
        if (Number.isInteger(value) && value >= 0 && value < SEED_SPACE) {
            seeds.push(value);
        } else {
            invalid.push(trimmed);
        }
    }
    return { seeds, invalid };
}

/**
 * Expand a sweep request into the exact ordered seed list to render.
 *
 * @param {object} args
 * @param {number} [args.count] how many takes (count mode)
 * @param {number[]} [args.seeds] explicit seeds (list mode); wins over `count`
 * @param {number} [args.baseSeed] current seed, used to derive count-mode seeds
 * @param {(n:number)=>number[]} [args.random] injectable RNG for count mode
 * @returns {{seeds:number[], mode:string, dropped:number[], error:string}}
 */
export function expandSeedSweep({ count, seeds, baseSeed = 0, random = null } = {}) {
    // Supplying a list at all means list mode. Falling through to derived seeds when
    // the list was merely *invalid* would render a seed the user never asked for.
    const providedList = Array.isArray(seeds);
    const explicit = providedList
        ? seeds.filter((value) => isSeed(Number(value))).map(Number)
        : [];

    // List mode: use exactly what was asked for, in order, minus duplicates.
    if (providedList) {
        const unique = [];
        const dropped = [];
        for (const seed of explicit) {
            if (unique.includes(seed)) dropped.push(seed);
            else unique.push(seed);
        }
        const capped = unique.slice(0, SWEEP_MAX_TAKES);
        for (const seed of unique.slice(SWEEP_MAX_TAKES)) dropped.push(seed);
        return {
            seeds: capped,
            mode: "list",
            dropped,
            error: capped.length < SWEEP_MIN_TAKES
                ? "A sweep needs at least one valid seed."
                : "",
        };
    }

    const requested = Number(count);
    if (count !== undefined && count !== null && count !== "" && !Number.isInteger(requested)) {
        return { seeds: [], mode: "count", dropped: [], error: "Take count must be a whole number." };
    }
    const takes = Number.isInteger(requested) ? requested : SWEEP_MIN_TAKES;
    if (takes < SWEEP_MIN_TAKES) {
        return { seeds: [], mode: "count", dropped: [], error: "A sweep needs at least one take." };
    }
    if (takes > SWEEP_MAX_TAKES) {
        return {
            seeds: [],
            mode: "count",
            dropped: [],
            error: `A sweep is limited to ${SWEEP_MAX_TAKES} takes.`,
        };
    }

    const base = isSeed(Number(baseSeed)) ? Number(baseSeed) : 0;
    const seedsOut = [];
    const dropped = [];
    for (let index = 0; index < takes; index += 1) {
        const original = typeof random === "function"
            ? (Number(random(index)) >>> 0)
            // Fold the index through the mixer so take seeds are unrelated to each other.
            : mixSeed((base + Math.imul(index, 0x9e3779b9)) >>> 0);

        let candidate = original;
        if (seedsOut.includes(candidate)) {
            // A duplicate take would be silently wasted GPU time, so nudge
            // deterministically rather than giving up. Collisions here are
            // astronomically unlikely; this is a correctness net, not a hot path.
            let resolved = null;
            for (let nudge = 1; nudge <= 64; nudge += 1) {
                const next = mixSeed((original + Math.imul(nudge, 0x85ebca6b)) >>> 0);
                if (!seedsOut.includes(next)) {
                    resolved = next;
                    break;
                }
            }
            if (resolved === null) {
                return { seeds: seedsOut, mode: "count", dropped, error: "Could not derive distinct seeds." };
            }
            dropped.push(original);
            candidate = resolved;
        }
        seedsOut.push(candidate);
    }

    return { seeds: seedsOut, mode: "count", dropped, error: "" };
}

/** "Take 2/3 · seed 1234567" for run labels and reports. */
export function formatTakeLabel(index, total, seed) {
    const position = Number(index) + 1;
    const count = Number(total) || 0;
    const value = isSeed(Number(seed)) ? Number(seed) : 0;
    return `Take ${position}/${count} · seed ${value}`;
}

/** Whether a take count means "sweep" rather than "a normal single run". */
export function isSweepActive(takes) {
    const value = Number(takes);
    return Number.isInteger(value) && value > SWEEP_MIN_TAKES;
}
