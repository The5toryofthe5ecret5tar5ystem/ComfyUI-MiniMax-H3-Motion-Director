# MiniMax H3 Motion Director - Character Replace masked engine helpers (Phase 1).
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""GPU-light core for background-true character replacement windows.

Phase 1 operates on asset mask directories; the H3 sampling pass that consumes
these helpers is wired in the executor slice. Everything here is testable on
CPU (torch only). The noise-mask convention matches the engine everywhere:

    mask value 1.0 = regenerate (the subject)
    mask value 0.0 = keep (the source background)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F

from .replace_spec import ReplaceSpec

MASK_REGENERATE = 1.0
MASK_KEEP = 0.0

# H3 video-VAE temporal layout: one latent token per entry, pixel frames per
# token repeating every 5 tokens (1+4+4+4+4 = 17 pixel frames per 5 tokens).
# Mirrors director.motion_context.FRAME_PER_TOKEN; kept local so replace_engine
# stays dependency-light. Frame index f lives in token t where
# sum(pattern[:t]) <= f < sum(pattern[:t+1]).
H3_FRAME_PER_TOKEN = (1, 4, 4, 4, 4)
_H3_TOKEN_CYCLE_FRAMES = sum(H3_FRAME_PER_TOKEN)  # 17
_H3_REMAINDER_TOKENS = (0, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5)  # r=0..16

_FRAME_RE = re.compile(r"frame_(\d+)(?:\.\w+)?$")


def video_latent_tokens_for_frames(pixel_frames: int) -> int:
    """Number of H3 video latent tokens that cover ``pixel_frames``."""
    frames = max(0, int(pixel_frames))
    full_cycles = frames // _H3_TOKEN_CYCLE_FRAMES
    remainder = frames - full_cycles * _H3_TOKEN_CYCLE_FRAMES
    return max(0, full_cycles * 5 + _H3_REMAINDER_TOKENS[remainder])


def pixel_frames_for_latent_tokens(latent_tokens: int) -> int:
    """Pixel-frame coverage of ``latent_tokens`` H3 video latent tokens."""
    tokens = max(0, int(latent_tokens))
    full_cycles = tokens // 5
    remainder = tokens - full_cycles * 5
    return full_cycles * _H3_TOKEN_CYCLE_FRAMES + sum(H3_FRAME_PER_TOKEN[:remainder])


def _token_pixel_ranges(latent_tokens: int) -> list[tuple[int, int]]:
    """Per-token half-open pixel ranges [start, end) for ``latent_tokens``."""
    out: list[tuple[int, int]] = []
    cursor = 0
    for token in range(max(0, int(latent_tokens))):
        width = H3_FRAME_PER_TOKEN[token % len(H3_FRAME_PER_TOKEN)]
        out.append((cursor, cursor + width))
        cursor += width
    return out


def pool_mask_to_latent_time(
    mask_hi: torch.Tensor,
    latent_tokens: int,
    *,
    _pad_value: float = 0.0,
) -> torch.Tensor:
    """Aggregate a per-pixel-frame [T,H,W] 0..1 mask onto H3 latent tokens.

    A latent token is marked regenerate (1) when ANY pixel frame it covers is
    marked subject, so a keep (0) token is always fully background - the
    pixel-exact background is only locked where that is guaranteed.
    ``mask_hi`` shorter than the token coverage is repeat-last padded; longer
    input is truncated to the covered range.
    """
    latent_tokens = max(1, int(latent_tokens))
    if mask_hi is None or mask_hi.ndim != 3 or int(mask_hi.shape[0]) <= 0:
        raise ValueError(f"pool mask expects [T,H,W], got {None if mask_hi is None else tuple(mask_hi.shape)}")
    mask = mask_hi.float()
    covered = pixel_frames_for_latent_tokens(latent_tokens)
    have = int(mask.shape[0])
    if have < covered:
        tail = mask[-1:].repeat(covered - have, 1, 1)
        mask = torch.cat([mask, tail], dim=0)
    elif have > covered:
        mask = mask[:covered]
    ranges = _token_pixel_ranges(latent_tokens)
    pooled = torch.stack([mask[start:end].amax(dim=0) for start, end in ranges], dim=0)
    return pooled.clamp(0.0, 1.0).contiguous()


def snap_window_length(frames: int) -> int:
    """Snap a requested window length to a valid MiniMax H3 frame count (% 17 == 5)."""
    from .frame_align import minimax_align_frame_count

    return max(1, minimax_align_frame_count(max(1, int(frames))))


def replace_windows_in_user_order(timeline: dict) -> list[dict[str, Any]]:
    """Replace windows in JSON list order (non-contiguous / out-of-order allowed).

    Returns items: {"start": int, "length": int (snapped), "raw": segment dict}.
    Segments without an explicit start/length are skipped.
    """
    windows: list[dict[str, Any]] = []
    for raw in timeline.get("segments") or []:
        if not isinstance(raw, dict):
            continue
        try:
            start = max(0, int(raw.get("start") or 0))
        except (TypeError, ValueError):
            start = 0
        try:
            if raw.get("end") is not None and "end" in raw:
                length = max(0, int(raw["end"]) - start)
            else:
                length = max(0, int(raw.get("length") or 0))
        except (TypeError, ValueError):
            length = 0
        if length <= 0:
            continue
        windows.append({"start": start, "length": snap_window_length(length), "raw": raw})
    return windows


def resolve_segment_audio_policy(default_policy: str, spec: ReplaceSpec | None) -> str:
    """Per-segment audio override over the job default (source|generate|none)."""
    if default_policy not in ("source", "generate", "none"):
        default_policy = "source"
    if spec is None:
        return default_policy
    policy = str(spec.audio_policy or "").strip().lower()
    if policy not in ("source", "generate", "none"):
        return default_policy
    return policy


def _gaussian_kernel_2d(radius: int, sigma: float) -> torch.Tensor:
    radius = max(1, int(radius))
    sigma = max(0.1, float(sigma))
    coords = torch.arange(-radius, radius + 1, dtype=torch.float32)
    kernel_1d = torch.exp(-(coords ** 2) / (2.0 * sigma * sigma))
    kernel_1d = kernel_1d / kernel_1d.sum()
    kernel = kernel_1d[:, None] * kernel_1d[None, :]
    return kernel / kernel.sum()


def gaussian_blur_frames(frames: torch.Tensor, sigma: float) -> torch.Tensor:
    """Spatial gaussian blur of [T, C, H, W] (or [T, H, W] treated as 1 channel)."""
    if sigma <= 0.0:
        return frames.clone()
    source = frames
    if frames.ndim == 3:
        source = frames.unsqueeze(1)
    if source.ndim != 4:
        raise ValueError(f"gaussian blur expects 3D/4D frames, got {tuple(frames.shape)}")
    t, c, h, w = source.shape
    radius = max(1, int(round(sigma * 3)))
    kernel = _gaussian_kernel_2d(radius, sigma)  # [2r+1, 2r+1]
    k = int(kernel.shape[0])
    # Depthwise: one shared kernel per channel, groups=c.
    weight = kernel.view(1, 1, k, k).repeat(c, 1, 1, 1)
    blurred = F.conv2d(
        source,
        weight,
        padding=k // 2,
        groups=c,
    )
    return blurred.squeeze(1) if frames.ndim == 3 else blurred


def load_mask_window(mask: Any, start_frame: int, length: int) -> torch.Tensor | None:
    """Load a per-frame binary mask window as float [T, H, W] (1 = subject).

    ``kind == "frames"``: a directory of PNG masks, one per source frame, named
    ``frame_%08d.png``. ``mask.offset`` rebases the directory (a rebased mask
    set written from source frame ``offset`` onward maps file ``frame_i`` to
    source frame ``offset + i``). Returns None when any window frame is missing.
    """
    if not isinstance(mask, dict) or str(mask.get("kind") or "none").strip().lower() != "frames":
        return None
    root = Path(str(mask.get("dir") or "")).expanduser()
    if not root.is_absolute():
        # Best-effort ComfyUI input-directory fallback for relative paths.
        try:
            import folder_paths  # type: ignore

            base = Path(str(folder_paths.get_input_directory() or ""))
            candidate = base / root
            if candidate.is_dir():
                root = candidate
        except Exception:
            pass
    if not root.is_dir():
        return None
    offset = int(mask.get("offset") or 0)
    by_index: dict[int, Path] = {}
    for path in root.iterdir():
        match = _FRAME_RE.match(path.name)
        if match:
            by_index[int(match.group(1))] = path
    if not by_index:
        return None

    try:
        import numpy as np
        from PIL import Image
    except Exception:  # pragma: no cover - both are repo requirements
        return None

    frames: list[torch.Tensor] = []
    for local in range(int(start_frame) - offset, int(start_frame) - offset + int(length)):
        path = by_index.get(local)
        if path is None:
            return None
        try:
            with Image.open(path) as img:
                gray = img.convert("L")
                arr = torch.from_numpy(np.asarray(gray, dtype=np.float32)) / 255.0
        except Exception:
            return None
        frames.append((arr > 0.5).float())
    return torch.stack(frames, dim=0)


def load_mask_window_with_lead(
    mask: Any,
    *,
    start_frame: int,
    nominal_length: int,
    lead_frames: int = 0,
) -> torch.Tensor | None:
    """Load a replace mask window extended backward by ``lead_frames``.

    ``start_frame`` / ``nominal_length`` describe the nominal window (the
    exported frames). When ``lead_frames > 0`` the returned mask is
    ``lead_frames + nominal_length`` frames long: it first tries the real asset
    frames covering ``[start-lead, start+nominal_length)`` (whole-scene mask
    sets), and otherwise replicates the window's first-frame silhouette over
    the runway head (the regenerated subject settles in place while the source
    keeps the background pixel-exact). Returns None when the nominal window
    itself cannot be loaded.
    """
    lead = max(0, int(lead_frames or 0))
    body = load_mask_window(mask, int(start_frame), int(nominal_length))
    if body is None:
        return None
    if not lead:
        return body
    full = load_mask_window(
        mask, int(start_frame) - lead, int(nominal_length) + lead
    )
    if full is not None and int(full.shape[0]) == int(body.shape[0]) + lead:
        return full
    head = body[:1].repeat(lead, 1, 1)
    return torch.cat([head, body], dim=0)


def to_latent_mask(
    mask_hi: torch.Tensor,
    latent_h: int,
    latent_w: int,
    *,
    grow: int = 0,
    feather: float = 0.0,
) -> torch.Tensor:
    """Downscale a [T, H, W] 0..1 mask to the H3 video-latent grid, then soften.

    Returns [T, latent_h, latent_w] float 0..1 with 1 = regenerate. ``grow``
    dilates (max-pool over 2*grow+1) in token space; ``feather`` applies a
    gaussian blur of sigma ``feather`` tokens (0 = hard).
    """
    mask = mask_hi.float()
    if mask.ndim == 3:
        mask = mask.unsqueeze(1)  # [T,1,H,W]
    if mask.ndim != 4:
        raise ValueError(f"mask must be [T,H,W], got {tuple(mask_hi.shape)}")
    t, _, h, w = mask.shape
    latent_h = max(1, int(latent_h))
    latent_w = max(1, int(latent_w))
    if (h, w) != (latent_h, latent_w):
        mask = F.interpolate(mask, size=(latent_h, latent_w), mode="nearest-exact")
    grow = max(0, int(grow))
    if grow > 0:
        pool = 2 * grow + 1
        mask = F.max_pool2d(mask, kernel_size=pool, stride=1, padding=grow)
    if feather and feather > 0:
        mask = gaussian_blur_frames(mask, float(feather))
    return mask[:, 0].clamp(0.0, 1.0).contiguous()


def negative_anchor_frames(
    frames: torch.Tensor, mask_hi: torch.Tensor
) -> torch.Tensor:
    """Render the subject region as a photographic negative (CGlide recipe).

    ``anchor = frames * (1 - mask) + (1 - frames) * mask`` over the subject
    (regenerate) region while the background stays a normal photograph. Feeding
    this as <Video 1> makes H3 distrust the old-subject pixels and compose the
    reference identity natively instead of pasting the original through an
    inpaint seam.

    ``frames`` is [T, H, W, 3] float 0..1; ``mask_hi`` is [T, H, W] 0..1
    (1 = subject / regenerate). Mask is spatially resized when needed.
    """
    frames = frames.float()
    mask_hi = mask_hi.float()
    if mask_hi.ndim == 2:
        mask_hi = mask_hi.unsqueeze(0)
    if frames.ndim != 4:
        raise ValueError(f"anchor frames must be [T,H,W,3], got {tuple(frames.shape)}")
    if frames.shape[0] != mask_hi.shape[0]:
        raise ValueError("anchor frames and mask frame counts differ")
    mask = mask_hi.unsqueeze(-1)  # [T,H,W,1]
    if tuple(mask.shape[1:3]) != tuple(frames.shape[1:3]):
        m4 = mask.permute(0, 3, 1, 2)
        m4 = F.interpolate(m4, size=tuple(frames.shape[1:3]), mode="nearest-exact")
        mask = m4.permute(0, 2, 3, 1)
    anchor = frames * (1.0 - mask) + (1.0 - frames) * mask
    return anchor.clamp(0.0, 1.0).contiguous()


def sanitize_source_frames(
    frames: torch.Tensor,
    mask_hi: torch.Tensor,
    *,
    method: str = "blur",
    blur_sigma: float = 14.0,
) -> torch.Tensor:
    """Identity-destroy the subject region of the source (echo suppression).

    ``frames`` is [T, H, W, 3] float 0..1; ``mask_hi`` is [T, H, W] 0..1
    (1 = subject). The subject region is replaced with a heavy blur (or an
    invert of the pixels) and alpha-composited with the mask so pose, motion
    and scene remain but the original identity is not present to echo.
    """
    frames = frames.float()
    mask_hi = mask_hi.float()
    if mask_hi.ndim == 2:
        mask_hi = mask_hi.unsqueeze(0)
    if frames.shape[0] != mask_hi.shape[0]:
        raise ValueError("frames and mask frame counts differ")
    t = int(frames.shape[0])
    perm = frames.permute(0, 3, 1, 2)  # [T,3,H,W]
    if method == "invert":
        altered = 1.0 - perm
    else:
        altered = gaussian_blur_frames(perm, float(blur_sigma))
    mask = mask_hi.unsqueeze(1)  # [T,1,H,W]
    if tuple(mask.shape[-2:]) != tuple(perm.shape[-2:]):
        mask = F.interpolate(mask, size=tuple(perm.shape[-2:]), mode="nearest-exact")
    blended = perm * (1.0 - mask) + altered * mask
    return blended.permute(0, 2, 3, 1).contiguous()
