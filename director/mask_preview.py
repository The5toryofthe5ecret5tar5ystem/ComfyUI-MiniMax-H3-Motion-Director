# MiniMax H3 Motion Director - mask sanity-check preview compose helpers.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Side-by-side JPEG composition for the Live Preview "Mask check" card.

Shared by the executor (sends a card automatically right after a window mask
is prepared) and the per-window "Test mask" route (lets the user run SAM3 on a
single window and inspect the result without rendering).
"""

from __future__ import annotations

import base64
import io
from typing import Any

import torch


def compose_mask_check_jpeg(
    visible,
    mask_vis,
    motion_ref=None,
    lead=0,
    ref_label: str = "motion ref (negative/blur)",
):
    """Side-by-side JPEG sanity check: source | subject overlay | ref panel.

    ``visible`` [T,H,W,3], ``mask_vis`` [T,H,W] 0..1 and ``motion_ref``
    [T,H,W,3] are the prepared window tensors. Only frame ``lead`` (the first
    real window frame, after the pre-roll head) is drawn. Returns a
    ``data:image/jpeg;base64,...`` URI or None on any failure.
    """
    import numpy as np
    from PIL import Image, ImageDraw

    def _frame(t):
        if t is None:
            return None
        return (
            t.detach().float().cpu().clamp(0.0, 1.0)
            .mul(255.0).round().to(torch.uint8).numpy()
        )

    def _pil(a):
        return Image.fromarray(a, "RGB")

    if visible is None or int(visible.shape[0]) <= 0:
        return None
    idx = int(min(max(0, int(lead or 0)), int(visible.shape[0]) - 1))
    src = _frame(visible[idx : idx + 1][0])
    if src is None:
        return None
    ov = src.copy()
    has_mask = mask_vis is not None and idx < int(mask_vis.shape[0])
    if has_mask:
        m = mask_vis[idx].detach().float().cpu().numpy()
        sel = m > 0.5
        if sel.any():
            blend = (
                ov[sel].astype(np.float32) * 0.30
                + np.array([235.0, 70.0, 70.0], dtype=np.float32) * 0.70
            ).astype(np.uint8)
            ov[sel] = blend
    ref = _frame(motion_ref[idx : idx + 1][0]) if motion_ref is not None else None
    h = 200

    def _scale(a):
        p = _pil(a)
        p.thumbnail((999, h))
        return p

    a = _scale(src)
    b = _scale(ov)
    c = _scale(ref) if ref is not None else a
    gap = 3
    lab_h = 16
    W = a.width + b.width + c.width + gap * 4
    canvas = Image.new("RGB", (W, h + 6 + lab_h), "#14161a")

    def _paste(p, x, label):
        canvas.paste(p, (x, 4))
        d = ImageDraw.Draw(canvas)
        d.text((x + 3, h + 7), label, fill=(170, 190, 170))

    x = gap
    _paste(a, x, "source")
    x += a.width + gap
    _paste(b, x, "subject overlay" if has_mask else "no subject mask!")
    x += b.width + gap
    _paste(c, x, str(ref_label))
    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=82)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def mask_coverage(mask_vis) -> dict[str, Any] | None:
    """Coverage summary of a [T,H,W] 0..1 mask: mean, regen_frames, total."""
    if mask_vis is None or int(mask_vis.shape[0]) <= 0:
        return None
    try:
        _m = mask_vis.detach().float()
        return {
            "mean": float(_m.mean()),
            "regen_frames": int((_m.amax(dim=(1, 2)) > 0.5).sum().item()),
            "total": int(_m.shape[0]),
        }
    except Exception:
        return {"mean": 0.0, "regen_frames": 0, "total": int(mask_vis.shape[0])}
