# MiniMax H3 Motion Director - Character Replace per-segment spec (Phase 1).
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Character Replace segment configuration.

Replace rides the existing v2v/rv2v video timeline: each segment keeps its
explicit source window (start + length) and identity references, and carries an
optional ``replace`` block describing the masked swap. This module owns the
tolerant parse/serialize of that block plus the audio-policy vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Per-segment audio handling for a replaced window.
#   source   = keep the source track for this window (default)
#   generate = regenerate audio (needs voice refs; slower)
#   none     = mute this window
AUDIO_POLICIES = ("source", "generate", "none")

# Default replace pre-roll ("lead") in source frames: render this many frames
# before the window's nominal start so the regenerated subject has a runway to
# settle into the opening pose. The runway head is trimmed before export and
# never enters the timeline. Set ``lead: 0`` on a window to disable.
DEFAULT_REPLACE_LEAD_FRAMES = 12


@dataclass
class ReplaceMaskSpec:
    """How the subject mask for one window is obtained.

    ``kind="frames"`` (Phase 1) reads an asset mask directory (one PNG per
    source frame, 0 = background, 255 = subject). ``kind="sam3"`` (Phase 2)
    auto-segments the window's real source frames at render time from the
    window's ``sam_prompts`` (no files). ``grow``/``feather`` run in H3
    latent-token space after downscale.
    """

    kind: str = "none"      # "none" | "frames" | "sam3"
    dir: str = ""           # frames directory (or sidecar folder); unused by sam3
    offset: int = 0         # frames in dir are rebased to this source frame
    grow: int = 0           # token-space dilation of the regenerate region
    feather: float = 0.0    # gaussian sigma in token space (0 = hard edge)
    obj_id: int = 1         # SAM3 tracked-object id (kind == "sam3")
    render: str = "anchor"  # "anchor" (negative-region full re-render) | "inpaint" (noise-mask keep)

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "dir": self.dir,
            "offset": int(self.offset or 0),
            "grow": int(self.grow or 0),
            "feather": float(self.feather or 0.0),
            "obj_id": max(1, int(self.obj_id or 1)),
            "render": self.render if self.render in ("anchor", "inpaint") else "anchor",
        }

    @staticmethod
    def from_json(raw: Any) -> "ReplaceMaskSpec":
        if not isinstance(raw, dict):
            return ReplaceMaskSpec()
        kind = str(raw.get("kind") or raw.get("mode") or "none").strip().lower()
        if kind not in ("none", "frames", "sam3"):
            kind = "none"
        render = str(raw.get("render") or raw.get("strategy") or "anchor").strip().lower()
        if render not in ("anchor", "inpaint"):
            render = "anchor"

        def _int(key: str, default: int = 0) -> int:
            try:
                return int(raw.get(key) or default)
            except (TypeError, ValueError):
                return default

        def _float(key: str, default: float = 0.0) -> float:
            try:
                return float(raw.get(key) if raw.get(key) is not None else default)
            except (TypeError, ValueError):
                return default

        return ReplaceMaskSpec(
            kind=kind,
            dir=str(raw.get("dir") or raw.get("folder") or "").strip(),
            offset=_int("offset"),
            grow=max(0, _int("grow")),
            feather=max(0.0, _float("feather")),
            obj_id=max(1, _int("obj_id", 1)),
            render=render,
        )


@dataclass
class ReplaceSpec:
    enabled: bool = False
    audio_policy: str = "source"               # AUDIO_POLICIES
    mask: ReplaceMaskSpec = field(default_factory=ReplaceMaskSpec)
    lead: int = DEFAULT_REPLACE_LEAD_FRAMES    # pre-roll runway frames (0 = off)
    sam_prompts: list[str] = field(default_factory=list)  # Phase 2 (stored only)
    note: str = ""
    # Optional click/box subject seeding (SAM3 visual prompt) for kind == "sam3".
    # pick_box is a single normalized box [xmin, ymin, width, height] in 0..1 on
    # the frame at pick_frame (index into the mask window; -1 = true window start
    # after the lead head). When set, SAM3 is seeded with this box instead of
    # (or as the first attempt before) the text prompts.
    pick_box: list[float] | None = None
    pick_frame: int = -1

    def to_json(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "audio_policy": self.audio_policy,
            "lead": max(0, int(self.lead or 0)),
            "mask": self.mask.to_json(),
            "sam_prompts": [str(p) for p in (self.sam_prompts or [])],
            "pick": {
                "box": [float(v) for v in (self.pick_box or [])],
                "frame": int(self.pick_frame if self.pick_frame is not None else -1),
            } if self.pick_box else None,
        }

    @staticmethod
    def from_json(raw: Any) -> "ReplaceSpec":
        if not isinstance(raw, dict):
            return ReplaceSpec()
        policy = str(raw.get("audio_policy") or raw.get("audioPolicy") or "source").strip().lower()
        if policy not in AUDIO_POLICIES:
            policy = "source"
        prompts = [
            str(p)
            for p in (raw.get("sam_prompts") or raw.get("samPrompts") or [])
            if str(p).strip()
        ]
        lead = DEFAULT_REPLACE_LEAD_FRAMES
        for key in ("lead", "pre_roll", "preRoll", "lead_frames", "leadFrames"):
            if key in raw:
                try:
                    lead = max(0, int(raw[key]))
                except (TypeError, ValueError):
                    lead = DEFAULT_REPLACE_LEAD_FRAMES
                break
        pick_box: list[float] | None = None
        pick_frame = -1
        pick_raw = raw.get("pick")
        if isinstance(pick_raw, dict):
            box_raw = pick_raw.get("box") or pick_raw.get("boxes")
            if isinstance(box_raw, (list, tuple)) and len(box_raw) == 4:
                try:
                    vals = [float(v) for v in box_raw]
                except (TypeError, ValueError):
                    vals = []
                if len(vals) == 4 and all(v == v and 0.0 <= v <= 1.0 for v in vals):
                    if vals[2] > 0.0 and vals[3] > 0.0:
                        pick_box = [vals[0], vals[1], min(vals[2], 1.0 - vals[0]), min(vals[3], 1.0 - vals[1])]
            try:
                pick_frame = max(-1, int(pick_raw.get("frame", pick_raw.get("frameIndex", -1)) or -1))
            except (TypeError, ValueError):
                pick_frame = -1
        return ReplaceSpec(
            enabled=bool(raw.get("enabled")),
            audio_policy=policy,
            mask=ReplaceMaskSpec.from_json(raw.get("mask")),
            lead=lead,
            sam_prompts=prompts,
            note=str(raw.get("note") or ""),
            pick_box=pick_box,
            pick_frame=pick_frame,
        )


def parse_replace_spec(segment_raw: Any) -> ReplaceSpec:
    """Read the per-segment replace block (``replace`` / ``characterReplace``)."""
    if not isinstance(segment_raw, dict):
        return ReplaceSpec()
    block = segment_raw.get("replace")
    if block is None:
        block = segment_raw.get("characterReplace") or segment_raw.get("character_replace")
    if block is None:
        return ReplaceSpec()
    spec = ReplaceSpec.from_json(block)
    return spec if spec.enabled else ReplaceSpec()
