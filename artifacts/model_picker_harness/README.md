# Model-picker harness (local only, not part of the test suite)

Mechanical check of the prompt enhancer's model control against the real
`enhance_models` payload shape. Mounts the actual `mountPromptEnhancerPanel`
under jsdom with ComfyUI's frontend `scripts/api.js` stubbed, then asserts the
scan feeds a `<select>`, installed entries sort first and are tagged, the
resolved default is selected without typing, picking an entry sends its id, the
custom escape hatch opens/closes, and an empty scan falls back to the text field.

Run from the repo root (jsdom comes from the repo's `node_modules`; the `./`
prefix matters - `--import` would otherwise look for an `artifacts` package):

    node --import ./artifacts/model_picker_harness/hooks.mjs ./artifacts/model_picker_harness/test.mjs

`scan.json` is a captured live response; refresh it with:

    curl -s -X POST http://127.0.0.1:8188/minimax/motion-director/enhance_models \
      -H 'Content-Type: application/json' \
      -d '{"llm_url":"","api_format":"Local (ComfyUI)","openai_compat_mode":"标准","api_key":""}' \
      -o artifacts/model_picker_harness/scan.json

Why not `web/js/tests/`: that suite must run on CI's Node 20, while this harness
needs `module.registerHooks` (Node 22.15+) to stub the ComfyUI frontend import -
which the standalone suite deliberately skips instead of stubbing. Kept under
`artifacts/` (gitignored) so it never lands in CI.
