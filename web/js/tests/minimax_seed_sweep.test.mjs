// Multi-seed sweep: which seeds a sweep actually renders.
//
// The failure modes that matter are boring ones: a duplicated take wastes GPU time,
// `base + i` seeds produce correlated takes that defeat the sweep, and a typo in a
// seed list must be reported rather than silently ignored.

import assert from "node:assert/strict";
import {
    SEED_SPACE,
    SWEEP_MAX_TAKES,
    expandSeedSweep,
    formatTakeLabel,
    isSweepActive,
    parseSeedList,
} from "../minimax_seed_sweep.mjs";

// ---------------------------------------------------------------------------
// parseSeedList
// ---------------------------------------------------------------------------

assert.deepEqual(parseSeedList("1, 2, 3").seeds, [1, 2, 3]);
assert.deepEqual(parseSeedList("10 20\n30").seeds, [10, 20, 30]);
assert.deepEqual(parseSeedList("1;2;3").seeds, [1, 2, 3]);
assert.deepEqual(parseSeedList("").seeds, []);
assert.deepEqual(parseSeedList(null).seeds, []);
assert.deepEqual(parseSeedList("0").seeds, [0], "seed 0 is valid");

// Junk must be surfaced, not dropped silently.
const junk = parseSeedList("1, abc, 2, -5, 1.5, 3");
assert.deepEqual(junk.seeds, [1, 2, 3]);
assert.deepEqual(junk.invalid, ["abc", "-5", "1.5"]);

// "12abc" must not silently become 12.
assert.deepEqual(parseSeedList("12abc").invalid, ["12abc"]);
assert.deepEqual(parseSeedList("12abc").seeds, []);

// Out of the 32-bit space is invalid rather than wrapped.
assert.deepEqual(parseSeedList(String(SEED_SPACE)).invalid, [String(SEED_SPACE)]);

// ---------------------------------------------------------------------------
// List mode
// ---------------------------------------------------------------------------

const listed = expandSeedSweep({ seeds: [7, 8, 9] });
assert.deepEqual(listed.seeds, [7, 8, 9]);
assert.equal(listed.mode, "list");
assert.equal(listed.error, "");

// Order is preserved - the user asked for these in this order.
assert.deepEqual(expandSeedSweep({ seeds: [9, 7, 8] }).seeds, [9, 7, 8]);

// Duplicates are dropped and reported.
const dupes = expandSeedSweep({ seeds: [5, 5, 6, 5] });
assert.deepEqual(dupes.seeds, [5, 6]);
assert.deepEqual(dupes.dropped, [5, 5]);

// A list wins over a count.
assert.deepEqual(expandSeedSweep({ seeds: [1, 2], count: 9 }).seeds, [1, 2]);
assert.equal(expandSeedSweep({ seeds: [1, 2], count: 9 }).mode, "list");

// An explicit list outranks the current seed.
assert.deepEqual(expandSeedSweep({ seeds: [42], baseSeed: 999 }).seeds, [42]);

// Invalid entries only: no seeds, and a reason.
const allBad = expandSeedSweep({ seeds: [-1, 1.5, NaN] });
assert.deepEqual(allBad.seeds, []);
assert.ok(allBad.error.length > 0);

// ---------------------------------------------------------------------------
// Count mode
// ---------------------------------------------------------------------------

const three = expandSeedSweep({ count: 3, baseSeed: 12345 });
assert.equal(three.mode, "count");
assert.equal(three.seeds.length, 3);
assert.equal(three.error, "");
assert.equal(new Set(three.seeds).size, 3, "takes must be distinct");
for (const seed of three.seeds) {
    assert.ok(Number.isInteger(seed) && seed >= 0 && seed < SEED_SPACE, `seed out of range: ${seed}`);
}

// Deterministic: the same request reproduces the same takes.
assert.deepEqual(expandSeedSweep({ count: 3, baseSeed: 12345 }).seeds, three.seeds);
// A different base gives different takes.
assert.notDeepEqual(expandSeedSweep({ count: 3, baseSeed: 54321 }).seeds, three.seeds);

// The whole point: take seeds must not be an arithmetic progression, or the takes
// come out visibly correlated and the sweep is wasted.
const swept = expandSeedSweep({ count: 6, baseSeed: 0 }).seeds;
const deltas = swept.slice(1).map((seed, index) => seed - swept[index]);
assert.ok(new Set(deltas).size > 1, `derived seeds look arithmetic: ${swept}`);
assert.notDeepEqual(swept, swept.map((_seed, index) => index), "must not be 0..n-1");
assert.notDeepEqual(swept, swept.map((_seed, index) => 1000 + index));

// Defaults and bounds.
assert.equal(expandSeedSweep({}).seeds.length, 1, "no count means one take");
assert.equal(expandSeedSweep({ count: 1 }).seeds.length, 1);
assert.equal(expandSeedSweep({ count: SWEEP_MAX_TAKES }).seeds.length, SWEEP_MAX_TAKES);

for (const bad of [0, -1, SWEEP_MAX_TAKES + 1, 999]) {
    const result = expandSeedSweep({ count: bad });
    assert.deepEqual(result.seeds, [], `count ${bad} should be refused`);
    assert.ok(result.error.length > 0);
}
assert.ok(expandSeedSweep({ count: 2.5 }).error.length > 0, "fractional take counts are refused");

// An unusable base seed falls back to 0 rather than producing NaN.
const fromGarbage = expandSeedSweep({ count: 2, baseSeed: "nonsense" });
assert.equal(fromGarbage.seeds.length, 2);
assert.ok(fromGarbage.seeds.every((seed) => Number.isInteger(seed)));

// An injected RNG is honoured, and still deduped.
const injected = expandSeedSweep({ count: 4, random: (index) => [11, 11, 12, 13][index] });
assert.equal(injected.seeds.length, 4);
assert.equal(injected.seeds[0], 11);
assert.equal(injected.seeds[2], 12);
assert.equal(injected.seeds[3], 13);
assert.deepEqual(injected.dropped, [11], "the replaced seed is reported");
assert.equal(new Set(injected.seeds).size, 4, "injected collisions still dedupe");
assert.ok(
    Number.isInteger(injected.seeds[1]) && injected.seeds[1] !== 11,
    "the colliding take is nudged to a distinct seed",
);

// ---------------------------------------------------------------------------
// Labels
// ---------------------------------------------------------------------------

assert.equal(formatTakeLabel(0, 3, 1234), "Take 1/3 · seed 1234");
assert.equal(formatTakeLabel(2, 3, 0), "Take 3/3 · seed 0");
assert.equal(formatTakeLabel(0, 1, 5), "Take 1/1 · seed 5");
assert.ok(formatTakeLabel(9, 10, 7).startsWith("Take 10/10"));

// A sweep is opt-in: one take is a normal run, not a sweep.
assert.equal(isSweepActive(1), false);
assert.equal(isSweepActive(0), false);
assert.equal(isSweepActive(undefined), false);
assert.equal(isSweepActive("2"), true);
assert.equal(isSweepActive(2), true);
assert.equal(isSweepActive(3), true);

console.log("minimax_seed_sweep.test.mjs OK");
