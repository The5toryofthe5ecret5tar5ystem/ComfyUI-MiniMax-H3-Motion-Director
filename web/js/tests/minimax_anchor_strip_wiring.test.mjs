// Wiring contract for the anchor ladder strip (P2).
//
// The strip itself is a browser module (it imports ComfyUI's scripts/api.js
// through minimax_anchor_api.mjs), so these tests assert on source text the way
// the pack's other wiring tests do. What is pinned here:
//
//   * the editor imports + mounts the strip and refreshes its cells from
//     commit(), which is the only place the segment count can change,
//   * the strip writes anchor state through the widget (never a local copy),
//   * the boundary cell exposes approve + re-roll, and re-roll re-seeds,
//   * the "render fill" pass stays disabled until the fill pass can be skipped,
//   * every anchor route the frontend calls has a matching backend route,
//   * every anchor.* i18n key exists in both dictionaries.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const read = (relative) => readFileSync(join(repoRoot, ...relative.split("/")), "utf8");

const timeline = read("web/js/minimax_timeline.js");
const strip = read("web/js/minimax_anchor_strip.mjs");
const api = read("web/js/minimax_anchor_api.mjs");
const routes = read("director/anchor_routes.py");
const ladder = read("director/anchor_ladder.py");
const executor = read("director/executor_core_legacy.py");
const plan = read("director/plan.py");
const conditioning = read("nodes/conditioning.py");
const i18n = read("web/js/minimax_i18n.js");

// --- editor wiring ----------------------------------------------------------- //

assert.ok(
    timeline.includes('from "./minimax_anchor_strip.mjs?boot=anchor_ladder_v1"'),
    "the timeline must import the strip with its boot token",
);
assert.ok(
    timeline.includes("this._anchorStrip = installAnchorStrip(this);"),
    "bindEvents must mount the strip next to the other page mounts",
);
assert.ok(
    timeline.includes("this._anchorStrip?.requestRefresh?.();"),
    "commit() must ask the strip to re-key its cells (segment count can change)",
);

// commit() is the refresh site: keep it inside the method, near the continuity
// refresh that already reacts to segment changes.
{
    const start = timeline.indexOf("    commit(skipRender = false");
    assert.ok(start !== -1, "commit() not found");
    const body = timeline.slice(start, timeline.indexOf("\n    normalizeSegments()", start));
    assert.ok(body.includes("_anchorStrip"), "the strip refresh must live inside commit()");
}

// --- strip behaviour --------------------------------------------------------- //

assert.ok(strip.includes('from "./minimax_i18n.js"'), "the strip must use the shared i18n helper");
assert.ok(
    strip.includes('from "./minimax_anchor_api.mjs?boot=anchor_ladder_v1"'),
    "the strip must use the anchor API client (with a boot token)",
);
assert.ok(strip.includes("function anchorsBlock(ed)"), "anchor state must be read through anchorsBlock()");
assert.ok(
    strip.includes("ed._writeTimelineWidget()") && strip.includes('onWidgetChanged?.("timeline_data"'),
    "anchor edits must be persisted into the timeline widget",
);
assert.ok(
    strip.includes('data-cell="approve"') && strip.includes('data-cell="reroll"'),
    "each boundary cell needs approve + re-roll actions",
);
assert.ok(
    strip.includes("nextAnchorSeed(previous)") && strip.includes('anchorAction(nodeIdOf(ed), "delete", index)'),
    "re-roll must delete the rendered anchor and pick a new seed",
);
assert.ok(
    strip.includes('option.disabled = mode === "hard"'),
    "hard mode is reserved (P4) and must not be selectable",
);
assert.ok(
    strip.includes('data-t="renderFill" disabled'),
    "the fill pass cannot be skipped yet, so its checkbox ships disabled",
);
assert.ok(
    strip.includes("requestRefresh: () =>") &&
        strip.includes("if (refreshTimer) clearTimeout(refreshTimer);"),
    "requestRefresh must be debounced (commit() fires on every drag)",
);
assert.ok(
    strip.includes("ed.mainBody.insertBefore(el, ed.viewport)"),
    "the strip belongs directly above the timeline canvas",
);
assert.ok(
    strip.includes("applyI18nDom(el)") && strip.includes("onLocaleChange?."),
    "the strip must re-localise on locale change",
);

// --- frontend endpoints vs backend routes ------------------------------------ //

const frontendPaths = ["/minimax/motion-director/anchors", "/action", "/plan"];
assert.ok(
    api.includes('const BASE = "/minimax/motion-director/anchors";'),
    "the API client must target /minimax/motion-director/anchors",
);
assert.ok(
    api.includes("anchorsApiUrl(`?node_id=${encodeURIComponent(nodeId ?? \"\")}`)") ||
        api.includes("anchorsApiUrl(`?node_id="),
    "listing must pass node_id as a query parameter",
);
for (const path of ["/action", "/plan"]) {
    assert.ok(
        api.includes(`anchorsApiUrl("${path}")`),
        `the API client must POST to ${path}`,
    );
}
assert.ok(
    strip.includes("anchorsApiUrl(") === false,
    "the strip must go through the client functions, not build URLs itself",
);
assert.ok(
    routes.includes('_route(routes, "GET", BASE, anchors_list)') &&
        routes.includes('_route(routes, "POST", BASE + "/action", anchors_action)') &&
        routes.includes('_route(routes, "POST", BASE + "/plan", anchors_plan_route)'),
    "every frontend anchor endpoint must have a registered backend route",
);
assert.ok(
    read("director/http_routes.py").includes("register_anchor_routes(routes)"),
    "register_routes() must call register_anchor_routes()",
);
assert.ok(
    api.includes("function anchorThumbUrl"),
    "thumbnails must go through the cache-busted URL helper",
);

// --- an explicit render click outranks the "Render anchors" checkbox --------- //

assert.ok(
    /block\.renderPass = true;/.test(strip),
    "runAnchors() must force renderPass on: ▶/Pre-roll are explicit render actions, and with " +
        "the checkbox off they used to load what existed, render nothing and report 'reused'",
);
assert.ok(
    strip.includes("current.renderPass = previous.renderPass;"),
    "and the checkbox state must be restored after the run",
);
assert.ok(
    /if \(armed\) block\.mode = "soft";/.test(strip) && strip.includes("current.mode = previous.mode;"),
    "a render action must arm the anchors mode for its own run and put it back: with mode 'off' the " +
        "engine drops the whole anchor block (onlyIndices included), so \u25b6 on a boundary used to " +
        "render the entire timeline as fills",
);
assert.ok(
    strip.includes('t("anchor.modeArmed")'),
    "arming the mode must be reported - the dropdown snaps back to Off and the render would look " +
        "like it came from nowhere",
);
{
    // Start at the handler, not at the template occurrence: adding another cell
    // button used to push the message code out of a fixed-size window.
    const start = strip.indexOf(`[data-cell="render"]').addEventListener(`);
    assert.ok(start !== -1, "the per-cell render handler was not found");
    const body = strip.slice(start, start + 1600);
    assert.ok(
        body.includes('anchor.renderNothing') && body.includes("diskItems.has(index)"),
        "the render button must decide its message from the listing: a boundary with no PNG on " +
            "disk is a failure, never 'it already existed and got reused'",
    );
}
assert.ok(
    strip.includes('anchor.preRollPartial'),
    "a pre-roll that leaves boundaries missing must say so instead of claiming success",
);
assert.ok(
    routes.includes('"renderPass": bool(getattr(plan, "render_pass", True))'),
    "the preflight must report renderPass so the footer can say rendering is off",
);

// --- lead placement: the pose lives inside the shot that ends on it ---------- //

assert.ok(
    strip.includes('const PLACEMENTS = ["boundary", "lead"];'),
    "the strip must offer both placements",
);
assert.ok(
    strip.includes("block.placement = PLACEMENTS.includes("),
    "the placement select must write anchors.placement through the widget",
);
assert.ok(
    strip.includes("anchorsBlock(ed).leadHard = Boolean(leadHardBox.checked);"),
    "the pin checkbox must write anchors.leadHard",
);
assert.ok(
    strip.includes('const lead = block.placement === "lead" && index > 0;'),
    "a thumbnail click must seek one second before the cut in lead mode",
);
assert.ok(
    ladder.includes('INJECT_MARKER_LEAD = "{{anchor_lead}}"') && ladder.includes("ANCHOR_LEAD_LINE ="),
    "the engine must have a lead prompt line and marker",
);
assert.ok(
    ladder.includes('idx_lead, idx_out = idx_out, None'),
    "lead injection must move the boundary anchor into the shot that ends on it",
);
assert.ok(
    plan.includes("anchor_leads: dict = field(default_factory=dict)"),
    "the plan must carry the lead anchors to the executor",
);
assert.ok(
    conditioning.includes("def append_minimax_keyframes(") &&
        conditioning.includes("def encode_h3_keyframe_latent("),
    "pinning a lead pose reuses the keyframe plumbing (marked guides)",
);
assert.ok(
    executor.includes("anchor_ladder.lead_keyframes(") &&
        executor.includes("positive = append_minimax_keyframes("),
    "the executor must pin the lead keyframe on the fill conditioning",
);

// --- prompt material: source policy + per-boundary editor -------------------- //

assert.ok(
    strip.includes('const PROMPT_SOURCES = ["auto", "template", "from", "to", "both"];'),
    "the strip must offer exactly the prompt sources the engine understands",
);
assert.ok(
    strip.includes("block.promptSource = PROMPT_SOURCES.includes("),
    "the source select must write anchors.promptSource through the widget",
);
assert.ok(
    strip.includes('data-cell="prompt"') && strip.includes("function openPromptEditor("),
    "every boundary cell needs the ✎ prompt editor",
);
assert.ok(
    strip.includes('data-t="preRoll"') && strip.includes("border-color:rgba(255,200,50,.9)"),
    "Pre-roll must wear the timeline's clip yellow: it is the 'fill every missing pose' action",
);
assert.ok(
    strip.includes("{{from_tail}}") && strip.includes("{{to_head}}") && strip.includes('"{{camera}}"'),
    "the editor must offer the neighbour material as insertable tokens",
);
assert.ok(
    strip.includes("block.prompts[promptIndex] = promptBodyEl.value"),
    "Save must write the per-boundary override (anchors.prompts[k])",
);
assert.ok(
    strip.includes("promptInfo = Array.isArray(data.boundaryText)"),
    "the composed preview must come from the server, never be re-implemented in JS",
);
for (const source of ["auto", "template", "from", "to", "both"]) {
    const key = `anchor.source${source.charAt(0).toUpperCase()}${source.slice(1)}`;
    assert.ok(
        (i18n.split(`"${key}":`).length - 1) >= 2,
        `${key} must exist in both dictionaries (it is built dynamically)`,
    );
}

// --- i18n -------------------------------------------------------------------- //

const anchorKeys = [...strip.matchAll(/\bt\("(anchor\.[A-Za-z0-9_.]+)"/g)].map((match) => match[1]);const uniqueKeys = [...new Set(anchorKeys)];
assert.ok(uniqueKeys.length >= 10, `expected the strip to use anchor.* keys, saw ${uniqueKeys.length}`);
for (const key of uniqueKeys) {
    const occurrences = i18n.split(`"${key}":`).length - 1;
    assert.ok(occurrences >= 2, `${key} must exist in both the ZH and EN dictionaries (saw ${occurrences})`);
}
// Dynamic status keys are built as `anchor.status.${status}`.
for (const status of ["pending", "ready", "approved", "rejected"]) {
    assert.ok(
        (i18n.split(`"anchor.status.${status}":`).length - 1) >= 2,
        `anchor.status.${status} must exist in both dictionaries`,
    );
}

console.log(`anchor strip wiring: ${uniqueKeys.length} keys, ${frontendPaths.length} endpoints ok`);
