"""All-intra preview clips for Director results.

Why this exists
---------------
Results used to be delivered as *every frame* base64-encoded as JPEG and pushed
through the ComfyUI websocket (``report_director_segment_preview(frames=[...])``).
Measured on a real 243-frame segment that is ~8.9 MB of JPEG, i.e. ~11.9 MB of
base64, and a six-segment project retains ~71 MB of base64 strings in the
browser. The payload has to be parsed synchronously on the browser main thread,
which is what makes the Results page stall.

Instead we write one small H.264 clip into the ComfyUI temp directory and hand
the UI a ``/view`` URL. The browser then streams it with ordinary HTTP range
requests (zero bytes over the websocket) and can seek instantly.

All-intra on purpose
--------------------
Every frame is encoded as a keyframe (``g=1``, no B-frames). That costs roughly
2x the size of an inter-coded clip, but it means ``video.currentTime = i / fps``
lands on *exactly* frame ``i``, so the Results scrub slider stays frame-accurate
without needing a per-frame HTTP route. Measured on a 243-frame 960x544 clip:
inter-coded 1.15 MB, all-intra ~2.5 MB, versus 11.9 MB for the base64 JPEGs.

Encoder notes
-------------
``h264_nvenc`` needs ``preset`` set *before* ``bf=0``; presets p3 and above
re-enable B-frames and then reject ``g=1`` with "Gop Length should be greater
than number of B frames + 1". ``p1`` disables B-frames and is also the cheapest
preset, which is what we want for a side channel. ``libx264`` is the fallback
when NVENC is unavailable.
"""

from __future__ import annotations

import logging
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.director.preview_clip")

#: Subfolder of the ComfyUI temp directory that holds preview clips. Served by
#: ComfyUI's own ``/view`` route as ``type=temp``, which validates that the
#: subfolder stays inside the temp root.
TEMP_SUBFOLDER = "minimax_director_preview"

#: Constant-quality target. Lower is better looking and larger. 28 measured at
#: ~2.5 MB for 243 frames at 960x544 (cq 26 -> 3.1 MB, cq 30 -> 2.1 MB).
DEFAULT_CRF = 28

#: Fragmented MP4 so the browser can start playing before the file is complete.
_MOVFLAGS = "frag_keyframe+empty_moov+default_base_moof"

_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def _safe(value: Any, fallback: str = "x") -> str:
    text = _SAFE.sub("_", str(value or "")).strip("._-")
    return text[:80] or fallback


def preview_root() -> Path:
    """Directory holding generated preview clips (created on demand)."""
    import folder_paths

    root = Path(folder_paths.get_temp_directory()) / TEMP_SUBFOLDER
    root.mkdir(parents=True, exist_ok=True)
    return root


def _frame_to_uint8(frame: Any):
    """Normalise one frame - torch tensor, PIL image, or ndarray - to uint8 HWC."""
    import numpy as np

    if hasattr(frame, "detach"):  # torch.Tensor
        array = frame.detach().cpu().clamp(0, 1).mul(255).to("cpu").numpy()
    elif hasattr(frame, "convert"):  # PIL.Image
        array = np.asarray(frame.convert("RGB"))
        return np.ascontiguousarray(array.astype("uint8") if array.dtype != np.uint8 else array)
    else:
        array = np.asarray(frame)

    if array.dtype != np.uint8:
        array = array.astype("uint8")
    if array.ndim == 2:
        array = np.stack([array] * 3, axis=-1)
    elif array.ndim == 3 and array.shape[-1] == 4:
        array = array[..., :3]
    return np.ascontiguousarray(array)


def _iter_frames(frames: Any) -> Iterable[Any]:
    """Yield frames one at a time.

    Per-frame iteration matters: a 2000-frame 960x544 result would be ~3 GB as a
    single uint8 array, so we never materialise the whole clip in RAM.
    """
    if hasattr(frames, "shape") and len(getattr(frames, "shape", ())) == 4:
        for index in range(int(frames.shape[0])):
            yield frames[index]
        return
    for frame in frames or ():
        if frame is not None:
            yield frame


def _is_empty(frames: Any) -> bool:
    """Cheap emptiness check that never materialises the frame list."""
    if frames is None:
        return True
    shape = getattr(frames, "shape", None)
    if shape is not None and len(shape) == 4:
        return int(shape[0]) <= 0
    try:
        return len(frames) == 0
    except TypeError:
        return False


def _encode(source: Any, fps: float, path: Path, *, crf: int) -> tuple[int, int, str, int]:
    """Encode ``source`` to ``path``. Returns (width, height, codec_label, frame_count).

    Consumes ``source`` one frame at a time and re-iterates it for the fallback
    codec, so a 2000-frame result never exists in RAM as a single array.
    """
    import av

    errors: list[str] = []
    for codec, options in (
        (
            "h264_nvenc",
            {"preset": "p1", "g": "1", "bf": "0", "rc": "vbr", "cq": str(int(crf))},
        ),
        (
            "libx264",
            {
                "preset": "veryfast",
                "crf": str(int(crf)),
                "g": "1",
                "keyint_min": "1",
                "scenecut": "0",
            },
        ),
    ):
        container = None
        try:
            iterator = iter(_iter_frames(source))
            try:
                first = _frame_to_uint8(next(iterator))
            except StopIteration:
                raise ValueError("no frames to encode")

            height, width = first.shape[0], first.shape[1]
            # yuv420p needs even dimensions; crop rather than scale so the
            # preview stays pixel-aligned with what the Director rendered.
            crop = (width % 2) or (height % 2)
            if crop:
                width -= width % 2
                height -= height % 2

            container = av.open(
                str(path),
                mode="w",
                format="mp4",
                options={"movflags": _MOVFLAGS},
            )
            stream = container.add_stream(codec, rate=max(1, int(round(fps))))
            stream.width = width
            stream.height = height
            stream.pix_fmt = "yuv420p"
            stream.options = dict(options)

            count = 0
            for array in _chain_first(first, iterator):
                if crop:
                    array = array[:height, :width]
                container.mux(stream.encode(av.VideoFrame.from_ndarray(array, format="rgb24")))
                count += 1
            for packet in stream.encode():
                container.mux(packet)
            container.close()
            return width, height, codec, count
        except Exception as exc:  # NVENC missing/unsupported -> try libx264
            errors.append(f"{codec}: {exc}")
            if container is not None:
                try:
                    container.close()
                except Exception:
                    pass
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    raise RuntimeError("preview clip encode failed (" + "; ".join(errors) + ")")


def _chain_first(first: Any, rest: Iterable[Any]) -> Iterable[Any]:
    yield first
    for frame in rest:
        yield _frame_to_uint8(frame)


def write_preview_clip(
    frames: Any,
    fps: float,
    *,
    node_id: Any,
    key: str,
    crf: int = DEFAULT_CRF,
) -> dict[str, Any] | None:
    """Encode a preview clip and return the payload fields for the UI.

    Returns ``None`` when there is nothing to encode or encoding failed; the
    caller is expected to fall back to the legacy base64 frame payload so a
    broken encoder can never lose a result.
    """
    if _is_empty(frames):
        return None

    try:
        root = preview_root() / _safe(node_id, "node")
        root.mkdir(parents=True, exist_ok=True)
        name = f"{_safe(key, 'clip')}.mp4"
        path = root / name

        width, height, codec, count = _encode(frames, fps, path, crf=crf)
        if not count:
            return None

        # ComfyUI's /view sets no Cache-Control, so a deterministic filename
        # could be replayed from the browser cache on the next run. The token
        # makes every emitted URL unique; the filename stays readable.
        token = uuid.uuid4().hex[:12]

        return {
            "preview_url": (
                f"/view?filename={name}"
                f"&subfolder={TEMP_SUBFOLDER}/{_safe(node_id, 'node')}"
                f"&type=temp&c={token}"
            ),
            "preview_filename": name,
            "preview_subfolder": f"{TEMP_SUBFOLDER}/{_safe(node_id, 'node')}",
            "preview_type": "temp",
            "preview_codec": codec,
            "preview_bytes": int(path.stat().st_size),
            "preview_frame_count": int(count),
            "preview_width": int(width),
            "preview_height": int(height),
        }
    except Exception as exc:
        log.warning("Preview clip encode failed; falling back to frames: %s", exc)
        return None


def build_result_preview(
    frames: Any,
    fps: float,
    *,
    node_id: Any,
    key: str,
    frame_to_b64: Callable[[Any], str],
    crf: int = DEFAULT_CRF,
) -> dict[str, Any]:
    """Build the emit kwargs for a completed result.

    Prefers a small all-intra preview clip served from the ComfyUI temp
    directory, because shipping every frame as base64 over the websocket is what
    stalled the Results page (~11.9 MB for a 243-frame segment, parsed
    synchronously on the browser main thread).

    ``frames`` is only built when encoding fails, so the expensive per-frame
    JPEG pass is skipped entirely on the normal path. ``frame_to_b64`` is
    injected so this module stays free of segment-runtime imports.
    """
    if _is_empty(frames):
        return {"image_b64": "", "width": 0, "height": 0}

    height, width = int(frames.shape[1]), int(frames.shape[2])
    first = frame_to_b64(frames[0])

    preview = write_preview_clip(frames, fps, node_id=node_id, key=key, crf=crf)
    if preview:
        return {"image_b64": first, "width": width, "height": height, "preview": preview}

    frames_b64 = [frame_to_b64(frames[index]) for index in range(int(frames.shape[0]))]
    return {
        "image_b64": frames_b64[0],
        "width": width,
        "height": height,
        "frames": frames_b64,
    }


def clip_url(filename: str, subfolder: str, type_: str = "temp") -> str:
    return f"/view?filename={filename}&subfolder={subfolder}&type={type_}"

def cleanup_previews(node_id: Any = None) -> int:
    """Delete generated preview clips (for one node, or all). Returns count removed."""
    try:
        root = preview_root()
    except Exception:
        return 0

    removed = 0
    targets = [root / _safe(node_id, "node")] if node_id is not None else [root]
    for target in targets:
        if not target.exists():
            continue
        for path in target.glob("*.mp4"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        if target is not root:
            shutil.rmtree(target, ignore_errors=True)
    return removed


def prune_previews(max_age_seconds: float = 6 * 3600.0) -> int:
    """Delete preview clips older than ``max_age_seconds``.

    The temp directory is not cleaned by ComfyUI, so without this a long session
    would accumulate clips indefinitely.
    """
    try:
        root = preview_root()
    except Exception:
        return 0

    cutoff = time.time() - max(0.0, float(max_age_seconds))
    removed = 0
    for path in root.rglob("*.mp4"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            pass
    return removed


__all__ = [
    "TEMP_SUBFOLDER",
    "DEFAULT_CRF",
    "preview_root",
    "write_preview_clip",
    "build_result_preview",
    "clip_url",
    "cleanup_previews",
    "prune_previews",
]
