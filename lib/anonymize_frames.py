# MiniMax H3 Motion Director - hide the replaced performer from the action caption.
# Copyright (C) 2026 WakaSoft. GPL-3.0. See LICENSE.

"""Invert the subject region of the action frames before they are captioned.

The action caption reads the source window, and the source window contains the
performer being replaced. The instruction tells the caption model not to describe
her appearance, and mostly that works - but a caption model looking straight at a
specific woman will occasionally volunteer her, and that text then has to argue with
the replacement reference for the rest of the prompt.

The Character Remake workflow this pack's caption mode is ported from solved it at
the pixel level: it fed a *composite* with the subject region inverted, so there was
no identity left to describe - only silhouette, pose, edges and background. That is
what this module reproduces. Nothing about the identity survives an inversion, while
everything the action caption actually needs (where she is, what she does, where the
camera is, what the room looks like) does.

The mask comes from `rembg`'s salient-object model, which is already installed in
ComfyUI's own environment and runs on CPU in a couple of seconds per frame. SAM3
would segment more accurately but needs a 3.4 GB checkpoint loaded into the same
process that is rendering, which is a steep price for a caption step; if the mask
cannot be produced the frames are passed through unchanged and the caller is told,
because a silent fallback would look like the option did nothing.
"""

from __future__ import annotations

import base64
import io
import logging
import os

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.lib")

# u2net is rembg's default and the smallest of its salient-object models. Overridable
# because the pack may be installed somewhere that already ships another one.
MODEL_ENV_VAR = "MINIMAX_H3_PE_MASK_MODEL"
DEFAULT_MODEL = "u2net"

# The mask edge is feathered so the composite has no hard seam: a caption model
# describing a jagged boundary is a wasted sentence, and the seam carries no
# information the action needs.
FEATHER_RADIUS = 6
# Below this fraction of the frame the mask is not a subject, it is noise (or the
# model grabbed a prop); inverting that does nothing useful.
MIN_COVERAGE = 0.01
MAX_COVERAGE = 0.97


def _session():
    """A cached rembg session, or (None, reason)."""
    global _SESSION, _SESSION_ERROR
    if _SESSION is not None:
        return _SESSION, ""
    if _SESSION_ERROR:
        return None, _SESSION_ERROR
    try:
        from rembg import new_session
    except Exception as exc:  # not installed in this environment
        _SESSION_ERROR = f"rembg is not installed ({type(exc).__name__})"
        return None, _SESSION_ERROR
    name = os.environ.get(MODEL_ENV_VAR, "").strip() or DEFAULT_MODEL
    try:
        _SESSION = new_session(name)
    except Exception as exc:
        _SESSION_ERROR = (
            f"the '{name}' segmentation model could not be loaded "
            f"({type(exc).__name__}: {exc})"
        )
        return None, _SESSION_ERROR
    return _SESSION, ""


_SESSION = None
_SESSION_ERROR = ""


def reset_session() -> None:
    """Drop the cached session (tests, or after a failed first download)."""
    global _SESSION, _SESSION_ERROR
    _SESSION = None
    _SESSION_ERROR = ""


def _mask_for(image, session):
    """The subject mask as a float array, or (None, reason)."""
    import numpy as np
    from rembg import remove

    try:
        mask = remove(image, session=session, only_mask=True)
    except Exception as exc:
        return None, f"mask inference failed ({type(exc).__name__}: {exc})"
    arr = np.asarray(mask).astype("float32") / 255.0
    if arr.ndim != 2:
        return None, f"unexpected mask shape {arr.shape}"
    coverage = float(arr.mean())
    if coverage < MIN_COVERAGE:
        return None, "no subject found in the frame"
    if coverage > MAX_COVERAGE:
        return None, "the mask covers the whole frame"
    return arr, ""


def _feather(arr):
    """Soft the mask edge; the heart of the subject stays fully inverted."""
    import numpy as np
    from PIL import Image, ImageFilter

    if FEATHER_RADIUS <= 0:
        return arr
    image = Image.fromarray((arr * 255.0).astype("uint8"), mode="L")
    image = image.filter(ImageFilter.GaussianBlur(FEATHER_RADIUS))
    return np.asarray(image).astype("float32") / 255.0


def invert_subject_regions(
    images_b64: list[str],
    *,
    frames: int | None = None,
    quality: int = 88,
) -> tuple[list[str], dict, str]:
    """Return ``(frames, info, error)`` with the subject region inverted.

    ``frames`` caps how many of the supplied frames are processed; the rest are
    returned untouched. Every failure returns the ORIGINAL frames plus a reason, so
    the caller can carry on with an honest note instead of losing the caption.
    """
    wanted = [img for img in (images_b64 or []) if img]
    if not wanted:
        return [], {}, "No frames to hide."

    session, error = _session()
    if session is None:
        return list(wanted), {"method": "none"}, error

    import numpy as np
    from PIL import Image

    limit = len(wanted) if frames is None else max(0, min(int(frames), len(wanted)))
    out: list[str] = []
    hidden = 0
    method = ""
    first_reason = ""
    for index, b64 in enumerate(wanted):
        if index >= limit:
            out.append(b64)
            continue
        try:
            raw = base64.b64decode(b64)
            image = Image.open(io.BytesIO(raw)).convert("RGB")
        except Exception as exc:
            log.debug("Anonymise: frame %d could not be decoded: %s", index, exc)
            out.append(b64)
            continue
        mask, mask_error = _mask_for(image, session)
        if mask is None:
            log.info("Anonymise: frame %d passed through (%s)", index, mask_error)
            first_reason = first_reason or mask_error
            out.append(b64)
            continue
        if mask.shape != (image.height, image.width):
            mask = np.asarray(
                Image.fromarray((mask * 255.0).astype("uint8"), mode="L").resize(
                    image.size, Image.BILINEAR
                )
            ).astype("float32") / 255.0
        alpha = _feather(mask)[..., None]
        pixels = np.asarray(image).astype("float32")
        # 255 - pixel inside the subject: identity is destroyed, geometry is not.
        mixed = pixels * (1.0 - alpha) + (255.0 - pixels) * alpha
        result = Image.fromarray(np.clip(mixed, 0, 255).astype("uint8"), mode="RGB")
        buffer = io.BytesIO()
        result.save(buffer, format="JPEG", quality=quality)
        out.append(base64.b64encode(buffer.getvalue()).decode("ascii"))
        hidden += 1
        method = method or "subject inverted"
    if hidden == 0:
        why = f" ({first_reason})" if first_reason else ""
        return list(wanted), {"method": "none"}, (
            f"the subject could not be masked in any frame, so the performer was not "
            f"hidden{why}"
        )
    return out, {"method": method, "frames": hidden}, ""
