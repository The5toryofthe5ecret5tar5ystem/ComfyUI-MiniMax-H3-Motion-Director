# MiniMax H3 Motion Director - story to segments.
# Copyright (C) 2026 WakaSoft. GPL-3.0. See LICENSE.

"""A story brief becomes one paragraph per segment, and the arithmetic is ours.

The split is one model call: it returns a `world:` paragraph plus one paragraph per
segment, and those paragraphs then go through the normal enhance path - so what these
tests pin is the part that has to be exact regardless of what the model writes:

* the frame grid (a 7-second segment is 175 frames, not 168, and the number is the same
  one the panel computes),
* the beat rules the instruction states (one take per segment, every beat changes state,
  each segment ends where the next can start, the look is not re-described),
* and lenient parsing: models write "Segment 3 -", "**segment 3:**", numbered lists or
  no markers at all, and a usable plan has to come out of all of them - with a note when
  the answer is short, never a silent one.
"""

from __future__ import annotations

import pytest

from mmx_pkg.lib.h3_story import (
    MAX_SEGMENTS,
    build_story_request,
    frames_for,
    parse_story_plan,
    plan_story,
)


# --- the frame grid -----------------------------------------------------------


@pytest.mark.parametrize(
    ("seconds", "frames"),
    # The formula snaps UP to the next 17k+5, so 1 s is 39 frames (not 24) and 30 s is
    # 736 (not 719): the same numbers minimax_gen_timeline.js produces.
    [(5, 124), (7, 175), (10, 243), (15, 362), (30, 736), (1, 39), (60, 1450)],
)
def test_durations_land_on_the_frame_grid(seconds, frames):
    """The panel's durationToMiniMaxFrames() gives these same numbers."""
    assert frames_for(seconds) == frames
    assert frames % 17 == 5, "H3 renders 17k+5 frames"


def test_absurd_values_are_bounded_not_rejected():
    assert frames_for(0) == frames_for(1), "a zero duration is a one-second segment"
    assert frames_for(10_000) == frames_for(60), "capped, so a typo cannot queue a 40 minute render"
    assert frames_for("7") == 175, "the panel sends numbers as strings often enough"


def test_the_token_budget_grows_with_the_segment_count():
    _, one = build_story_request({"story": "x", "segments": 1, "seconds": 5})
    _, twelve = build_story_request({"story": "x", "segments": 12, "seconds": 5})
    assert twelve > one, "a plan that runs out of room comes back short"


# --- what the instruction has to say ------------------------------------------


def test_the_instruction_states_the_rules_that_make_a_plan_usable():
    text, _ = build_story_request({"story": "a girl finds an orc", "segments": 10, "seconds": 7})
    flat = " ".join(text.split())
    assert "exactly 10 segments" in flat
    assert "175 frames" in flat, "the segment length is stated in the frames H3 renders"
    assert "ONE continuous take per segment" in flat
    assert "every beat must change something visible" in flat
    assert "STARTS by continuing the pose and the motion the previous segment ended in" in flat
    assert "never in mid-air unless the fall itself is the point" in flat
    assert "Do NOT describe her face, hair or clothing inside a segment" in flat
    assert "a girl finds an orc" in flat, "the brief travels with the request"


# --- parsing ------------------------------------------------------------------


ANSWER = """world:
A dense pine forest at dawn, low mist, cold blue light; a young woman with a long braid
and a leather satchel.

segment 1:
She wakes on the platform of a tree house, sits up, and looks out over the canopy.
Camera holds. Audio: birds, creaking planks.

segment 2:
She stands, crosses to the railing and sees a shape far off between the trunks.
Camera holds, slight push in. Audio: a distant crack of timber.
"""


def test_the_world_block_and_the_beats_are_separated():
    world, beats, notes = parse_story_plan(ANSWER, 2)
    assert world.startswith("A dense pine forest")
    assert "braid" in world, "her look belongs to the world paragraph"
    assert beats[0].startswith("She wakes")
    assert beats[1].startswith("She stands")
    assert notes == []


def test_a_short_answer_is_padded_and_reported():
    world, beats, notes = parse_story_plan(ANSWER, 4)
    assert len(beats) == 4, "the timeline needs one entry per segment"
    assert beats[2] == "" and beats[3] == ""
    assert notes and "returned 2" in notes[0]


def test_a_long_answer_is_trimmed_and_reported():
    _world, beats, notes = parse_story_plan(ANSWER, 1)
    assert len(beats) == 1
    assert notes and "first 1" in notes[0]


def test_markers_survive_the_way_models_actually_write_them():
    messy = (
        "**World:** a snowy ridge at noon.\n\n"
        "**Segment 1** - she crouches and packs a snowball.\n\n"
        "Segment 2: she throws it and it bursts on a trunk.\n"
        "3. She laughs, once, and sits back.\n"
    )
    world, beats, notes = parse_story_plan(messy, 3)
    assert "snowy ridge" in world
    assert len(beats) == 3
    assert "snowball" in beats[0] and "bursts" in beats[1] and "laughs" in beats[2]
    assert notes == []


def test_no_markers_at_all_still_yields_paragraphs_and_says_so():
    prose = (
        "The clearing is bright and the grass is wet.\n\n"
        "She steps out of the treeline and stops.\n\n"
        "She kneels at the water and drinks.\n"
    )
    world, beats, notes = parse_story_plan(prose, 2)
    assert len(beats) == 2
    assert notes and "did not label" in notes[0]


def test_beats_are_flattened_and_bounded():
    long_body = "She runs. " * 400
    _world, beats, _notes = parse_story_plan(f"segment 1:\n{long_body}", 1)
    assert "\n" not in beats[0]
    assert len(beats[0]) <= 1200


def test_a_beat_never_carries_the_models_own_headings():
    text = "segment 1:\n**Beat 1:** she wakes. **Beat 2:** she stands."
    _world, beats, _notes = parse_story_plan(text, 1)
    assert "**" not in beats[0] and "#" not in beats[0]
    assert "she wakes" in beats[0]


# --- the call itself -----------------------------------------------------------


def test_an_empty_story_is_refused_before_any_model_call():
    plan, err = plan_story(story="   ", segments=3, seconds=7)
    assert plan is None
    assert "Write the story first" in err


def test_the_segment_count_and_length_are_clamped():
    _text, _tokens = build_story_request({"story": "x", "segments": 500, "seconds": 900})
    plan, err = plan_story(story="", segments=500, seconds=900)
    assert plan is None and err, "still refused, but without a 500-segment instruction"
    assert MAX_SEGMENTS == 60
