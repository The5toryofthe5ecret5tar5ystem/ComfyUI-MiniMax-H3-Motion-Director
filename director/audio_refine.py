"""Plan-aware application of the audio room chain.

*Where* the chain runs is the whole design.  It is applied here, at output
assembly, for two reasons:

**Cache safety.**  Segment audio caches (``segment_cache.save_segment_audio_cache``)
store *dry* model audio, and the executor writes them while rendering - before
this module ever runs.  Because the chain is downstream of that cache, turning a
room on, changing its size, or giving one scene a different space never
invalidates a segment, a context cache, or a finished render.  That is why
``audio_refine`` stays out of the segment cache fingerprint by default.

**Per-scene spaces.**  A merged export builds one track out of many segments, so
a scene's own room has to be applied to that scene's audio *before* the merge.
Applying it after the merge could only ever produce a single space for the whole
clip, which defeats the point of a per-scene field.

Failures follow the house style used for the other optional post-processing
stages (see ``finalize_director_outputs``): a track that cannot be processed is
kept dry, the run continues, and the report says so.  It is never silent - the
whole failure mode being avoided is a broken toolchain that looks like success.
"""

from __future__ import annotations

import logging
from typing import Any

from .audio_effects import apply_audio_effects, chain_from_config
from .audio_refine_config import audio_refine_is_active

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.audio_refine")


def raw_segments(plan: Any) -> list:
    """The raw timeline segment dictionaries, or ``[]``."""
    raw = getattr(plan, "raw", None)
    if not isinstance(raw, dict):
        return []
    segments = raw.get("segments")
    return segments if isinstance(segments, list) else []


def scene_room_for(plan: Any, seg_index: Any) -> str:
    """Per-scene ``room`` for a segment index, or ``""`` when the scene sets none.

    Read from the raw timeline rather than from ``SegmentPlan`` on purpose: that
    dataclass is constructed at six separate sites, and a builder silently
    dropping a field is a failure mode this repository has already been bitten
    by - the ``resume`` flag was dropped by four different builders.
    """
    try:
        index = int(seg_index)
    except (TypeError, ValueError):
        return ""
    segments = raw_segments(plan)
    if index < 0 or index >= len(segments):
        return ""
    item = segments[index]
    if not isinstance(item, dict):
        return ""
    value = item.get("room") or item.get("roomPreset") or item.get("room_preset")
    return str(value or "").strip()


def segment_order_for(plan: Any, count: int) -> list[int | None]:
    """Map each output slot to its segment index.

    Mirrors the mapping ``audio_export`` already uses for per-segment output, so
    a partial (resume) run attributes each track to the right scene.
    """
    total = len(getattr(plan, "segments", None) or [])
    run_indices = getattr(plan, "run_indices", None)
    if run_indices is not None:
        order = sorted(int(i) for i in run_indices)
    else:
        order = list(range(total))
    return [order[i] if i < len(order) else None for i in range(int(count))]


def apply_plan_audio_refine(
    plan: Any,
    audios: list,
    *,
    config: dict[str, Any] | None,
    indices: list[int | None] | None = None,
) -> tuple[list, str]:
    """Apply the configured room to each track, per scene.

    Returns ``(audios, report_note)``.  ``report_note`` is empty when nothing
    was configured or nothing changed, and otherwise states plainly which rooms
    were applied and which tracks were left dry.
    """
    # ``not audios`` would raise on a tensor slot, and a non-sequence is not a
    # list of tracks to process in the first place: hand it straight back.
    if not isinstance(audios, (list, tuple)) or not len(audios):
        return audios, ""
    if not audio_refine_is_active(config):
        return audios, ""

    active = config or {}
    order = indices if indices is not None else segment_order_for(plan, len(audios))
    sox_path = str(active.get("sox_path") or "")

    processed: list = []
    applied = 0
    rooms: set[str] = set()
    failures: list[str] = []

    for slot, audio in enumerate(audios):
        seg_index = order[slot] if slot < len(order) else None
        chain = chain_from_config(active, room_override=scene_room_for(plan, seg_index))
        if chain is None or chain.is_noop:
            processed.append(audio)
            continue
        try:
            processed.append(apply_audio_effects(audio, chain, sox_path=sox_path))
        except Exception as exc:  # noqa: BLE001 - keep the render, report loudly
            label = seg_index if seg_index is not None else slot
            failures.append(f"{label}: {exc}")
            log.warning("Audio room skipped for segment %s: %s", label, exc)
            processed.append(audio)
            continue
        applied += 1
        rooms.add(scene_room_for(plan, seg_index) or str(active.get("room") or "custom"))

    note = ""
    if applied:
        note += (
            f"\n\nAudio room: {', '.join(sorted(rooms))} applied to "
            f"{applied} track(s)."
        )
    if failures:
        note += (
            f"\n\nAudio room: {len(failures)} track(s) left DRY - "
            f"{failures[0]}. Audio is unprocessed for those tracks."
        )
    return processed, note


__all__ = [
    "apply_plan_audio_refine",
    "raw_segments",
    "scene_room_for",
    "segment_order_for",
]
