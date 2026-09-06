#!/usr/bin/env node
// Runs every standalone frontend test under web/js/tests/*.test.mjs.
// Each test is a self-contained Node script using node:assert (some bring up
// a jsdom environment). Exits non-zero if any test file fails.
//
//   node scripts/run_js_tests.mjs        (all tests)
//   node scripts/run_js_tests.mjs audio  (only files whose name contains audio)

import { spawnSync } from "node:child_process";
import { readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const testsDir = join(here, "..", "web", "js", "tests");
const filter = process.argv[2] ? process.argv[2].toLowerCase() : "";

const files = readdirSync(testsDir)
    .filter((name) => name.endsWith(".test.mjs"))
    .filter((name) => !filter || name.toLowerCase().includes(filter))
    .sort();

if (files.length === 0) {
    console.error(`No JS tests matched${filter ? ` for "${filter}"` : ""}.`);
    process.exit(1);
}

let failed = 0;
for (const file of files) {
    const result = spawnSync(process.execPath, [join(testsDir, file)], {
        encoding: "utf8",
    });
    const status = result.status === 0 ? "PASS" : "FAIL";
    if (result.status !== 0) {
        failed += 1;
    }
    console.log(`[${status}] ${file}`);
    if (result.status !== 0) {
        const tail = (result.stderr || result.stdout || "").trim().split("\n").slice(-12).join("\n");
        if (tail) {
            console.log(tail.split("\n").map((line) => `    ${line}`).join("\n"));
        }
    }
}

console.log(`\nJS tests: ${files.length - failed}/${files.length} passed.`);
process.exit(failed === 0 ? 0 : 1);
