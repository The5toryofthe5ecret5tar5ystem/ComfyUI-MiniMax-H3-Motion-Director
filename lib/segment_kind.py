"""Row kinds on a Director timeline.

A Character Replace job is a list of rows. Historically every row was a *replace
window*: a masked edit of a range of the source video. A **generated row** is the
other kind - it has no source range at all and is rendered from its prompt and
references, which is what lets a replace chain continue past the end of the
footage (or break away from it anywhere in the middle).

Rows written before this existed carry no kind and stay replace windows, so no
project file needs migrating.

This module is deliberately dependency-free (dict in, string out) so the plan
builder, the executor and the frontend normalizer can all ask the same question
and never disagree about what a row is.
"""

from __future__ import annotations

from typing import Any

SEGMENT_KIND_REPLACE = "replace"
SEGMENT_KIND_GENERATE = "generate"

# Row kinds are authored by hand and by the UI, and older experiments used other
# spellings. Unknown values are treated as a replace window: the historic
# behaviour is the safe default, because a window with a bad kind still renders
# whereas a source-free row with a bad kind has nothing to render from.
_GENERATE_VALUES = frozenset(
    {
        "generate",
        "generated",
        "gen",
        "generated_segment",
        "generatedsegment",
        # The generated row renders as a source-free reference segment, so the
        # task names are accepted as kind aliases too.
        "ref2va",
        "r2v",
        "t2v",
    }
)
_REPLACE_VALUES = frozenset({"replace", "replace_window", "replacewindow", "window", "masked"})

# Keys the UI/JSON may carry the kind under.
_KIND_KEYS = (
    "kind",
    "segmentKind",
    "segment_kind",
    "rowKind",
    "row_kind",
    "segmentType",
    "segment_type",
)
# Boolean conveniences ({"generate": true}).
_GENERATE_FLAGS = ("generate", "generated", "isGenerated", "is_generated")

# A generated row cannot consume source pixels, so it must use one of H3's
# source-free tasks; r2v keeps the character references in play, which is what a
# replace job has attached.
GENERATED_SEGMENT_TASK = "r2v"


def segment_kind(raw: Any) -> str:
    """Kind of a timeline row. Anything unrecognised is a replace window."""
    if not isinstance(raw, dict):
        return SEGMENT_KIND_REPLACE
    for key in _KIND_KEYS:
        value = raw.get(key)
        if value is None:
            continue
        if isinstance(value, bool):
            if value:
                return SEGMENT_KIND_GENERATE
            continue
        text = str(value).strip().lower()
        if not text:
            continue
        if text in _GENERATE_VALUES:
            return SEGMENT_KIND_GENERATE
        if text in _REPLACE_VALUES:
            return SEGMENT_KIND_REPLACE
    for flag in _GENERATE_FLAGS:
        if raw.get(flag) is True:
            return SEGMENT_KIND_GENERATE
    return SEGMENT_KIND_REPLACE


def is_generated_segment(raw: Any) -> bool:
    """True when a row renders without source pixels."""
    return segment_kind(raw) == SEGMENT_KIND_GENERATE


def generated_row_length(raw: Any) -> int:
    """Un-snapped requested length of a generated row (0 when it has none)."""
    if not isinstance(raw, dict):
        return 0
    try:
        if raw.get("end") is not None and "end" in raw:
            length = int(raw["end"]) - int(raw.get("start") or 0)
        else:
            length = int(raw.get("length") if raw.get("length") is not None else raw.get("frameCount") or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, length)


__all__ = [
    "GENERATED_SEGMENT_TASK",
    "SEGMENT_KIND_GENERATE",
    "SEGMENT_KIND_REPLACE",
    "generated_row_length",
    "is_generated_segment",
    "segment_kind",
]
