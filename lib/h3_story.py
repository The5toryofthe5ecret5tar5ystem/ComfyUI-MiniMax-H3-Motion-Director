# MiniMax H3 Motion Director - story to segments.
# Copyright (C) 2026 WakaSoft. GPL-3.0. See LICENSE.

"""Turn a story brief into one prompt per segment.

A multi-segment project is a story spread over N renders, and until now the user wrote
each segment's prompt by hand. One model call can do the spreading - but only if it is
asked the right question, because H3's rules are not a screenwriter's:

* **One continuous take per segment.** H3 renders one shot; there are no cuts inside a
  segment. A cut happens between segments, which is exactly why N segments can tell a
  long story.
* **Every beat must change state.** A beat where nothing changes is a wasted render.
* **Each segment ends where the next can start.** Chaining feeds the previous clip's
  final frames in as the anchor, so a segment must end on a holdable pose and the next
  must open by continuing it.
* **The look is not re-described per segment.** Identity comes from the reference
  images and the shared world paragraph; repeating it competes with the references.

So the splitter produces two things: a `world:` paragraph (place, light, her look once)
and one paragraph per segment. Those paragraphs then go through the normal enhancer
path, which is where the H3 contract, the recipe shape and the review list live.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from .prompt_enhance_templates import OUTPUT_LANGUAGE_EN, normalize_output_language

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.lib")

# MiniMax's frame grid, the same formula the panel uses (minimax_gen_timeline.js
# durationToMiniMaxFrames): n = max(5, round(seconds * fps)), snapped up to 17k+5.
FRAME_GRID = 17
GRID_OFFSET = 5
MIN_SECONDS = 1.0
MAX_SECONDS = 60.0
MAX_SEGMENTS = 60

# Per-segment prose is a paragraph, not an essay; the enhancer caps what it sends too.
MAX_BEAT_CHARS = 1200
# Room for N paragraphs plus the world block, with headroom: a model that runs out
# mid-list returns fewer segments than asked for, which is reported, not hidden.
TOKENS_PER_SEGMENT = 190
BASE_TOKENS = 320


def frames_for(seconds: float, fps: float = 24.0) -> int:
    """The frame count a requested duration becomes (17k+5, minimum 5)."""
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        value = MIN_SECONDS
    value = max(MIN_SECONDS, min(MAX_SECONDS, value))
    count = max(5, int(round(value * fps)))
    return count + ((GRID_OFFSET - (count % FRAME_GRID)) % FRAME_GRID)


_STORY_INSTRUCTION = """You are planning a {segments}-segment video story for MiniMax H3.

H3 renders ONE continuous take per segment: there are no cuts inside a segment, so the
camera either holds or moves within the take. A cut happens between segments.

Answer with exactly two parts, in this format and nothing else:

world:
<one short paragraph: the place, the time of day, the light, and the look of the main
character as the user described her. No action, no events.>

segment 1:
<the action of this segment only>
segment 2:
<the action of this segment only>
...and so on, up to segment {segments}.

Rules for the segments:
- There are exactly {segments} segments, numbered 1 to {segments}. Each one is a single
  take of about {seconds} seconds ({frames} frames).
- Each segment holds 2 to 4 beats, and every beat must change something visible: a
  position, a possession, a state, a distance closed. Never write a beat where nothing
  changes, and never repeat a beat.
- Segment 1 says where the story starts and the pose the character begins in. Every
  later segment STARTS by continuing the pose and the motion the previous segment ended
  in, and ENDS in a pose the next one can continue from - a stable state, never in
  mid-air unless the fall itself is the point.
- Spread the story's events across all {segments} segments in proportion: do not rush
  the ending into the last segment, and do not spend three segments on the first beat.
- State the camera for each segment (held, or moving and how) and the sound it needs
  (foley, and any spoken line as <d>...</d>).
- Do NOT describe her face, hair or clothing inside a segment: the world paragraph
  carries her look once.
- Do not invent characters, places or events the user did not ask for.
- Each segment paragraph: 60 to 110 words, plain text. No lists, no headings inside a
  paragraph, no double-quote characters, no markdown.

The user's story:
{story}"""

# The world block and the segment markers, as the instruction asks for them. Both are
# matched leniently: a model will write "Segment 3 -" or "**segment 3:**" or a plain
# numbered list sooner or later, and the plan is still perfectly usable.
_WORLD_LINE_RE = re.compile(
    r"^[\s>*#\-]*(?:world|setting|premise)[\s>*#\-]*:[ \t]*(.*)$", re.I
)
_SEGMENT_WORD_RE = re.compile(
    r"^[\s>*#\-]*(?:segment|shot|part)[\s>*#\-]*#?(\d{1,3})[\s>*#\-]*[:.\-)]?[ \t]*(.*)$",
    re.I,
)
_SEGMENT_NUMBER_RE = re.compile(r"^[\s>*#\-]*(\d{1,3})[\s>*#\-]*[:.\-)]?[ \t]+(.*)$")


@dataclass
class StoryPlan:
    """A split story: the shared world paragraph plus one paragraph per segment."""

    world: str
    beats: list[str]
    seconds: float
    frames: int
    notes: list[str] = field(default_factory=list)

    @property
    def segments(self) -> int:
        return len(self.beats)


def _flatten(text: str) -> str:
    body = " ".join(str(text or "").replace("\x00", "").split())
    body = body.replace('"', "").replace("\u201c", "").replace("\u201d", "")
    for marker in ("```", "**", "##"):
        body = body.replace(marker, "")
    return body.strip()


def _marker(line: str) -> tuple[int, str] | None:
    """``(index, inline text)`` when the line starts a segment, else None."""
    match = _SEGMENT_WORD_RE.match(line)
    if match:
        return int(match.group(1)), match.group(2)
    match = _SEGMENT_NUMBER_RE.match(line)
    if match:
        return int(match.group(1)), match.group(2)
    return None


def parse_story_plan(text: str, segments: int) -> tuple[str, list[str], list[str]]:
    """``(world, beats, notes)`` from whatever the model answered.

    Line-based and lenient on purpose: the format is a *request*, so numbered lists,
    bold headings, a missing world marker and a stray preamble all still produce a
    usable plan. What cannot be salvaged is reported in ``notes`` rather than hiding a
    short answer.
    """
    wanted = max(1, int(segments or 1))
    raw = str(text or "").replace("\r\n", "\n")
    notes: list[str] = []

    world_lines: list[str] = []
    blocks: list[list[str]] = []
    for line in raw.splitlines():
        if _WORLD_LINE_RE.match(line):
            # The marker itself is not part of the paragraph; anything above it was
            # the model thinking out loud about the task.
            world_lines = [_WORLD_LINE_RE.match(line).group(1)]
            continue
        if _marker(line) is not None:
            match = _marker(line)
            blocks.append([match[1]] if match[1].strip() else [])
            continue
        if blocks:
            blocks[-1].append(line)
        elif world_lines:
            world_lines.append(line)

    beats = [_flatten(" ".join(block)) for block in blocks]
    if not beats:
        # No markers at all: paragraphs are the best available reading of the answer.
        chunks = [_flatten(chunk) for chunk in re.split(r"\n\s*\n", raw)]
        beats = [chunk for chunk in chunks if chunk]
        if beats:
            notes.append(
                "The model did not label the parts; its paragraphs were used as segments."
            )

    world = _flatten(" ".join(world_lines))
    beats = [beat[:MAX_BEAT_CHARS] for beat in beats]
    if len(beats) < wanted:
        notes.append(
            f"The model returned {len(beats)} segment(s) instead of {wanted}; the "
            "remaining segment(s) were left empty - write them, or run it again."
        )
        beats += [""] * (wanted - len(beats))
    elif len(beats) > wanted:
        notes.append(f"The model returned {len(beats)} segments; the first {wanted} were used.")
        beats = beats[:wanted]
    return world, beats, notes


def build_story_request(plan: dict) -> tuple[str, int]:
    """The instruction to send, and the token budget for the answer."""
    segments = max(1, min(MAX_SEGMENTS, int(plan.get("segments") or 1)))
    seconds = max(MIN_SECONDS, min(MAX_SECONDS, float(plan.get("seconds") or 5.0)))
    frames = frames_for(seconds)
    instruction = _STORY_INSTRUCTION.format(
        segments=segments,
        seconds=f"{seconds:g}",
        frames=frames,
        story=str(plan.get("story") or "").strip(),
    )
    return instruction, BASE_TOKENS + TOKENS_PER_SEGMENT * segments


def plan_story(
    *,
    story: str,
    segments: int,
    seconds: float,
    task_key: str = "",
    url: str = "",
    model: str = "",
    api_format: str = "",
    openai_compat_mode: str = "",
    api_key: str = "",
    output_language: str = OUTPUT_LANGUAGE_EN,
    unload_after: bool = False,
    timeout: int = 240,
) -> tuple[StoryPlan | None, str | None]:
    """Ask the model for a segment plan. Returns ``(plan, error)``.

    One call: the per-segment prompts then go through the normal enhance path, which is
    where the H3 contract, the recipe shape and the review list live. Asking this call
    for finished blocks as well produced worse blocks, not fewer calls worth making.
    """
    from .prompt_enhancer import enhance_prompt_sync

    brief = str(story or "").strip()
    if not brief:
        return None, "Write the story first: a few sentences is enough."

    count = max(1, min(MAX_SEGMENTS, int(segments or 1)))
    seconds = max(MIN_SECONDS, min(MAX_SECONDS, float(seconds or 5.0)))
    instruction, max_tokens = build_story_request(
        {"story": brief, "segments": count, "seconds": seconds}
    )

    text, err = enhance_prompt_sync(
        task_type="default",
        user_prompt=instruction,
        url=url,
        model=model,
        api_format=api_format,
        openai_compat_mode=openai_compat_mode,
        api_key=api_key,
        custom_template="{user_prompt}",
        output_language=output_language,
        character_feature_enhance=False,
        # The story plan is not a prompt rewrite: the H3 contract is attached by the
        # per-segment enhancement that follows, once each segment has its own text.
        h3_rules=False,
        max_tokens=max_tokens,
        unload_after=unload_after,
        timeout=timeout,
    )
    if err:
        return None, f"Story planning failed: {err}"

    world, beats, notes = parse_story_plan(text or "", count)
    if not any(beat.strip() for beat in beats) and not world.strip():
        if normalize_output_language(output_language) == "zh":
            return None, "The model returned nothing usable for the story."
        return None, "The model returned nothing usable for the story."

    log.info(
        "Story plan: %d segment(s) requested, %d filled, %d note(s)",
        count,
        sum(1 for beat in beats if beat.strip()),
        len(notes),
    )
    return StoryPlan(world=world, beats=beats, seconds=seconds, frames=frames_for(seconds), notes=notes), None
