# Changelog

Notable changes in this fork. Older releases are tagged in git and published on the
[releases page](https://github.com/The5toryofthe5ecret5tar5ystem/ComfyUI-MiniMax-H3-Motion-Director/releases).

## Unreleased

### Added

- **Story to segments.** A multi-segment project is a story spread over N renders, and
  every segment prompt had to be written by hand. The enhancer panel now takes the whole
  story in a few sentences, a segment count and a seconds-per-segment value, and splits
  it in one model call into a shared `world` paragraph plus one paragraph per segment -
  following the rules that make a multi-segment render work: one continuous take per
  segment, beats that change state, each segment ending on a pose the next one continues
  from, and the character's look stated once instead of re-described per segment. The
  segments are created when the timeline is empty or is a generation timeline (a
  hand-laid video or replace timeline is never re-timed), each segment then goes through
  the normal enhancement, and the existing review list shows every result before
  anything is applied.
- **Regenerate a single prompt, or all of them, in the review list.** A list of ten
  story prompts is not accepted or rejected as a whole: one segment usually misses, and
  re-running the batch to fix it costs ten model passes and loses the nine that were
  fine. Each row has **Regenerate** (re-running from its own original text, task and
  block, with the settings the batch used) and the footer has **Regenerate all** for
  rows that are still ticked.

- **Your own prompt recipes, in a file a pack update cannot overwrite.** The recipe
  dropdown was server-owned and closed: the shapes shipped as Python constants, an
  update replaced them, and there was nowhere to put an edit. Recipes of your own now
  live in `<ComfyUI user dir>/minimax_h3_motion_director/recipes.json`, which updates
  never touch. Each entry is a *variant of a built-in* (`based_on`) that inherits
  everything it does not set - the block, the tasks Auto may match, whether a source
  video is required - and borrows that built-in's assembly in `Build from images`
  mode, where the block is written by code rather than by a model. `"auto": true`
  opts a recipe into Auto picking it; without it Auto keeps choosing the pack's own.
  The dropdown keeps the pack's nine shapes; your recipes load from the **Browse...**
  button beside it, which says how many you have, lists each one's summary, ticks the
  active one and lights up while one of yours is being sent. The selected one keeps a
  place in the dropdown (marked `(yours)`) so the panel always shows what it will use.
  The file is re-read whenever it changes (no restart), and anything wrong with it - a
  duplicate key, a `based_on` that is not a recipe, broken JSON - is shown in the panel
  instead of silently dropping the recipe.
- **A starter file for every shape.** `recipe_templates/` ships one JSON file per
  recipe (`character_replace.json`, `ref2va.json`, `first_last.json`, ...) with the
  pack's current block text in it, ready to copy into your recipes file and edit, plus
  a `README.md` with the field reference. They are generated from the recipes
  themselves (`scripts/generate_recipe_templates.py`) and a test fails when the two
  drift apart, so the text you start editing from is the text the pack uses today.

### Changed

- **Vision frames follow the segment, not the file.** The caption pass sampled the
  source video uniformly across its whole length, so a Character Replace window was
  described from three moments somewhere else in the footage - and on a long project
  the same three moments for every window. The panel now sends the segment's own
  window (`start_sec`/`end_sec`) and the frames are sampled inside it; a segment with
  no window still falls back to the whole file, and so does the ffprobe index-scan
  fallback, which now keeps the window as well.
- **`Vision frames` (1-5) is a setting.** The count was a constant (3, or 2 on
  Ollama). It sits next to the other enhancer options, persists per browser, and also
  caps how many frames of the RefMod character are decoded for the wardrobe line
  (`refmod_frames`). An inserted reference clip keeps its own smaller count.
- **From four frames on, they are sampled as movement pairs.** Each moment becomes a
  near-duplicate pair (two frames a few frames apart), because a set of stills is the
  only thing a vision model gets and a single frame says nothing about what moves. It
  at least shows which limb travels and which way; a slow cyclic motion leaves no
  visible difference between any number of stills, and belongs in the prompt.
- **A Character Replace window keeps your own words.** The action prose of a replace
  block came from the caption alone, so anything typed about the motion was dropped -
  and the caption cannot see a movement that leaves no difference between frames. The
  prompt box's text now travels into the block as a note after the action sentence:
  *"Her own note on the motion of this window, which still frames cannot show: <your
  text>. Follow it; never replace what <Video 1> does, and never invent a different
  action."* The caption stays the description of what the frames demonstrably show,
  and the note only adds to it.

### Fixed

- **Enhancing the same replace window twice no longer nests the motion note.** The note
  is appended to the window's action prose, and the panel writes the assembled block back
  into the prompt box - so the next run read that note back in, from inside the block and
  from inside the note. A live run showed round 2 putting round 1's note inside its own,
  the identity lines dragged along with it and both copies cut off mid-sentence, leaving a
  block that described the previous block instead of the window. The previous note is now
  peeled out (however deep the nesting goes) and only the user's own words carry forward;
  a block that came back without a note contributes nothing rather than echoing its own
  caption as if it were the user's brief. The note also no longer keeps its trailing full
  stop, which had been adding a ".." to the block on every round.
- **The action caption describes the action before anything else.** A live run came back
  with the room, the bed and the camera and then stopped mid-word ("... the camera holds a
  static low-angle point-of-"), because the action was listed last and the caption ran out
  of its 512 tokens before reaching it - so the block carried a scene and no action at
  all, on a window whose whole point was what the body was doing. The instruction now puts
  the action first, bounds the answer at about 110 words, and the action caption gets 768
  tokens.
- **A caption that was really the model's own notes is no longer pasted into the
  block.** A caption model sometimes answers with a transcript of its reasoning
  ("The user wants... I need to cover... Let me write a single paragraph, no quotes")
  and sometimes describes the attached frames one at a time ("frames 1-2 nearly
  identical"). Both went into the prompt verbatim, so a whole render was spent on the
  model's notes about the task instead of on the window. The answer is now cut back to
  the description that follows the handover, instruction echoes and first-person
  narration are stripped, a language that was not asked for is dropped (a leaked
  Chinese word inside an English caption), the frames are no longer compared or listed,
  and an answer that is still notes is asked once more with an instruction that names
  the problem - after that the run reports it instead of shipping the transcript.
- **The motion note no longer duplicates a whole structured prompt.** A replace window
  carries the prompt box's own text in as a note about movement. When the box held a
  full prompt (`subject_definitions`, identity, `Camera:`, `Scene:`), the note was a
  verbatim copy of the block, cut off mid-sentence. Only the part that speaks about
  movement travels now - a short note as typed, or the prompt's own
  `detailed_description`/`summary` - and a structured prompt with nothing about
  movement contributes no note at all.
- **A stale cached module could kill the prompt enhancer in silence.** ComfyUI's
  cache rule covers paths ending in `.js` (and `.css`), so the pack's `.mjs` modules
  were left to the browser's own freshness heuristics: a copy cached before an export
  was added stayed in use, a freshly served `.js` entry then failed to *link* against
  it ("does not provide an export named ..."), and the enhancer - imported lazily,
  inside a `.catch` that only wrote to the console - never mounted. Both the Enhance
  and the Settings button stayed on screen and did nothing when clicked, on every
  reload, until the cache was cleared by hand. Three layers now cover it:
  the shared module is imported under a version token
  (`minimax_reference_assets.mjs?boot=reference_assets_v2`) so a browser holding the
  old URL is made to ask for the new one, the pack serves its own `.mjs` files with
  `Cache-Control: no-store` (the rule the core already applies to `.js`, installed at
  startup from `director/web_cache.py`), and a panel that fails to load says so on the
  button that was pressed instead of returning silently.
- **A reference picture in a folder could not be read.** The panel asked for the file
  name alone, so a picture in a subfolder - or one in outputs - came back "not found"
  and the caption silently lost it. A slot's `subfolder` and `type` now travel with
  the request, and the image route and loader honour them.
- **One unreadable picture no longer discards the rest.** A single failed fetch threw
  out of the whole collection, so the caption ran with no reference images at all and
  the panel reported success. Each input is now read on its own, what failed is
  logged with its reason, and the status line says how many inputs were skipped; a
  collection that fails outright is reported as such rather than looking like a run
  without references.

## v1.9.0 — 2026-09-18

The prompt enhancer can now improve a prompt without rebuilding it. Every other
path decides the *shape* of the answer - MiniMax's official template, a recipe, or
the block caption mode assembles from images - which is what you want when the
prompt is a note to yourself and exactly what you do not want when it already
follows the guide: the tags are bindings, the `Camera:` / `Scene:` / `Audio:`
lines are engine controls, and a rewrite that renames a slot or restates the
wardrobe costs a render.

`Polish wording only` keeps the prompt and edits only the prose. It goes to the
model verbatim - no template, no recipe, no engine rules and no reference images -
and the answer is *checked* rather than trusted: the tag, heading and `[Shot N]`
inventory of both texts is compared, and a dropped or invented tag earns one retry
that names it. If the structure still differs the text comes back anyway, with a
warning in the status line, because a usable polish plus a note beats a click that
does nothing.

### Changed

- **`Polish wording only` is a third prompt mode.** It is exclusive with `Build
  from images`, parks the controls that only shape a rewrite (recipe, compact
  rules, character detail, hide-the-performer), collects no frames at all, and
  reports `wording polished, structure and tags kept` when the structure check
  passes.
- **`docs/PROMPT_WRITING_GUIDE.md` section 10** documents what polish mode will
  and will not touch, and when to reach for a recipe instead.
- **Common References are a pool, not a fallback.** A segment's pictures were
  resolved as *the segment's own, or the shared block* - never both - so a window
  that carried one reference of its own silently lost the shared identity, and the
  prompt's `<Picture N>` tags pointed at pictures the render never sent. Both plan
  builders now run the same compile (`compile_effective_references`): the shared
  assets this segment keeps, then its own, renumbered densely from `<Picture 1>`,
  with `useCommonAssets` / `excludedCommonAssetIds` honoured and the official
  9-picture / 3-video / 3-audio limits enforced with a message that says what to
  remove. Mentions stored as `{{mmx-ref:...}}` resolve to the segment's own tags on
  the video timeline too, and an unknown one is left as written rather than killing
  the render.
- **Per-window RefMod.** One mod set is harvested from the connected conditioning
  and appended to every segment, so a mod that belongs to some windows had no way to
  say so. Each window now carries a `refmod` switch (Replace list, or a segment's
  context menu), the plan carries `refmodEnabled` and the executor honours it at both
  conditioning sites - including the five-frame Source Bridge.
- **A RefMod window can use its pictures too.** The `character replace (RefMod
  identity)` recipe dropped identity prose because the mod reaches the DiT only and
  text about her face would fight it. When the window also carries numbered
  references those are visible to the text encoder as well, so they are captioned
  and named as the same woman: the mod keeps the detail, the pictures are what the
  prompt can point at. With no pictures attached the old suppression stays.

### Fixed

- **`Unload model` says what it actually did.** It answered from the enhancer's
  own model cache, so an empty cache printed "no model was resident" while
  ComfyUI's render models held the card - true, and read as a lie. The answer now
  carries the name that was being held, the free-VRAM figure before and after, and
  a fresh engine snapshot, and the engine note names the state it is in (`no model
  loaded (12.4 GB VRAM free)` / `CUDA - qwen... loaded`). That blank state was half
  the confusion: "the enhancer holds nothing" and "the panel is not saying" looked
  identical.
- **"Unload the model afterwards" is visible now.** Its effect happens inside the
  enhancement, in a worker thread, so the panel could only ever say "done" -
  whether it worked or not. The response reports what the cache holds once the run
  finishes, and the status line ends with `model unloaded afterwards` or `the model
  is still resident - unload it manually`.
- **The Enhance button keeps the panel's language while it runs.** Its in-progress
  label was a hardcoded Chinese literal, so an English panel showed 扩写中… the
  moment a run started while the buttons beside it stayed English. The label now
  comes from the translation table (`Enhancing…` / `扩写中…`), and the button still
  returns to "Enhance" when the run ends - success or failure.
- **The caption pass can see the Common References.** In Character Replace the
  identity lives in the shared block and the windows used to carry none of their
  own, so collecting vision from the window alone sent no reference image at all and
  the caption described a character it had never been shown. The enhancer now
  resolves the same reference list the render does, in the same order, and tells the
  model the slot each picture gets.

## v1.8.4 — 2026-09-18

The prompt enhancer now runs entirely inside ComfyUI. It loads a GGUF model from
your own `models/LLM` folder with llama.cpp - no Ollama, no API key, no second
server to start - and rewrites your prompt through the same H3 ruleset as before,
so task types, reference slots and output language behave exactly as they did.
The model list comes from what you actually have on disk, and the recommended
Qwen3.8 27B abliterated is a one-click download (13.3 GB, sized for a 16 GB card)
with the size shown before anything is fetched.

This also fixes the reason none of it worked: `register_prompt_enhance_routes`
was defined but never called, so all seven enhancement endpoints were missing at
runtime while the panel's calls failed against a misleading `405 Method Not
Allowed`.

The enhancer can also *build* the prompt instead of rewriting it. Caption mode
(`Build from images`) is a port of the external Character Remake workflow
("Masked Motion + QwenVL") that handled character replacement reliably where
rewriting did not - not because its prompt was better, but because the language
model was never asked to write the structure. Two narrow vision calls answer two
narrow questions ("what does this character look like", "what happens in this
source window") and this pack's own code glues the answers into the section
block, so every header, role line, retention rule and discard sentence is
module-owned and cannot be reordered, forgotten or invented. Each call sees only
the images it should: identity from the reference slots, action from the source
frames, never the other way round. Six recipes are covered - character replace
with and without a RefMod, ref2va, source edit, start image and first/last - and
each names the images the model must look at, including the endpoint frames for
i2v/fl2v that the panel previously never sent: a caption is the only way that
prose can agree with frame 0.

A RefMod window can now have its `wardrobe:` line filled in. A mod reaches the
Director as an unnamed latent blob appended after text encoding, so it is
invisible to the text encoder and to the prompt - deliberately - which left the
one line the guide requires unanswered. The mod's own latents are decoded with
the H3 video VAE and captioned, and the answer comes back as a wardrobe line
plus at most one 2-4 word clue. Never a description of her face: prose about
identity fights the reference instead of helping it.

And the source performer can be hidden from the action caption. A caption model
looking straight at the performer occasionally volunteers her description, which
then argues with the replacement reference for the rest of the prompt. The
subject region of those frames is inverted before they are captioned (rembg's
salient-object mask on CPU, a couple of seconds per frame), so nothing about the
identity survives and everything the caption actually needs - silhouette, pose,
camera, room - does. It is opt-in, and it says so in the note when the mask
could not be built.

There is now a single command that reports whether a build is actually ready -
`npm run qa` (`python scripts/qa_readiness.py`). It sweeps the pack and writes a
severity-ordered report to `artifacts/qa_readiness_report.{json,md}`, exiting
non-zero only when something reached the fail threshold. It covers the failure
modes the test suites cannot see: whether the copy ComfyUI loads matches the copy
you edited, whether a module is instantiated twice under two `?boot=` tokens,
whether the frontend calls an endpoint that no longer exists, whether a
registration function is defined but never called, whether a translation key was
added to one locale only. Add `--live` to also probe a running ComfyUI, or
`--fast` to skip the suites. See `docs/QA_READINESS.md`.

Character Replace could be configured into a state where it could never run, and
said nothing about it until the run was over: the validator accepted the
configuration, the header implied it was engaged, and the engine rendered the
whole clip before admitting it had not replaced anything.

The long-form Character Replace workflow was four settings spread across three
parts of the UI, and the one button that covered a whole clip looked identical to
the two that add a single window. It is now one named action - and it no longer
deletes the prompt it was supposed to be applied to.

The Director also repairs its own widget tail when a workflow loads, so a file
saved before a widget existed heals itself instead of arriving unqueueable.

And the Results page plays its previews again: the transport no longer parks on
frame 0 while the picture runs.

### Changed

- **The prompt enhancer can build the prompt from your images.** A new *Build
  from images* switch sends the segment's reference images, its source frames and
  (for i2v/fl2v) its endpoint frames to the model as captions instead of asking it
  to rewrite your text. The panel says which mode produced the result, and the
  server states when it declined a recipe it cannot caption rather than quietly
  rewriting.
- **`Recipe` picks the target shape explicitly.** `Auto` derives it from the task
  and whether a source video is present, so nothing changes unless asked; a named
  recipe replaces MiniMax's official one-paragraph template with the shape the
  guide specifies for that job - a replace window with `<Picture N>` refs, a
  replace window whose identity comes from a RefMod, the ref2va block, or the
  simpler start-image / first-last / source-edit / text-only segments.
- **`H3 prompt rules (compact)` sends the short form of the engine contract**,
  which is what a small local model can actually follow without dropping slots.
- **`Hide the source performer`** inverts the subject region of the action frames
  before they are captioned, so the caption cannot describe the woman being
  replaced.
- **The local model list is a catalog, not a text field.** GGUF files already
  under ComfyUI's `LLM` folders are listed beside the quants that can be fetched,
  the recommended Qwen3.8 27B abliterated is one click away with its size shown
  before anything is pulled, and a download reports real progress - measured from
  huggingface_hub's own staging directory, so it survives a panel reload.
- **The panel says where inference will run.** In local mode the engine note
  reports the backend that actually loaded (CUDA / Vulkan / Metal / CPU), and
  warns once when a GPU build is present but its backend never mapped into the
  process - the wheel built against a different CUDA major that silently falls
  back to the CPU.
- **`Cover entire clip` is now `Long-form replace - cover whole clip`**, styled
  and placed as the panel's primary action instead of the seventh control in a
  10 px row. It does the whole recipe in one click: cut the source into equal
  windows at the chosen length, enable replace and continuity on every window,
  and set Export mode to *by segment* so a single bad window can be re-rendered
  without touching its neighbours. The outcome is stated before it runs
  (`Will create 27 windows x 15.08 s . covers 6:50 . continuity: on . export mode
  set to by segment`), and the window utilities (`+ Add after`,
  `+ Add at playhead`) moved behind a divider.
- **The panel now reads its own state**: `27 windows` and `covers 100%` badges in
  the header, and per-row hints (`first window - no anchor`,
  `anchors to W1 tail`) that explain what `cont` does.
- **A way in while Replace is OFF.** A slim bar appears when a source is loaded
  and is longer than one window: `6:50 source . this clip needs 27 replace
  windows` plus a one-click entry that turns Replace on and covers the clip. The
  only entry point used to be a toggle that advertised nothing.
- **No source loaded now says so.** With an empty timeline the button is disabled
  and the panel reads `Load a source video first` rather than returning silently,
  which made it look broken.
- **The replace panel is localised.** Its strings were hardcoded English in a UI
  that is otherwise translated, so there was nothing to search for in Chinese.
- **One switch to enable every replace window.** A long-form chain only engages
  if each window's own `enabled` flag is set - the backend tests
  `seg.replace.enabled`, not the panel's mode - so covering a 2:14 clip meant
  ticking 15 boxes by hand. Worse, `Replace: ON` changed the panel without
  changing a single window, which made an unengaged run look engaged. An
  `enable all` checkbox in the panel header now sets them together. It is
  tri-state: half-filled whenever the list disagrees with itself, so it never
  claims a state the windows are not actually in.
- **The replace header reports enabled windows, not just coverage.** The panel
  showed `27 windows` and `covers 100%`, both of which stay true with every
  window switched off - and the engine keys off `seg.replace.enabled`, so the run
  would be plain video-to-video while the panel read as engaged. A third badge
  counts the switches themselves: `Replace ON 27/27`, `Replace ON 3/27`, or a red
  `Replace OFF - no window enabled`.
- **A window with no mask source no longer reads back as `frames`.** The
  per-window selector stored `frames` for anything that was not `sam3`, so a
  window that never touched the control claimed a PNG folder with no folder set.
  A missing kind is now read from what is configured: a folder means the file
  route, no folder means the file-free SAM3 route. An explicit `frames` is left
  alone - that is a real choice, and the validator reports the empty folder.

### Fixed

- **`Enhance` returned a 500 on every click.** `director_enhance_prompt` called
  `is_replace_task_prompt` without importing it, so every request died with
  `NameError: name 'is_replace_task_prompt' is not defined` while the suite stayed
  green: the rule tests call `enhance_prompt_sync` directly, the panel harness
  stubs the HTTP layer, and the QA sweep only walks GET routes. Nothing exercised
  the handler - exactly where a missing import is invisible until someone clicks
  the button. `tests/test_enhance_route_handler.py` now drives both paths (rewrite
  and captions) through the real function, and immediately found a second bug: the
  route never passed the compact-rules flag on to the enhancer.
- **Vision mode failed on every Qwen3-VL checkpoint.** llama.cpp registers the
  Transformers Jinja helpers (`raise_exception`, `strftime_now`, the non-escaping
  `tojson`, the loop-control extension) for its text formatter only; the
  multimodal handlers build a bare sandboxed environment, and Qwen3-VL's template
  calls `raise_exception` in its guard branches - so the request died with
  `UndefinedError: 'raise_exception' is undefined` before generating a token. The
  handlers' environment now gets the same helpers. The first attempt at this was a
  silent no-op (it patched `llama_multimodal` as a top-level module; llama.cpp
  keeps it at `llama_cpp.llama_multimodal`), which is why the test asserts the
  patch reached the class it names.
- **Caption mode could not send a system turn at all.** `MTMDChatHandler`
  prepends its own `DEFAULT_SYSTEM_MESSAGE` whenever the system content is empty,
  so a request without one arrived with two system messages and was rejected with
  `TemplateError: System message must be at the beginning.` The caption path sends
  no system turn, so the message builder now omits it instead of sending it empty.
- **An enhancement that finished left your prompt unchanged.** The run completed
  (`generated 449 tokens`, `Prompt built from images (character_replace): 3442
  chars`) and the textarea still held the old text. Both prompt boxes are owned by
  the mention controller, which keeps its own rich state and re-renders the
  textarea from it, so writing `.value` directly left the controller on the old
  text and its next read painted the old prompt back over the new one - every step
  reported success while the result silently reverted. The panel now writes
  through the controller (`setValue`), for the global prompt and the per-segment
  box alike, and the harness pins a controller stub that reproduces the clobber.
- **`Unload model` works on the Local (ComfyUI) backend.** Both the button and
  `Unload the model afterwards` are offered for local models - it is the one
  backend where freeing VRAM hands it straight back to the render - but the route
  only knew Ollama and llama-swap, so clicking it answered `Current API format
  does not support model unload`. It now calls the runtime that owns the model,
  reports the file it dropped and how many were resident, and distinguishes
  "nothing was loaded" from "freed".
- **The Results page player no longer sits on frame 0 while the video plays.**
  A finished result was played through the *playlist* transport even when it was
  a single clip, and that transport re-derives the frame index from `seeked`
  alone. `seeked` never fires during ordinary playback, so the scrubber, the
  `0.00 / 9.96` readout and the `Frame 1 / 250` counter all stayed pinned at the
  start while the element played on - and anything that re-synced the element to
  the stale index 0 yanked it back to the beginning, which is why only the
  opening frames were ever visible.
  A lone clip is one continuous video, so it now plays through the element
  itself: the src is assigned once and the element's own clock drives the index
  from `timeupdate`. Only Multi Segment, which genuinely spans several clips,
  keeps the playlist bookkeeping. Scrubbing a single clip moves the element
  instead of a wall-clock index the picture knows nothing about, a fresh load
  resets the index so the scrubber cannot claim a frame the picture is not on,
  and the two audio-sync paths now accept a lone clip as a clip - they used
  "empty playlist" to mean "not a clip", which would have left every single-clip
  result playing silent. Pinned by
  `web/js/tests/minimax_output_single_clip_transport.test.mjs`.

- **Covering a clip no longer deletes its prompt.** The action rebuilds
  `timeline.segments` to lay the clip out in equal windows, and it built every
  window with the plain new-window factory, which starts blank. So the prompt you
  had just written for the clip was gone the moment you covered it - and since the
  prompt box reads the selected window, the box emptied in front of you. The
  character references beside the prompt went with it, which is worse: a replace
  render that silently loses its refs has nothing left to hold the identity it was
  replacing. Only the layout is rebuilt now. A window's position (`start`,
  `length`) is the layout and is always replaced; its prompt, negative prompt,
  task type, pictures/audio/video refs, generated source image and context link
  are content and are carried across, each window getting its own copy so one
  window's edits cannot rewrite its siblings.
  Re-cutting to the same number of windows is the same windows laid out again, so
  each keeps what it had - including its own mask recipe, which previously
  collapsed to window 1's. Any other count is a different cut with no positional
  mapping left, and the clip collapses to a single recipe taken from the first
  window, which is what it already did. A shorter cut also re-clamps
  `selectedIndex`, since the prompt box reads `segments[selectedIndex]` and a
  stale index there looks exactly like a deleted prompt.
  Pinned by `web/js/tests/minimax_replace_longform_content.test.mjs`, which also
  fails if a field added to the new-window factory later is not added to the carry
  list - otherwise this exact bug returns with the next content field.

- **A workflow saved before a widget was declared now loads instead of failing to
  queue.** ComfyUI writes `null` into every widget a file predates, because it has
  no saved value to restore them from, and the type coercion happens on the way in:
  `int(None)` and `float(None)` raise, while `str(None)` and `bool(None)` do not.
  So a file from before a numeric widget existed dies with
  `Failed to convert an input value to a FLOAT value: audio_refine_denoise, None`
  and the whole workflow is unqueueable — including the five example workflows in
  this repo, which had to be hand-patched one at a time.
  `repairDirectorWidgetTailWorkflow` now does that on load, before the graph is
  configured, so the bug stops coming back with every save.
  It is anchored on the `postprocess_config` value rather than counted back from
  the end of the array: a file saved before a widget existed is simply *shorter*,
  and counting backwards would line the table up against the wrong slots and
  overwrite live values with defaults. Only two tail shapes are recognised — the
  current one and the pre-`verbose_logging` one — so an unfamiliar file is left
  alone rather than guessed at. Slots are only touched when the value is missing,
  null, or of the wrong type, and the loose `*_ui` mirrors are filled only where
  they already carry the key and hold null, so a value the user set is never
  rewritten. A stray section header sitting in a boolean slot is replaced too.
  Guarded at both ends: the per-case behaviour is covered by
  `web/js/tests/minimax_director_widget_tail.test.mjs`, and
  `tests/test_director_widget_tail_parity.py` fails if the frontend table drifts
  from the node's declaration in `nodes/director.py` — a repair that writes into
  the wrong slot would be worse than the null it was fixing.
- **A `frames` mask with no folder is now a pre-flight error.** It is not a
  preference, it is a guaranteed fallback: `prepare_replace_window` cannot build
  the anchor without a mask, so the window renders as plain video-to-video and
  only mentions it in the final report - after every segment has been paid for.
  `Validate` now reports a missing folder, an unresolvable folder, a folder with
  no `frame_*.png`, and an unusable mask kind as errors, and a folder that covers
  only part of a window as a warning (runtime drops the whole window when any
  frame is absent). Directory resolution and the `offset` rebase mirror
  `load_mask_window` exactly, so the verdict cannot disagree with the run.
- **`Character Replace fell back to plain RV2V` now appears during the run, not
  after it.** The engine emits a live warning when a segment degrades, and the
  run banner leads with it (`Segment 1: Character Replace fell back to plain
  video-to-video - the mask could not be loaded for this window; check the mask
  folder, or switch the mask source to sam3`), accumulating a count for the
  segments that repeat it. Previously this was collected and only rendered into
  the final report, so the cause - almost always a window configuration mistake
  that was knowable before segment 1 - was discovered once everything had
  rendered.
- **Two modules were being loaded twice, and one of them styled the page twice.**
  ESM keys a module by its full URL including the query string, so
  `minimax_prompt_mentions.js` pulled in untokenised by `minimax_image_batch.js`
  and as `?boot=director_ui_v2` by `minimax_timeline.js` was two independent
  instances - two copies of every module-level binding, and two injected
  stylesheets, because the idempotence guard was a module-local flag.
  `minimax_r2v_common_ui.mjs` had the same split. Both importers now use one
  agreed token, and the mention stylesheet keys off an element id so it stays
  idempotent even if an instance ever duplicates again. A test reconciles every
  shared module's token so this cannot silently return.
- **The auto-mask no longer repeats a doomed search on every window.** The SAM3
  attempt plan is five passes over the whole window - roughly two minutes each on
  a 260-frame clip - and when text seeding finds nothing, nothing about the next
  window makes the same prompt more likely to land. A chain could spend hours
  rediscovering the same nothing before falling back on every segment. The first
  window still runs the full plan; once it has missed for a given
  (checkpoint, prompt), later text-seeded windows retry only the strongest
  anchor(s) - the same reduction the interactive *Test mask* route already used.
  A success clears the entry, entries expire after 30 minutes so a later attempt
  against different footage gets the full plan back, and the log says plainly
  that the retry was reduced and why.
- **"building echo-free motion reference" is now "preparing ...".** The line was
  logged just before the attempt that can still return nothing, so it read as if
  the reference had been made and the fallback message two lines later looked
  contradictory.
- **The default SAM3 prompt no longer describes a subject that is not on screen.**
  It was `the woman, full body from head to toe, including every strand of her
  hair` - written to pull hair into the mask, but phrased as a description of a
  standing, fully-visible figure. SAM3's text grounding answers literally, so on
  a subject lying down and visible from the waist up it grounded nothing: over
  five attempts at both detection profiles, `responses=0` and 0 of 260 frames
  masked, then a silent fallback to plain video-to-video for the whole window.
  Measured on the real footage, changing only the prompt:

  | prompt | result | frames masked |
  | --- | --- | --- |
  | `the woman, full body from head to toe, including every strand of her hair` | none | 0/30 |
  | `the woman` | MASK | 30/30, first attempt |
  | `the person` | MASK | 30/30, first attempt |
  | `the man` (control) | none | 0/30 |
  | `dog` (control) | none | 0/30 |

  The default is now `the woman`, matching what the proven standalone
  `sam3_scene_mask.py` has always used. The controls confirm the text genuinely
  steers detection rather than returning the largest region: the wrong-gender and
  absent-object prompts both found nothing. Hair coverage belongs in the mask
  grow/feather settings, not in a clause that may describe nothing on screen.
- **A window with no SAM3 prompt can no longer be written.** `ensureReplaceConfigOnSeg`
  stored `sam_prompts: []` whenever the prompt field was empty, so the engine fell
  back to its own default and could ground nothing. Since an unconfigured window
  now defaults to the `sam3` mask kind, that was the common path rather than an
  edge case: it turned a fast, obvious failure into a silent one that first spent
  about ten minutes per window on doomed detection. The default prompt is now
  carried into the window instead.
- **The SAM3 prompt field no longer suggests the pattern that fails.** Its
  tooltip read `e.g. 'the woman with long blue hair including every strand'`,
  which is the long descriptive clause implicated above; it now asks for a short
  noun phrase.
- **Swapping a RefMod now invalidates cached work instead of reusing the old
  mod's output.** RefMod blocks are harvested from the connected conditioning and
  appended to every segment, so they change the picture - but they arrive through
  the *conditioning* rather than the timeline, and nothing in either cache
  fingerprint looked at them. Two different mods at the same retention produced
  byte-identical fingerprints, so changing the mod silently reused latents
  generated with the previous one and the old identity bled into the new render.
  The harvested blocks are now digested (hashed from the latents actually fed to
  the DiT, since by then a mod is an unnamed blob with no name to compare) and
  that digest is part of the segment cache key and the generation-environment
  identity behind the motion-context cache. The key is added only when a RefMod
  is connected, so projects without one keep their existing caches. The console
  line now reports the digest as well as the block count: a count cannot tell two
  mods apart, which is exactly what made "I switched mods and the old identity is
  still showing" invisible.

## v1.8.3 — 2026-09-16

The learned-latent upscaler stops re-reading and re-converting its checkpoint on
every call and finally gives its VRAM back, and the v1.8.2 UI changes are made to
reach the browser at all.

### Added

- **Keep the learned-latent upscaler resident (opt-in, off by default).**
  `latent_upscale_cache_model` keeps the built upscaler on the device instead of
  freeing it, so a multi-segment run stops paying a load per call. The upscale
  stage runs after the H3 DiT is unloaded, so an uncached call is a full
  load → free cycle stacked on the DiT's own unload and reload; a resident
  upscaler trades that churn for VRAM held for the rest of the session, sharing
  the card with the reloaded DiT. That trade-off is why it ships off, and the note
  beside the checkbox says so (en + zh). The cache is a single entry keyed on
  `(checkpoint path, dtype, device)`, so a precision or device change rebuilds; a
  stale model is released **before** its replacement is built, so the two are
  never resident together; and clearing the flag releases it.
  `clear_resident_model()` / `has_resident_model()` are exposed for explicit
  reclaim. It changes speed, not frames — the first-pass cache is unaffected.

### Fixed

- **The upscaler re-read and re-converted its checkpoint on every call.** Each
  call re-read the file from disk and ran the float8 → fp16 conversion again. The
  last two decoded state dicts are now kept in CPU RAM, keyed on the path plus its
  size and mtime so that replacing the file on disk invalidates the entry. The
  decoded dict is read-only for every caller (`build_model` reads shapes,
  `load_state_dict` copies), so it is handed out without copying, and
  `clear_checkpoint_cache()` is available for file swaps.
- **The upscaler's VRAM was never actually returned.** Its `finally` block
  dropped the model and the input, then called `empty_cache()` while `mean` and
  `std` were still live device tensors. `empty_cache()` only returns blocks that
  are already unused, and unreachable-but-uncollected tensors keep holding their
  memory — the same trap the segment VRAM cleanup hit. Every device reference is
  now dropped and collected before emptying.
- **The v1.8.2 UI changes never reached the browser.** ComfyUI caches frontend
  modules by URL, so a changed module is only re-served when the `?boot=` token on
  its import changes. Two modules changed in v1.8.2 without their token being
  bumped — `minimax_postprocess_ui.mjs` (the external-patch note and the
  resident-upscaler toggle) and `minimax_timeline.js` (Cover entire clip and the
  `cont` checkbox) — so browsers kept running the cached copies: the controls were
  in the file on disk and served by ComfyUI the whole time, and nothing ever asked
  for them. Both tokens are bumped and the two guard tests were updated in
  lockstep. Worth stating plainly: those guards assert the token *string*, so they
  stay green while a token is stale — they only catch the reverse mistake (bumping
  a token and forgetting the test). Nothing detects that a module changed on its
  own.

### Tests

- **Checkpoint cache.** Covers the hit, invalidation when the file changes on
  disk, the two-entry bound, the explicit clear, and that building a model does
  not mutate the cached dict.
- **Resident model.** Covers the cache key, the bound and the release path, the
  config parse and its default, that the option does not invalidate the first-pass
  cache, and a source contract for the `keep_resident` wiring through the call
  chain.

## v1.8.2 — 2026-09-16

Seamless long-form Character Replace, a masked-replace fix that makes the inpaint
path actually replace the subject instead of returning the source, and audio fixes
across the Segment and Results views.

### Added

- **Character Replace continuity anchor.** Adjacent replace windows are independent
  re-renders, so both windows try to match the same source frame at their shared
  boundary — and being two different guesses, the regenerated subject popped
  ("teleported") whenever windows met. A window can now condition on the previous
  window's **last rendered frame**, injected as an extra `<Picture>` reference plus
  a prompt line naming it, so it opens from the prior output's pose instead of a
  fresh one. On by default (`replace.continuity`), a no-op on the first window, and
  a per-window **cont** checkbox turns it off for deliberately gapped windows.
  Fresh renders and cache-reused windows both record their tail, so a resumed run
  keeps chaining.
- **"Cover entire clip" auto-windowing.** Long clips no longer need windows added by
  hand: one button fills the whole source with contiguous windows at the chosen
  length (frames or seconds), the last window taking the remainder (a sub-second
  tail is folded into the previous window so it cannot become a degenerate stub),
  and the first window's replace settings are copied to every generated window.
  Together with per-window export this is the long-form ("infinite") Character
  Replace workflow: set the length once, cover the clip, export each window on its
  own so a single bad window can be re-rendered without touching its neighbours.

### Fixed

- **Masked (inpaint) replace returned the source unchanged.** A 97-frame inpaint
  window reported "masked replace ready" with a 0.71-mean video noise mask attached
  to the sampler, yet came back frame-for-frame identical to the source (mean |diff|
  8/255, against 51+/255 for the same window in anchor mode). ComfyUI starts masked
  sampling from `latent_image + noise`, so the encoded source left *inside* the
  regenerate region is a strong hint — the denoiser refines what it is shown and
  reconstructs the original performer instead of inventing the replacement. The
  regenerate region is now erased before the latent reaches the sampler, so sampling
  starts from pure noise there, while the keep region still carries the source and
  the noise mask still blends it back every step (the background stays pixel-exact).
  A mask whose shape does not line up with the latent is ignored rather than risking
  a misaligned erase, and the audio stream is untouched.
- **SeedVR2 upscaling silently fell back to the first pass.** ComfyUI imports
  custom-node packages at startup but does not keep the `custom_nodes` directory on
  `sys.path` when a node later executes, so the lazy import raised
  `ModuleNotFoundError: No module named 'seedvr2_videoupscaler'` and the failure was
  downgraded to "keeping first-pass result". The directory is now added back through
  `folder_paths` before the import.
- **Global Refine failures did not name the model holding VRAM.** The refine-failure
  path deliberately keeps models loaded, which skipped the anchored-model scan
  inside the VRAM cleanup — precisely when it matters, since a model ComfyUI can no
  longer unload is a likely cause of the OOM. The scan now runs on failure and the
  warning names the count, with the referrer dump (naming the custom node holding
  the module) in the log.
- **Clear VRAM unloaded the model at the wrong time, twice per boundary.** The
  segment-end cleanup keyed off the timeline's segment count rather than the
  segments actually rendered, so a one-segment selection from a long timeline
  dropped the DiT even though the post-loop refine passes wanted it resident; it now
  matches the pre-sampling call. The loop-top cleanup was also removed outright: the
  segment-end cleanup already unloads before the next segment, so it was a second
  unload plus `gc` plus `empty_cache` on every single segment boundary.
- **The external-attention-patch skip was invisible.** Global Refine is skipped for
  H3-SLA / Spectrum-patched models unless you opt in, but the panel said nothing
  about it — the only evidence was a render-time warning. A note next to the toggle
  now explains the skip (and that the reason is reported at render time) whenever
  the toggle is off.
- **The Segment audio preview was silent in source/keep modes.** Audio is only
  decoded in `generate` mode, so the Segment view had nothing to play even though
  the exported window does keep its original track. It now falls back to the
  window's own source audio — exactly what the export uses. Muted windows stay
  silent, and generated audio still wins whenever it has samples.
- **Result audio crackled and clicked when seeking.** The player pointed at a
  `data:` URL, which has to be re-parsed and re-seeked out of a giant attribute
  string, so the drift helper's seeks produced audible artifacts. Playback now uses
  a streamed, seekable Blob URL that is revoked on every swap so a long run does not
  pin every track in memory; an empty or header-only payload clears the source and
  disables the volume control instead of pointing at a broken URL.
- **The bundled faceswap example workflow shipped `latent_continuation_enabled:
  null`** in all three widget mirrors. ComfyUI coerces `bool(None)` without raising,
  which is why it loaded, but the frontend re-injects the `None` on load. It now
  ships `false`, matching the node default and the other shipped examples.

### Tests

- **Upscaler + Global Refine routing matrix.** Sweeps all five `upscale_method`
  values (lanczos, upscale model, RTX VSR, SeedVR2, H3 learned latent) across
  second sampling on/off, tiled refine, temporal split, and the external-patch /
  `skip_fl2v` / `force_skip` / disabled guards. 25 CPU-only tests; this is the
  canary that would have caught both upscaler regressions at dispatch time.
- **Real-upscaler GPU smoke.** Runs each upscaler once on a tiny input and asserts
  the output shape — the "does it actually produce frames" layer on top of the
  offline matrix. Every GPU case skips cleanly without CUDA or the model files, so
  the file is safe to leave in the normal suite.
- **Regression for the upscaler logger `NameError`** that broke upscaling: forces
  the non-empty VRAM report the CUDA branch logs, which the existing CUDA tests
  never produced.
- **Multi-segment + postprocess ordering contract.** Pins the per-segment sequence
  and both clear-VRAM sites, including that the DiT is *not* cleared between
  first-pass sampling and Global Refine.
- **Stub-module leak containment.** Stub-style tests install fake `director.*` /
  `comfy.*` modules into `sys.modules` and never remove them, so a later test that
  imported the real module got the fake. Modules are now snapshotted per test and
  reverted, with real modules deliberately left alone so torch's one-time
  `TORCH_LIBRARY` namespace registration is not re-triggered.
- **Masked-replace erase cases** (split region, all-keep, nested stream, mismatched
  mask, audio untouched) and a source contract pinning the Character Replace
  continuity wiring.

## v1.8.1 — 2026-09-15

Hotfix for the upscaler regression that stopped Global Refine from upscaling.

### Fixed

- **Global Refine silently kept the first pass.** A `log.warning` had been added to
  the learned-latent upscaler, but the module has no logger, so every CUDA upscale
  raised `NameError: log is not defined` — and the Global Refine catch-all swallowed
  it into "keeping first-pass result", which read as "upscaling just stopped
  working". The logger is now defined, Global Refine logs the full traceback when it
  fails, and a CUDA OOM re-raises as a hard error instead of quietly downgrading to
  the first pass.

## v1.8.0 — 2026-09-15

Refine longer clips by splitting them in time, a new video upscaler, and a
Clear-VRAM toggle that actually frees memory.

### Added

- **Temporal split for Global Refine (`temporal_split`, `temporal_chunk_frames`,
  `temporal_overlap_frames`).** The second-sampling pass re-sampled the entire upscaled
  latent at once, so activation VRAM scaled with sequence length. It now re-samples one
  overlapping time chunk at a time and cross-fades the overlaps, bounding peak VRAM to a
  single chunk. Chunk length and overlap snap to H3's 17-frame grid. Audio is carried
  through unchanged (never re-sampled). Deliberately scoped: used only when there is no
  Motion Context repinning and no H3 noise mask, so conditioning applies uniformly to every
  chunk and needs no per-chunk time re-anchoring. Composes with Tiled refine as a temporal
  outer loop around the spatial inner loop, and falls back to the tiled or plain
  single-stage path when one chunk covers the whole clip. The cross-fade weights sum to 1
  per token, so an identity sampler reproduces the input exactly.
- **SeedVR2 upscale method (`upscale_method: "seedvr2"`).** Temporal-aware pixel-space
  upscaling. It loads its own 3B DiT + VAE (the H3 model is unloaded first, then reloaded),
  keeps aspect ratio, and the caller resizes to the exact target.
- **Runtime probe for SeedVR2.** The post-process panel checks whether the SeedVR2 package
  is importable and reports it in the capability line, so a missing install is visible
  before a run instead of failing inside the upscale stage.

### Fixed

- **Clear VRAM Between Segments could silently do nothing.** Three causes:
  - Every cleanup step ran inside a single `try`, so a raise in the *first* step
    (`cleanup_models_gc`) skipped the unload and the cache empty that follow — one failing
    call disabled the entire cleanup. Each step now runs in its own guarded call and
    reports its own failure.
  - The end-of-segment cleanup always unloaded the model, so a single-segment run dropped
    it and immediately reloaded it for Global Refine / Face Refine. That is wasted work,
    and on a low-VRAM card the reload could OOM where staying loaded was fine. It now
    honours `seg_total > 1`, matching the pre-sampling call.
  - A model ComfyUI cannot unload (dead wrapper — `free_memory` skips those entries) was
    reported only to the log.

  `cleanup_segment_vram` now returns a summary and the executor surfaces it as a **VRAM**
  section in the execution report, naming the failing step or the anchored model, so
  "freed nothing" no longer looks identical to "worked".
- **The bundled example workflows shipped `clear_vram_between_segments: false`**, the
  opposite of the declared default. They now ship `true`.
- **The legacy widget-reorder migration could reassign the Clear-VRAM toggle.**
  `migrateReorderedDirectorTail` rewrites widget values in place, and its guard only
  compared value *types*, which unrelated layouts satisfy. It now also requires real
  group-header labels (`Performance` / `性能`) on both header slots.
- **`_split_streams` mis-split a plain tensor in tiled refine.** `torch.Tensor` has
  `unbind`, so the `hasattr(samples, "unbind")` branch matched a bare tensor before the
  `isinstance` check could. The tensor check now comes first.

### Changed

- **`gaussian_blur_frames` runs on CUDA when available.** The inpaint echo-free reference
  blurs hundreds of RGB frames; on CPU that was a multi-minute stall. The result is
  returned on the input device (identical up to fp rounding).
- Four `log.info` calls around the Character Replace echo-free reference,
  subject-erasing keep/cond source, and masked-source VAE encode, so a slow stage is
  identifiable from the log instead of looking like a hang.

### Tests

- New `tests/test_temporal_refine.py` (grid snapping, edge ramp, and a lossless-stitch
  invariant under an identity sampler) and expanded
  `tests/test_vram_cleanup_leak_report.py` covering per-step failure isolation, the
  partial-failure report, the anchored-model report, `unload_models=False`, the disabled
  no-op, and a missing `comfy` module.

## v1.7.0 — 2026-09-14

Render once, then iterate on post-processing without re-rendering; VRAM-bounded
refine; and an opt-in experimental latent-space continuation.

### Added

- **Reuse first pass (`save.reuse_first_pass`).** The first-pass H3 sample is the
  expensive half of a render. With the checkbox on, the raw AV latent is cached on disk
  keyed on everything that produced it *except* post-processing, so a later run with the
  same seed / prompt / references / resolution but different Global Refine, Face Refine or
  Audio Room settings skips sampling entirely and only re-runs post-processing. A 107-frame
  r2v render measured 363 s down to 33 s on reuse. The key deliberately invalidates when
  the seed, prompt, references, resolution, sampler or model change, because those
  genuinely change the first pass. Every hit and miss is now logged, and a settings
  snapshot plus a field-level drift diff explain any unexpected miss (e.g. the H3 loader's
  non-deterministic quantization-op registration order shifting the model-runtime hash
  across restarts).
- **Tiled refine (`tiled_refine`, `tile_size`, `tile_overlap`).** The Global Refine
  second-sampling pass can now be split into overlapping spatial tiles, so a large upscale
  fits in less VRAM: each tile is sampled alone (with its own keyframe crop), brightness is
  matched back to the input, and tiles are stitched with a linear cross-fade on the interior
  edges. Audio is taken from the first tile.
- **Export comparison (`export_comparison`).** Writes both the raw first pass and the
  post-processed result to `<prefix>_raw_firstpass` and `<prefix>_postprocessed` so the two
  can be compared side by side.
- **Refine opt-out on an external patch (`allow_refine_on_external_patch`).** When a patch
  (external) supplies the output, the second sampling pass can now be skipped via config.
- **Latent continuation (EXPERIMENTAL, opt-in `latent_continuation_enabled`).** Ports the
  community "video joiner / continue in latent space" mechanism natively: the previous
  segment's final latent is injected directly into the next segment's sampling stream and
  locked with a nested H3 noise mask (0 = preserve, 1 = generate), instead of the
  conditioning-only Motion Context. Marked EARLY TEST in the tooltip; needs GPU validation
  before production use.

### Changed

- The post-process page now puts the reuse / performance toggles in a compact bar at the
  top instead of scattering them through Global Refine.

### Tests

- 492 tests, with new suites for the first-pass cache, tiled refine, and latent
  continuation.

## v1.6.0 — 2026-09-13

RefMod identity references, a Results player that streams instead of shipping base64, and
Audio Refine made cache-free.

### Added

- **RefMod identity references.** A connected `Apply H3 RefMod` chain now reaches every
  segment: the Director harvests its reference blocks and appends them to each segment's
  own conditioning, so a character mod can carry identity across a whole chain with no
  headshot and no character sheet. The mod is attached to the DiT only — it is never
  presented to the text encoder, and no `<Picture n>` label is created for it.
- **`Minimax h3 Director - ref2va + RefMod example workflow 1x4s.json`** — a single 4 s shot
  for fast identity iteration, shipping an in-workflow usage guide covering identity,
  wardrobe, the knobs and their reasons, the failure modes, and a bisect order.
- **A wardrobe channel.** A RefMod latent is roughly a 96 x 54 thumbnail per frame, so it
  carries face and body and physically cannot carry a garment's cut, seams or trim. Clothing
  now comes from a `wardrobe:` prompt section, or from a full-resolution picture reference,
  with the prompt assigning each source its job so the two do not fight.
- **Streamed preview clips in Results.** Finished segments and final results are encoded to
  a small all-intra H.264 clip in ComfyUI's temp directory and streamed over `/view`, instead
  of pushing every frame as base64 JPEG through the websocket. One 243-frame segment measured
  ~11.9 MB of base64 parsed synchronously on the browser main thread; the clip is ~2.5 MB and
  streams with ordinary HTTP range requests, at zero websocket cost. All-intra is deliberate:
  every frame is a keyframe, so a seek lands on the exact frame rather than the nearest
  earlier one.

### Fixed

- **The RefMod wiring was in dead code.** Three classes share the name
  `MiniMaxH3MotionDirector` and chain by inheritance, and `__init__.py` imports
  `director_output` last, so the live `execute` is `director_inputs`'. The RefMod wiring had
  been added to `director.py`, which never runs. The socket was declared, the wire connected
  and `/history` showed it — but the live execute had no such parameter, so ComfyUI dropped
  it into `**kwargs` and discarded it. Moved to the class that actually executes, and a test
  now walks the MRO for the first `execute` that names its parameters and fails if any
  declared input is unbound.
- **`audio_refine_enabled` / `audio_refine_steps` / `audio_refine_denoise` were declared but
  never bound**, so they were silently discarded exactly like the RefMod input. Found by the
  same probe, now guarded by the same test.
- **`None` in saved widget values broke prompt validation.** Re-saving a workflow in ComfyUI
  wrote explicit `None` into the Director's audio-refine slots, the frontend restored them
  into `widgets_values`, and `int(None)` failed with *"Failed to convert an input value to an
  INT/FLOAT value"*. All mirrors of the affected example workflows are corrected.
- **A misleading warning on RefMod-only segments.** The plan builder warned that an `r2v`
  segment "has no reference media — will behave like t2v/t2i. Upload 图片/音频/视频 on this
  material card", which is precisely what a RefMod run does not need. It now reports the
  reference block count instead, and only warns when nothing was appended.
- **Audio Refine no longer participates in the segment cache fingerprint.** The room and
  level chain runs once at final output assembly, never per segment, so `per_segment` is gone
  and tuning a room invalidates nothing — no segment, context or audio cache.
- **Undeclared inputs are now reported.** The Director prints any input it received but did
  not declare, instead of dropping it into `**kwargs` in silence. That probe is what surfaced
  the two unbound parameter sets above.

### Documentation

- New RefMod usage guide shipping inside the example workflow, plus a rewritten
  [`example_workflows/README.md`](example_workflows/README.md) section covering how the
  reference actually reaches the model, the identity and wardrobe prompt patterns, and the
  ranked fixes for when a clothing reference takes over the face.

## v1.5.0 — 2026-09-12

A new post-processing stage, plus a Resume correctness pass.

### Added

- **Audio Room — per-scene acoustic space.** A third column in the postprocess panel
  places model-generated audio in a real space instead of leaving it dry on the camera
  mic. Nine named rooms (`dry`, `bedroom`, `bathroom`, `bar`, `office`, `car`, `hall`,
  `cathedral`, `outdoor`) each set all six SoX reverberation parameters at once, or pick
  **Custom** and set reverberance, HF damping, room size, stereo depth, pre-delay and wet
  gain yourself. A separate **Level** section provides normalise and gain.
- **Per-scene rooms.** A scene can declare its own space via a `room` field in the
  timeline, so a bathroom scene and a bedroom scene in one render no longer share a
  single acoustic setting.
- **Never-spoken guard on the shared prompt block.** H3 generates audio from the same
  text it renders, so a bare token or quoted phrase in shared reference material is a
  shape it can read aloud. A checkbox appends an explicit control line marking the block
  as reference-only, and the risk check strips that line before testing for dialogue.

### Fixed

- **Resume was ignored by four different plan builders.** `prompt_batch`/gen, `fl2v`,
  `mixed` and `external_groups` each dropped the resume flag, so Resume silently restarted
  from segment 1 on those timeline shapes. A structural test now scans every builder for
  the resume fields, which is how the fourth instance was located.
- **Resume start point.** The engine decides where a resumed run begins; the dialog no
  longer computes it independently, and the authoritative cache check agrees with it.
- **Resume preview honesty.** The preview and its audio check had blind spots that could
  present a stale or partially-cached run as complete, and a stopped run could be left
  marked `running` indefinitely.
- **Resume was greyed out** whenever the manifest carried no done marks, even when
  caches were present and reusable.
- **CUDA out-of-memory was reported as a sampler incompatibility.** An OOM inside the
  external-sampler branch was wrapped into "the sampler does not support standard ComfyUI
  SAMPLER objects and MiniMax H3 NestedTensor inputs", sending you after the wrong
  problem. OOM now surfaces as OOM.
- **Idle requestAnimationFrame loop.** The Replace-windows timeline loop ran at display
  rate for as long as a node sat on the canvas, doing nothing when the node was idle. It
  now drops to a 250 ms poll when the node is neither selected nor in Replace mode, and
  returns to full rate immediately on hover. The frame handle is stored, so it can
  actually be cancelled — previously `cancelAnimationFrame` was a no-op and the loop only
  stopped by accident, via its own `isConnected` check.

### Changed

- Postprocess config schema **v10 → v11** (`audio_refine` section).

### Notes

- The Audio Room chain runs at output assembly, downstream of the segment audio cache,
  and processes model audio *before* the merge. Enabling or changing a room therefore
  invalidates no segment, context cache or finished render; only the **Per-segment** opt-in
  changes cache identity.
- Requires **SoX** on PATH (auto-detected; `sudo pacman -S sox` on Arch/CachyOS). A track
  that cannot be processed is left dry and named in the report rather than failing the run. SoX is not enough on its own: the `soundfile`
  Python package performs the temp-file round trip and is **not** a ComfyUI
dependency, so it is now declared in `requirements.txt`.

## v1.4.0 — 2026-09-10

- **Partial export on Stop.** Stopping assembles everything already completed into a
  usable partial video and records the run as `stopped`, leaving the resume manifest
  intact so Resume continues from the first unfinished segment.
- **Timeline undo / redo** (`Ctrl+Z` / `Ctrl+Shift+Z`, `Ctrl+Y`), bounded at 50 steps and
  recorded from the single commit funnel. Deliberately inert while typing in a text field.
- **Named presets** storing settings only (never segments, prompts, task type or seed),
  with server-side atomic storage and a loud failure on a corrupt index.
- **Multi-seed sweep** rendering N takes with hashed seeds, with `resume: false` forced so
  each take actually re-renders.
- **Pre-run tools**: Validate, Preview prompt, and a References cross-check.

## Earlier releases

See the [releases page](https://github.com/The5toryofthe5ecret5tar5ystem/ComfyUI-MiniMax-H3-Motion-Director/releases)
and git tags `v1.0.0` … `v1.4.0`.
