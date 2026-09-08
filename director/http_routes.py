# Portions derived from ComfyUI_MiniMaxH3_Director
# Copyright AIMixer and contributors
# Originally licensed under Apache License 2.0
# Modified for MiniMax H3 Motion Director, 2026-08-09
# This derivative project is distributed under GPL-3.0.
# See NOTICE and LICENSES/Apache-2.0-AIMixer.txt.

"""HTTP routes for MiniMax H3 Motion Director."""

from __future__ import annotations

import logging
import os
import re
import shutil
import importlib.util

import folder_paths
from aiohttp import web
from server import PromptServer

from .face_refine_validation import compatible_sam_models
from .material_library_routes import register_material_library_routes
from .video_export import (
    FINAL_VIDEO_REGISTRY,
    FinalVideoUnavailable,
    StaleFinalVideoRun,
    video_save_capabilities,
)
from . import resume_state

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.director")

CHUNK_ROOT = os.path.join(folder_paths.get_temp_directory(), "minimax_upload_chunks")
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._\-()\u4e00-\u9fff]+")
_ROUTES_REGISTERED = False


def _safe_basename(name: str) -> str:
    base = os.path.basename(str(name or "video.mp4").replace("\\", "/"))
    base = _SAFE_NAME.sub("_", base).strip("._")
    return base or "video.mp4"


async def minimax_upload_video_chunk(request):
    try:
        post = await request.post()
    except Exception as exc:
        return web.Response(status=400, text=f"Invalid upload: {exc}")

    upload_id = str(post.get("upload_id") or "").strip()
    filename = _safe_basename(post.get("filename"))
    chunk_field = post.get("chunk")
    if not upload_id or chunk_field is None:
        return web.Response(status=400, text="Missing upload_id or chunk.")

    if ".." in upload_id or "/" in upload_id or "\\" in upload_id:
        return web.Response(status=400, text="Invalid upload_id.")

    try:
        chunk_index = int(post.get("chunk_index", 0))
        total_chunks = int(post.get("total_chunks", 1))
    except (TypeError, ValueError):
        return web.Response(status=400, text="Invalid chunk index.")

    if total_chunks < 1 or chunk_index < 0 or chunk_index >= total_chunks:
        return web.Response(status=400, text="Chunk index out of range.")

    session_dir = os.path.join(CHUNK_ROOT, upload_id)
    os.makedirs(session_dir, exist_ok=True)
    part_path = os.path.join(session_dir, f"{chunk_index:06d}.part")

    with open(part_path, "wb") as out:
        while True:
            block = chunk_field.file.read(1024 * 1024)
            if not block:
                break
            out.write(block)

    if chunk_index + 1 < total_chunks:
        return web.json_response({"status": "ok", "chunk_index": chunk_index})

    input_dir = folder_paths.get_input_directory()
    out_path = os.path.join(input_dir, filename)
    if os.path.exists(out_path):
        stem, ext = os.path.splitext(filename)
        for n in range(1, 1000):
            candidate = f"{stem}_{n}{ext}"
            candidate_path = os.path.join(input_dir, candidate)
            if not os.path.exists(candidate_path):
                out_path = candidate_path
                filename = candidate
                break

    with open(out_path, "wb") as out:
        for i in range(total_chunks):
            part = os.path.join(session_dir, f"{i:06d}.part")
            if not os.path.isfile(part):
                shutil.rmtree(session_dir, ignore_errors=True)
                return web.Response(status=400, text=f"Missing chunk {i}.")
            with open(part, "rb") as src:
                shutil.copyfileobj(src, out)

    shutil.rmtree(session_dir, ignore_errors=True)
    log.info("MiniMax H3 Motion Director uploaded video to input/: %s", filename)
    return web.json_response({"name": filename, "subfolder": "", "type": "input"})


async def minimax_probe_video(request):
    try:
        if request.can_read_body and request.content_type == "application/json":
            body = await request.json()
        else:
            body = dict(request.query)
    except Exception as exc:
        return web.Response(status=400, text=f"Invalid request: {exc}")

    video_file = str(body.get("videoFile") or body.get("video_file") or "").strip()
    if not video_file:
        return web.Response(status=400, text="Missing videoFile.")

    from ..lib.video_io import probe_video_clip

    clip = {
        "videoFile": video_file,
        "fileName": os.path.basename(video_file),
        "subfolder": str(body.get("subfolder") or "").strip(),
        "type": str(body.get("type") or "input").strip() or "input",
    }
    try:
        info = probe_video_clip(clip)
    except Exception as exc:
        log.warning("MiniMax H3 Motion Director video probe failed: %s", exc)
        return web.Response(status=400, text=str(exc))
    return web.json_response(info)


async def minimax_detect_shots(request):
    """Detect shot boundaries with PySceneDetect; return logical cut frames."""
    try:
        body = await request.json()
    except Exception as exc:
        return web.Response(status=400, text=f"Invalid JSON: {exc}")

    from ..lib.shot_detect import (
        detect_timeline_shot_cuts,
        scenedetect_available,
        scenedetect_install_hint,
    )

    if not scenedetect_available():
        return web.Response(
            status=400,
            text=(
                "PySceneDetect is not installed in ComfyUI's Python "
                f"({__import__('sys').executable}). "
                f"Run: {scenedetect_install_hint()}"
            ),
        )

    try:
        frame_rate = float(body.get("frameRate") or body.get("frame_rate") or 24)
    except (TypeError, ValueError):
        frame_rate = 24.0
    try:
        total_frames = int(body.get("totalFrames") or body.get("total_frames") or 0)
    except (TypeError, ValueError):
        return web.Response(status=400, text="Invalid totalFrames.")

    sensitivity = str(body.get("sensitivity") or "medium").strip().lower()
    try:
        min_shot_frames = int(body.get("minShotFrames") or body.get("min_shot_frames") or 12)
    except (TypeError, ValueError):
        min_shot_frames = 12

    clips_in = body.get("clips")
    clips: list[dict] = []
    if isinstance(clips_in, list) and clips_in:
        for item in clips_in:
            if not isinstance(item, dict):
                continue
            video_file = str(item.get("videoFile") or item.get("video_file") or "").strip()
            if not video_file:
                continue
            clips.append(
                {
                    "videoFile": video_file,
                    "fileName": os.path.basename(video_file),
                    "subfolder": str(item.get("subfolder") or "").strip(),
                    "type": str(item.get("type") or "input").strip() or "input",
                    "logicalStart": item.get("logicalStart", item.get("logical_start", 0)),
                    "logicalEnd": item.get("logicalEnd", item.get("logical_end", total_frames)),
                    "nativeFps": item.get("nativeFps", item.get("native_fps")),
                }
            )
    else:
        video_file = str(body.get("videoFile") or body.get("video_file") or "").strip()
        if not video_file:
            return web.Response(status=400, text="Missing clips[] or videoFile.")
        clips.append(
            {
                "videoFile": video_file,
                "fileName": os.path.basename(video_file),
                "subfolder": str(body.get("subfolder") or "").strip(),
                "type": str(body.get("type") or "input").strip() or "input",
                "logicalStart": 0,
                "logicalEnd": total_frames,
                "nativeFps": body.get("nativeFps", body.get("native_fps")),
            }
        )

    if total_frames <= 0:
        return web.Response(status=400, text="totalFrames must be > 0.")

    try:
        result = detect_timeline_shot_cuts(
            clips,
            frame_rate=frame_rate,
            total_frames=total_frames,
            sensitivity=sensitivity,
            min_shot_frames=min_shot_frames,
        )
    except ImportError as exc:
        return web.Response(status=400, text=str(exc))
    except Exception as exc:
        log.warning("MiniMax H3 Motion Director shot detect failed: %s", exc)
        return web.Response(status=400, text=str(exc))

    return web.json_response(result)


def _register_route(routes, method: str, path: str, handler) -> None:
    if hasattr(routes, "add_route"):
        routes.add_route(method, path, handler)
    elif method == "POST" and hasattr(routes, "post"):
        routes.post(path)(handler)
    elif method == "GET" and hasattr(routes, "get"):
        routes.get(path)(handler)
    else:
        raise AttributeError("Unsupported ComfyUI route table API")


async def minimax_postprocess_capabilities(_request):
    """Lazy dependency/model discovery for modal selectors only."""
    def filenames(*categories):
        result = []
        for category in categories:
            try:
                result.extend(folder_paths.get_filename_list(category) or [])
            except Exception:
                continue
        return sorted(dict.fromkeys(str(value) for value in result))

    return web.json_response({
        "diffusion_models": filenames("diffusion_models"),
        "upscale_models": filenames("upscale_models"),
        "latent_upscale_models": filenames("latent_upscale_models"),
        "face_detectors": filenames("ultralytics_bbox", "ultralytics"),
        "sam_models": compatible_sam_models(),
        "sam_model_folder": os.path.join(folder_paths.models_dir, "sams"),
        "dependencies": {
            "nvidia_rtx_vsr": importlib.util.find_spec("nvvfx") is not None,
            "ultralytics": importlib.util.find_spec("ultralytics") is not None,
            "insightface": importlib.util.find_spec("insightface") is not None,
            "sam": importlib.util.find_spec("ultralytics") is not None,
        },
        "video_save": video_save_capabilities(),
    })


async def minimax_save_final_video(request):
    try:
        body = await request.json()
    except Exception as exc:
        return web.json_response({"ok": False, "error": f"Invalid JSON: {exc}"}, status=400)
    node_id = str(body.get("node_id") or "").strip()
    run_id = str(body.get("run_id") or "").strip()
    if not node_id or not run_id:
        return web.json_response({"ok": False, "error": "Missing node_id or run_id"}, status=400)
    try:
        result = FINAL_VIDEO_REGISTRY.save(
            node_id,
            run_id,
            body.get("save") or body,
            segment_range=body.get("segment_range"),
        )
        return web.json_response(result)
    except StaleFinalVideoRun as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=409)
    except FinalVideoUnavailable as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=404)
    except ValueError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)
    except Exception as exc:
        log.exception("MiniMax H3 Motion Director Final Result save failed")
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def minimax_release_final_video(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    node_id = str(body.get("node_id") or "").strip()
    if node_id:
        FINAL_VIDEO_REGISTRY.release(node_id)
    return web.json_response({"ok": True})


async def minimax_resume_status(request):
    """Return the run manifest (done segments / resume point) for a node."""
    node_id = str(request.query.get("node_id") or request.query.get("nodeId") or "").strip()
    return web.json_response(resume_state.resume_status(node_id or None))


async def minimax_resume_preview(request):
    """Cache status for the Resume popup.

    GET: lightweight manifest + cached-segment summaries (no plan rebuild).
    POST: authoritative per-segment hit/stale/missing analysis by rebuilding
    the plan from the node's current inputs (mirrors the engine exactly).
    """
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        node_id = str(body.get("node_id") or "").strip()
        if not node_id:
            return web.json_response({"error": "no node id"})
        from ..nodes.director_common import analyze_resume_cache

        keys = (
            "timeline_data", "task_type", "global_prompt", "total_frames",
            "frame_rate", "width", "height", "ref_max_size",
            "motion_context_enabled", "i2v_groups", "r2v_groups",
        )
        inputs = {key: body.get(key) for key in keys if key in body and body.get(key) is not None}
        return web.json_response(analyze_resume_cache(node_id, **inputs))

    node_id = str(request.query.get("node_id") or request.query.get("nodeId") or "").strip()
    payload = resume_state.resume_status(node_id or None)
    payload["caches"] = resume_state.segment_cache_preview(node_id or None)
    return web.json_response(payload)


async def minimax_stop_request(request):
    """Ask the running executor to finish the current segment, then stop."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    node_id = str(body.get("node_id") or "").strip()
    resume_state.request_graceful_stop(node_id or None)
    return web.json_response({"ok": True, "node_id": node_id})


async def minimax_clear_run(request):
    """Start-over: clear the run manifest and this node's segment caches."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    node_id = str(body.get("node_id") or "").strip()
    existed = resume_state.clear_run(node_id or None)
    return web.json_response({"ok": True, "node_id": node_id, "cleared": existed})


def _run_window_mask_test(body: dict):
    """Synchronous core of the per-window SAM3 mask test (runs in a worker)."""
    from .mask_preview import compose_mask_check_jpeg, mask_coverage
    from .sam3_auto import run_window_auto_mask
    from ..lib.video_io import load_timeline_segment

    video_file = str(body.get("videoFile") or body.get("video_file") or "").strip()
    if not video_file:
        raise ValueError("Missing videoFile.")

    subfolder = str(body.get("subfolder") or "").strip()
    vtype = str(body.get("type") or "input").strip() or "input"
    try:
        frame_rate = float(body.get("frameRate") or body.get("frame_rate") or 24)
    except (TypeError, ValueError):
        frame_rate = 24.0
    try:
        source_total = int(
            body.get("sourceFrameCount")
            or body.get("source_frame_count")
            or body.get("totalFrames")
            or body.get("total_frames")
            or 0
        )
    except (TypeError, ValueError):
        source_total = 0
    if source_total <= 0:
        raise ValueError("Missing sourceFrameCount/totalFrames.")

    def _int_field(*names: str, default: int = 0) -> int:
        for name in names:
            try:
                value = int(body.get(name) or default)
            except (TypeError, ValueError):
                continue
            if value:
                return value
        return default

    start = _int_field("start", "startFrame", "start_frame")
    end = _int_field("end", "endFrame", "end_frame")
    if end <= start:
        raise ValueError("Window end must be after start.")
    lead = max(0, _int_field("lead", "leadFrames", "lead_frames"))
    prompt = str(body.get("prompt") or body.get("samPrompt") or "").strip() or None
    try:
        obj_id = int(body.get("objId") or body.get("obj_id") or 1) or None
    except (TypeError, ValueError):
        obj_id = None
    long_edge = _int_field("longEdge", "long_edge")
    action = str(body.get("action") or "").strip().lower()
    try:
        test_frames = int(body.get("testFrames") if body.get("testFrames") is not None else body.get("test_frames", 0) or 0)
    except (TypeError, ValueError):
        test_frames = 0
    # The manual quick test only needs the opening of the window (seed + a short
    # tracking stretch) - running all ~222 frames wastes ~2 min per test. Cap
    # quick tests to the first 48 frames unless the caller says otherwise.
    if test_frames <= 0 and action != "full":
        test_frames = 48
    try:
        pick_frame = int(body.get("pickFrame") if body.get("pickFrame") is not None else body.get("pick_frame", -1) or -1)
    except (TypeError, ValueError):
        pick_frame = -1
    box = None
    box_raw = body.get("box") or body.get("boundingBox") or body.get("bounding_box")
    if isinstance(box_raw, (list, tuple)) and len(box_raw) == 4:
        try:
            vals = [float(v) for v in box_raw]
        except (TypeError, ValueError):
            vals = []
        if len(vals) == 4 and all(v == v and 0.0 <= v <= 1.0 for v in vals) and vals[2] > 0.0 and vals[3] > 0.0:
            box = [vals[0], vals[1], min(vals[2], 1.0 - vals[0]), min(vals[3], 1.0 - vals[1])]

    timeline = {
        "frameRate": frame_rate,
        "totalFrames": source_total,
        "video": {
            "videoFile": video_file,
            "fileName": os.path.basename(video_file.replace("\\", "/")),
            "subfolder": subfolder,
            "type": vtype,
            "sourceFrameCount": source_total,
        },
    }
    if long_edge:
        timeline["output"] = {"longEdge": long_edge}

    # Mirror the run: mask window = [start-lead, start) lead head + [start, end).
    begin = max(0, start - lead)
    end = min(source_total, end)
    if end <= begin:
        raise ValueError("Window range falls outside the source.")
    frames = load_timeline_segment(timeline, begin, end)

    frame_count = int(frames.shape[0])
    original_count = frame_count
    head = max(0, start - begin)
    effective_lead = min(lead, head)
    if pick_frame is not None and pick_frame >= 0:
        pick_index = max(0, min(int(pick_frame), frame_count - 1))
    else:
        pick_index = max(0, min(effective_lead, frame_count - 1))
    # Quick tests run on the first N frames only (seed + short tracking). The
    # frame shown for picking is the same frame either way, so truncation below
    # is fine for both the frame action and the mask run.
    if action != "full" and test_frames > 0 and test_frames < frame_count:
        frames = frames[: int(test_frames)]
        frame_count = int(frames.shape[0])
        pick_index = max(0, min(pick_index, frame_count - 1))
    frame_w = int(frames.shape[2])
    frame_h = int(frames.shape[1])

    if action in ("frame", "pick"):
        from .mask_preview import frame_jpeg

        return {
            "ok": True,
            "action": "frame",
            "image_b64": frame_jpeg(frames[pick_index]),
            "width": frame_w,
            "height": frame_h,
            "index": pick_index,
        }

    # The manual Test mask is a quick sanity check: with a box only the box
    # attempt runs; without a box only the two strongest text anchors. The full
    # retry policy is reserved for the real render (executor path).
    result = run_window_auto_mask(
        frames,
        prompts=[prompt] if prompt else None,
        obj_id=obj_id,
        lead_frames=effective_lead,
        boxes=box,
        boxes_frame=(pick_index if box is not None else -1),
        quick=(action != "full"),
    )
    mask = result.get("mask")
    coverage = mask_coverage(mask)
    tested_note = (
        f" (first {frame_count} of {original_count} window frames)"
        if original_count > frame_count
        else ""
    )
    if mask is None:
        label = (
            "Window mask test: NO subject detected"
            + (" (single quick pass - not the full retry policy)" if action != "full" else "")
            + " - would fall back to plain RV2V"
            + tested_note
        )
    elif coverage:
        label = (
            f"Window mask test: {int(coverage['regen_frames'])}/{int(coverage['total'])} "
            f"frames regenerated (mean {float(coverage['mean']):.2f})"
            + (" [box-seeded]" if result.get("used_box") else "")
            + tested_note
        )
    else:
        label = "Window mask test: coverage unavailable" + tested_note
    image_b64 = compose_mask_check_jpeg(
        frames,
        mask,
        None,
        lead=pick_index,
        ref_label="window start frame",
    )
    return {
        "ok": True,
        "image_b64": image_b64,
        "coverage": coverage,
        "attempts": list(result.get("attempts") or []),
        "fallback": mask is None,
        "reason": str(result.get("reason") or ""),
        "label": label,
        "used_box": bool(result.get("used_box") or box),
        "pick_index": pick_index,
        "width": frame_w,
        "height": frame_h,
        "frames": frame_count,
        "original_frames": original_count,
        "start": start,
        "end": end,
    }


async def minimax_test_mask(request):
    """Run SAM3 auto-mask for one replace window and return the Mask check image."""
    try:
        body = await request.json()
    except Exception as exc:
        return web.Response(status=400, text=f"Invalid JSON: {exc}")

    if str(body.get("videoFile") or body.get("video_file") or "").strip() in ("", "None"):
        return web.Response(status=400, text="Missing videoFile.")
    try:
        import asyncio

        result = await asyncio.to_thread(_run_window_mask_test, body)
    except ValueError as exc:
        return web.Response(status=400, text=str(exc))
    except Exception as exc:
        log.warning("MiniMax H3 Motion Director window mask test failed: %s", exc)
        return web.json_response(
            {"ok": False, "error": f"Mask test failed: {exc}"}, status=500
        )
    return web.json_response(result)


def register_routes() -> bool:
    """Register MiniMax H3 Motion Director HTTP routes on the ComfyUI PromptServer."""
    global _ROUTES_REGISTERED
    if _ROUTES_REGISTERED:
        return True

    server = PromptServer.instance
    if server is None:
        log.warning("MiniMax H3 Motion Director: PromptServer not ready, HTTP routes not registered")
        return False

    routes = server.routes
    _register_route(routes, "POST", "/minimax/motion-director/upload_chunk", minimax_upload_video_chunk)
    _register_route(routes, "POST", "/minimax/motion-director/probe_video", minimax_probe_video)
    _register_route(routes, "GET", "/minimax/motion-director/probe_video", minimax_probe_video)
    _register_route(routes, "POST", "/minimax/motion-director/detect_shots", minimax_detect_shots)
    _register_route(routes, "POST", "/minimax/motion-director/test_mask", minimax_test_mask)
    _register_route(routes, "GET", "/minimax/motion-director/postprocess_capabilities", minimax_postprocess_capabilities)
    _register_route(routes, "POST", "/minimax/motion-director/save_video", minimax_save_final_video)
    _register_route(routes, "POST", "/minimax/motion-director/release_video", minimax_release_final_video)
    _register_route(routes, "GET", "/minimax/motion-director/resume_status", minimax_resume_status)
    _register_route(routes, "GET", "/minimax/motion-director/resume_preview", minimax_resume_preview)
    _register_route(routes, "POST", "/minimax/motion-director/resume_preview", minimax_resume_preview)
    _register_route(routes, "POST", "/minimax/motion-director/stop_request", minimax_stop_request)
    _register_route(routes, "POST", "/minimax/motion-director/clear_run", minimax_clear_run)
    register_material_library_routes(routes)
    _ROUTES_REGISTERED = True
    log.info("MiniMax H3 Motion Director HTTP routes registered")
    return True
