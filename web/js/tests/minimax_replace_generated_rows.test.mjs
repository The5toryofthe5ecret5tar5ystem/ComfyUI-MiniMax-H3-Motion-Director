import assert from "node:assert/strict";

import {
    coverageFrames,
    generatedFrames,
    reinsertGeneratedRows,
    splitReplaceRows,
} from "../minimax_replace_layout_core.mjs";

// A replace job's rows are either masked windows over the source video or
// generated rows that render from their own prompt and references. Every count
// in the panel has to know the difference:
//
//   - "how many windows" and "how much of the source is covered" are questions
//     about the windows alone, and answered over the whole list they over-report
//     by exactly the generated rows, and
//   - the long-form re-cut rebuilds the window list from the layout, so a
//     generated row - which cannot be derived from the layout - used to be
//     deleted along with its prompt.

const window_ = (start, length = 240) => ({
    id: `w${start}`,
    start,
    length,
    frameCount: length,
    replace: { enabled: true },
});

const generated = (start, length = 243) => ({
    id: `g${start}`,
    kind: "generate",
    start,
    length,
    frameCount: length,
    replace: { enabled: false },
});

// --------------------------------------------------------------------------
// splitting
// --------------------------------------------------------------------------

{
    const rows = [window_(0), generated(240), window_(240)];
    const { windows, generated: gen } = splitReplaceRows(rows);
    assert.equal(windows.length, 2);
    assert.equal(gen.length, 1);
    assert.equal(gen[0].id, "g240");
}

// Unknown rows are windows, and junk is ignored rather than crashing a render.
{
    const { windows, generated: gen } = splitReplaceRows([
        window_(0),
        { kind: "banana", start: 240, length: 240 },
        null,
        "nope",
        undefined,
    ]);
    assert.equal(windows.length, 2);
    assert.equal(gen.length, 0);
    assert.equal(splitReplaceRows(null).windows.length, 0);
}

// --------------------------------------------------------------------------
// coverage is about the footage, not the output
// --------------------------------------------------------------------------

{
    const rows = [window_(0, 240), window_(240, 240), generated(480, 243)];
    // Windows cover 480 of 480 frames - the generated row does not cover the
    // source, it is added to the output, so it must not push this past 100%.
    assert.equal(coverageFrames(rows, 480), 480);
    assert.equal(coverageFrames(rows, 1137), 480);
}

// The historic clamp: a window may not claim frames past the end of the clip.
{
    const rows = [window_(0, 240), window_(240, 240)];
    assert.equal(coverageFrames(rows, 300), 300);
}

// A generated row past the end of the footage still counts its own frames.
{
    const rows = [window_(0, 240), generated(1137, 243)];
    assert.equal(coverageFrames(rows, 1137), 240);
    assert.equal(generatedFrames(rows), 243);
    assert.equal(generatedFrames([window_(0), window_(240)]), 0);
}

// --------------------------------------------------------------------------
// the long-form re-cut keeps generated rows where they were
// --------------------------------------------------------------------------

{
    const previous = [window_(0), generated(240), window_(240)];
    const newWindows = [window_(0, 175), window_(175, 175), window_(350, 175)];
    const rows = reinsertGeneratedRows(newWindows, previous);

    assert.equal(rows.length, 4);
    // It sat between the first and second window, and it still does.
    assert.equal(rows[0].id, "w0");
    assert.equal(rows[1].id, "g240");
    assert.equal(rows[2].id, "w175");
}

// Several generated rows in a row keep their order, and one that sat after the
// last window (the extension case) stays at the end.
{
    const previous = [window_(0), window_(240), generated(480, 243), generated(480, 243)];
    const rows = reinsertGeneratedRows([window_(0, 175), window_(175, 175)], previous);

    assert.deepEqual(rows.map((r) => r.id), ["w0", "w175", "g480", "g480"]);
}

// A shorter cut cannot host every position: the extra rows land at the end
// instead of being dropped.
{
    const previous = [window_(0), generated(240), window_(240), generated(480)];
    const rows = reinsertGeneratedRows([window_(0, 175)], previous);

    assert.equal(rows.length, 3);
    assert.equal(rows[0].id, "w0");
    assert.equal(rows.filter((r) => r.id.startsWith("g")).length, 2);
}

// A generated row first in the list stays first.
{
    const previous = [generated(0), window_(0)];
    const rows = reinsertGeneratedRows([window_(0, 175), window_(175, 175)], previous);
    assert.equal(rows[0].id, "g0");
}

// No generated rows means the layout is returned exactly as built - the
// behaviour every existing project has.
{
    const previous = [window_(0), window_(240)];
    const newWindows = [window_(0, 175)];
    const rows = reinsertGeneratedRows(newWindows, previous);
    assert.equal(rows.length, 1);
    assert.equal(rows[0], newWindows[0]);
    assert.equal(reinsertGeneratedRows(null, previous).length, 0);
}

console.log("minimax_replace_generated_rows: OK");
