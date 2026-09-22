# MiniMax H3 Motion Director - engine rules for the prompt enhancer.
# Copyright (C) 2026 WakaSoft. GPL-3.0. See LICENSE.

"""Engine-correct prompt rules for the Motion Director's prompt enhancer.

The panel hands a user's segment prompt to a general-purpose language model and
asks for a better version. Without this module the model is told nothing about
what the Director does with that text, and ordinary "helpful" edits break the
shot: it copies the headshot's pose ("use this face"), turns a repeated `Scene:`
line into a running commentary of other segments, quotes a word outside `<d>` so
the video model reads the whole prompt aloud, or writes a beat as an absence.

The rules below are the distilled contract for a single Director segment prompt,
taken from the pack's own prompt-writing guide (`PROMPT_WRITING_GUIDE.md`) and the
validated segment-writer template (`QWEN_SEGMENT_WRITER_TEMPLATE_v3.md`). They are
sent as an extra system prompt when the panel's "H3 prompt rules" toggle is on.

Scope notes:
- The rules describe what to WRITE, not what to rebuild. An enhancement keeps the
  user's facts and structure; it sharpens and completes them.
- Replace windows (`rv2v`/`v2v` with a source video) get one extra block, because
  the discard sentence and wardrobe ownership are replace-only contracts.
"""

from __future__ import annotations

from .h3_prompt_recipes import recipe_block, resolve_recipe
from .prompt_enhance_templates import OUTPUT_LANGUAGE_EN, normalize_output_language

# Tasks that run against Director segments. Everything here is single-segment text.
H3_DIRECTOR_TASKS = frozenset({"default", "t2v", "i2v", "fl2v", "r2v", "v2v", "rv2v", "mixed", "r2flv"})

# Replace windows edit source footage, so `VIDEO N` is an input clip rather than a
# motion reference and the discard sentence becomes mandatory.
H3_REPLACE_TASKS = frozenset({"v2v", "rv2v"})

_TRUE_VALUES = frozenset({"1", "true", "yes", "on", "h3", "h3_rules"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off", "none", "disabled"})


def h3_rules_enabled(value) -> bool:
    """Normalize the panel's toggle (bool, or the strings a script may send)."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in _FALSE_VALUES:
        return False
    if text in _TRUE_VALUES:
        return True
    return False


_RULES_HEAD = """
You are improving ONE prompt for the MiniMax H3 "Motion Director". The text you
return is read by the video model as instructions about the shot, and never by a
person. Sharpen and complete what the user wrote - do not replace it with a story
of your own.
""".strip()

_RULES_OUTPUT = """
Output contract
- Return only the enhanced prompt text. No commentary, no explanation, no summary
  of your changes, no code fence around the whole answer, and no section heading
  the input did not already have.
- Preserve the input's structure and line order. Keep its `subject_definitions:`,
  `summary:` and `detailed_description:` blocks if present, and keep `Camera:`,
  `Scene:` and `Audio:` as the lines they already are. Never invent a section.
- Keep every fact the user stated: wardrobe, props, positions, room, other people,
  spoken lines, and the numbers they gave the reference images and frames. Add no
  new event, character, prop, garment or line of dialogue. Never remove a consent,
  safety or control line, and never reword the user's explicit instructions into
  something weaker.
- Write in the present tense. Use plain hyphens only - no em dashes and no en
  dashes. No narrator, no third person outside the dialogue tags.
- Replace every `<...>` placeholder with concrete text drawn from the input's own
  facts. If a placeholder has no fact behind it, delete the placeholder phrase
  instead of inventing one.
- Never write a phrase aimed at the reader ("in every segment", "as above", "the
  whole sequence", "repeat this for each shot"). The video model believes it and
  stages extra beats.
""".strip()

_RULES_CONSISTENCY = """
Consistency, and prose the model can actually play
- State each property once, and never contradict yourself. If a property is
  mentioned twice both mentions must agree: hair left loose in one sentence cannot
  be pulled back in the next, and she cannot wear two different outfits. Where the
  input is silent, leave the property alone - an invented detail is a contradiction
  waiting to happen.
- Cut anything the model cannot play. Mood and reviewer commentary - "she exudes a
  cheerful character", "giving the scene a lively vibe", "adding a playful energy",
  "she stands tall and elegant" - is not action. Replace it with a beat that moves
  her, or delete it. This is different from describing her look, which the input
  asked for: keep the look, drop the commentary about it.
- Keep the replacement mapping intact. A replace window's sentence must still say
  what is replaced (the source performer) and who overwrites it (the subject).
  Never fold the subject's description into the "replace X with Y" clause, and
  never phrase it so it reads as if the source performer stays.
- Refer to the reference images the way this pack does: the caller numbers its
  attachments `image0`, `image1`, ... for reference images and `frame0`, `frame1`,
  ... for source-video frames, and that numbering is what the prompt should use.
  Never write `@tag` aliases, and never invent a different numbering. Do not add
  `<Picture N>` / `<Video N>` tags the input did not already use - the engine adds
  them when the prompt needs them.
""".strip()

_RULES_SLOTS = """
Reference slots are bindings, not decoration
- `<Picture N>`, `<Video N>` and `<Audio N>` are the native reference slots. Never
  renumber, translate, drop or invent one, and never write the user's `@tag`
  aliases into the prompt body.
- `<Picture 1>` is facial identity only: face, skin tone, hair, expressions. Never
  copy its pose, framing or camera angle.
- `<Picture 2>` is body shape, proportions, clothing and fit only. Never reproduce
  a character sheet's grid, standing poses or layout.
- `<Picture 3>` is the location: layout, key props, lighting, atmosphere. Never any
  person's identity.
- `<Audio 1>` is a voice reference: timbre, tone and delivery only. Never its words.
- `<Video 1>` carries action, pose, position, timing, camera and framing only. Its
  own pixels and its performer are never reproduced.
- Define only the slots the input uses, and give each one its role plus what must
  not be taken from it.
""".strip()

_RULES_REPEAT = """
Lines that repeat must not carry events
- `Camera:`, `Scene:`, `Audio:` and any shared block are sent to the model with
  every segment, so every sentence in them must be true at the first and at the
  last second of every segment. If a line describes something that happens at a
  point in time, it is a beat and belongs in the `detailed_description:` of the one
  segment that performs it.
- `Scene:` holds the place, the light, who is present and the mood only. No action,
  no event, no story progression. If it could be written in the past or the future
  tense, it is not a scene fact.
- State the camera once, in `Camera:`. Never restate the framing in `Scene:` or in
  the action prose; a locked-off shot supplies no camera motion at all.
- `Audio:` carries the sound rules (talk control, silence, mic proximity, no male
  audio, room tone). Name a specific sound only in the one segment that performs
  it, inside that segment's action prose.
""".strip()

_RULES_BEATS = """
Beats
- Every beat must change state: say what moves and where it ends up. "She is
  kneeling" is a state and gives the model nothing to play; "she lowers herself
  onto her knees, then pulls the drawer open" is two beats with two named end
  states. Cut or convert anything that reads as "she continues doing X".
- Keep roughly one beat per 2 to 3 seconds of runtime (about 4 to 6 beats for a 10
  second segment, 6 to 8 for 15 seconds). Read the result back and ask what is
  physically different at the end, and which sentence covers the second half. No
  answer to the first is drift; no answer to the second is a loop.
- Carry state forward in words ("still wearing the same dress", "hands still
  tied"). State carries across segments; beats do not repeat.
""".strip()

_RULES_SPEECH = """
Speech
- A spoken line is exactly `She (S1) says <d>[English] <the line>.</d>`. Keep the
  literal `[English]` marker immediately after `<d>` and never translate or drop it.
- The `<d>` markers belong to real dialogue and nothing else. Never use one in a
  rule, in `summary:`, in `subject_definitions:` or in the action prose: a marker
  sitting in prose opens a spoken block that never closes, and the video model then
  reads the rest of the prompt aloud.
- Put no quoted words and no on-screen text anywhere outside a `<d>` block.
- A segment with no spoken line must state, as an unconditional fact, that she is
  completely silent: no speech, no words, no whispering, no vocal sound of any
  kind. Never write "she speaks only the lines she has" when she has none, and
  never leave the voice rule conditional or implicit. A voice reference
  (`<Audio 1>`) primes speech, so the silence rule matters more with one attached,
  not less.
- Dialogue consumes runtime at roughly 2 to 3 words per second. Keep lines short,
  place them where the action pauses, and spend the rest of the runtime on beats.
""".strip()

_RULES_FRAMING = """
Framing, negatives and settings
- One framing per scene. The viewer's body, hands and face are never visible. If a
  body position matters, name it in words and make every turn of it head-only
  ("turns only her head", "her body never turns around").
- There is no negative prompt. A "never" can only suppress a named artefact, so
  always write the positive action alongside it. Never write a whole beat as an
  absence: "she does not move" gives the model nothing to play.
- Room, task, reground and audio mode are Director timeline settings, not prompt
  text. Never write them into the prompt. The only valid room words are `dry`,
  `bedroom`, `bathroom`, `bar`, `office`, `car`, `hall`, `cathedral`, `outdoor`.
""".strip()

_RULES_REPLACE = """
This is a replace window: source footage is being edited so the identity changes
- The discard sentence is mandatory. Keep it intact if the input already has it,
  and ADD it if it does not, in this wording: the source footage's performer "is a
  DIFFERENT, unrelated woman and is fully discarded - never carry over her face,
  hair, skin, body or clothing; <Subject 1> overwrites her completely." This is a
  structural requirement of the replace task, not a new fact, so adding it never
  counts as inventing detail.
- Decide where the new identity comes from and say so, because it changes what the
  prompt may describe. When the input names a reference image as the source of her
  appearance (image0), describe her the way that reference image shows her - from
  the picture, not from assumption. When the input says the identity is carried by
  an attached character reference, do NOT describe her face, hair or body in prose
  at all: state that her identity arrives from that reference and leave the words
  out, or the prose and the reference will contradict each other.
- A replace window opens where the source window opens. If the input has an opening
  line, keep it; if it has none, use `Begin from the opening frame of this window
  and its established composition, then continue the action forward.` rather than
  inventing a different starting point.
- Preserve the input's own line structure. A window prompt that is written as
  labelled lines (roles, `Camera:`, `Scene:`, `Audio:`, `summary:`,
  `detailed_description:`) stays that way - never flatten a structured window into
  one paragraph. Keep an audio-policy line if the input has one.
- Write no other prose about the source performer. The discard line is the only
  mention allowed: H3 treats a video reference as content to reproduce, so an
  undefined performer leaks back in when the discard line is missing or weakened.
- Everything that must survive the edit has to be stated outright. Masking and
  anchor modes re-render the entire frame, so name each kept property - wardrobe,
  props, room features, the other people present - instead of leaving it implied.
- Wardrobe ownership is one decision, not both. If a reference image carries the
  outfit, write the wardrobe line to match it, or drop the line; if the text owns
  the outfit, describe the garment and keep the sentence that limits her to it.
""".strip()

_RULES_STRUCTURED = """
The calling task expects structured JSON
- Keep that exact output shape and put the improved prompt text into the same
  fields. Every rule above still applies to the text you write inside those fields.
""".strip()

# The full contract is ~9k characters, and with a recipe block attached it is ~14k.
# That is a lot of prefill for a small local model on partial offload (2-4 tok/s),
# and the tokens are re-read on every retry pass. Compact mode keeps the invariants
# that a live failure actually produced - invented events, contradicting properties,
# unplayable mood prose, beats that never change state, a `<d>` marker sitting in
# prose, a missing silence rule - and drops the explanatory examples, which is where
# most of the length lives. It is a trade, not an upgrade: the long form explains
# *why* each rule exists, and small models follow explained rules more reliably.
_RULES_COMPACT = """
Write ONE MiniMax H3 "Motion Director" segment prompt. The video model reads it,
never a person.

Keep what the user wrote
- Return only the improved prompt: no commentary, no code fence. Keep its facts,
  structure and line order, including `subject_definitions:`, `summary:`,
  `detailed_description:`, `Camera:`, `Scene:` and `Audio:`. Never invent a section.
- Add no event, character, prop, garment or dialogue line, and never weaken a
  consent, safety or control line. Fill `<...>` placeholders from the input's own
  facts, or delete the phrase - never invent one to fill it.
- Present tense. Plain hyphens only (no em or en dashes). Write nothing aimed at the
  reader ("in every segment", "repeat this for each shot") - the model stages it.

Do not contradict yourself
- State each property once; where the input is silent, stay silent. Hair, clothing
  and props must agree everywhere they are mentioned.
- Cut prose the model cannot play - "she exudes a cheerful character", "a lively
  vibe", "she stands tall and elegant". Replace it with a beat that moves her, or
  delete it. Keep her look if the input described it; drop the commentary about it.

References are bindings
- `<Picture N>`, `<Video N>`, `<Audio N>`: never renumber, translate, drop or invent
  one; keep the caller's `imageN` / `frameN` numbering and keep `@tags` out of the
  body. `<Picture 1>` = face, hair, skin only - never its pose, framing or lighting.
  `<Picture 2>` = body and clothing - never a sheet's grid. `<Picture 3>` = location,
  never a person. `<Audio 1>` = timbre, never words. `<Video 1>` = action, pose,
  timing and camera; its performer is never reproduced.
- `Camera:`, `Scene:` and `Audio:` repeat with every segment, so every sentence in
  them must be true at its first and its last second: no event, no progression, no
  restated framing. A specific sound belongs in the one segment that performs it.

Beats
- Every beat changes state: what moves, and where it ends. "She is kneeling" is
  nothing to play; "she lowers onto her knees and pulls the drawer open" is two
  beats. About one beat per 2-3 seconds (4-6 for 10s, 6-8 for 15s). Carry state in
  words ("still wearing the same dress", "hands still tied").

Speech
- A line is exactly `She (S1) says <d>[English] <the line>.</d>`; keep the literal
  `[English]`. `<d>` belongs to real dialogue and nowhere else - a marker in prose
  makes the video model read the rest aloud. No quoted words or on-screen text
  outside a `<d>` block. Dialogue runs 2-3 words per second, so keep lines short.
- A segment with no line must state as a fact that she is completely silent: no
  speech, no words, no vocal sound of any kind. Never leave the voice rule
  conditional or implied.

Framing
- One framing per scene, stated once in `Camera:`. The viewer's body, hands and face
  are never visible. Name a body position if it matters and make turns head-only.
- there is no negative prompt: never write a beat as an absence ("she does not
  move"); always give the positive action.
- Room, task, reground and audio mode are timeline settings, not prompt text.
""".strip()


def build_h3_enhance_rules(
    task_key: str,
    *,
    output_language: str = OUTPUT_LANGUAGE_EN,
    has_source: bool = False,
    structured: bool = False,
    recipe: str = "",
    replace: bool = False,
    audio_policy: str = "",
    compact: bool = False,
) -> str:
    """Return the rules block for one enhancement, or "" when it does not apply.

    `task_key` is the resolved Director task ("rv2v", "r2v", ...). The recipe picks
    the target shape (see `h3_prompt_recipes`): a replace window gets the discard
    sentence and role lines, a ref2va segment gets the full block, and so on. The
    replace-only rules are attached once - either by the recipe or by the fallback
    block - never twice.

    `compact` swaps the long contract for the condensed one. The recipe block is
    kept either way: it is the shape the caller asked for, and it is short.
    """
    key = str(task_key or "").strip().lower()
    if key not in H3_DIRECTOR_TASKS:
        return ""

    chosen = resolve_recipe(recipe, task_key=key, has_source=has_source, replace=replace)

    if compact:
        parts = [_RULES_COMPACT]
    else:
        parts = [_RULES_HEAD, _RULES_OUTPUT, _RULES_CONSISTENCY, _RULES_SLOTS]
        parts.extend([_RULES_REPEAT, _RULES_BEATS, _RULES_SPEECH, _RULES_FRAMING])
    if key in H3_REPLACE_TASKS and has_source:
        # The replace contract (discard sentence, identity ownership, window
        # opener) applies to every replace window, whatever shape it is written
        # in. The recipe below adds the shape, not a replacement for this.
        parts.append(_RULES_REPLACE)
        if audio_policy:
            # The panel knows the window's audio policy from the replace spec; without
            # this the model has to guess between keeping the source track (no <d>
            # lines) and generating the audio (the full cue block), and it guesses
            # wrong about half the time.
            from .h3_prompt_caption import AUDIO_LINES, normalize_audio_policy

            policy = normalize_audio_policy(audio_policy)
            parts.append(
                "Audio policy for this window (authoritative - do not choose another):\n"
                f"- The window's audio policy is `{policy}`: {AUDIO_LINES[policy]}\n"
                "- Write the `Audio:` line to match exactly that policy."
            )
    block = recipe_block(chosen)
    if block:
        parts.append(block)
    if structured:
        parts.append(_RULES_STRUCTURED)

    language = "Simplified Chinese" if normalize_output_language(output_language) == "zh" else "English"
    parts.append(
        f"- Write the enhanced prompt in {language}. Slot labels (`<Picture 1>`, "
        "`<Video 1>`, `<Audio 1>`), the `[English]` dialogue marker and the section "
        "headers stay exactly as they are."
    )
    return "\n\n".join(part for part in parts if part).strip()
