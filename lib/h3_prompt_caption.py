# MiniMax H3 Motion Director - build a replace prompt from images.
# Copyright (C) 2026 WakaSoft. GPL-3.0. See LICENSE.

"""Build a replace-window prompt out of two narrow captions plus a template.

This is a port of the Character Remake workflow ("Masked Motion + QwenVL") that
handled character replacement reliably where prompt rewriting did not. The trick
there was not a better prompt: it was that a language model was never asked to
*write the structure*. Two small vision calls answered two narrow questions -
"what does this character look like" and "what happens in this source window" -
and a StringFormat template glued the answers into the section block.

Why that works better than rewriting:

* Every header, role line, retention rule and the discard sentence come from this
  module, not from the model. It cannot forget them, reorder them or invent a slot.
* Each call is a captioning task, which vision models are good at, instead of a
  13k-character instruction-following task, which smaller models are not.
* Each call sees exactly the images it should: identity comes from the reference
  images only, action from the source frames only. Neither can describe the other.

The remaining limitation, inherited from the original workflow: the action caption
reads the raw source frames, which still contain the previous performer. The
original pipeline fed a *composite* (the subject region inverted) so there was no
identity to describe. This module relies on the instruction instead, and says so.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .prompt_enhance_templates import OUTPUT_LANGUAGE_EN, normalize_output_language

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.lib")

# Replace windows fed by a source video, plus the reference-segment and source-edit
# tasks, which can ground their identity/scene/action lines in images too. Tasks with
# nothing to look at (t2v, i2v/fl2v as the panel sends them) keep the rewrite path.
CAPTION_RECIPES = frozenset({
    "character_replace",
    "character_replace_refmod",
    "ref2va",
    "source_edit",
    # i2v / fl2v supply fixed endpoint frames instead of reference slots. They used
    # to have nothing to look at because the panel never sent those frames; it does
    # now, and a caption is the only way the prose can agree with frame 0.
    "start_image",
    "first_last",
})
REPLACE_RECIPES = frozenset({"character_replace", "character_replace_refmod"})

# How much output each caption may produce. The instructions ask for one or two
# sentences (identity) and one paragraph (action), so this is generous headroom;
# the original workflow used the same 512.
IDENTITY_CAPTION_TOKENS = 512
ACTION_CAPTION_TOKENS = 512
# Two labelled lines share the budget, so this is deliberately tighter than the
# identity caption: a wardrobe line that rambles is worse than a short one.
CHARACTER_CAPTION_TOKENS = 320
# One paragraph of visible state; the same order of magnitude as the identity caption.
FRAME_CAPTION_TOKENS = 512
# A clue longer than this is a description, and the guide forbids one.
MAX_CLUE_WORDS = 6

IDENTITY_INSTRUCTION = """
Analyze this reference image for identity-preserving video generation.

Refer to the woman as <Subject 1>. Write one or two short sentences.
Include: subject type, overall proportions and silhouette, face shape, skin tone,
hair and defining facial features if visible, clothing, materials, colors,
accessories and distinctive markings, makeup if any, and any features that must
stay consistent across frames.

Do NOT describe the image background, camera angle, pose, lighting, composition
or action. Describe only the subject's stable appearance.

CRITICAL OUTPUT RULES: plain text only. No double-quote characters. No line breaks,
newlines or paragraph breaks; write a single paragraph. No markdown.
""".strip()

ACTION_INSTRUCTION = """
Analyze this video for reference-to-video generation. You are writing the
detailed_description of a video remake.

Write a concise single paragraph covering: the environment and background; camera
framing, angle and movement; lighting; and the actions being done over time.
Refer to the woman as <Subject 1>, and to any other visible person as <Subject 2>
only if visible.

Do NOT describe the subjects' appearance or clothing - another part of the prompt
carries that. Do NOT infer things that are not clearly visible; describe only what
actually happens, the rough position of things and the rough animations.

CRITICAL OUTPUT RULES: plain text only. No double-quote characters. No line breaks,
newlines or paragraph breaks; write a single paragraph. No markdown.
""".strip()

SCENE_INSTRUCTION = """
Analyze this reference image for scene continuity in video generation.

Write one short paragraph describing ONLY the location: the layout, the materials
and the key props, the lighting (its source, direction and quality) and the
atmosphere.

Do NOT describe any person - no identity, face, hair, body, clothing or pose. If a
person is visible, ignore them completely. Do NOT describe any action or event; a
still frame has none.

CRITICAL OUTPUT RULES: plain text only. No double-quote characters. No line breaks,
newlines or paragraph breaks; write a single paragraph. No markdown.
""".strip()

# A RefMod window is the one case where describing her is the WRONG thing to do: the
# mod's reference is appended after text encoding, so appearance prose cannot be
# grounded in it and only competes with it for the subject binding (guide 6.4). What
# the guide still asks for is a wardrobe line that MATCHES the mod and, optionally,
# one 2-4 word clue - both of which need to see the character.
REFMOD_CHARACTER_INSTRUCTION = """
Analyze this character reference for identity-preserving video generation.

Her face, hair, skin tone and build come from this reference and are NOT described
in the prompt, so do not write about them beyond the short clue below.

Answer with exactly two labelled lines and nothing else:

OUTFIT: the clothing the character wears, written so a video model can dress her in
it - name each garment with its cut, length, colour, fabric and fit. If the
reference shows no clear clothing, or the clothing differs between the images,
write exactly: none
CLUE: two to four words that identify her at a glance, for example "the auburn-
haired woman" or "the green-skinned elf". If nothing is distinctive, write exactly:
none

Do NOT describe the background, the camera, the pose, the lighting or any action.
Do NOT write a paragraph and do NOT describe her face in detail. Two lines only.

CRITICAL OUTPUT RULES: plain text only. No double-quote characters. No markdown. No
line breaks inside a line.
""".strip()

# i2v: the frame is the starting truth, so the caption describes the OPENING STATE.
START_FRAME_INSTRUCTION = """
Analyze this frame for start-image video generation. It is the exact first frame of
the shot, and the shot continues forward from it.

Refer to the woman as <Subject 1>. Write one short paragraph describing what this
frame establishes: who is in it and what she wears (garments, colours, materials),
the room or setting with its key props, the lighting (source, direction, quality),
the framing and the camera's angle - and the pose and position she is in at this
instant, named precisely enough that the movement can continue from it.

Do NOT describe anything that is not visible in the frame. Do NOT invent an action,
an event or a next moment; this is a still frame and a description of its state.

CRITICAL OUTPUT RULES: plain text only. No double-quote characters. No line breaks,
newlines or paragraph breaks; write a single paragraph. No markdown.
""".strip()

# fl2v: two fixed frames, so the caption describes the states and the change between
# them. The change is a property of the pair, which is what the model cannot infer
# from a written prompt alone.
FRAME_SPAN_INSTRUCTION = """
Analyze these two frames for first-and-last-frame video generation. The first image
is the START frame of the shot and the last image is its END frame; the motion
between them is the shot.

Refer to the woman as <Subject 1>. Write one short paragraph that states: the setting
and lighting shared by both frames, what she looks like and wears, the pose and
position she holds in the START frame, the pose and position she holds in the END
frame, and the change between them (what moved, where it ended up, whether the
camera moved too).

Do NOT invent an action beyond the change the two frames actually show, and do NOT
describe anything that is not visible in either frame.

CRITICAL OUTPUT RULES: plain text only. No double-quote characters. No line breaks,
newlines or paragraph breaks; write a single paragraph. No markdown.
""".strip()

# The window keeps the source track, the model generates it, or the window is
# silent. Stated as a fact the model cannot misread (the rewrite path had to guess
# this from the input, which is why captions mode is the reliable one).
AUDIO_LINES = {
    "source": (
        "the window keeps its original track exactly - no added lines, no added "
        "sounds, no regenerated speech; NO MALE AUDIO: never any male voice, male "
        "moan or male sound."
    ),
    "generate": (
        "the model generates this window's audio - her non-verbal sounds and the "
        "scene foley, named at the instant they happen, all CLOSE to the camera mic, "
        "warm room tone low beneath. TALK-CONTROL: she speaks ONLY the exact <d> "
        "lines this window carries; every other sound she makes is wordless. NO MALE "
        "AUDIO: the viewer makes no sound at all - no voice, no moan, no breath; "
        "never any male voice, male moan or male sound."
    ),
    "none": (
        "this window is silent - no speech, no added sounds, no room tone, no foley; "
        "NO MALE AUDIO: never any male voice, male moan or male sound."
    ),
}
DEFAULT_AUDIO_POLICY = "source"

_DISCARD_LINE = (
    "<Video 1> is this window's source footage: the sole source of the action, pose, "
    "position, timing, camera, framing and setting. Its performer is a DIFFERENT, "
    "unrelated woman and is fully discarded - never carry over her face, hair, skin, "
    "body or clothing; <Subject 1> overwrites her completely."
)
_CAMERA_LINE = (
    "Camera: exactly as <Video 1> - same framing, same angle, same movement; never "
    "re-shot or reframed."
)
_SCENE_LINE = (
    "Scene: the location, props and lighting exactly as <Video 1> has them, unchanged."
)
_SUMMARY_LINE = (
    "<Subject 1> replaces the source performer inside this window: same pose, same "
    "place, same motion, frame for frame - only she is redrawn, everything else stays "
    "as <Video 1>."
)
_CLOSING_LINE = (
    "The room, props, lighting, camera and audio stay exactly as <Video 1>. No second "
    "person. No on-screen text, subtitles or watermarks."
)

_PICTURE_LINES = (
    "<Picture 1> is the sole source of her face, hair and skin: facial identity, "
    "expressions, skin tone and hair. Static portrait - never import its background, "
    "framing, angle or lighting; face and hair data only.",
    "<Picture 2> is the sole source of her body: build, proportions and skin tone. "
    "Body data only - never import the sheet's grid, layout, standing poses or studio "
    "light.",
)

_REFMOD_STATIC_LINE = (
    "The character reference is static - it carries identity only: never import its "
    "background, framing, panel layout, lighting or standing pose. Action, camera and "
    "lighting come from <Video 1> alone."
)


def _refmod_subject_line(clue: str = "") -> str:
    """The RefMod subject line, optionally carrying the guide's short clue.

    Guide 6.4: "If the mod alone under-delivers, add a SHORT clue (2-4 words, e.g.
    'the auburn-haired woman') once and re-test - do not expand it into a full
    appearance paragraph." The clue is therefore one insertion point, never a second
    sentence, and the rest of the line keeps saying the reference owns her identity.
    """
    clue = " ".join(str(clue or "").split())
    if not clue:
        return (
            "<Subject 1> is the woman carried by the attached character reference: her "
            "face, hair, skin tone and build come from that reference and are not "
            "described in this text."
        )
    subject = (
        f"{clue} carried by the attached character reference"
        if clue.lower().startswith(("the ", "a ", "an "))
        else f"the woman carried by the attached character reference ({clue})"
    )
    return (
        f"<Subject 1> is {subject}. This clue is a short identifier only, not a "
        "description: her face, hair, skin tone and build come from that reference and "
        "are not described in this text."
    )


def normalize_audio_policy(value) -> str:
    text = str(value or "").strip().lower()
    return text if text in AUDIO_LINES else DEFAULT_AUDIO_POLICY


def _clean_caption(text: str) -> str:
    """One line, no stray quotes or markdown, first sentence(s) only."""
    body = " ".join(str(text or "").split())
    body = body.replace('"', "").replace("\u201c", "").replace("\u201d", "")
    for marker in ("```", "#", "**"):
        body = body.replace(marker, "")
    return body.strip()


def _language_note(output_language: str) -> str:
    if normalize_output_language(output_language) == "zh":
        return (
            "以简体中文书写身份与动作描述；槽位标签（`<Picture 1>`、`<Video 1>`、"
            "`<Audio 1>`）与 `[English]` 对话标记保持原样。"
        )
    return ""


def parse_character_caption(text: str) -> tuple[str, str]:
    """Split a RefMod character caption into ``(outfit, clue)``.

    The instruction asks for ``OUTFIT:`` and ``CLUE:`` lines, but a small model
    sometimes answers with prose instead. An unlabelled answer is not thrown away -
    it becomes the outfit line, because that is the line the guide says must match
    the reference. A clue is only ever taken from an explicit ``CLUE:`` line: guessing
    which half of a sentence is the clue is how invented detail gets in.
    """
    body = _clean_caption(text)
    if not body:
        return "", ""
    lowered = body.lower()
    outfit = clue = ""
    outfit_at = lowered.find("outfit:")
    clue_at = lowered.find("clue:")
    if outfit_at >= 0 or clue_at >= 0:
        if outfit_at >= 0:
            end = clue_at if clue_at > outfit_at else len(body)
            outfit = body[outfit_at + len("outfit:") : end].strip()
        if clue_at >= 0:
            clue = body[clue_at + len("clue:") :].strip()
    else:
        outfit = body
    if outfit.strip().lower().rstrip(".") in ("none", "n/a", "unknown"):
        outfit = ""
    if clue.strip().lower().rstrip(".") in ("none", "n/a", "unknown"):
        clue = ""
    # Trim a trailing sentence that is not about clothing before it becomes a
    # wardrobe line: the label already bounds it, but models add a closing remark.
    for stop in (" Do NOT", " Note:", " Remember"):
        index = outfit.find(stop)
        if index > 0:
            outfit = outfit[:index].strip()
    if len(clue.split()) > MAX_CLUE_WORDS:
        clue = ""
    return outfit.strip().strip("."), clue.strip().strip(".")


@dataclass
class CaptionResult:
    text: str
    identity: str = ""
    scene: str = ""
    action: str = ""
    character: str = ""
    skipped: list[str] = field(default_factory=list)


def build_replace_window_prompt(
    *,
    recipe: str,
    identity_caption: str = "",
    action_caption: str = "",
    character_caption: str = "",
    audio_policy: str = "source",
    picture_count: int = 0,
    output_language: str = OUTPUT_LANGUAGE_EN,
) -> CaptionResult:
    """Assemble the replace window block from the captions.

    `recipe` is the resolved recipe key ("character_replace" or
    "character_replace_refmod"). The RefMod variant deliberately drops the identity
    caption: the mod reaches the model after text encoding, so prose about her face
    and hair cannot be grounded in it and only fights the reference. What it does use
    is `character_caption` - the wardrobe line that must MATCH the mod, plus an
    optional short clue - because both are grounded in the mod's own images.
    """
    refmod = recipe == "character_replace_refmod"
    identity = "" if refmod else _clean_caption(identity_caption)
    action = _clean_caption(action_caption)
    outfit, clue = parse_character_caption(character_caption) if refmod else ("", "")
    skipped: list[str] = []
    if refmod:
        if not outfit:
            skipped.append("wardrobe")
        if not clue:
            skipped.append("clue")

    lines: list[str] = ["subject_definitions:"]
    if refmod:
        lines.append(_refmod_subject_line(clue))
        lines.append(_REFMOD_STATIC_LINE)
        if outfit:
            lines.append(
                f"wardrobe: she wears {outfit}. Dress her in this outfit only - never a "
                "different outfit than the character reference shows, and never the "
                "source performer's clothing."
            )
    else:
        lines.append(
            "<Subject 1> is the woman in the attached references: she is the new "
            "character who completely replaces the woman in the source video."
        )
        # Only name the picture slots the caller actually attaches.
        lines.extend(_PICTURE_LINES[: max(0, min(picture_count, len(_PICTURE_LINES)))])
        if identity:
            lines.append(f"Identity: {identity}")
    lines.append(_DISCARD_LINE)
    lines.append(_CAMERA_LINE)
    lines.append(_SCENE_LINE)
    lines.append(f"Audio: {AUDIO_LINES[normalize_audio_policy(audio_policy)]}")

    lines.extend(["", "summary:", _SUMMARY_LINE])

    body = [f"[Shot 1] Begin from the opening frame of this window. {action}"]
    if not refmod:
        body.append(
            "Only <Subject 1> is regenerated: her face, hair, skin and body come from "
            "the attached references, her outfit from the identity line."
        )
    else:
        tail = (
            "<Subject 1> is the woman from the attached character reference; she stays "
            "exactly where the source has her - same position, size in frame, body "
            "language and timing"
        )
        tail += ", and her outfit is the wardrobe line exactly." if outfit else "."
        body.append(tail)
    body.append(_CLOSING_LINE)

    lines.extend(["", "detailed_description:", " ".join(body)])
    note = _language_note(output_language)
    if note:
        lines.extend(["", note])

    return CaptionResult(
        text="\n".join(lines).strip(),
        identity=identity,
        action=action,
        character=character_caption if refmod else "",
        skipped=skipped,
    )


def _first_sentence(text: str, limit: int = 160) -> str:
    """A one-line summary taken from the user's own words (never invented)."""
    body = " ".join(str(text or "").split())
    for stop in (". ", "! ", "? "):
        index = body.find(stop)
        if 0 < index < limit:
            return body[: index + 1].strip()
    return body[:limit].strip()


_POV_CAMERA_LINE = (
    "Camera: the camera IS the viewer's eyes moving through the scene as he does. "
    "His body, hands and face are never visible; her contact with the viewer reaches "
    "toward and past the lens."
)
_POV_AUDIO_LINE = (
    "Audio: cue-by-cue and beat-timed - her non-verbal sounds and the scene foley, "
    "named at the instant they happen, all CLOSE to the camera mic, warm room tone low "
    "beneath. TALK-CONTROL: she speaks ONLY the exact <d> lines this segment carries; "
    "every other sound she makes is wordless. NO MALE AUDIO: the viewer makes no sound "
    "at all - no voice, no moan, no breath; never any male voice, male moan or male "
    "sound; the viewer stays completely silent."
)


def build_ref2va_prompt(
    *,
    identity_caption: str = "",
    scene_caption: str = "",
    action_text: str = "",
    picture_count: int = 0,
    output_language: str = OUTPUT_LANGUAGE_EN,
) -> CaptionResult:
    """Assemble the r2v segment block: images describe her and the room, the user's
    own prompt supplies the action.

    This is the same division of labour as the replace recipes. The role lines, the
    POV camera rule and the audio controls are code-owned; only the identity and the
    location come from the model, and only from images that actually show them. The
    action stays the user's text - it is the one part no image can supply, and
    rewriting it was what used to lose their intent.
    """
    identity = _clean_caption(identity_caption)
    scene = _clean_caption(scene_caption)
    action = " ".join(str(action_text or "").split())

    lines: list[str] = ["subject_definitions:"]
    lines.append("<Subject 1> is the woman this segment follows.")
    if picture_count >= 1:
        lines.append(_PICTURE_LINES[0])
    if picture_count >= 2:
        lines.append(_PICTURE_LINES[1])
    if identity:
        lines.append(f"Identity: {identity}")
    if scene:
        lines.append(
            "The location reference is the sole source of the room, its props and its "
            "lighting; layout and atmosphere only, never any person's identity."
        )
    lines.append(_POV_CAMERA_LINE)
    if scene:
        lines.append(f"Scene: {scene}")
    lines.append(_POV_AUDIO_LINE)

    lines.extend(["", "summary:"])
    lines.append(_first_sentence(action) or "<Subject 1> performs the actions below.")

    lines.extend(["", "detailed_description:"])
    opener = (
        "[Shot 1] Live-action cinematic static POV shot, the camera locked at face "
        "level. Begin from the opening frame and its established composition, pose and "
        "lighting, then continue the action forward."
    )
    lines.append(f"{opener} {action}".strip() if action else opener)
    note = _language_note(output_language)
    if note:
        lines.extend(["", note])

    return CaptionResult(
        text="\n".join(lines).strip(), identity=identity, scene=scene, action=action,
        skipped=[] if scene else ["scene"],
    )


def build_source_edit_prompt(
    *,
    action_caption: str = "",
    change_text: str = "",
    audio_policy: str = "source",
    output_language: str = OUTPUT_LANGUAGE_EN,
) -> CaptionResult:
    """Assemble a source-edit (v2v) block: the source supplies the action, the user's
    own prompt supplies the one thing that changes."""
    action = _clean_caption(action_caption)
    change = " ".join(str(change_text or "").split())

    lines: list[str] = [
        "subject_definitions:",
        "<Subject 1> is the woman in this window.",
        "<Video 1> is this window's source footage: the sole source of the action, pose, "
        "position, timing, camera, framing and setting. Everything about it stays as it "
        f"is except this: {change}",
        _CAMERA_LINE,
        _SCENE_LINE,
        f"Audio: {AUDIO_LINES[normalize_audio_policy(audio_policy)]}",
        "",
        "summary:",
        _first_sentence(change) or "One change to the source window.",
        "",
        "detailed_description:",
    ]
    detail = (
        "[Shot 1] Begin from the opening frame of this window. "
        + (f"{action} " if action else "")
        + f"The change this window performs: {change} Everything else stays exactly as "
        "<Video 1>: same people, same positions, same timing, same room, same camera. No "
        "on-screen text, subtitles or watermarks."
    )
    lines.append(_clean_caption(detail))
    note = _language_note(output_language)
    if note:
        lines.extend(["", note])

    return CaptionResult(text="\n".join(lines).strip(), action=action)


def build_start_image_prompt(
    *,
    frame_caption: str = "",
    action_text: str = "",
    output_language: str = OUTPUT_LANGUAGE_EN,
) -> CaptionResult:
    """Assemble an i2v segment: the frame supplies the opening state, the user's own
    prompt supplies the movement.

    The frame is the starting truth and the prose has to agree with it, which is the
    one thing a rewritten prompt cannot check. As in the other recipes the structure
    is code-owned and only the description of what is visible comes from the model;
    the action stays verbatim in the user's words.
    """
    frame = _clean_caption(frame_caption)
    action = " ".join(str(action_text or "").split())

    lines: list[str] = ["subject_definitions:"]
    subject = "<Subject 1> is the woman this segment follows."
    if frame:
        subject += f" Her appearance, wardrobe, pose and position come from the supplied first frame as it shows them: {frame}"
    else:
        subject += " Her appearance, wardrobe, pose and position come from the supplied first frame - describe her only as that frame shows her."
    lines.append(subject)
    lines.append(
        "Camera: the framing is the supplied frame's own; do not reframe. The viewer's "
        "body, hands and face are never visible."
    )
    lines.append(
        "Scene: the place, its props and its lighting are the supplied frame's own, "
        "unchanged."
    )
    lines.append(_POV_AUDIO_LINE)

    lines.extend(["", "summary:"])
    lines.append(_first_sentence(action) or "The movement this segment performs.")

    lines.extend(["", "detailed_description:"])
    opener = (
        "[Shot 1] Begin from the supplied first frame and its established composition, "
        "pose and lighting, then continue the action forward."
    )
    lines.append(f"{opener} {action}".strip() if action else opener)
    note = _language_note(output_language)
    if note:
        lines.extend(["", note])

    return CaptionResult(
        text="\n".join(lines).strip(), character=frame, action=action,
        skipped=[] if frame else ["frame"],
    )


def build_first_last_prompt(
    *,
    span_caption: str = "",
    motion_text: str = "",
    output_language: str = OUTPUT_LANGUAGE_EN,
) -> CaptionResult:
    """Assemble an fl2v segment: two fixed frames, and the motion between them.

    The pair is the only source of the transition, so the caption states both end
    states and what changes; the user's prompt supplies the intent and stays
    verbatim. Neither frame may be re-described as if it happened again.
    """
    span = _clean_caption(span_caption)
    motion = " ".join(str(motion_text or "").split())

    lines: list[str] = ["subject_definitions:"]
    subject = (
        "<Subject 1> is the woman this segment follows. Her appearance and wardrobe "
        "come from the two supplied frames as they show them."
    )
    if span:
        subject += f" The frames show: {span}"
    lines.append(subject)
    lines.append(
        "Camera: as the two frames have it; if they differ, the move between them is "
        "the move. Never reframe."
    )
    lines.append(
        "Scene: the place, its props and its lighting are the frames' own, unchanged."
    )
    lines.append(_POV_AUDIO_LINE)

    lines.extend(["", "summary:"])
    lines.append(_first_sentence(motion) or "The movement between the two frames.")

    lines.extend(["", "detailed_description:"])
    opener = (
        "[Shot 1] Begin from the supplied first frame, move through the motion below, "
        "and arrive exactly at the supplied last frame."
    )
    lines.append(f"{opener} {motion}".strip() if motion else opener)
    lines.append(
        "The two frames are the truth at both ends: never re-describe either one as an "
        "event that happens again, and never continue past the last frame."
    )
    note = _language_note(output_language)
    if note:
        lines.extend(["", note])

    return CaptionResult(
        text="\n".join(lines).strip(), character=span, action=motion,
        skipped=[] if span else ["frame"],
    )


def _assemble_for_recipe(
    recipe: str,
    *,
    captions: dict[str, str],
    user_prompt: str,
    audio_policy: str,
    picture_count: int,
    output_language: str,
) -> CaptionResult:
    if recipe in REPLACE_RECIPES:
        return build_replace_window_prompt(
            recipe=recipe,
            identity_caption=captions.get("identity", ""),
            action_caption=captions.get("action", ""),
            character_caption=captions.get("character", ""),
            audio_policy=audio_policy,
            picture_count=picture_count,
            output_language=output_language,
        )
    if recipe == "ref2va":
        return build_ref2va_prompt(
            identity_caption=captions.get("identity", ""),
            scene_caption=captions.get("scene", ""),
            action_text=user_prompt,
            picture_count=picture_count,
            output_language=output_language,
        )
    if recipe == "source_edit":
        return build_source_edit_prompt(
            action_caption=captions.get("action", ""),
            change_text=user_prompt,
            audio_policy=audio_policy,
            output_language=output_language,
        )
    if recipe == "start_image":
        return build_start_image_prompt(
            frame_caption=captions.get("start_frame", ""),
            action_text=user_prompt,
            output_language=output_language,
        )
    if recipe == "first_last":
        return build_first_last_prompt(
            span_caption=captions.get("frame_span", ""),
            motion_text=user_prompt,
            output_language=output_language,
        )
    raise ValueError(f"recipe '{recipe}' has no caption template")


def plan_captions(
    recipe: str,
    *,
    source_frames: int = 0,
    reference_images: int = 0,
    character_images: int = 0,
    frame_images: int = 0,
) -> list[str]:
    """Which captions this recipe needs, given what the request actually carries.

    The list is ordered and the caller runs them in that order. Each entry names
    both the question and (implicitly) the images it may see:

    ``identity``    her stable appearance, from the reference images
    ``character``   the RefMod character's outfit + short clue, from the mod or its
                    images (a RefMod window must NOT describe her face)
    ``scene``       the place, camera and lighting, from the reference images
    ``action``      what happens over time, from the source-video frames
    ``start_frame`` the visible state of the supplied first frame, for i2v
    ``frame_span``  both endpoint frames and the change between them, for fl2v
    """
    if recipe not in CAPTION_RECIPES:
        return []
    needed: list[str] = []
    if recipe == "start_image":
        return ["start_frame"] if frame_images > 0 else []
    if recipe == "first_last":
        # Two frames are the pair; one alone cannot describe the change, which is
        # the part no written prompt can supply.
        return ["frame_span"] if frame_images >= 2 else []
    if recipe == "character_replace_refmod":
        if character_images > 0:
            needed.append("character")
    elif reference_images > 0:
        needed.append("identity")
        if recipe == "ref2va":
            # r2v has no source video: the location lives in a reference image.
            needed.append("scene")
    if source_frames > 0 and recipe in ("character_replace", "character_replace_refmod", "source_edit"):
        needed.append("action")
    return needed


def build_from_images(
    *,
    recipe: str,
    url: str,
    model: str,
    api_format: str,
    user_prompt: str = "",
    openai_compat_mode: str = "",
    api_key: str = "",
    source_images: list[str] | None = None,
    reference_images: list[str] | None = None,
    character_images: list[str] | None = None,
    frame_images: list[str] | None = None,
    hide_performer: bool = False,
    audio_policy: str = DEFAULT_AUDIO_POLICY,
    output_language: str = OUTPUT_LANGUAGE_EN,
    unload_after: bool = False,
    timeout: int = 120,
) -> tuple[CaptionResult | None, str | None]:
    """Run the captions this recipe needs and assemble the prompt.

    Each caption sees only the images it should: ``identity`` and ``scene`` get the
    reference images, ``action`` gets the source frames, ``character`` gets the
    RefMod's own frames, and the frame captions get the segment's fixed endpoint
    frames. The action caption runs last so "unload the model afterwards" lands on
    the final request instead of making the second call reload the model.

    ``hide_performer`` inverts the subject region of the action frames first, so the
    caption cannot describe the performer being replaced (see `anonymize_frames`).
    """
    from .prompt_enhancer import enhance_prompt_sync

    sources = [img for img in (source_images or []) if img]
    refs = [img for img in (reference_images or []) if img]
    character = [img for img in (character_images or []) if img]
    frames = [img for img in (frame_images or []) if img]
    needed = plan_captions(
        recipe,
        source_frames=len(sources),
        reference_images=len(refs),
        character_images=len(character),
        frame_images=len(frames),
    )
    if not needed:
        if recipe == "character_replace_refmod":
            return None, (
                "This RefMod window needs the character's own frames: give the "
                "RefMod character a mod name or a path to its images, then caption "
                "mode can fill the wardrobe line and the short clue."
            )
        if recipe in ("start_image", "first_last"):
            need = "its first frame" if recipe == "start_image" else "both of its frames"
            return None, (
                f"This segment's recipe needs {need} to caption: the panel sends "
                "them with the request, so attach them to the segment first."
            )
        return None, (
            f"Recipe '{recipe}' has nothing to caption in this request "
            f"({len(sources)} source frame(s), {len(refs)} reference image(s) attached). "
            "Caption mode needs a replace, reference-segment or source-edit segment "
            "with images; a text-to-video segment has none."
        )

    def _caption(instruction: str, images: list[str], cap: int, unload: bool):
        return enhance_prompt_sync(
            task_type="default",
            user_prompt=instruction,
            url=url,
            model=model,
            api_format=api_format,
            openai_compat_mode=openai_compat_mode,
            api_key=api_key,
            images_b64=images,
            image_num=len(images),
            # The instruction IS the request: no task template, no engine rules.
            # A caption is a question about an image, not a prompt rewrite.
            custom_template="{user_prompt}",
            output_language=output_language,
            character_feature_enhance=False,
            h3_rules=False,
            max_tokens=cap,
            unload_after=unload,
            timeout=timeout,
        )

    # The action caption is the one that reads the source window, so it is the one
    # that can name the performer being replaced. Inverting the subject region first
    # removes the identity while keeping pose, silhouette and setting readable. This
    # has to happen BEFORE the plan table below captures the frame lists.
    performer_hidden: str = ""
    if hide_performer and sources:
        from .anonymize_frames import invert_subject_regions

        hidden, hide_info, hide_error = invert_subject_regions(sources, frames=len(sources))
        if hidden and hide_info.get("method") != "none":
            sources = hidden
            performer_hidden = "hidden"
            log.info(
                "Prompt enhance: action frames anonymised (%s over %s frame(s))",
                hide_info.get("method"),
                hide_info.get("frames"),
            )
        else:
            performer_hidden = "visible"
            if hide_error:
                log.warning("Prompt enhance: could not hide the performer: %s", hide_error)

    plans = {
        "identity": (IDENTITY_INSTRUCTION, refs, IDENTITY_CAPTION_TOKENS),
        "character": (REFMOD_CHARACTER_INSTRUCTION, character, CHARACTER_CAPTION_TOKENS),
        "scene": (SCENE_INSTRUCTION, refs, ACTION_CAPTION_TOKENS),
        "action": (ACTION_INSTRUCTION, sources, ACTION_CAPTION_TOKENS),
        "start_frame": (START_FRAME_INSTRUCTION, frames, FRAME_CAPTION_TOKENS),
        "frame_span": (FRAME_SPAN_INSTRUCTION, frames, FRAME_CAPTION_TOKENS),
    }

    captions: dict[str, str] = {}
    for index, kind in enumerate(needed):
        instruction, images, cap = plans[kind]
        is_last = index == len(needed) - 1
        text, err = _caption(instruction, images, cap, unload_after and is_last)
        if err:
            return None, f"{kind.capitalize()} caption failed: {err}"
        captions[kind] = text or ""

    if not any(value.strip() for value in captions.values()):
        return None, "Every caption came back empty."

    try:
        result = _assemble_for_recipe(
            recipe,
            captions=captions,
            user_prompt=user_prompt,
            audio_policy=audio_policy,
            picture_count=len(refs),
            output_language=output_language,
        )
    except ValueError as exc:
        return None, str(exc)
    # The caller reports these in the panel's note: whether the performer was hidden
    # is the one thing about this run the user cannot see in the output text.
    if performer_hidden == "visible":
        result.skipped.append("performer-visible")
    elif performer_hidden == "hidden":
        result.skipped.append("performer-hidden")
    return result, None

