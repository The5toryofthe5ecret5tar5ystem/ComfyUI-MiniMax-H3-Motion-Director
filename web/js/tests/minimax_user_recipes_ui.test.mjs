import assert from "node:assert/strict";
import fs from "node:fs";

// Recipes of your own come from a file in ComfyUI's user directory, which the route
// reads on every panel open. Two things have to be visible in the panel or the feature
// is a trap: which entries are yours, and what is wrong when the file has a typo (the
// recipe would otherwise simply be missing from the list, with no explanation).
//
// Source-level: mounting needs a live Director node and a ComfyUI api object.

const enhancer = fs.readFileSync(new URL("../minimax_prompt_enhancer.js", import.meta.url), "utf8");
const i18n = fs.readFileSync(new URL("../minimax_i18n.js", import.meta.url), "utf8");

function functionBody(source, signature) {
    const at = source.indexOf(signature);
    assert.ok(at > 0, `${signature} must still exist`);
    let depth = 0;
    for (let i = source.indexOf("{", at); i < source.length; i += 1) {
        if (source[i] === "{") depth += 1;
        else if (source[i] === "}") {
            depth -= 1;
            if (depth === 0) return source.slice(source.indexOf("{", at), i + 1);
        }
    }
    throw new Error(`${signature} body is not brace-balanced`);
}

const load = functionBody(enhancer, "pe.loadRecipes = async (");

assert.match(
    load,
    /pe\.userRecipesPath = data\.user_path \|\| "";/,
    "the route says where the user's recipes live",
);
assert.match(
    load,
    /pe\.userRecipeErrors = Array\.isArray\(data\.errors\) \? data\.errors : \[\];/,
    "and what is wrong with the file, so the panel can say it",
);
assert.match(
    load,
    /option\.textContent = item\.source === "user"[\s\S]*?t\("pe\.recipeUser"\)/,
    "the user's own entries are marked in the dropdown",
);

const note = functionBody(enhancer, "pe.updateRecipeNote = () => {");

assert.match(
    note,
    /t\("pe\.recipeIssues", \{[\s\S]*?problem: pe\.userRecipeErrors\[0\]/,
    "a broken file is reported with its first problem",
);
assert.match(
    note,
    /t\("pe\.recipeFromFile", \{ path: pe\.userRecipesPath \|\| "recipes\.json" \}\)/,
    "a user recipe says which file it came from",
);
assert.match(
    note,
    /pe\.recipeNote\.textContent = \[text, \.\.\.extra\]\.filter\(Boolean\)\.join\("\\n"\);/,
    "summary and file line are joined, not overwritten",
);
assert.match(
    note,
    /pe\.recipeNote\.style\.color = pe\.userRecipeErrors\.length \? "#f87171" : "#7d8698";/,
    "and a problem reads as a problem",
);
assert.ok(
    enhancer.includes('pe.recipeNote.style.whiteSpace = "pre-line";'),
    "two lines of note need pre-line to show as two lines",
);

// The RefMod field must follow the *assembly* of a user recipe: a variant of the
// RefMod replace needs the character field, and a variant of anything else must not
// show it.
assert.match(
    note,
    /const assembly = item\?\.based_on \|\| key;/,
    "the RefMod row keys off the assembly, not the raw recipe key",
);
assert.match(note, /pe\.refmodRow\.style\.display = assembly === "character_replace_refmod"/);

// --- the strings exist in both locales, and each locale is its own language ----

const CJK = /[\u4e00-\u9fff]/;

for (const key of ["pe.recipeUser", "pe.recipeFromFile", "pe.recipeIssues"]) {
    const values = [...i18n.matchAll(new RegExp(`"${key.replace(/\./g, "\\.")}": "([^"]*)"`, "g"))]
        .map((match) => match[1]);
    assert.equal(values.length, 2, `${key}: one string per locale`);
    assert.ok(values.some((value) => !CJK.test(value)), `${key}: an English one`);
    assert.ok(values.some((value) => CJK.test(value)), `${key}: a Chinese one`);
}

const fromFile = [...i18n.matchAll(/"pe\.recipeFromFile": "([^"]*)"/g)].map((m) => m[1]);
assert.ok(
    fromFile.every((value) => value.includes("{path}")),
    "both locales show where the file is, or the line cannot be acted on",
);

console.log("User recipe panel reporting passed");
