# MiniMax H3 Motion Director - pre-flight project validator.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Pre-flight project validation (no GPU work).

Rebuilds the Director plan exactly the way an execution would (via
``prepare_director_plan``) so engine-level errors are caught, and layers
static, human-friendly checks on top: H3 frame grid, empty prompts, missing
reference/source files, and Character Replace window sanity.

Used by the frontend "Validate" button through the
``/minimax/motion-director/validate`` route.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import folder_paths

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.director")

# Mirror the keys the frontend sends for resume_preview (same widget set).
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

_H3_GRID = 17


def _input_file_exists(subfolder: str, name: str) -> bool:
    name = str(name or "").strip()
    if not name:
        return True
    if name.startswith(("http://", "https://", "data:")):
        return True
    base = folder_paths.get_input_directory()
    candidate = os.path.join(base, str(subfolder or "").strip(), name)
    if os.path.isfile(candidate):
        return True
    # annotated paths may live outside input/ but still resolve
    try:
        resolved = folder_paths.get_annotated_filepath(name)
        if resolved and os.path.isfile(resolved):
            return True
    except Exception:
        pass
    return False


def _issue(issues: list, severity: str, code: str, message: str,
           segment: int | None = None) -> None:
    item: dict[str, Any] = {"severity": severity, "code": code, "message": message}
    if segment is not None:
        item["segment"] = segment
    issues.append(item)


def _raw_refs(timeline: dict) -> tuple[list[dict], list[dict], list[dict]]:
    r2v = timeline.get("r2vCommon") or {}
    pics: list[dict] = []
    audios: list[dict] = []
    videos: list[dict] = []
    for seg in timeline.get("segments") or []:
        if not isinstance(seg, dict):
            continue
        pics.extend(seg.get("refs") or [])
        audios.extend(seg.get("refAudios") or [])
        videos.extend(seg.get("refVideos") or [])
    pics.extend(r2v.get("refs") or [])
    audios.extend(r2v.get("refAudios") or [])
    videos.extend(r2v.get("refVideos") or [])
    return pics, audios, videos


def _static_checks(timeline: dict, task_key: str, issues: list) -> None:
    segments = timeline.get("segments") or []
    is_replace = bool(timeline.get("replaceMode"))
    if not segments:
        _issue(issues, "error", "no_segments", "The timeline has no segments.")
        return

    for i, seg in enumerate(segments):
        if not isinstance(seg, dict):
            continue
        prompt = str(seg.get("prompt") or "").strip()
        if not prompt:
            _issue(issues, "warning", "empty_prompt", "Segment has an empty prompt.", i)
        try:
            frames = int(seg.get("frameCount") or seg.get("length") or 0)
        except (TypeError, ValueError):
            frames = 0
        if not is_replace and frames > 0 and frames % _H3_GRID != 5:
            _issue(issues, "warning", "h3_grid",
                   f"Frame count {frames} is off the H3 grid (needs 17k+5).", i)
        replace = seg.get("replace") or {}
        if isinstance(replace, dict) and replace.get("enabled"):
            # Replace windows only run on the video timeline; on any other mode
            # the block is silently dropped, so say so instead.
            if task_key not in {"v2v", "rv2v"}:
                _issue(issues, "warning", "replace_ignored",
                       "Character Replace is enabled on this window, but the project is "
                       "not a video-edit mode (rv2v/v2v), so the window will be ignored.", i)
            mask = replace.get("mask") or {}
            if str(mask.get("kind") or "none") == "sam3" and not (replace.get("sam_prompts") or []):
                _issue(issues, "error", "replace_sam3_prompt",
                       "Replace window uses SAM3 masking but has no subject prompt.", i)
            if str(replace.get("audio_policy") or "source") not in ("source", "generate", "none"):
                _issue(issues, "error", "replace_audio_policy",
                       "Replace window audio_policy is invalid.", i)

    # reference files
    pics, audios, videos = _raw_refs(timeline)
    seen = set()
    for ref in pics:
        if not isinstance(ref, dict):
            continue
        name = str(ref.get("imageFile") or ref.get("fileName") or "").strip()
        sub = str(ref.get("subfolder") or "").strip()
        key = (sub, name)
        if name and key not in seen and not _input_file_exists(sub, name):
            _issue(issues, "warning", "missing_ref",
                   f"Reference image not found in input/: {name}")
        seen.add(key)
    for ref in audios:
        if not isinstance(ref, dict):
            continue
        name = str(ref.get("audioFile") or ref.get("fileName") or "").strip()
        sub = str(ref.get("subfolder") or "").strip()
        key = (sub, name)
        if name and key not in seen and not _input_file_exists(sub, name):
            _issue(issues, "warning", "missing_audio",
                   f"Reference audio not found in input/: {name}")
        seen.add(key)

    # source video for video-editing tasks
    if task_key in {"v2v", "rv2v"} or str(timeline.get("timelineMode") or "").lower() == "video":
        video = timeline.get("video") or {}
        video_file = str(video.get("videoFile") or "").strip()
        if not video_file and not (video.get("frames") or []):
            _issue(issues, "error", "no_source_video",
                   "This mode needs a source video, but none is set.")
        elif video_file and not _input_file_exists(
                str(video.get("subfolder") or ""), video_file):
            _issue(issues, "error", "missing_source_video",
                   f"Source video not found in input/: {video_file}")
        # A video timeline needs a known frame total; at 0 the plan silently
        # collapses every window to zero length.
        try:
            total = int(timeline.get("totalFrames") or 0)
        except (TypeError, ValueError):
            total = 0
        try:
            src = int(video.get("sourceFrameCount") or 0)
        except (TypeError, ValueError):
            src = 0
        map_len = len(video.get("frameMap") or [])
        if total <= 0 and src <= 0 and map_len <= 0:
            _issue(issues, "error", "unknown_source_frames",
                   "Source frame count is unknown (totalFrames is 0). Reload the "
                   "video so the editor derives it, then run again.")


def validate_project(node_id: str | None, **plan_inputs: Any) -> dict[str, Any]:
    """Validate a Director project. Returns ``{ok, issues, segment_total?}``.

    ``ok`` is False when any *error*-severity issue exists (warnings do not
    block). On an engine-level failure the plan-rebuild exception message is
    returned under ``error``.
    """
    issues: list[dict[str, Any]] = []

    timeline_data = plan_inputs.get("timeline_data")
    if not timeline_data or not str(timeline_data).strip():
        return {"ok": False,
                "issues": [{"severity": "error", "code": "empty_timeline",
                            "message": "The Director timeline is empty."}]}
    try:
        timeline = json.loads(timeline_data)
    except json.JSONDecodeError as exc:
        return {"ok": False,
                "issues": [{"severity": "error", "code": "bad_json",
                            "message": f"Invalid timeline_data JSON: {exc}"}]}

    from ..lib.task_prompts import resolve_task_key

    task_type = str(plan_inputs.get("task_type") or timeline.get("global", {}).get("taskType") or "")
    task_key = resolve_task_key(task_type) if task_type else ""

    _static_checks(timeline, task_key, issues)

    # Engine-level rebuild (catches no-source-video, mixed/external errors, etc.)
    try:
        from ..nodes.director_common import prepare_director_plan

        kwargs = {k: plan_inputs[k] for k in PLAN_INPUT_KEYS if k in plan_inputs}
        plan = prepare_director_plan(unique_id=node_id, **kwargs)
        segment_total = len(getattr(plan, "segments", []) or [])
    except Exception as exc:
        log.warning("MiniMax H3 Motion Director validate: plan rebuild failed: %s", exc)
        _issue(issues, "error", "plan_error", str(exc))
        return {"ok": False, "issues": issues}

    if segment_total == 0:
        _issue(issues, "error", "empty_plan", "The plan builder produced no segments.")

    declared = len([s for s in (timeline.get("segments") or []) if isinstance(s, dict)])
    if declared and segment_total and segment_total < declared:
        _issue(issues, "warning", "segments_collapsed",
               f"The plan produced {segment_total} of {declared} timeline segments "
               "(check that segment start and length fit inside the source frames).")

    ok = not any(i.get("severity") == "error" for i in issues)
    return {"ok": ok, "segment_total": segment_total, "issues": issues}
