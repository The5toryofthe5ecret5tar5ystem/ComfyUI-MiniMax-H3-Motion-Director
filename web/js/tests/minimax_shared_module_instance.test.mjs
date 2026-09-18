import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

// ESM keys modules by full URL, including the query string. So a module imported
// as "./x.js?boot=v1" in one place and "./x.js" (or a different token) in another
// is instantiated TWICE: two copies of every module-level binding, two `let`
// flags, two caches. Nothing errors - the two halves just stop agreeing.
//
// This happened for real: minimax_prompt_mentions.js was pulled in untokenised
// by image_batch.js and as ?boot=director_ui_v2 by timeline.js, and the two
// instances each injected their own copy of the stylesheet because the guard was
// a module-local `stylesInjected` flag.

const here = path.dirname(fileURLToPath(import.meta.url));
const JS_DIR = path.resolve(here, "..");

const files = fs
    .readdirSync(JS_DIR)
    .filter((n) => (n.endsWith(".js") || n.endsWith(".mjs")) && !n.includes(".bak"))
    .sort();

// Specifiers that point at ComfyUI's own frontend, resolved by the browser
// against the server root rather than on disk. They are not ours to reconcile.
const isExternal = (spec) => !spec.startsWith(".");

const IMPORT_RE = /(?:import\s+[^'"]*?from\s*|import\s*|import\()\s*['"]([^'"]+)['"]/g;

/** target filename -> Map(token -> Set(importing file)) */
const usage = new Map();

for (const name of files) {
    const src = fs.readFileSync(path.join(JS_DIR, name), "utf8");
    for (const match of src.matchAll(IMPORT_RE)) {
        const raw = match[1];
        if (isExternal(raw)) continue;
        const [spec, query = ""] = raw.split("?");
        const resolved = path.resolve(JS_DIR, spec);
        // Only reconcile modules that live in this directory.
        if (path.dirname(resolved) !== JS_DIR) continue;
        let target = path.basename(resolved);
        if (!path.extname(target)) {
            for (const ext of [".mjs", ".js"]) {
                if (fs.existsSync(`${resolved}${ext}`)) {
                    target = path.basename(resolved) + ext;
                    break;
                }
            }
        }
        if (!fs.existsSync(path.join(JS_DIR, target))) continue;
        if (!usage.has(target)) usage.set(target, new Map());
        const byToken = usage.get(target);
        if (!byToken.has(query)) byToken.set(query, new Set());
        byToken.get(query).add(name);
    }
}

const conflicts = [];
for (const [target, byToken] of usage) {
    if (byToken.size > 1) {
        const parts = [...byToken.entries()].map(
            ([token, importers]) =>
                `${token || "(no token)"} via ${[...importers].sort().join(", ")}`,
        );
        conflicts.push(`  ${target}\n    ${parts.join("\n    ")}`);
    }
}

assert.equal(
    conflicts.length,
    0,
    "these modules are imported under more than one ?boot token, which loads two "
    + `independent instances of each:\n${conflicts.join("\n")}`,
);

// The style injection must survive an accidental duplicate instance too: keying
// off the element id makes it idempotent regardless of module-local flags.
const mentions = fs.readFileSync(path.join(JS_DIR, "minimax_prompt_mentions.js"), "utf8");
assert.match(
    mentions,
    /const MENTION_STYLE_ID = "/,
    "the mention stylesheet needs a stable id so injection can be idempotent",
);
assert.match(
    mentions,
    /if \(document\.getElementById\(MENTION_STYLE_ID\)\) return;/,
    "injectStyles must check the document, not only the module-local flag",
);
assert.match(
    mentions,
    /el\.id = MENTION_STYLE_ID;/,
    "the injected style element must carry that id",
);

console.log(`shared-module instance tests passed (${usage.size} shared modules reconciled)`);
