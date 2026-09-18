# MiniMax H3 Motion Director - prompt recipes for the enhancer.
# Copyright (C) 2026 WakaSoft. GPL-3.0. See LICENSE.

"""Node-specific prompt recipes, distilled from the pack's prompt-writing guide.

The enhancer used to always wrap the user's text in MiniMax's *official* task
template. That template has one output contract - "editing instruction + detailed
description, one continuous paragraph" - and no idea what this node does with the
text, so a character-replace window came back as prose with no discard sentence, no
role lines and no window opener. A live session showed exactly that.

Recipes fix it by making the target shape explicit:

* **Auto** (default) derives the recipe from the node's task and whether the
  segment carries a source video, so nothing changes for users who never touch it.
* A named recipe replaces the official shape with the one the guide specifies for
  that job - the ref2va segment block, a replace window with `<Picture N>` refs, a
  replace window whose identity comes from a RefMod, and the simpler
  start-image / first-last / source-edit / text-only segments.

The recipe is *only* the shape. The engine contract (slot bindings, `<d>`
discipline, the invariant test, beats that change state) lives in
`h3_prompt_rules` and is always attached.

Source of truth for the text below: `docs/PROMPT_WRITING_GUIDE.md`, shipped with
this pack (sections cited per recipe).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Recipes that edit a source video and therefore carry the replace contract.
REPLACE_RECIPES = frozenset({"character_replace", "character_replace_refmod"})

_AUTO = "auto"
_OFFICIAL = "official"


@dataclass(frozen=True)
class Recipe:
    key: str
    label: str
    # Task keys this recipe is the automatic choice for. Empty = manual only.
    tasks: tuple[str, ...] = ()
    needs_source: bool = False
    # Summary shown in the panel tooltip.
    summary: str = ""
    block: str = ""

    @property
    def is_replace(self) -> bool:
        return self.key in REPLACE_RECIPES


_RECIPE_REF2VA = """
Shape the answer as this pack's r2v / ref2va segment block. Keep the section order.

subject_definitions:
<Subject 1> is <who she is in this scene, including any consent framing>.
<Picture 1> (headshot) is the sole source of her facial identity: her face, skin tone, hair and expressions. Static portrait - never copy its pose, framing or angle; use it for her face only.
<Picture 2> (full-body character sheet) is the sole source of her body shape, proportions, clothing and fit. Proportions and clothing ONLY - never reproduce the sheet's grid, standing poses or layout.
<Picture 3> (the location) is the sole source of its layout, key props and lighting. Layout and atmosphere only; never any person's identity.
<Audio 1> is her voice reference: her timbre, tone and delivery only, never its words.
Camera: the camera IS the viewer's eyes moving through the scene as he does, <path>. His body, hands and face are never visible; <how her contact reads on screen>.
Scene: <one paragraph that is permanently true: the place, the light, who is present and the mood. No events, no actions, no progression.>
Audio: cue-by-cue and beat-timed - <her non-verbal sounds and the scene foley>, named at the instant they happen, all CLOSE to the camera mic, warm room tone low beneath. TALK-CONTROL: she speaks ONLY the exact <d> lines this segment carries; every other sound she makes is wordless. NO MALE AUDIO: the viewer makes no sound at all - no voice, no moan, no breath; never any male voice, male moan or male sound; the viewer stays completely silent.

summary:
<one line - this segment only>.

detailed_description:
[Shot N] <opener>. <action prose: 4-6 named beats with end states>. <dialogue>. Audio: <beat-timed cues>. End with <what the next segment starts from>.

Rules for the r2v shape
- Define ONLY the reference slots whose files are attached; omit the others entirely.
- Give each slot its role and what must not be taken from it.
- Openers: the first shot opens "Live-action cinematic static POV shot, the camera locked at face level. Begin from the opening frame and its established composition, pose and lighting, then continue the action forward." Every later shot opens "Continue the POV directly from the previous shot's final frame, preserving its pose, camera and lighting."
- Give the first shot an explicit scope line ("This shot only: ... Nothing from later shots appears yet.") so later content does not leak in.
- Name any body position that matters and lock it ("REVERSE COWGIRL: ... her BACK to the camera"), and make every glance head-only: "turns only her head", "her body never turns around".
- Dialogue is `She (S1) says <d>[English] <the line>.</d>`; the literal `[English]` stays right after `<d>`.
""".strip()

_RECIPE_REPLACE_PICTURES = """
Shape the answer as this pack's character-replace window (guide 6.3): a normal r2v block
plus the replace lines below, for ONE window.

subject_definitions:
<Subject 1> is <one identity line: who she is in this window>.
<Picture 1> is the sole source of her face, hair and skin: facial identity, expressions, skin tone and hair. Static portrait - never import its background, framing, angle or lighting; face and hair data only.
<Picture 2> is the sole source of her body: build, proportions and skin tone. Body data only - never import the sheet's grid, layout, standing poses or studio light.
wardrobe: she wears <the outfit: name the garments and their cut, seams, fabric, colours and fit>. Dress her in this outfit only - never in clothing from the reference images and never in the source performer's clothing.
<Video 1> is this window's source footage: the sole source of the action, pose, position, timing, camera, framing and setting. Its performer is a DIFFERENT, unrelated woman and is fully discarded - never carry over her face, hair, skin, body or clothing; <Subject 1> overwrites her completely.
Camera: exactly as <Video 1> - same framing, same angle, same movement; never re-shot or reframed.
Scene: the location, props and lighting exactly as <Video 1> has them, unchanged.
Audio: <the audio policy line>

summary:
<Subject 1> replaces the source performer inside this window: same pose, same place, same motion, frame for frame - only she is redrawn, everything else stays as <Video 1>.

detailed_description:
[Shot 1] Begin from the opening frame of this window. <action prose: what SHE does, following the source window's action beat for beat>. Only <Subject 1> is regenerated: her face, hair, skin and body come from <Picture 1> and <Picture 2>, her outfit from the wardrobe line. She stays exactly where the source has her - same position, size in frame, body language and timing. The room, props, lighting, camera and audio stay exactly as <Video 1>. No second person. No on-screen text, subtitles or watermarks. End with <closing beat>.

Audio policy line
- Keeping the source track: `the window keeps its original track exactly - no added lines, no added sounds, no regenerated speech; NO MALE AUDIO: never any male voice, male moan or male sound.` Do not write `<d>` lines for the source performer.
- Generating audio: use the full cue block (cues + TALK-CONTROL + NO MALE AUDIO) with `<d>` lines for the new subject only.

Rules for a replace window
- The discard sentence is NOT optional: keep it if the input has it, and write it if
  the input does not - it is a structural requirement of the replace task, never
  invented detail. H3 treats a video reference as content to reproduce, so the
  source performer bleeds back into the render without it. This is the top failure
  mode of replace prompts.
- Never write prose about the source performer's face, hair, skin or clothing. The discard line is the only mention allowed.
- Keep only the reference lines for slots that are actually attached. Fill the wardrobe slot - it is the only place clothing is defined, and an unfilled placeholder leaves the model free to keep the source performer's outfit. If a reference carries the outfit, either match the wardrobe line to it or drop the line.
- Add one preservation line per other subject or object that must survive: "the man, the bed and the lamp stay exactly as `<Video 1>` has them, unchanged".
- `anchor` mode re-renders the whole frame, so every property you want kept must be stated; `inpaint` freezes the background for you but is weaker on identity.
- The window is standalone: it starts from the opening frame of this window, never from a previous shot's final frame.
""".strip()

_RECIPE_REPLACE_REFMOD = """
Shape the answer as this pack's character-replace window when the identity is carried by a
character-reference mod (guide 6.4). There is no `<Picture N>` slot for it, so the subject
line and the static-reference rule below REPLACE the picture lines.

subject_definitions:
<Subject 1> is the woman carried by the attached character reference: her face, hair, skin tone and build come from that reference and are not described in this text.
The character reference is static - it carries identity only: never import its background, framing, panel layout, lighting or standing pose. Action, camera and lighting come from <Video 1> alone.
wardrobe: she wears <the outfit: name the garments and their cut, seams, fabric, colours and fit>. Dress her in this outfit only - never in the character reference's clothing and never in the source performer's clothing.
<Video 1> is this window's source footage: the sole source of the action, pose, position, timing, camera, framing and setting. Its performer is a DIFFERENT, unrelated woman and is fully discarded - never carry over her face, hair, skin, body or clothing; <Subject 1> overwrites her completely.
Camera: exactly as <Video 1> - same framing, same angle, same movement; never re-shot or reframed.
Scene: the location, props and lighting exactly as <Video 1> has them, unchanged.
Audio: <the audio policy line>

summary:
<Subject 1> replaces the source performer inside this window: same pose, same place, same motion, frame for frame - only she is redrawn, everything else stays as <Video 1>.

detailed_description:
[Shot 1] Begin from the opening frame of this window. <action prose: what SHE does, following the source window's action beat for beat>. <Subject 1> is the woman from the attached character reference; she stays exactly where the source has her - same position, size in frame, body language and timing; her outfit is the wardrobe line exactly. The room, props, lighting, camera and audio stay exactly as <Video 1>. No second person. No on-screen text, subtitles or watermarks. End with <closing beat>.

Rules when identity comes from a mod
- Never describe her face, hair or body in prose: the mod is appended to the references AFTER text encoding, so the text encoder never sees it and prose about her appearance cannot be grounded in it. Keep the prose about the scene, the action and the wardrobe only.
- Do not invent a `<Picture N>` tag for the mod - there is none, and an unattached slot is flagged as a missing asset.
- Keep ONE described subject. Additional described people compete with the mod for the subject binding.
- The mod is a FULL visual reference: whatever its images show (clothing, room, lighting, pose) can reach the model, and no wording can filter it. Decide who owns the outfit and be consistent: if the mod owns it, write the wardrobe line to match what the mod shows, or drop the line; if the text owns it, keep the "dress her in this outfit only" half and accept that a conflicting mod outfit will fight it. Never leave the slot unfilled.
- The discard sentence is NOT optional: keep it in full if the input has it, and write
  it if the input does not - a structural requirement of the replace task.
""".strip()

_RECIPE_SOURCE_EDIT = """
Shape the answer as a source-edit (v2v) segment, guide-style block, for ONE window.

subject_definitions:
<Subject 1> is <who she is in this window>.
<Video 1> is this window's source footage: the sole source of the action, pose, position, timing, camera, framing and setting. Everything about it stays as it is except <the one thing being changed>.
Camera: exactly as <Video 1> - same framing, same angle, same movement; never re-shot or reframed.
Scene: the location, props and lighting exactly as <Video 1> has them, unchanged.
Audio: <the audio policy line - kept source track, or the cue block when the model generates it>

summary:
<one line - the single change this window performs>.

detailed_description:
[Shot 1] Begin from the opening frame of this window. <the edit, described as what changes and what the result looks like>. Everything else stays exactly as <Video 1>: same people, same positions, same timing, same room, same camera. No on-screen text, subtitles or watermarks. End with <closing beat>.

Rules for a source edit
- Name the one thing that changes, then state that everything else survives; the engine re-renders the frame, so unnamed properties are not guaranteed.
- Do not describe the edit as a replacement of a person unless that is genuinely the task (use a replace recipe for that).
- Keep the window's audio policy explicit - and if the source track is kept, write no `<d>` lines.
""".strip()

_RECIPE_START_IMAGE = """
Shape the answer as a start-image (i2v) segment.

subject_definitions:
<Subject 1> is <who she is in this scene>. Her appearance, wardrobe, pose and position come from the supplied first frame - describe her only as that frame shows her.
Camera: <how the camera behaves after the frame: locked, or the described move>.
Scene: <what is permanently true: place, light, who is present, mood. No events.>
Audio: <the cue block: named sounds, close to the camera mic, TALK-CONTROL, NO MALE AUDIO>

summary:
<one line - this segment only>.

detailed_description:
[Shot N] Begin from the supplied first frame and its established composition, pose and lighting, then continue the action forward. <action prose: beats with named end states>. <dialogue>. End with <what the next segment starts from>.

Rules for a start-image segment
- The frame is the starting truth: never contradict what it already shows, and never re-describe it as if it happens again.
- There are no reference slots in this task; do not write `<Picture N>` or invent one.
- Everything after frame 0 has to be written: the frame supplies the pose, the prose supplies the movement.
""".strip()

_RECIPE_FIRST_LAST = """
Shape the answer as a first-and-last-frame (fl2v) segment: the two supplied frames are
fixed constraints and the prose describes only the motion between them.

subject_definitions:
<Subject 1> is <who she is in this scene>. Her appearance and wardrobe come from the two supplied frames - describe her only as they show her.
Camera: <how the camera behaves between the frames>.
Scene: <what is permanently true: place, light, who is present, mood. No events.>
Audio: <the cue block: named sounds, close to the camera mic, TALK-CONTROL, NO MALE AUDIO>

summary:
<one line - the movement this segment performs>.

detailed_description:
[Shot N] Begin from the supplied first frame, move through <the motion>, and arrive exactly at the supplied last frame. <action prose: the beats that carry her from one to the other, with named end states>. <dialogue>.

Rules for a first-last segment
- The two frames are the truth at both ends: the prose describes the path between them and must not fight either one.
- Never describe the end state as a new event that happens after the last frame arrives.
- No reference slots exist in this task; do not write `<Picture N>`.
""".strip()

_RECIPE_TEXT_ONLY = """
Shape the answer as a text-only (t2v) segment: nothing is supplied, so the prose carries
the whole scene.

subject_definitions:
<Subject 1> is <who she is in this scene, described fully: look, wardrobe, build>.
Camera: <framing and how the camera behaves>.
Scene: <what is permanently true: place, light, who is present, mood. No events, no progression.>
Audio: <the cue block: named sounds, close to the camera mic, TALK-CONTROL, NO MALE AUDIO>

summary:
<one line - this segment only>.

detailed_description:
[Shot N] <opener>. <action prose: beats with named end states>. <dialogue>. End with <what the next segment starts from>.

Rules for a text-only segment
- Nothing is supplied: her look and the room have to be written in words, fully enough that the model does not have to guess.
- Still carry state forward in words ("still wearing the same dress") and keep repeated lines free of events.
- No reference slots exist in this task; do not write `<Picture N>`.
""".strip()

_RECIPE_OFFICIAL = """
Shape the answer as the calling task's own MiniMax template asks for it: an editing
instruction followed by a detailed description of the target video. Do not restructure the
input into labelled sections if it is not already written that way, and do not flatten
labelled lines if it is.
""".strip()

RECIPES: tuple[Recipe, ...] = (
    Recipe(
        key=_AUTO,
        label="Auto (from the task)",
        summary="Pick the recipe from the node's task and whether the segment has a source video.",
    ),
    Recipe(
        key="ref2va",
        label="Reference segment (r2v / ref2va)",
        tasks=("r2v",),
        summary="The full segment block: subject_definitions with slot roles, Camera, Scene, Audio, summary, detailed_description.",
        block=_RECIPE_REF2VA,
    ),
    Recipe(
        key="character_replace",
        label="Character replace window (reference images)",
        # mv2v is this pack's alias of v2v (`prompt_enhance_templates._TEMPLATE_ALIASES`
        # and the timeline's v2v prompt-only style both treat them as one task).
        tasks=("rv2v", "v2v", "mv2v"),
        needs_source=True,
        summary="Replace window whose identity comes from <Picture N> references: discard sentence, role lines, wardrobe, window opener.",
        block=_RECIPE_REPLACE_PICTURES,
    ),
    Recipe(
        key="character_replace_refmod",
        label="Character replace window (RefMod identity)",
        needs_source=True,
        summary="Replace window where the identity arrives from a character-reference mod: no appearance prose, no <Picture N> tag.",
        block=_RECIPE_REPLACE_REFMOD,
    ),
    Recipe(
        key="source_edit",
        label="Source edit (v2v)",
        summary="One change to the source window; everything else stated as unchanged.",
        block=_RECIPE_SOURCE_EDIT,
    ),
    Recipe(
        key="start_image",
        label="Start image to video (i2v)",
        tasks=("i2v",),
        summary="Begin from the supplied first frame and describe the action forward.",
        block=_RECIPE_START_IMAGE,
    ),
    Recipe(
        key="first_last",
        label="First + last frame (fl2v)",
        tasks=("fl2v",),
        summary="Both frames are fixed; describe only the motion between them.",
        block=_RECIPE_FIRST_LAST,
    ),
    Recipe(
        key="text_only",
        label="Text to video (t2v)",
        tasks=("t2v",),
        summary="Nothing is supplied, so the prose carries the whole scene.",
        block=_RECIPE_TEXT_ONLY,
    ),
    Recipe(
        key=_OFFICIAL,
        label="Official MiniMax template",
        summary="Leave the shape to MiniMax's own task template (the behaviour before recipes existed).",
        block=_RECIPE_OFFICIAL,
    ),
)

RECIPE_BY_KEY = {recipe.key: recipe for recipe in RECIPES}
RECIPE_KEYS = tuple(recipe.key for recipe in RECIPES)


def recipe_options() -> list[dict]:
    """The list the panel's dropdown is built from."""
    return [
        {
            "key": recipe.key,
            "label": recipe.label,
            "summary": recipe.summary,
            "tasks": list(recipe.tasks),
            "needs_source": recipe.needs_source,
        }
        for recipe in RECIPES
    ]


def normalize_recipe(value) -> str:
    text = str(value or "").strip().lower()
    return text if text in RECIPE_BY_KEY else ""


def resolve_recipe(
    requested,
    *,
    task_key: str = "",
    has_source: bool = False,
    replace: bool = False,
) -> str:
    """Return the recipe key to use; "" means "no recipe block".

    A named request always wins (that is the point of the dropdown). Auto picks by
    task, and a replace window with a source video beats the task's own recipe:
    rv2v is *both* the reference segment task and the replace task, and their shapes
    are different.
    """
    explicit = normalize_recipe(requested)
    if explicit and explicit != _AUTO:
        return explicit

    key = str(task_key or "").strip().lower()
    if replace and has_source and key in ("rv2v", "v2v", "mv2v"):
        return "character_replace"
    for recipe in RECIPES:
        if key and key in recipe.tasks:
            if recipe.needs_source and not has_source:
                continue
            return recipe.key
    return _OFFICIAL


def recipe_block(recipe_key: str) -> str:
    recipe = RECIPE_BY_KEY.get(recipe_key)
    return recipe.block if recipe else ""
