# MiniMax H3 Motion Director - anchor ladder (P1, soft mode).
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Anchor ladder: pre-generated boundary anchors for segment fills.

A *boundary anchor* is the settled pose at a segment boundary. This module plans
one anchor per boundary from the timeline's ``anchors`` block, renders each as a
short chunk (default 22 frames ~= 0.92 s) from the segment's own references, and
then injects the resolved frames into the fill segments as extra ``<Picture N>``
references plus the matching prompt lines.

Why: measured on a 6x7.3 s A/B (``docs/ANCHOR_LADDER_PROPOSAL.md``), chained
fills hold for ~3 segments and then collapse (frame-histogram correlation vs
segment 1: 0.41 at segment 6), while anchor-locked fills stay flat (0.77) and
drift the room/lighting least. The anchor pass costs ~10 % of the fill pass.

P1 scope (this file + the executor hook + the two plan builders):

* ``mode: "soft"`` only - anchors arrive as reference pictures, so character
  references and audio stay intact and no new node/conditioning path is needed.
* payload/config driven: ``timeline_data["anchors"]``. No UI yet (P2).
* anchors are cached as PNG files + sidecar JSON next to the segment caches, so
  a re-run (or Resume) reuses approved anchors instead of re-rendering them.

Payload shape::

    "anchors": {
      "mode": "soft",             # off | soft (hard is P4)
      "chunkFrames": 22,          # 17k+5 grid; snapped up
      "seedBase": 4242,           # per-boundary seed = seedBase + index
      "seeds": [101, 102, ...],   # optional explicit per-boundary seeds
      "beats": ["...", "..."],    # optional, len == segments + 1 (boundary poses)
      "open": "...",              # optional beat for boundary 0
      "promptTemplate": "...",    # optional; {{shared}} {{beat}} {{index}}
      "injectPrompt": true,       # expand {{anchor_in}}/{{anchor_out}} / append lines
      "renderPass": true,         # false = reuse on-disk anchors only
      "keepAudio": false          # anchor chunks are silent by design
    }

Per segment (optional): ``anchorPrompt`` (this segment's END pose, used as the
next boundary's beat), ``anchorIn``/``anchorOut`` (boundary index overrides).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.director.anchors")

ANCHOR_MODE_OFF = "off"
ANCHOR_MODE_SOFT = "soft"
ANCHOR_MODE_HARD = "hard"  # reserved (P4); treated as soft for now
ANCHOR_MODES = (ANCHOR_MODE_OFF, ANCHOR_MODE_SOFT, ANCHOR_MODE_HARD)

DEFAULT_CHUNK_FRAMES = 22
MIN_CHUNK_FRAMES = 5
DEFAULT_SEED_BASE = 4242
SIDECAR_SUFFIX = ".json"

INJECT_MARKER_IN = "{{anchor_in}}"
INJECT_MARKER_OUT = "{{anchor_out}}"

DEFAULT_BEAT = "holds a calm, natural pose, looking toward the camera"

ANCHOR_IN_LINE = (
    "<Picture {tag}> is the FIRST frame of this shot: open on exactly that pose, "
    "framing and lighting, and continue from it."
)
ANCHOR_OUT_LINE = (
    "<Picture {tag}> is the pose this shot must END on: arrive exactly at it, "
    "keeping her wardrobe, hair and the lighting identical throughout."
)

DEFAULT_PROMPT_TEMPLATE = (
    "{shared}\n\n"
    "summary:\n"
    "Single quiet beat: {beat}\n\n"
    "detailed_description:\n"
    "Live-action, first-person POV at eye height, steady camera, the same location "
    "and lighting as the surrounding shots. <Subject 1> {beat}\n"
    "Audio: calm room tone and soft breathing."
)


# --------------------------------------------------------------------------- #
# grid + paths
# --------------------------------------------------------------------------- #
def snap_h3_length(frames: int) -> int:
    """Snap ``frames`` up to H3's 17k+5 frame grid (min 5)."""
    value = int(frames or 0)
    if value <= MIN_CHUNK_FRAMES:
        return MIN_CHUNK_FRAMES
    k = -(-(value - MIN_CHUNK_FRAMES) // 17)  # ceil division
    return 17 * int(k) + MIN_CHUNK_FRAMES


def anchor_file_name(index: int, seed: int, *, variant: int = 1, chunk_frames: int = 0) -> str:
    base = f"A{int(index):02d}_s{int(seed)}_v{int(variant)}"
    if chunk_frames:
        base += f"_f{int(chunk_frames)}"
    return base + ".png"


def resolve_item_path(item: "AnchorItem", root: Path | str | None) -> Path | None:
    """Absolute path for an item's PNG; items may also carry an explicit path."""
    if item.path:
        return Path(item.path)
    if root is None:
        return None
    return Path(root) / anchor_file_name(item.index, item.seed, variant=item.variant,
                                         chunk_frames=item.chunk_frames)


def free_anchor_indices(segment, count: int = 2, *, max_images: int = 9) -> list[int]:
    """First free reference-picture indices for this segment (may be short).

    Scans from 0 upward so gaps left by removed references are reused, exactly
    like the reference compiler assigns slots.
    """
    used = {int(getattr(ref, "index", -1)) for ref in (getattr(segment, "refs", None) or [])}
    out: list[int] = []
    candidate = 0
    while len(out) < count and candidate < max_images:
        if candidate not in used:
            out.append(candidate)
        candidate += 1
    return out


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
@dataclass
class AnchorItem:
    index: int
    seed: int
    beat: str
    chunk_frames: int = DEFAULT_CHUNK_FRAMES
    variant: int = 1
    path: str = ""
    status: str = "pending"   # pending | ready | approved | rejected

    def merged_beat(self) -> str:
        return (self.beat or "").strip() or DEFAULT_BEAT


@dataclass
class DraftPass:
    """Cheap "does the story work?" pass: the fills at reduced resolution/steps."""

    enabled: bool = False
    scale: float = 0.5
    steps: int = 0

    @classmethod
    def parse(cls, value: Any) -> "DraftPass | None":
        if not isinstance(value, dict):
            return None
        try:
            scale = float(value.get("scale") or 0.5)
        except (TypeError, ValueError):
            scale = 0.5
        try:
            steps = int(value.get("steps") or 0)
        except (TypeError, ValueError):
            steps = 0
        return cls(
            enabled=bool(value.get("enabled", False)),
            scale=min(1.0, max(0.1, scale)),
            steps=max(0, min(64, steps)),
        )


@dataclass
class AnchorPlan:
    mode: str = ANCHOR_MODE_OFF
    chunk_frames: int = DEFAULT_CHUNK_FRAMES
    depth: int = 0
    candidates: int = 1
    inject_prompt: bool = True
    render_pass: bool = True
    pre_roll_only: bool = False
    force_render: bool = False
    only_indices: tuple[int, ...] = ()
    selected_indices: tuple[int, ...] | None = None
    draft: "DraftPass | None" = None
    prompt_template: str = ""
    items: list[AnchorItem] = field(default_factory=list)

    @property
    def enabled(self) -> bool:
        if self.mode not in (ANCHOR_MODE_SOFT, ANCHOR_MODE_HARD):
            return False
        if not self.items:
            return False
        # An explicit empty selection means "no boundary participates".
        return self.selected_indices != ()

    def is_selected(self, index: Any) -> bool:
        """True when this boundary is part of the ladder the user asked for."""
        if self.selected_indices is None:
            return True
        try:
            return int(index) in self.selected_indices
        except (TypeError, ValueError):
            return False

    @property
    def boundary_count(self) -> int:
        return len(self.items)

    def item(self, index: Any) -> AnchorItem | None:
        if index is None:
            return None
        try:
            idx = int(index)
        except (TypeError, ValueError):
            return None
        for item in self.items:
            if item.index == idx:
                return item
        return None


def _clean_str(value: Any) -> str:
    return str(value or "").strip()


def _clean_index_list(value: Any) -> tuple[int, ...]:
    """Normalize ``anchors.onlyIndices`` into a sorted tuple of boundary indices."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return ()
    if isinstance(value, (int, float, str)):
        value = [value]
    out: list[int] = []
    for entry in value:
        try:
            index = int(entry)
        except (TypeError, ValueError):
            continue
        if index >= 0 and index not in out:
            out.append(index)
    return tuple(sorted(out))


# Strings accepted in ``anchors.boundaries`` for the two presets.
_BOUNDARY_ALL_ALIASES = ("all", "every", "every-boundary", "*")
_BOUNDARY_BOOKEND_ALIASES = ("bookends", "bookend", "ends", "first-last", "final")
_BOUNDARY_NONE_ALIASES = ("none", "off", "no", "no-boundaries")


def _parse_boundary_selection(value: Any, *, boundary_max: int) -> tuple[int, ...] | None:
    """Parse ``anchors.boundaries`` -> ``None`` (all) or the participating indices.

    ``"all"``/absent selects every boundary; ``"bookends"`` selects the opening
    (0) and closing (``boundary_max``) pose; ``"none"`` selects nothing; an
    explicit list is filtered to indices that exist in this timeline.
    """
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if not text or text in _BOUNDARY_ALL_ALIASES:
            return None
        if text in _BOUNDARY_BOOKEND_ALIASES:
            return (0, int(boundary_max)) if int(boundary_max) > 0 else (0,)
        if text in _BOUNDARY_NONE_ALIASES:
            return ()
        return tuple(sorted({i for i in _clean_index_list(text) if 0 <= i <= int(boundary_max)})) or ()
    if isinstance(value, (list, tuple, set)):
        cleaned = tuple(sorted({i for i in _clean_index_list(value) if 0 <= i <= int(boundary_max)}))
        return cleaned or ()  # an explicit list always means "exactly these"
    return None


def parse_anchor_config(
    timeline: dict | None,
    segments: Iterable[Any],
    *,
    default_chunk_frames: int = DEFAULT_CHUNK_FRAMES,
) -> AnchorPlan | None:
    """Parse ``timeline["anchors"]`` into an :class:`AnchorPlan` (None when off)."""
    block = (timeline or {}).get("anchors")
    if not isinstance(block, dict):
        return None
    mode = _clean_str(block.get("mode") or ANCHOR_MODE_OFF).lower()
    if mode not in ANCHOR_MODES:
        log.warning("Unknown anchors.mode %r; anchors disabled.", mode)
        return None
    if mode == ANCHOR_MODE_OFF:
        return None

    seg_list = list(segments or [])
    count = len(seg_list)
    if count <= 0:
        return None

    chunk = snap_h3_length(block.get("chunkFrames") or block.get("chunk_frames") or default_chunk_frames)
    seed_base = int(block.get("seedBase") or block.get("seed_base") or DEFAULT_SEED_BASE)
    beats = [str(b or "") for b in (block.get("beats") or [])]
    explicit_seeds = list(block.get("seeds") or [])
    candidates = max(1, min(4, int(block.get("candidates") or 1)))
    only_raw = block.get("onlyIndices")
    if only_raw is None:
        only_raw = block.get("only_indices")
    only_indices = _clean_index_list(only_raw)
    selected_indices = _parse_boundary_selection(
        block.get("boundaries", block.get("boundarySelection")), boundary_max=count,
    )

    items: list[AnchorItem] = []
    for boundary in range(count + 1):
        if boundary < len(explicit_seeds):
            seed = int(explicit_seeds[boundary])
        else:
            seed = seed_base + boundary
        if boundary < len(beats) and beats[boundary].strip():
            beat = beats[boundary]
        elif boundary == 0:
            beat = _clean_str(block.get("open"))
        elif boundary == count:
            beat = _clean_str(getattr(seg_list[boundary - 1], "anchor_prompt", "")) or _clean_str(block.get("close"))
        else:
            beat = _clean_str(getattr(seg_list[boundary - 1], "anchor_prompt", ""))
        items.append(AnchorItem(index=boundary, seed=seed, beat=beat, chunk_frames=chunk))

    plan = AnchorPlan(
        mode=mode,
        chunk_frames=chunk,
        depth=max(0, int(block.get("depth") or 0)),
        candidates=candidates,
        inject_prompt=bool(block.get("injectPrompt", block.get("inject_prompt", True))),
        render_pass=bool(block.get("renderPass", block.get("render_pass", True))),
        pre_roll_only=bool(block.get("preRollOnly", block.get("pre_roll_only", False))),
        force_render=bool(block.get("forceRender", block.get("force_render", False))),
        only_indices=only_indices,
        selected_indices=selected_indices,
        draft=DraftPass.parse(block.get("draft")),
        prompt_template=_clean_str(block.get("promptTemplate") or block.get("prompt_template")),
        items=items,
    )

    # Per-segment boundary overrides (anchorIn / anchorOut), defaulted to the
    # natural mapping: segment i owns boundary i (its open) and boundary i+1
    # (its close).
    for position, seg in enumerate(seg_list):
        raw_in = getattr(seg, "anchor_in", None)
        raw_out = getattr(seg, "anchor_out", None)
        seg.anchor_in = position if raw_in is None else int(raw_in)
        seg.anchor_out = (position + 1) if raw_out is None else int(raw_out)
    return plan


# --------------------------------------------------------------------------- #
# prompt helpers
# --------------------------------------------------------------------------- #
def anchor_prompt(item: AnchorItem, *, shared_prompt: str, template: str = "") -> str:
    """Prompt used to render one boundary anchor chunk."""
    body = (template or DEFAULT_PROMPT_TEMPLATE)
    text = (
        body.replace("{shared}", (shared_prompt or "").strip())
        .replace("{beat}", item.merged_beat())
        .replace("{index}", str(item.index))
    )
    for marker in ("{{shared}}", "{{beat}}", "{{index}}"):
        text = text.replace(marker, "")
    return text


# --------------------------------------------------------------------------- #
# storyboard (pre-roll animatic)
# --------------------------------------------------------------------------- #
DEFAULT_STORYBOARD_HOLD = 12  # frames each boundary pose is held (~0.5 s at 24 fps)


def storyboard_frames(
    tensors: dict[int, Any],
    *,
    order: Iterable[int] | None = None,
    hold_frames: int = DEFAULT_STORYBOARD_HOLD,
) -> Any | None:
    """Animatic of the boundary anchors: each pose held for ``hold_frames`` frames.

    Returns an IMAGE batch ``[F, H, W, C]`` in boundary order so it can travel
    the normal video path (CreateVideo / SaveVideo) - the story skeleton the
    user reviews before paying for the fills.
    """
    import torch

    keys = sorted(int(key) for key in tensors) if order is None else [int(key) for key in order]
    hold = max(1, int(hold_frames))
    rows: list[Any] = []
    size: tuple[int, int] | None = None
    for key in keys:
        tile = tensors.get(key)
        if tile is None or not hasattr(tile, "ndim"):
            continue
        if int(tile.ndim) == 3:
            tile = tile[None, ...]
        if int(tile.ndim) != 4 or int(tile.shape[0]) <= 0:
            continue
        frame = tile[-1:]
        height, width = int(frame.shape[1]), int(frame.shape[2])
        if size is None:
            size = (height, width)
        elif (height, width) != size:
            import torch.nn.functional as torch_functional

            frame = torch_functional.interpolate(
                frame.permute(0, 3, 1, 2), size=size, mode="bilinear", align_corners=False,
            ).permute(0, 2, 3, 1)
        rows.append(frame.repeat(hold, 1, 1, 1))
    if not rows:
        return None
    return torch.cat(rows, dim=0).clamp(0.0, 1.0)


def write_contact_sheet(
    tensors: dict[int, Any],
    *,
    items: Iterable["AnchorItem"] | None = None,
    dest: Path | str | None = None,
    columns: int = 0,
    cell: int = 384,
) -> Path | None:
    """Grid PNG of every boundary pose with its index/seed/beat label (best effort)."""
    if dest is None:
        return None
    try:
        import numpy as np
        from PIL import Image, ImageDraw
    except Exception as exc:  # noqa: BLE001 - the sheet is a convenience
        log.warning("anchor ladder: contact sheet unavailable (%s)", exc)
        return None

    lookup = {int(item.index): item for item in (items or [])}
    tiles: list[tuple[str, Any]] = []
    for key in sorted(int(key) for key in tensors):
        tile = tensors.get(key)
        if tile is None or not hasattr(tile, "ndim"):
            continue
        frame = tile[-1] if int(tile.ndim) == 4 else tile
        try:
            array = frame.detach().to("cpu").float().clamp(0, 1).numpy()
        except AttributeError:
            array = np.asarray(frame)
        array = (np.asarray(array) * 255.0 + 0.5).astype("uint8")
        image = Image.fromarray(array).convert("RGB")
        if image.height and int(image.height) != int(cell):
            scale = max(1, int(cell)) / float(image.height)
            image = image.resize(
                (max(1, int(round(image.width * scale))), max(1, int(cell))), Image.LANCZOS,
            )
        item = lookup.get(key)
        label = f"#{key + 1}"
        if item is not None:
            label += f"  seed {int(item.seed)}"
            beat = (item.merged_beat() or "").strip()
            if beat:
                label += f"  {beat[:52]}"
        tiles.append((label, image))
    if not tiles:
        return None

    count = len(tiles)
    columns = int(columns) if int(columns) > 0 else max(1, int(round(count ** 0.5)))
    rows = (count + columns - 1) // columns
    cell_w = max(tile[1].width for tile in tiles)
    cell_h = max(tile[1].height for tile in tiles)
    label_h = 22
    sheet = Image.new("RGB", (columns * cell_w, rows * (cell_h + label_h)), (16, 16, 18))
    draw = ImageDraw.Draw(sheet)
    for position, (label, image) in enumerate(tiles):
        row, column = divmod(position, columns)
        x = column * cell_w + max(0, (cell_w - image.width) // 2)
        y = row * (cell_h + label_h)
        sheet.paste(image, (x, y))
        draw.text((column * cell_w + 6, y + cell_h + 4), label, fill=(220, 220, 220))
    try:
        target = Path(dest)
        target.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(target)
        return target
    except Exception as exc:  # noqa: BLE001 - the sheet is a convenience
        log.warning("anchor ladder: contact sheet write failed for %s (%s)", dest, exc)
        return None


def expand_segment_prompt(
    prompt: str,
    *,
    in_tag: int | None = None,
    out_tag: int | None = None,
    inject: bool = True,
) -> str:
    """Expand ``{{anchor_in}}`` / ``{{anchor_out}}`` (append when absent)."""
    text = prompt or ""
    if not inject:
        return text
    has_in = INJECT_MARKER_IN in text
    has_out = INJECT_MARKER_OUT in text
    in_line = ANCHOR_IN_LINE.format(tag=in_tag) if in_tag else ""
    out_line = ANCHOR_OUT_LINE.format(tag=out_tag) if out_tag else ""
    text = text.replace(INJECT_MARKER_IN, in_line).replace(INJECT_MARKER_OUT, out_line)
    if has_in or has_out:
        return text
    appended = [line for line in (in_line, out_line) if line]
    if not appended:
        return text
    return text.rstrip() + "\n\n" + "\n".join(appended) + "\n"


# --------------------------------------------------------------------------- #
# synthetic render segment
# --------------------------------------------------------------------------- #
def build_anchor_segment(plan, item: AnchorItem):
    """A standalone, source-free ``r2v`` segment that renders one anchor chunk.

    It borrows the references of the segment that *opens* on this boundary (or
    the previous segment for the closing boundary) but carries no context link,
    no continuity and no source clip, so it renders as a fresh standalone shot.
    """
    from .plan import SegmentPlan  # local import: plan.py imports this module
    from .plan import SEGMENT_KIND_GENERATE  # type: ignore[attr-defined]

    segments = list(getattr(plan, "segments", []) or [])
    if not segments:
        raise ValueError("anchor ladder: plan has no segments")
    owner_index = min(item.index, len(segments) - 1)
    owner = segments[owner_index]
    offset = 1000 + int(item.index)
    return SegmentPlan(
        index=offset,
        start_frame=0,
        end_frame=int(item.chunk_frames),
        prompt=anchor_prompt(item, shared_prompt=getattr(plan, "global_prompt", "") or "",
                             template=("" if plan.anchors is None else plan.anchors.prompt_template)),
        task_type=getattr(owner, "task_type", "r2v — 参考主体生视频(Reference to Video)"),
        task_key="r2v",
        use_global=False,
        refs=list(getattr(owner, "refs", None) or []),
        ref_audios=[],
        ref_videos=[],
        negative_prompt=getattr(owner, "negative_prompt", "") or "",
        ui_index=offset,
        anchor_index=int(item.index),
        seed_override=int(item.seed),
        kind=SEGMENT_KIND_GENERATE,
    )


# --------------------------------------------------------------------------- #
# images
# --------------------------------------------------------------------------- #
def anchor_image_tensor(path: Path | str):
    """Load a PNG as a ComfyUI IMAGE tensor ``[1, H, W, 3]`` float 0..1."""
    import numpy as np
    import torch
    from PIL import Image

    with Image.open(path) as img:
        rgb = img.convert("RGB")
        arr = np.asarray(rgb).astype("float32") / 255.0
    return torch.from_numpy(arr)[None, ...]


def save_anchor_image(tensor, path: Path | str) -> bool:
    """Save the last frame of a chunk tensor as PNG (best effort)."""
    try:
        import numpy as np
        from PIL import Image

        frame = tensor
        if hasattr(frame, "ndim") and frame.ndim == 4:
            frame = frame[-1]
        arr = frame.detach().to("cpu").float().clamp(0, 1).numpy()
        arr = (arr * 255.0 + 0.5).astype("uint8")
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(arr).save(dest)
        return True
    except Exception as exc:  # noqa: BLE001 - anchors must never abort a run
        log.warning("anchor ladder: could not save anchor %s (%s)", path, exc)
        return False


def _sidecar_payload(item: AnchorItem, *, status: str) -> dict:
    return {
        "index": int(item.index),
        "seed": int(item.seed),
        "chunk_frames": int(item.chunk_frames),
        "beat": item.merged_beat(),
        "status": status,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "pipeline": "anchor_ladder_v1",
    }


def read_sidecar(path: Path | str) -> dict:
    side = Path(str(path) + SIDECAR_SUFFIX)
    try:
        if side.is_file():
            return json.loads(side.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return {}


def write_sidecar(path: Path | str, item: AnchorItem, *, status: str) -> None:
    try:
        side = Path(str(path) + SIDECAR_SUFFIX)
        side.parent.mkdir(parents=True, exist_ok=True)
        side.write_text(json.dumps(_sidecar_payload(item, status=status), indent=1), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        log.debug("anchor ladder: sidecar write failed for %s (%s)", path, exc)


def anchor_fingerprint(plan) -> str:
    """Stable digest of the anchor set; changes when anchors are re-rolled."""
    anchors = getattr(plan, "anchors", None)
    if anchors is None or not getattr(anchors, "enabled", False):
        return ""
    root = getattr(plan, "anchors_root", None)
    rows: list[dict[str, Any]] = []
    for item in anchors.items:
        path = resolve_item_path(item, root)
        row: dict[str, Any] = {"i": int(item.index), "seed": int(item.seed), "mode": anchors.mode}
        try:
            if path is not None and Path(path).is_file():
                stat = Path(path).stat()
                row["size"] = int(stat.st_size)
                row["mtime"] = int(stat.st_mtime)
        except OSError:
            pass
        rows.append(row)
    blob = json.dumps(
        {
            "rows": rows,
            "sel": sorted(anchors.selected_indices) if anchors.selected_indices is not None else "all",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# passes
# --------------------------------------------------------------------------- #
def load_anchor_tensors(plan, *, root: Path | str | None, warnings: list[str] | None = None,
                        allow_pending: bool = True) -> dict[int, Any]:
    """Load on-disk anchors for every boundary that has one; warn when missing."""
    anchors: AnchorPlan | None = getattr(plan, "anchors", None)
    out: dict[int, Any] = {}
    if anchors is None or not anchors.enabled:
        return out
    for item in anchors.items:
        if not anchors.is_selected(item.index):
            continue  # strict selection: off boundaries are neither rendered nor loaded
        path = resolve_item_path(item, root)
        if path is None or not Path(path).is_file():
            message = (
                f"Anchor {item.index} is not on disk ({path}); that boundary renders without an anchor."
            )
            if warnings is not None:
                warnings.append(message)
            log.warning("anchor ladder: %s", message)
            continue
        out[item.index] = anchor_image_tensor(path)
    _ = allow_pending
    return out


def run_anchor_pass(
    plan,
    *,
    render: Callable[[Any], Any],
    root: Path | str | None,
    reports: list[str] | None = None,
    warnings: list[str] | None = None,
    only: Iterable[int] | None = None,
    force: bool = False,
) -> dict[int, Any]:
    """Render (or load) every boundary anchor; returns ``{boundary_index: tensor}``.

    ``render`` receives a synthetic standalone segment and returns its decoded
    frames ``[F, H, W, C]``. Anchors already on disk are reused, so Resume and
    repeat runs never re-render approved boundaries. ``only`` limits *rendering*
    to those boundaries (the per-cell "render this pose" button) - boundaries
    outside the set are still loaded from disk when present, but never rendered.
    ``force`` re-renders the boundaries in ``only`` even when a PNG already
    exists (iterating on a beat), overwriting it in place.
    """
    anchors: AnchorPlan | None = getattr(plan, "anchors", None)
    out: dict[int, Any] = {}
    if anchors is None or not anchors.enabled:
        return out
    wanted = {int(value) for value in only} if only else None
    rendered = 0
    reused = 0
    failures = 0
    for item in anchors.items:
        if not anchors.is_selected(item.index):
            continue  # strict selection: off boundaries never reach the fills
        path = resolve_item_path(item, root)
        exists = path is not None and Path(path).is_file()
        if wanted is not None and int(item.index) not in wanted:
            if exists:
                try:
                    out[item.index] = anchor_image_tensor(path)
                    reused += 1
                except Exception:  # noqa: BLE001 - an unreadable neighbour is not an error here
                    log.debug("anchor ladder: could not read excluded anchor %s", path)
            continue
        if exists and not (force and (wanted is None or int(item.index) in wanted)):
            try:
                out[item.index] = anchor_image_tensor(path)
                reused += 1
                continue
            except Exception as exc:  # noqa: BLE001 - fall through to re-render
                log.warning("anchor ladder: could not read %s (%s); re-rendering.", path, exc)
        try:
            seg = build_anchor_segment(plan, item)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            message = f"Anchor {item.index} could not be prepared: {exc}"
            if warnings is not None:
                warnings.append(message)
            log.warning("anchor ladder: %s", message)
            continue
        try:
            frames = render(seg)
        except Exception as exc:  # noqa: BLE001 - a failed anchor must not kill the run
            failures += 1
            message = f"Anchor {item.index} failed to render: {exc}"
            if warnings is not None:
                warnings.append(message)
            log.warning("anchor ladder: %s", message)
            continue
        if frames is None or int(getattr(frames, "shape", [0])[0]) <= 0:
            failures += 1
            message = f"Anchor {item.index} produced no frames."
            if warnings is not None:
                warnings.append(message)
            log.warning("anchor ladder: %s", message)
            continue
        if path is None:
            message = (
                f"Anchor {item.index} rendered but has nowhere to be saved (no anchor directory)."
            )
            if warnings is not None:
                warnings.append(message)
            log.warning("anchor ladder: %s", message)
        elif save_anchor_image(frames, path):
            write_sidecar(path, item, status="ready")
        out[item.index] = frames[-1:] if hasattr(frames, "ndim") and frames.ndim == 4 else frames
        rendered += 1
    summary = (
        f"Anchor ladder ({anchors.mode}): {len(out)} boundary anchor(s) ready "
        f"({rendered} rendered, {reused} reused, {failures} failed)."
    )
    if reports is not None:
        reports.append(summary)
    log.info("anchor ladder: %s", summary)
    return out


def apply_injection(
    plan,
    tensors: dict[int, Any],
    *,
    reports: list[str] | None = None,
    warnings: list[str] | None = None,
    max_images: int = 9,
) -> int:
    """Append anchor references + prompt lines to every fill segment."""
    from .plan import SegmentRef  # local import to avoid a cycle

    anchors: AnchorPlan | None = getattr(plan, "anchors", None)
    if anchors is None or not anchors.enabled:
        return 0
    touched = 0
    for seg in getattr(plan, "segments", []) or []:
        idx_in = getattr(seg, "anchor_in", None)
        idx_out = getattr(seg, "anchor_out", None)
        if idx_in is not None and not anchors.is_selected(idx_in):
            idx_in = None
        if idx_out is not None and not anchors.is_selected(idx_out):
            idx_out = None
        tensor_in = tensors.get(int(idx_in)) if idx_in is not None else None
        tensor_out = tensors.get(int(idx_out)) if idx_out is not None else None
        if tensor_in is None and tensor_out is None:
            continue
        slots = free_anchor_indices(seg, count=2, max_images=max_images)
        used: dict[str, int] = {}
        remaining = list(slots)
        for name, tensor in (("in", tensor_in), ("out", tensor_out)):
            if tensor is None or not remaining:
                continue
            index = remaining.pop(0)
            ref = SegmentRef(index=index, tensor=tensor, asset_id=f"anchor:{index}")
            seg.refs = list(getattr(seg, "refs", None) or []) + [ref]
            used[name] = index + 1  # prompt tags are 1-based <Picture N>
        if not used and warnings is not None:
            warnings.append(
                f"Segment {int(getattr(seg, 'index', 0)) + 1}: no free reference slot for its "
                "boundary anchor(s); the segment renders without them."
            )
            continue
        seg.prompt = expand_segment_prompt(
            getattr(seg, "prompt", "") or "",
            in_tag=used.get("in"),
            out_tag=used.get("out"),
            inject=bool(anchors.inject_prompt),
        )
        touched += 1
    if reports is not None:
        reports.append(f"Anchor ladder: {touched} segment(s) conditioned on boundary anchors.")
    if touched:
        log.info("anchor ladder: %d segment(s) conditioned on boundary anchors.", touched)
    return touched


__all__ = [
    "ANCHOR_MODE_OFF",
    "ANCHOR_MODE_SOFT",
    "ANCHOR_MODE_HARD",
    "DEFAULT_CHUNK_FRAMES",
    "DEFAULT_SEED_BASE",
    "AnchorItem",
    "AnchorPlan",
    "snap_h3_length",
    "anchor_file_name",
    "resolve_item_path",
    "free_anchor_indices",
    "parse_anchor_config",
    "anchor_prompt",
    "expand_segment_prompt",
    "build_anchor_segment",
    "anchor_image_tensor",
    "save_anchor_image",
    "read_sidecar",
    "write_sidecar",
    "anchor_fingerprint",
    "load_anchor_tensors",
    "run_anchor_pass",
    "apply_injection",
    "INJECT_MARKER_IN",
    "INJECT_MARKER_OUT",
]
