import assert from "node:assert/strict";
import fs from "node:fs";

// The Replace-windows installer drove its own requestAnimationFrame loop at
// display rate for as long as a Director node existed, whether or not anything
// was happening, and never stored the frame handle (so it could not be
// cancelled).  These assertions pin the fix: an idle node slow-polls instead,
// the handle is real, and hovering restores full rate immediately.
//
// Source-level because the loop is inline in a 15k-line file and only runs
// against a live LiteGraph canvas.

const src = fs.readFileSync(new URL("../minimax_timeline.js", import.meta.url), "utf8");

/**
 * Brace-match the installer's body.
 *
 * This used to slice a fixed 60,000 characters from the function's start, which
 * silently stopped covering the code once the function grew past that mark: the
 * assertions then failed against a body that looked truncated. Matching braces
 * keeps the scope honest however long the installer gets.
 */
function functionBody(source, signature) {
    const at = source.indexOf(signature);
    assert.ok(at > 0, `${signature} must still exist`);
    let depth = 0;
    let i = source.indexOf("{", at);
    for (; i < source.length; i += 1) {
        if (source[i] === "{") depth += 1;
        else if (source[i] === "}") {
            depth -= 1;
            if (depth === 0) break;
        }
    }
    return source.slice(source.indexOf("{", at), i + 1);
}

const body = functionBody(src, "function installReplaceWindowsMode(");

assert.match(body, /const IDLE_POLL_MS = \d+;/, "idle poll interval must be defined");
assert.match(body, /const isBusy = \(\) => \{/, "an activity predicate must gate the loop");
assert.match(body, /const schedule = \(\) => \{/, "scheduling must go through schedule()");

// The handle must be captured so cancellation is possible at all.
assert.match(
    body,
    /raf = requestAnimationFrame\(tick\);/,
    "the requestAnimationFrame handle must be stored in raf",
);

// And the old unconditional tail must be gone.
assert.doesNotMatch(
    body,
    /\}\s*;\s*requestAnimationFrame\(tick\);\s*setToggleLabel\(\);/,
    "the loop must not restart unconditionally",
);

// Idle must get off requestAnimationFrame entirely rather than merely skipping work.
assert.match(
    body,
    /raf = 0;\s*if \(idleTimer\) return;\s*idleTimer = setTimeout\(/,
    "idle must fall back to a timer instead of a frame",
);

// Hover must cut the slow poll short, so throttling costs no interaction latency.
assert.match(body, /ed\._wakeReplaceLoop = \(\) => \{/, "a wake hook must be exposed");
assert.match(
    src,
    /mouseenter", \(\) => \{ this\._isHovering = true; this\._wakeReplaceLoop\?\.\(\); \}/,
    "mouseenter must wake the loop immediately",
);

// Playback and replace mode must both keep full rate.
assert.match(body, /ed\.isPlaying \|\| ed\._pauseSettling \|\| ed\._isHovering/);
assert.match(body, /directorIsVideoMode\(ed\) && ed\.timeline\?\.replaceMode/);

console.log("replace-windows idle loop tests passed");
