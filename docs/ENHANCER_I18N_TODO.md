# Handover: finish translating the prompt-enhancer panel

Paste-ready task brief. Written 2026-09-17 at the end of a long session, so the
remaining work is documented here instead of living only in that conversation.

> **Status 2026-09-17 (later): the i18n pass is done and deployed.** Every
> display string in `minimax_prompt_enhancer.js` goes through `t()` now (59
> `pe.*` keys in both locales); the three unload variants were collapsed to one
> wording each; the four enum literals listed below stay untranslated and carry
> a why-comment. `node --check` clean, `qa_readiness.py --fast --live` reports
> READY — i18n parity PASS, and the panel no longer appears in the
> untranslated-text list. Deployed to the install copy; backup at
> `.deploy-backup-20260917-191029`. Everything below stays as the original
> brief and rationale.
>
> **Same day, afterwards:** the panel gained a select-based model picker, an
> engine status line (GPU/CPU/missing), a real download progress bar, and an
> "H3 prompt rules" toggle that ships the engine contract to the enhancing
> model. See `lib/h3_prompt_rules.py`, `lib/model_download.py`, and
> `docs/PROMPT_ENHANCER_LOCAL_SETUP.md`.

## Panel features added after the i18n pass

**Model picker.** The Model row is a `<select>` built from the `/enhance_models`
scan: automatic default, installed entries (tagged "installed"), downloadable
catalog entries (tagged "to download"), then a custom escape hatch with the old
text field. Values are the ids the backend already accepted, so nothing about
sending changed.

**Engine status.** A line under the Model row reports the local llama.cpp engine:
GPU (with backend), CPU-only, or not installed. Detection reads `/proc/self/maps`
— which `libggml-*` the wheel shipped vs which the loader actually mapped —
because `llama_supports_gpu_offload()` returns False even when the GPU is doing
the work.

**Download progress.** `GET /minimax/motion-director/download_status` reports an
in-flight catalog download, measured from the filesystem (staging bytes plus the
finished file) because `hf_hub_download` blocks with no callback. The panel polls
it once a second and paints a bar with percent, GB progress, ETA and the vision
phase; the request that performs the download is started without awaiting it.
State lives in `lib/model_download.py`, so it survives a panel reload; a staging
file nobody has written to for 60s is treated as a dead transfer rather than
progress.

**H3 prompt rules.** The enhancer is a general-purpose model, and nothing used to
tell it what the Director does with the text. `lib/h3_prompt_rules.py` now
carries the engine contract (slot bindings and what each may not supply, the
`<d>` marker discipline, why repeated `Camera:`/`Scene:`/`Audio:` lines must not
carry events, beats that change state, no negative prompt, replace-window discard
rules) and the panel sends `h3_rules: true` by default via a checkbox whose state
persists in the same localStorage settings blob. Off = exactly the previous
behaviour, byte for byte.


## The immediate task

`web/js/minimax_prompt_enhancer.js` still contains ~30 **hardcoded Chinese**
display strings. The panel was never wired to i18n at all — it didn't even import
`minimax_i18n.js` — so switching the interface to English left it untranslated.

Already translated (do not redo): panel title, `Model:`, `Output language:`, the
two checkbox labels, and the two action buttons. That work is in place with keys
`pe.title`, `pe.modelLabel`, `pe.outputLanguageLabel`, `pe.characterDetail`,
`pe.autoEnhance`, `pe.enhanceCurrent`, `pe.enhanceAll`.

### ⚠️ Do NOT translate these — they are enum values, not UI text

They look like labels and are compared or sent to the server. Translating any of
them breaks behaviour silently:

```js
const API_ZHIPU = "智谱 GLM";              // API-format identifier
const OPENAI_COMPAT_STANDARD = "标准";      // compared against the stored mode
const OUTPUT_LANGUAGE_ZH = "中文";          // the literal value sent to request Chinese output
const CHARACTER_DETAIL_NORMAL = "一般";
```

A blind find-and-replace across this file will break them. That is the single
biggest hazard in this task. Consider adding a comment above each saying why.

### Strings still to translate

**Labels and buttons**

| Chinese | English |
| --- | --- |
| `刷新模型` | Refresh models |
| `全局提示词` | Global prompt |
| `卸载 Ollama` / `卸载本地模型` / `卸载模型 (llama-swap)` | Unload model |
| `用后卸载 Ollama` / `用后卸载本地模型 (释放显存)` / `用后卸载模型 (llama-swap)` | Unload the model afterwards (frees VRAM) |

The three unload variants were chosen dynamically in `updateApiFormatUI()`.
**Resolved 2026-09-17:** collapsed — the checkbox reads "Unload the model
afterwards (frees VRAM)" and the button "Unload model" for every backend; the
active backend is already visible in the API dropdown, so the per-backend
wording was redundant (and the two leftover keys `pe.unloadLocal` /
`pe.unloadAfterLocal` were removed with it).

**Tooltips / help text** (these are long, one key each)

| Chinese | Notes |
| --- | --- |
| `按 MiniMax H3 官方 task 模板扩写短提示词…` | panel description |
| `仅 OpenAI Compatible 生效。选择 llama-swap 后…` | compat-mode toggle |
| `LLM 扩写输出语言。MiniMax H3 官方示例与 T5…` | output-language select |
| `Queue 时在服务端自动用 LLM 扩写每段…` | auto-enhance, 3 consecutive lines |
| `rv2v/r2v/r2i 等含参考图任务：未勾选时…` | character-detail, 2 consecutive lines |
| `OpenAI / llama-swap API Key（可选）` | placeholder |
| `智谱 API Key` | placeholder |

**Status messages** (transient, lower priority but currently Chinese in an English UI)

```
扩写中…  准备中…  收集素材…  正在获取模型列表…  正在卸载模型…
扩写失败  卸载失败  扩写返回为空  未知错误  未下载模型；已取消
当前 API 格式不支持手动卸载模型
没有可扩写的分段提示词（请先填写各片段或全局提示词）
} 模型已卸载        ← template string, has a leading brace
```

### Procedure

1. Replace each display literal with `t("pe.…")`. `t` is already imported in this
   file. **Match on the string, not on a line number** — line numbers shift as you
   edit and will misfire.
2. Add both ZH and EN keys to `web/js/minimax_i18n.js`. The ZH block ends around
   line 525 and the EN block starts around 527; keys are flat dotted strings.
3. Verify parity: every new key must exist in both dictionaries, or one locale
   renders the raw key. `npm run qa` checks this.
4. `node --check web/js/minimax_prompt_enhancer.js` before deploying.

`web/js/minimax_prompt_enhance_batch.mjs` (the batch review overlay) is, by
decision, **left English-only for now**: it has no i18n at all and wiring it is
a separate backlog item. One hardcoded string is known to the QA sweep
(`textContent = 'Stopping after the current prompt…'`).

## Environment

```
Dev repo   ~/WakaCloud/git/ComfyUI-MiniMax-H3-Motion-Director
Install    /mnt/ssd2/cmfy/ComfyUI-Easy-Install/ComfyUI/custom_nodes/ComfyUI-MiniMax-H3-Motion-Director
Python     /mnt/ssd2/cmfy/ComfyUI-Easy-Install/python_embeded/bin/python3
ComfyUI    http://127.0.0.1:8188   (Python changes need a restart; JS needs a reload)
```

**These two copies are separate git repositories.** `git pull` in the dev repo does
NOT deploy. The workflow is: edit dev → copy to install → verify. Back up first:

```bash
I=/mnt/ssd2/cmfy/ComfyUI-Easy-Install/ComfyUI/custom_nodes/ComfyUI-MiniMax-H3-Motion-Director
B=$I/.deploy-backup-$(date +%Y%m%d-%H%M%S); mkdir -p $B/web/js
cp -p "$I/web/js/<file>" "$B/web/js/" 2>/dev/null
cp -p "<dev>/web/js/<file>" "$I/web/js/<file>"
```

ComfyUI serves these with `Cache-Control: no-store`, so a **plain reload** picks up
JS changes — no hard refresh needed.

## Verification tooling

`npm run qa` (or `python scripts/qa_readiness.py --fast --live`) sweeps the pack:
dev-vs-install drift, module parse, import resolution, duplicate module instances,
routes-vs-fetch, i18n parity, untranslated strings. Reports to
`artifacts/qa_readiness_report.md`. See `docs/QA_READINESS.md`.

The i18n checks are `i18n_parity`, `i18n_keys` (unknown + unused keys) and
`i18n_coverage` (counts user-visible strings that bypass `t()` — this is what
flagged the enhancer panel, reported as a SUGGESTION rather than an error).

**Nice-to-have:** `i18n_coverage` under-called this bug. A panel that is 100%
untranslated deserves more than a suggestion. Consider promoting it when an entire
file has zero `t()` usage.

## Context: what the enhancer is

A task-aware prompt rewriter for MiniMax H3, running **entirely inside ComfyUI**
(no Ollama, no external server). It loads a GGUF model from ComfyUI's own
`models/LLM` tree via `llama_cpp` and rewrites prompts through the pack's H3
ruleset: seven task types with per-task slot syntax (`<Picture N>`, `<Video K>`),
optional vision grounding from attached references, structured output for
replacement tasks, a character-detail mode with a minimum-length gate, and output
language control.

| File | Role |
| --- | --- |
| `lib/prompt_local_models.py` | catalog: scans `models/LLM`, merges a download manifest |
| `lib/prompt_local_catalog.json` | curated downloadable quants (huihui-ai Qwen3.8 27B abliterated) |
| `lib/prompt_local_runtime.py` | llama.cpp load/inference, cached, with a VRAM ladder |
| `lib/prompt_enhancer.py` | backend dispatch; `API_FORMAT_LOCAL` is the default |
| `director/prompt_enhance_routes.py` | 8 HTTP endpoints (incl. `download_model`) |
| `web/js/minimax_prompt_enhancer.js` | the panel (this file needs the i18n pass) |
| `web/js/minimax_prompt_enhance_batch.mjs` | batch run + accept/reject review list |

### Two non-obvious constraints, already solved — don't undo them

**1. The panel is mounted by dynamic import from `minimax_timeline.js`, with no
`?boot=` token.**

`minimax_prompt_enhancer.js` dynamically imports `minimax_timeline.js` (it is the
boot entry), so a static import back is circular — which is why the panel was
never mounted for years. It is loaded lazily on first click instead. The import
must stay **token-less**: ComfyUI auto-loads that file as
`/extensions/<pack>/minimax_prompt_enhancer.js`, and every distinct URL (including
`?boot=…`) is a *separate module instance* with its own state and stylesheets.
Adding a token for consistency with its neighbours would create a second panel.
`npm run qa`'s module-identity check guards this.

**2. The settings overlay is centred, not anchored to its button.**

ComfyUI's DOM-widget wrappers apply `transform: scale(zoom)`, and a transformed
ancestor makes `position: fixed` resolve against that ancestor rather than the
viewport — so viewport coordinates put an anchored popover off-screen. The overlay
uses `inset: 0` + flex centering, which needs no coordinate maths.

## Honest status

- **Backend: verified working.** A real enhancement was run end-to-end through
  `enhance_prompt_sync` with `API_FORMAT_LOCAL` against a local 3B GGUF: 469
  characters of correct rv2v replacement prompt, no error.
- **Frontend: partially verified by the user, not by me.** Buttons appear, the
  settings overlay opens, and the model resolved to a real local path. Never
  confirmed: a successful enhancement *clicked through the UI*, the vision path,
  and the download flow.
- **Batch review list: never exercised at all.**
- The installer's local model default is `UD-Q3_K_XL` (13.3 GB) but nothing is
  downloaded yet; the resolved default falls back to the user's existing
  `Qwen2.5-VL-3B-Instruct-abliterated` GGUF, which is correct behaviour.
- **i18n (2026-09-17): mechanically verified, not clicked.** `node --check` on
  both edited files; the QA sweep's i18n parity/keys checks pass and the panel is
  off the untranslated list. Nobody has yet opened the panel in a browser in
  English mode and watched the new strings render.

Uncommitted: everything since commit `75be24f`. Two sessions of work.

## Also unwired, found but not fixed

`director/prompt_enhance_runtime.py` is imported nowhere. It was written to
enhance prompts **during a render** (`maybe_enhance_segment_prompt`) but was never
connected to the executor. Pre-run enhancement was chosen deliberately over
mid-run; this module is dormant. Delete it or wire it — don't leave it ambiguous.
