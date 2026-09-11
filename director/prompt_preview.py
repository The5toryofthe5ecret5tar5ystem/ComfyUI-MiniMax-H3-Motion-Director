# MiniMax H3 Motion Director - effective prompt preview.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Show what the engine will actually send to the model.

Rebuilds the plan the way an execution would, then applies the *same*
per-task prompt reinforcement the executor applies (``reinforce_r2v_prompt`` /
``reinforce_v2v_prompt`` / ``reinforce_rv2v_prompt`` / ``reinforce_fl2v_prompt``)
so the preview cannot drift from real behaviour.

Used by the frontend "Preview prompt" button through the
``/minimax/motion-director/preview_prompt`` route.
"""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.director")

PLAN_INPUT_KEYS = (
    "timeline_data",
    "task_type",
    "global_prompt",
    "total_frames",
    "frame_rate",
    "width",
    "height",
    "ref_max_size",
    "motion_context_enabled",
    "color_reanchor_enabled",
    "i2v_groups",
    "r2v_groups",
)


def _r2v_audio_indices(seg: Any) -> list[int]:
    """Mirror executor_core_legacy: semantic <Audio N> tags win over raw index."""
    tags = [
        value
        for (kind, _asset_id), value in (getattr(seg, "reference_tags", None) or {}).items()
        if kind == "audio"
    ]
    parsed = [
        int(tag.removeprefix("<Audio ").removesuffix(">")) - 1
        for tag in tags
        if isinstance(tag, str) and tag.startswith("<Audio ") and tag.endswith(">")
    ]
    if parsed:
        return parsed
    return [int(getattr(a, "index", 0)) for a in (getattr(seg, "ref_audios", None) or []) if a is not None]


def effective_prompt_for_segment(seg: Any) -> tuple[str, str]:
    """Return ``(base_prompt, effective_prompt)`` exactly as the engine builds it."""
    from .plan import (
        reinforce_r2v_prompt,
        reinforce_rv2v_prompt,
        reinforce_v2v_prompt,
    )

    base = getattr(seg, "prompt", "") or ""
    task_key = str(getattr(seg, "task_key", "") or "")

    if task_key == "r2v":
        ref_idxs = [int(getattr(r, "index", 0)) for r in (getattr(seg, "refs", None) or []) if r is not None]
        vid_idxs = [int(getattr(v, "index", 0)) for v in (getattr(seg, "ref_videos", None) or []) if v is not None]
        return base, reinforce_r2v_prompt(
            base, ref_indices=ref_idxs, video_indices=vid_idxs,
            audio_indices=_r2v_audio_indices(seg),
        )
    if task_key == "v2v":
        return base, reinforce_v2v_prompt(base)
    if task_key == "rv2v":
        ref_idxs = [int(getattr(r, "index", 0)) for r in (getattr(seg, "refs", None) or []) if r is not None]
        audio_idxs = [int(getattr(a, "index", 0)) for a in (getattr(seg, "ref_audios", None) or []) if a is not None]
        return base, reinforce_rv2v_prompt(base, ref_indices=ref_idxs, audio_indices=audio_idxs)
    if task_key == "fl2v":
        from .fl2v_timeline import reinforce_fl2v_prompt

        refs = getattr(seg, "refs", None) or []
        has_start = any(getattr(r, "index", None) == 0 for r in refs)
        has_end = any(getattr(r, "index", None) == 1 for r in refs)
        if not has_start and not has_end and refs:
            has_start = True
            has_end = len(refs) >= 2
        return base, reinforce_fl2v_prompt(
            base, has_end_frame=has_end, has_start_frame=has_start)
    return base, base


def preview_prompts(node_id: str | None, **plan_inputs: Any) -> dict[str, Any]:
    """Per-segment base + effective prompt (engine-accurate)."""
    timeline_data = plan_inputs.get("timeline_data")
    if not timeline_data or not str(timeline_data).strip():
        return {"error": "The Director timeline is empty."}
    try:
        timeline = json.loads(timeline_data)
    except json.JSONDecodeError as exc:
        return {"error": f"Invalid timeline_data JSON: {exc}"}

    try:
        from ..nodes.director_common import prepare_director_plan

        kwargs = {k: plan_inputs[k] for k in PLAN_INPUT_KEYS if k in plan_inputs}
        plan = prepare_director_plan(unique_id=node_id, **kwargs)
    except Exception as exc:
        log.warning("MiniMax H3 Motion Director preview: plan rebuild failed: %s", exc)
        return {"error": str(exc)}

    if plan is None:
        return {"error": "The plan builder returned no segments."}

    global_prompt = str((timeline.get("global") or {}).get("prompt") or "").strip()
    raw_segments = [s for s in (timeline.get("segments") or []) if isinstance(s, dict)]

    out: list[dict[str, Any]] = []
    for i, seg in enumerate(getattr(plan, "segments", []) or []):
        base, effective = effective_prompt_for_segment(seg)
        # Which side supplied the base text (segment-mode falls back to global).
        raw_prompt = ""
        ui_index = getattr(seg, "ui_index", None)
        lookup = int(ui_index) if isinstance(ui_index, int) else i
        if 0 <= lookup < len(raw_segments):
            raw_prompt = str(raw_segments[lookup].get("prompt") or "").strip()
        source = "segment" if raw_prompt else ("global" if global_prompt else "empty")
        added = effective[: len(effective) - len(base)] if base and effective.endswith(base) else ""
        out.append({
            "index": int(getattr(seg, "index", i)),
            "task_key": str(getattr(seg, "task_key", "") or ""),
            "frame_count": int(getattr(seg, "frame_count", 0) or 0),
            "source": source,
            "added": added.strip(),
            "base_prompt": base,
            "effective_prompt": effective,
        })

    return {"segments": out, "global_prompt": global_prompt}
