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
import re
from typing import Any

import folder_paths

from ..lib.segment_kind import is_generated_segment

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
_FRAME_MASK_RE = re.compile(r"^frame_(\d+)\.png$", re.IGNORECASE)

# MiniMax H3 has no fps input: the frame count *is* the duration, and the model's
# joint video+audio latent is defined at a fixed 24 fps (see ComfyUI's own H3
# nodes: "Duration snaps to the model's 17k+5 frame grid at 24 fps", and the
# ref2va reference video is documented as "Reference video frames at 24 fps").
H3_MODEL_FPS = 24.0


def _resolve_mask_dir(raw_dir: str) -> str | None:
    """Resolve a frames-mask directory the way ``load_mask_window`` does.

    Keeping the two in step is the point: this must agree with runtime, or the
    pre-flight verdict would disagree with what actually happens.
    """
    text = str(raw_dir or "").strip()
    if not text:
        return None
    root = os.path.expanduser(text)
    if not os.path.isabs(root):
        try:
            candidate = os.path.join(folder_paths.get_input_directory(), root)
            if os.path.isdir(candidate):
                root = candidate
        except Exception:
            pass
    return root if os.path.isdir(root) else None


def _mask_frame_indices(root: str) -> set:
    """Source-frame indices present in a ``frame_%08d.png`` mask folder."""
    found: set = set()
    try:
        for entry in os.listdir(root):
            match = _FRAME_MASK_RE.match(entry)
            if match:
                found.add(int(match.group(1)))
    except OSError:
        pass
    return found


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


def _check_frame_rate(timeline: dict, issues: list) -> None:
    """Warn when the project rate is not the 24 fps the model runs at.

    H3 takes frames, not seconds, so a project whose rate differs from 24 gets a
    picture that plays at the wrong speed: N frames of 30 fps footage are handed
    over as N model frames and come back stamped at 24, i.e. 25% slow - and the
    same rate then drives the segment audio trim and the merged export stamp, so
    the audio is short on every clip (and the merged file fast) as well.

    A warning rather than an error: the render is valid, it just does not play at
    the speed the footage does, and only the user knows whether that is intended.
    """
    raw = timeline.get("frameRate")
    if raw is None:
        raw = (timeline.get("video") or {}).get("fps")
    try:
        fps = float(raw)
    except (TypeError, ValueError):
        return
    if fps <= 0 or abs(fps - H3_MODEL_FPS) < 0.01:
        return
    ratio = fps / H3_MODEL_FPS
    _issue(
        issues,
        "warning",
        "frame_rate_not_24",
        f"Project frame rate is {fps:g} fps, but MiniMax H3 generates at a fixed "
        f"{H3_MODEL_FPS:g} fps - the frame count is the duration, and there is no fps "
        f"input. Frames are passed to the model as they are, so this project's picture "
        f"plays {ratio:.2f}x {'slow' if ratio > 1 else 'fast'} against the footage; "
        "segment audio is trimmed at this rate (so each clip ends in silence when it "
        f"is above {H3_MODEL_FPS:g}) and the merged export is stamped with it while the "
        "per-segment clips are written at 24. Convert the source - and any frame-keyed "
        "mask with it - to 24 fps, or set the project frame rate to 24.",
    )


def _static_checks(timeline: dict, task_key: str, issues: list) -> None:
    segments = timeline.get("segments") or []
    is_replace = bool(timeline.get("replaceMode"))
    _check_frame_rate(timeline, issues)
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
        if is_generated_segment(seg):
            # A generated row renders without source pixels, and the plan drops any
            # window block on it - so validating the mask it still points at would
            # block a run over a mask that is never loaded. Say it once instead.
            if isinstance(replace, dict) and replace.get("enabled"):
                _issue(issues, "warning", "replace_ignored_generated_row",
                       "This row is a generated segment but still carries a Character "
                       "Replace window; the row kind wins and the window is ignored.", i)
            continue
        if isinstance(replace, dict) and replace.get("enabled"):
            # Replace windows only run on the video timeline; on any other mode
            # the block is silently dropped, so say so instead.
            if task_key not in {"v2v", "rv2v"}:
                _issue(issues, "warning", "replace_ignored",
                       "Character Replace is enabled on this window, but the project is "
                       "not a video-edit mode (rv2v/v2v), so the window will be ignored.", i)
            mask = replace.get("mask") or {}
            kind = str(mask.get("kind") or "none").strip().lower()
            if kind == "sam3":
                if not (replace.get("sam_prompts") or []):
                    _issue(issues, "error", "replace_sam3_prompt",
                           "Replace window uses SAM3 masking but has no subject prompt.", i)
            elif kind == "frames":
                # A frames mask that cannot be loaded is a guaranteed fallback:
                # prepare_replace_window returns None and the window silently
                # renders as plain rv2v. Catch it here rather than after the run.
                raw_dir = str(mask.get("dir") or "").strip()
                if not raw_dir:
                    _issue(issues, "error", "replace_mask_dir_missing",
                           "Replace window uses a PNG mask folder but no folder is set, so "
                           "Character Replace cannot build its anchor and would silently "
                           "fall back to plain video-to-video. Set a mask folder, or switch "
                           "the mask source to 'sam3' to auto-mask this window instead.", i)
                else:
                    root = _resolve_mask_dir(raw_dir)
                    if root is None:
                        _issue(issues, "error", "replace_mask_dir_not_found",
                               f"Replace mask folder not found: {raw_dir}. Relative paths "
                               "resolve against ComfyUI's input directory.", i)
                    else:
                        have = _mask_frame_indices(root)
                        if not have:
                            _issue(issues, "error", "replace_mask_dir_empty",
                                   f"Replace mask folder has no frame_*.png files: {raw_dir}.", i)
                        else:
                            # The window must be covered end to end; a single
                            # missing frame drops the whole window to rv2v.
                            try:
                                start = int(seg.get("start") or 0)
                            except (TypeError, ValueError):
                                start = 0
                            try:
                                span = int(frames or 0)
                            except (TypeError, ValueError):
                                span = 0
                            try:
                                offset = int(mask.get("offset") or 0)
                            except (TypeError, ValueError):
                                offset = 0
                            if span > 0:
                                want = {start - offset + step for step in range(span)}
                                missing = want - have
                                if missing:
                                    _issue(issues, "warning", "replace_mask_gap",
                                           f"Replace mask folder covers {len(want) - len(missing)} "
                                           f"of {len(want)} frames in this window "
                                           f"({len(missing)} missing). The engine falls back to "
                                           "plain video-to-video for the whole window when any "
                                           "frame is absent.", i)
            else:
                _issue(issues, "error", "replace_mask_unsupported",
                       f"Replace window has no usable mask source (kind is {kind!r}). Set a "
                       "PNG mask folder, or 'sam3' with a subject prompt; otherwise Character "
                       "Replace falls back to plain video-to-video.", i)
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
