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

    Phase 1 supports ``kind="frames"`` (asset mask directory, one PNG per
    source frame, 0 = background, 255 = subject). ``sam3`` is added in Phase 2.
    ``grow``/``feather`` run in H3 latent-token space after downscale.
    """

    kind: str = "none"      # "none" | "frames" (Phase 2 adds "sam3")
    dir: str = ""           # frames directory (or sidecar folder)
    offset: int = 0         # frames in dir are rebased to this source frame
    grow: int = 0           # token-space dilation of the regenerate region
    feather: float = 0.0    # gaussian sigma in token space (0 = hard edge)

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "dir": self.dir,
            "offset": int(self.offset or 0),
            "grow": int(self.grow or 0),
            "feather": float(self.feather or 0.0),
        }

    @staticmethod
    def from_json(raw: Any) -> "ReplaceMaskSpec":
        if not isinstance(raw, dict):
            return ReplaceMaskSpec()
        kind = str(raw.get("kind") or raw.get("mode") or "none").strip().lower()
        if kind not in ("none", "frames"):
            kind = "none"

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
        )


@dataclass
class ReplaceSpec:
    enabled: bool = False
    audio_policy: str = "source"               # AUDIO_POLICIES
    mask: ReplaceMaskSpec = field(default_factory=ReplaceMaskSpec)
    lead: int = DEFAULT_REPLACE_LEAD_FRAMES    # pre-roll runway frames (0 = off)
    sam_prompts: list[str] = field(default_factory=list)  # Phase 2 (stored only)
    note: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "audio_policy": self.audio_policy,
            "lead": max(0, int(self.lead or 0)),
            "mask": self.mask.to_json(),
            "sam_prompts": [str(p) for p in (self.sam_prompts or [])],
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
        return ReplaceSpec(
            enabled=bool(raw.get("enabled")),
            audio_policy=policy,
            mask=ReplaceMaskSpec.from_json(raw.get("mask")),
            lead=lead,
            sam_prompts=prompts,
            note=str(raw.get("note") or ""),
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
