# MiniMax H3 Motion Director - in-run SAM3 auto-mask (Phase 2).
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Prompt-driven auto masks for Character Replace windows.

Phase 1 requires per-frame mask PNGs on disk (``mask.kind == "frames"``).
This module adds ``mask.kind == "sam3"``: at render time the executor runs the
SAM3 video predictor over the window's real source frames with the window's
``sam_prompts`` (e.g. "the woman with long blue hair including every strand"),
and produces the per-frame subject mask directly in memory - no mask files.

Calling pattern mirrors the pack's proven standalone tool
(``sam3_scene_mask.py``): build the video predictor once, start a session on a
list of RGB PIL frames, add one text prompt per object id, propagate in video,
and merge each frame's ``out_binary_masks`` with a logical OR.

GPU-lifecycle contract: the predictor is a large video model, and the Director
executor runs it while the H3 stack is resident. The executor therefore calls
:func:`release_sam3` right after a window's mask is built (before H3 sampling)
so VRAM is returned. Building the predictor is comparatively slow, so it is
module-cached *within* one mask request; only the executor decides to drop the
cache between segments.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.director.sam3_auto")

# Thresholds proven by sam3_scene_mask.py for prompt-driven subject tracking.
SAM3_IMAGE_SIZE = 1008
SAM3_DEFAULT_PROMPT = (
    "the woman, full body from head to toe, "
    "including every strand of her hair"
)
SAM3_OBJ_ID_DEFAULT = 1

# Detection profiles applied to the predictor model around each session.
# Defaults mirror the proven standalone sam3_scene_mask.py. The relaxed
# profile is only used as a retry when a window comes back empty: it accepts
# weaker detections so a clearly visible but lower-confidence subject can seed
# a track (at the cost of a higher chance of a sloppy mask, which is why the
# normal profile is always tried first).
_DETECTION_DEFAULTS = {
    "score_threshold_detection": 0.5,
    "new_det_thresh": 0.7,
    "assoc_iou_thresh": 0.1,
    "det_nms_thresh": 0.1,
}
_DETECTION_RELAXED = {
    "score_threshold_detection": 0.35,
    "new_det_thresh": 0.45,
    "assoc_iou_thresh": 0.1,
    "det_nms_thresh": 0.15,
}

_PREDICTOR_CACHE: dict[str, Any] = {}
_SAM3_PACK_INSERTED = False


def _ensure_sam3_importable() -> bool:
    """Make the ``sam3`` package importable (ComfyUI custom node dir)."""
    global _SAM3_PACK_INSERTED
    if _SAM3_PACK_INSERTED:
        return True
    try:
        import sam3  # noqa: F401
    except Exception:
        # ComfyUI normally adds each custom node folder to sys.path when the
        # pack loads; fall back to locating the vendored sam3/ tree.
        for root in (
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "custom_nodes"),
            "/mnt/ssd2/cmfy/ComfyUI-Easy-Install/ComfyUI/custom_nodes",
        ):
            if not os.path.isdir(root):
                continue
            try:
                for name in sorted(os.listdir(root)):
                    cand = os.path.join(root, name)
                    if name.startswith("comfyui-easy-sam3") and os.path.isdir(os.path.join(cand, "sam3")):
                        if cand not in sys.path:
                            sys.path.insert(0, cand)
                        break
            except Exception:
                continue
        try:
            import sam3  # noqa: F401
        except Exception:
            return False
    _SAM3_PACK_INSERTED = True
    return True


def resolve_sam3_checkpoint() -> str | None:
    """Pick a SAM3 checkpoint from ComfyUI's ``sam3`` model folder."""
    try:
        import folder_paths  # type: ignore

        names = folder_paths.get_filename_list("sam3")
    except Exception:
        names = []
    if not names:
        for cand in (
            "/mnt/ssd2/cmfy/ComfyUI-Easy-Install/ComfyUI/models/sam3/sam3.pt",
            os.path.expanduser("~/ComfyUI/models/sam3/sam3.pt"),
        ):
            if os.path.isfile(cand):
                return cand
        return None
    preferred = "sam3.pt" if "sam3.pt" in names else names[0]
    try:
        return folder_paths.get_full_path_or_raise("sam3", preferred)
    except Exception:
        return None


def _build_predictor(checkpoint: str):
    """Build the SAM3 video predictor with the proven tracking thresholds."""
    from sam3.model_builder import build_sam3_video_predictor

    predictor = build_sam3_video_predictor(checkpoint_path=checkpoint, gpus_to_use=None)
    m = predictor.model
    m.score_threshold_detection = 0.5
    m.new_det_thresh = 0.7
    m.assoc_iou_thresh = 0.1
    m.det_nms_thresh = 0.1
    m.hotstart_delay = 15
    m.hotstart_unmatch_thresh = 8
    m.hotstart_dup_thresh = 8
    m.suppress_unmatched_only_within_hotstart = True
    m.min_trk_keep_alive = -1
    m.max_trk_keep_alive = 30
    m.init_trk_keep_alive = 30
    m.suppress_overlapping_based_on_recent_occlusion_threshold = 0.7
    m.suppress_det_close_to_boundary = False
    m.fill_hole_area = 16
    m.recondition_every_nth_frame = 16
    m.masklet_confirmation_enable = False
    m.decrease_trk_keep_alive_for_empty_masklets = False
    m.image_size = SAM3_IMAGE_SIZE
    return predictor


def _acquire_predictor(checkpoint: str | None):
    ckpt = checkpoint or resolve_sam3_checkpoint()
    if not ckpt:
        raise RuntimeError("no SAM3 checkpoint found in the 'sam3' model folder")
    cached = _PREDICTOR_CACHE.get(ckpt)
    if cached is not None:
        return ckpt, cached
    log.info("SAM3 auto-mask: building video predictor from %s ...", ckpt)
    predictor = _build_predictor(ckpt)
    _PREDICTOR_CACHE[ckpt] = predictor
    return ckpt, predictor


def release_sam3(checkpoint: str | None = None) -> None:
    """Drop the cached SAM3 predictor and free GPU memory (safe to call anytime)."""
    import gc

    keys = list(_PREDICTOR_CACHE.keys())
    if checkpoint:
        keys = [k for k in keys if k == checkpoint]
    for k in keys:
        predictor = _PREDICTOR_CACHE.pop(k, None)
        if predictor is not None:
            try:
                del predictor
            except Exception:
                pass
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def _apply_detection_profile(predictor, *, relaxed: bool) -> dict[str, Any]:
    """Apply a detection profile to the cached predictor; return the old values."""
    profile = _DETECTION_RELAXED if relaxed else _DETECTION_DEFAULTS
    previous: dict[str, Any] = {}
    model = getattr(predictor, "model", None)
    if model is None:
        return previous
    for key, value in profile.items():
        if hasattr(model, key):
            previous[key] = getattr(model, key)
            try:
                setattr(model, key, value)
            except Exception:
                previous.pop(key, None)
    return previous


def _restore_detection_profile(predictor, previous: dict[str, Any]) -> None:
    """Put back previously saved detection attribute values."""
    if not previous:
        return
    model = getattr(predictor, "model", None)
    if model is None:
        return
    for key, value in previous.items():
        try:
            setattr(model, key, value)
        except Exception:
            pass


def candidate_prompt_frames(total: int, lead: int = 0) -> list[int]:
    """Anchor frame indices to try for a window mask, best first.

    Returns [0, true window start, middle, last] (clamped, de-duplicated):
    - frame 0 keeps the historical behaviour and also masks the pre-roll lead
      head when the lead frames belong to the same shot;
    - the true window start (index ``lead``) and the window middle cover the
      common failure where the pre-roll head (or the very first frame) is a
      different shot, a cut, or a moment when the subject is off-frame even
      though she is clearly visible for the rest of the window.
    """
    total = max(0, int(total))
    lead = max(0, int(lead))
    if total <= 0:
        return []
    mid = lead + max(0, (total - lead) // 2)
    out: list[int] = []
    for idx in (0, lead, mid, total - 1):
        idx = max(0, min(int(idx), total - 1))
        if idx not in out:
            out.append(idx)
    return out


def mask_attempt_plan(total: int, lead: int = 0) -> list[tuple[int, bool]]:
    """Ordered (prompt_frame, relaxed) attempts for a window's auto mask.

    Mirrors the executor's retry policy: every candidate anchor first with the
    normal profile, then relaxed-profile retries on the two most robust anchors
    (true window start and middle). Kept here so the executor and the per-window
    "Test mask" route run the exact same attempts.
    """
    anchors = candidate_prompt_frames(total, lead)
    plan: list[tuple[int, bool]] = [(anchor, False) for anchor in anchors]
    for anchor in anchors[1:3]:
        plan.append((anchor, True))
    return plan


def _sanitize_box(box) -> list[float] | None:
    """Validate/normalize a single [xmin, ymin, width, height] box (0..1)."""
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        vals = [float(v) for v in box]
    except (TypeError, ValueError):
        return None
    if any(v != v or v < 0.0 or v > 1.0 for v in vals):
        return None
    x0, y0, w, h = vals
    if w <= 0.0 or h <= 0.0:
        return None
    return [x0, y0, min(w, 1.0 - x0), min(h, 1.0 - y0)]


def _sanitize_points(points, labels=None):
    """Validate a list of normalized [x, y] clicks (0..1) into (pts, labels).

    Returns ``([ [x,y], ... ], [0/1, ...])`` or None. Labels default to 1
    (positive / include); 0 marks a negative (exclude) click.
    """
    if not isinstance(points, (list, tuple)) or not points:
        return None
    labels = list(labels or []) if isinstance(labels, (list, tuple)) else []
    pts: list[list[float]] = []
    lbls: list[int] = []
    for i, point in enumerate(points):
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            return None
        try:
            x = float(point[0])
            y = float(point[1])
        except (TypeError, ValueError):
            return None
        if x != x or y != y or not (0.0 <= x <= 1.0) or not (0.0 <= y <= 1.0):
            return None
        pts.append([x, y])
        try:
            lbl = int(labels[i]) if i < len(labels) else 1
        except (TypeError, ValueError):
            lbl = 1
        lbls.append(1 if lbl else 0)
    if not pts:
        return None
    return pts, lbls


def run_window_auto_mask(
    frames,
    *,
    prompts=None,
    obj_id: int | None = None,
    lead_frames: int = 0,
    boxes=None,
    boxes_frame: int = -1,
    points=None,
    point_labels=None,
    checkpoint: str | None = None,
    quick: bool = False,
) -> dict[str, Any]:
    """Run the full window auto-mask attempt policy and return a result dict.

    When ``boxes`` is a single normalized [xmin, ymin, width, height] box it is
    tried first as a SAM3 visual prompt on frame ``boxes_frame`` (default = the
    true window start after the lead head); if that yields no mask the text
    prompt policy from :func:`mask_attempt_plan` is attempted. Without a box,
    only the text prompt attempts run. The SAM3 predictor is always released
    before returning so VRAM is free for H3 sampling.

    ``quick=True`` bounds the run for interactive "Test mask" calls: with a box
    only the box attempt runs, and without a box only the two strongest text
    anchors run - the full retry/relaxed policy is reserved for the actual
    render (quick=False). This keeps a manual test under ~2-4 minutes so a long
    HTTP request cannot time out.

    Returns ``{"mask": [T,H,W] 0..1 or None, "attempts": [str, ...],
    "coverage": {...}|None, "reason": str}``. ``reason`` is empty when a mask
    was found.
    """
    if frames is None or int(frames.shape[0]) <= 0 or frames.ndim != 4:
        return {
            "mask": None,
            "attempts": [],
            "coverage": None,
            "reason": "no source frames for auto SAM3 masking",
        }
    total = int(frames.shape[0])
    lead = int(lead_frames or 0)
    box = _sanitize_box(boxes)
    pts = _sanitize_points(points, point_labels) if points is not None else None
    plan = mask_attempt_plan(total, lead)
    quick = bool(quick)
    # (prompt_frame, relaxed, seed_for_this_attempt)
    # seed is None (text) or {"kind": "points"|"box", ...}.
    items: list[tuple[int, bool, dict | None]] = []
    seed = None
    if pts is not None:
        seed = {"kind": "points", "pts": pts[0], "lbls": pts[1]}
    elif box is not None:
        seed = {"kind": "box", "box": box}
    if seed is not None:
        anchor = int(boxes_frame) if boxes_frame is not None and int(boxes_frame) >= 0 else lead
        anchor = max(0, min(anchor, total - 1))
        items.append((anchor, False, seed))
        if not quick:
            for pf, relaxed in plan:
                items.append((pf, relaxed, None))
    else:
        text_plan = plan[:2] if quick else plan
        for pf, relaxed in text_plan:
            items.append((pf, relaxed, None))

    attempted: list[str] = []
    # A mask that only covers a handful of frames (e.g. just the prompt frame)
    # is not a usable window mask - require a meaningful temporal footprint so
    # a 1-frame seed is never reported as success.
    usable_min = max(5, int(total * 0.03))
    chosen = None
    chosen_relaxed = False
    chosen_pf = -1
    chosen_box = False
    chosen_points = False
    try:
        for pf, relaxed, seed in items:
            mask_hi = None
            kind = (seed or {}).get("kind", None) if seed else None
            kind_label = kind if kind in ("box", "points") else "pf"
            try:
                seed_boxes = None
                seed_points = None
                seed_labels = None
                if seed is not None and seed.get("kind") == "box":
                    seed_boxes = seed.get("box")
                elif seed is not None and seed.get("kind") == "points":
                    seed_points = seed.get("pts")
                    seed_labels = seed.get("lbls")
                mask_hi = segment_window_frames(
                    frames,
                    prompts=prompts,
                    obj_id=obj_id,
                    prompt_frame=pf,
                    relaxed=relaxed,
                    boxes=seed_boxes,
                    points=seed_points,
                    point_labels=seed_labels,
                    checkpoint=checkpoint,
                )
            except Exception as exc:
                log.warning(
                    "SAM3 auto-mask attempt failed (prompt_frame=%d relaxed=%s seed=%s): %s",
                    pf, relaxed, kind_label, exc,
                )
            if mask_hi is None:
                attempted.append(
                    f"{kind_label}={pf}{'/relaxed' if relaxed else ''}:no-mask"
                )
                continue
            try:
                _m = mask_hi.float()
                regen = int((_m.amax(dim=(1, 2)) > 0.5).sum().item())
            except Exception:
                regen = 0
            attempted.append(
                f"{kind_label}={pf}{'/relaxed' if relaxed else ''}:{regen}"
            )
            if regen >= usable_min:
                chosen = mask_hi
                chosen_pf = pf
                chosen_relaxed = relaxed
                chosen_box = kind == "box"
                chosen_points = kind == "points"
                log.info(
                    "SAM3 auto-mask coverage (prompt_frame=%d relaxed=%s seed=%s): "
                    "mean=%.4g regen_frames=%d/%d",
                    pf, relaxed, kind_label, float(_m.mean()), regen, int(_m.shape[0]),
                )
                break
    finally:
        try:
            release_sam3()
        except Exception:
            pass
    if chosen is not None:
        coverage = None
        try:
            _m = chosen.float()
            coverage = {
                "mean": float(_m.mean()),
                "regen_frames": int((_m.amax(dim=(1, 2)) > 0.5).sum().item()),
                "total": int(_m.shape[0]),
            }
        except Exception:
            pass
        return {
            "mask": chosen,
            "attempts": attempted,
            "coverage": coverage,
            "reason": "",
            "prompt_frame": chosen_pf,
            "relaxed": chosen_relaxed,
            "used_box": chosen_box,
            "used_points": chosen_points,
        }
    return {
        "mask": None,
        "attempts": attempted,
        "coverage": None,
        "reason": (
            "auto SAM3 mask produced no subject mask for this window "
            f"(attempts: {', '.join(attempted) or 'none'} - check that the "
            "subject is clearly visible in the window and that the SAM3 prompt "
            "matches her appearance; see log)"
            + (" Quick test: only the strongest anchor(s) were tried." if quick else "")
        ),
    }


def frames_to_pils(frames):
    """Convert torch float [T,H,W,3] (0..1) source frames into RGB PIL images."""
    import numpy as np
    from PIL import Image

    arr = frames.detach().float().cpu()
    if arr.numel() == 0:
        return []
    if arr.max() <= 1.01:
        arr = arr * 255.0
    arr = arr.clamp(0.0, 255.0).round().byte().numpy()
    return [Image.fromarray(arr[i], mode="RGB") for i in range(int(arr.shape[0]))]


def _merge_mask_outputs(outputs: dict[str, Any] | None):
    """Merge a frame's SAM3 object masks into one [H, W] bool (None = absent)."""
    import numpy as np

    if not isinstance(outputs, dict):
        return None
    masks = outputs.get("out_binary_masks")
    if masks is None:
        return None
    arr = np.asarray(masks)
    if arr.ndim != 3 or int(arr.shape[0]) <= 0:
        return None
    return np.any(arr, axis=0)


def _fit_mask_arr(mask_bool, h: int, w: int):
    """Return a [H, W] bool mask, upscaling/downscaling SAM3's grid when needed.

    SAM3 can return masks at its internal inference resolution rather than the
    source frame size; dropping those silently made a valid mask look like
    "no subject detected" (0 responses, all-zero). Returns None when the mask
    cannot be fitted.
    """
    import numpy as np

    if mask_bool is None or mask_bool.ndim != 2 or int(mask_bool.shape[0]) <= 0 or int(mask_bool.shape[1]) <= 0:
        return None
    if mask_bool.shape == (h, w):
        return mask_bool
    try:
        from PIL import Image

        _img = Image.fromarray((mask_bool.astype(np.uint8) * 255))
        _img = _img.resize((int(w), int(h)), Image.LANCZOS)
        _arr = np.asarray(_img, dtype=np.uint8) > 127
        if _arr.shape == (h, w):
            return _arr
    except Exception:
        pass
    return None


def segment_window_frames(
    frames,
    *,
    prompts=None,
    checkpoint: str | None = None,
    obj_id: int | None = None,
    prompt_frame: int = 0,
    relaxed: bool = False,
    boxes=None,
    points=None,
    point_labels=None,
) -> "torch.Tensor | None":
    """Segment ``frames`` [T,H,W,3] by text prompt into a [T,H,W] 0..1 mask.

    White (1) = subject to regenerate. Returns None when SAM3 cannot run or the
    session produced nothing (caller falls back to a plain RV2V window).
    ``prompts`` is a list of text prompts (each becomes one tracked object; all
    are merged with OR). An empty prompt list falls back to
    :data:`SAM3_DEFAULT_PROMPT`.

    When ``boxes`` is a single normalized [xmin, ymin, width, height] box in
    0..1 it is used as a SAM3 visual prompt on ``prompt_frame`` instead of the
    text prompts (dramatically more reliable for a clearly visible subject).
    ``prompt_frame`` chooses which frame index the prompt is anchored on (the
    first frame of the window is the default). ``relaxed`` applies the relaxed
    detection profile (lower score/new-detect thresholds) for this session
    only; the cached predictor's attributes are restored afterwards.
    """
    import torch

    if not _ensure_sam3_importable():
        log.warning("SAM3 auto-mask: sam3 package unavailable")
        return None
    if frames is None or int(frames.shape[0]) <= 0 or frames.ndim != 4:
        return None
    box = _sanitize_box(boxes) if boxes is not None else None
    pts = _sanitize_points(points, point_labels) if points is not None else None
    text_prompts = [str(p).strip() for p in (prompts or []) if str(p).strip()]
    if not text_prompts:
        text_prompts = [SAM3_DEFAULT_PROMPT]
    try:
        ckpt, predictor = _acquire_predictor(checkpoint)
    except Exception as exc:
        log.warning("SAM3 auto-mask: predictor build failed: %s", exc)
        return None
    import numpy as np

    pils = frames_to_pils(frames)
    if not pils:
        return None
    previous = None
    try:
        previous = _apply_detection_profile(predictor, relaxed=bool(relaxed))
        resp = predictor.handle_request(
            dict(type="start_session", resource_path=pils)
        )
        sid = resp.get("session_id") if isinstance(resp, dict) else None
        if sid is None:
            log.warning("SAM3 auto-mask: session did not start")
            return None
        pf = max(0, min(int(prompt_frame or 0), len(pils) - 1))
        start_obj = int(obj_id or SAM3_OBJ_ID_DEFAULT)
        seed_immediate = None
        seed_tag = "points seed" if pts is not None else ("box seed" if box is not None else "")
        with torch.autocast("cuda", dtype=torch.float32):
            if pts is not None:
                # Point clicks route to SAM3's instance tracker path (no text,
                # no box): each positive click includes the object, a 0 label
                # excludes. This is the geometry-free alternative to the box.
                add_resp = predictor.handle_request(
                    dict(
                        type="add_prompt",
                        session_id=sid,
                        frame_index=pf,
                        text=None,
                        points=pts[0],
                        point_labels=pts[1],
                        obj_id=start_obj,
                    )
                )
                try:
                    seed_immediate = _merge_mask_outputs(
                        (add_resp or {}).get("outputs", {}) or {}
                    )
                except Exception:
                    seed_immediate = None
            elif box is not None:
                # Text + box together: the text grounds the object class while
                # the box localizes it. A box-only prompt on this SAM3 build
                # produced no masklet at all (0 propagation responses), so the
                # text is required to seed the semantic path. We also keep the
                # immediate prompt-frame mask SAM3 returns from add_prompt so a
                # quiet propagation cannot wipe out a valid seed.
                add_resp = predictor.handle_request(
                    dict(
                        type="add_prompt",
                        session_id=sid,
                        frame_index=pf,
                        text=text_prompts[0],
                        bounding_boxes=[box],
                        bounding_box_labels=[1],
                        obj_id=start_obj,
                    )
                )
                try:
                    seed_immediate = _merge_mask_outputs(
                        (add_resp or {}).get("outputs", {}) or {}
                    )
                except Exception:
                    seed_immediate = None
            else:
                for i, text in enumerate(text_prompts):
                    predictor.handle_request(
                        dict(
                            type="add_prompt",
                            session_id=sid,
                            frame_index=pf,
                            text=text,
                            obj_id=start_obj + i,
                        )
                    )
            masks_by_frame: dict[int, np.ndarray | None] = {}
            try:
                stream = predictor.handle_stream_request(
                    dict(
                        type="propagate_in_video",
                        session_id=sid,
                        propagation_direction="forward",
                        start_frame_index=0,
                        max_frame_num_to_track=None,
                    )
                )
                for response in stream or ():
                    if not isinstance(response, dict):
                        continue
                    frame_idx = response.get("frame_index", 0)
                    masks_by_frame[int(frame_idx)] = _merge_mask_outputs(
                        response.get("outputs", {}) or {}
                    )
            finally:
                try:
                    predictor.handle_request(dict(type="close_session", session_id=sid))
                except Exception:
                    pass
        if not masks_by_frame and seed_immediate is None:
            log.warning("SAM3 auto-mask: no mask responses for the window")
            return None
        # Assemble [T,H,W] bool at the source frame resolution. Frames with no
        # detected object stay all-zero (subject absent/occluded), which keeps
        # the source pixel-exact instead of falling back to a plain regen.
        h, w = int(pils[0].size[1]), int(pils[0].size[0])
        out = np.zeros((len(pils), h, w), dtype=bool)
        responses = 0
        shape_ok = 0
        shape_resized = 0
        shape_dropped = 0
        if seed_immediate is not None:
            fitted = _fit_mask_arr(seed_immediate, h, w)
            if fitted is not None and pf < len(out):
                out[pf] = fitted
        for frame_idx, merged in masks_by_frame.items():
            if merged is None:
                continue
            responses += 1
            fitted = _fit_mask_arr(merged, h, w)
            if fitted is None:
                shape_dropped += 1
                continue
            if merged.shape == (h, w):
                shape_ok += 1
            else:
                shape_resized += 1
            if frame_idx < len(out):
                out[frame_idx] = fitted
        if seed_tag or shape_resized or shape_dropped or responses == 0:
            try:
                nonzero = int(np.count_nonzero(out.any(axis=(1, 2))))
                seed_desc = None
                if pts is not None:
                    seed_desc = f"{len(pts[0])}pt"
                elif box is not None:
                    seed_desc = [round(float(v), 3) for v in box]
                log.info(
                    "SAM3 mask assembly (%s): prompt_frame=%d seed=%s text=%r responses=%d "
                    "seed_immediate=%s ok=%d resized=%d dropped=%d nonzero_frames=%d/%d seed_frame_has_mask=%s",
                    seed_tag or "text",
                    pf,
                    seed_desc,
                    str(text_prompts[0]) if pts is None and box is not None and text_prompts else None,
                    responses,
                    bool(seed_immediate is not None and seed_immediate.any()),
                    shape_ok, shape_resized, shape_dropped,
                    nonzero, len(pils),
                    bool(out[pf].any()) if pf < len(out) else False,
                )
            except Exception:
                pass
        mask = torch.from_numpy(out.astype(np.float32))
        return mask.contiguous()
    except Exception as exc:
        log.warning("SAM3 auto-mask: session failed: %s", exc)
        try:
            release_sam3(ckpt)
        except Exception:
            pass
        return None
    finally:
        if previous:
            try:
                _restore_detection_profile(predictor, previous)
            except Exception:
                pass


__all__ = [
    "SAM3_DEFAULT_PROMPT",
    "SAM3_OBJ_ID_DEFAULT",
    "candidate_prompt_frames",
    "frames_to_pils",
    "mask_attempt_plan",
    "release_sam3",
    "resolve_sam3_checkpoint",
    "run_window_auto_mask",
    "segment_window_frames",
]
