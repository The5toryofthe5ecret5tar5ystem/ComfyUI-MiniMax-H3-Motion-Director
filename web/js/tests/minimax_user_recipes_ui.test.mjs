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
    /if \(item\.source === "user"\) continue;[\s\S]*?pe\.recipeSelect\.appendChild\(pe\.recipeOptionFor\(item\)\);/,
    "the dropdown lists the pack's recipes, not yours",
);
assert.match(
    load,
    /const active = items\.find\(\(r\) => r\.key === keep && r\.source === "user"\);[\s\S]*?if \(active\) pe\.recipeSelect\.appendChild\(pe\.recipeOptionFor\(active\)\);/,
    "one of yours that is already selected keeps a place, or a stored custom looks like Auto",
);
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

const optionFor = functionBody(enhancer, "pe.recipeOptionFor = (item) => {");
assert.match(
    optionFor,
    /option\.textContent = item\.source === "user" \? `\$\{base\} \$\{t\("pe\.recipeUser"\)\}` : base;/,
    "an entry of yours is marked as yours wherever it is shown",
);

// --- the Browse menu -----------------------------------------------------------

const browse = functionBody(enhancer, "pe.toggleRecipeMenu = () => {");

assert.match(
    browse,
    /const mine = pe\.userRecipes\(\);/,
    "the menu lists the recipes from the user's file",
);
assert.match(browse, /row\.onclick = \(\) => pe\.selectRecipe\(item\.key\);/, "a row loads that recipe");
assert.match(
    browse,
    /t\("pe\.recipeMenuEmpty", \{ path: pe\.userRecipesPath \|\| "recipes\.json" \}\)/,
    "an empty file says where to add one instead of showing nothing",
);
assert.match(
    browse,
    /t\("pe\.recipeIssues", \{[\s\S]*?problem: pe\.userRecipeErrors\[0\]/,
    "a broken file is reported in the menu too",
);
assert.match(
    browse,
    /t\("pe\.recipeMenuHint", \{ path: pe\.userRecipesPath \|\| "recipes\.json" \}\)/,
    "the menu says which file to edit",
);
assert.match(
    browse,
    /document\.addEventListener\("pointerdown", pe\._closeRecipeMenuOnOutside, true\);/,
    "clicking away closes the menu",
);

const select = functionBody(enhancer, "pe.selectRecipe = (key) => {");
assert.match(
    select,
    /pe\.recipeSelect\.appendChild\(pe\.recipeOptionFor\(item \|\| \{ key: value, label: value \}\)\);/,
    "selecting one of yours adds it to the dropdown on demand",
);
assert.match(select, /savePeSettings\(\{ h3Recipe: value \}\);/, "and the choice is remembered");
assert.match(select, /pe\.closeRecipeMenu\(\);/, "and the menu closes");

const browseBtn = functionBody(enhancer, "pe.syncRecipeBrowseBtn = () => {");
assert.match(
    browseBtn,
    /t\("pe\.recipeBrowse"\)\} \(\$\{mine\.length\}\)/,
    "the button says how many you have",
);
assert.match(
    browseBtn,
    /pe\.recipeBrowseBtn\.style\.background = active \? "#3b82f6" : "#252a34";/,
    "and lights up while one of yours is the active recipe",
);

// --- the note under the dropdown ------------------------------------------------

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
assert.match(note, /pe\.syncRecipeBrowseBtn\(\);/, "the note refresh also refreshes the button");

assert.match(
    functionBody(enhancer, "header.onclick = () => {"),
    /pe\.closeRecipeMenu\(\);/,
    "collapsing the panel closes the menu with it",
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

for (const key of [
    "pe.recipeUser",
    "pe.recipeFromFile",
    "pe.recipeIssues",
    "pe.recipeBrowse",
    "pe.recipeBrowseTip",
    "pe.recipeMenuYour",
    "pe.recipeMenuEmpty",
    "pe.recipeMenuHint",
]) {
    const values = [...i18n.matchAll(new RegExp(`"${key.replace(/\./g, "\\.")}": "([^"]*)"`, "g"))]
        .map((match) => match[1]);
    assert.equal(values.length, 2, `${key}: one string per locale`);
    assert.ok(values.some((value) => !CJK.test(value)), `${key}: an English one`);
    assert.ok(values.some((value) => CJK.test(value)), `${key}: a Chinese one`);
}

for (const key of ["pe.recipeFromFile", "pe.recipeIssues", "pe.recipeMenuEmpty", "pe.recipeMenuHint"]) {
    const values = [...i18n.matchAll(new RegExp(`"${key.replace(/\./g, "\\.")}": "([^"]*)"`, "g"))]
        .map((match) => match[1]);
    assert.ok(
        values.every((value) => value.includes("{path}")),
        `${key}: both locales show where the file is, or the line cannot be acted on`,
    );
}

console.log("User recipe panel reporting passed");
