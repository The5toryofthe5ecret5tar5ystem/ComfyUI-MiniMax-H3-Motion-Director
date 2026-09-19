# MiniMax H3 Motion Director - pre-flight VRAM budgeting.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Estimate whether a segment fits before it is rendered.

The pack could already say *that* a run failed ("ran out of VRAM during H3
sampling") but never *how close* it was, so the only way to learn a project's
ceiling was to lose a segment's worth of GPU time to it. This module answers the
question ahead of time, from the two quantities that actually decide it:

* **Sequence cost** - H3 packs the video into a DiT sequence of
  ``latent_frames x (width/32) x (height/32)`` tokens, and the attention
  workspace grows with that count. This is what makes a 345-frame segment so
  much more expensive than a 175-frame one (3.1x the tokens, not 2x).
* **What is free right now** - the failure mode is not "the model is too big",
  it is "a single contiguous allocation could not be placed".

Both are computable without touching the GPU, which is the point: the check runs
in the Validate route and in the Settings panel before anything is queued.

Provenance of the constants
---------------------------

The token model follows H3's layout - video VAE time compression 4 plus the
initial frame, 32 px patches - using the same latent-frame formula the runtime
already uses (``director.segment_continuity``: ``(frames - 1) // 4 + 1``), so the
estimate and the engine cannot disagree about a segment's shape:

===============  ==============  =================
frames @1376x768  latent frames   video tokens
===============  ==============  =================
175               44              ~45.4k
243               61              ~63.0k
311               78              ~80.5k
345               87              ~89.8k
===============  ==============  =================

``ATTENTION_KB_PER_TOKEN`` is *measured*, not derived: the 345-frame 1376x768
case packed 89,784 video tokens plus 2,064 reference rows into one sequence and
asked sparse int8 attention for a single 2.99 GiB workspace block while 63 MiB
was free - 91,848 tokens at 34.1 KB each, which is what the default below
encodes. It is therefore a calibration constant: better data raises its
accuracy, and :func:`calibrate_attention_kb_per_token` exists to record that
data rather than hard-coding a second guess.

An estimate here is advisory. Nothing in this module changes a project.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

#: H3's video VAE compresses time 4:1 and keeps one initial latent frame.
LATENT_FRAME_DIVISOR = 4
LATENT_FRAME_OFFSET = 1

#: H3 patches (and snaps canvases to) 32 px squares.
SPATIAL_STRIDE = 32

#: Assumed shape of a reference picture when only its long edge is known.
PICTURE_ASPECT = 16.0 / 9.0

#: Measured attention workspace per sequence token (see module docstring).
ATTENTION_KB_PER_TOKEN = 34.1

#: Keep this much of the device free for the rest of ComfyUI + CUDA context.
DEFAULT_RESERVE_GB = 2.0

#: Ratio thresholds against the machine's tier baseline. Both come from the two
#: runs that motivated this module on one machine: a 1.37x shape completed (on
#: the dense fallback), a 1.97x shape did not.
RATIO_TIGHT = 1.3
RATIO_OVER = 1.8

_GB = 1024.0 ** 3


def latent_frames(frames: int) -> int:
    """Latent frames H3's video VAE produces for ``frames`` input frames.

    Same formula as ``director.segment_continuity._latent_time_frames``: the VAE
    compresses 4:1 with the first frame kept, so the estimate agrees with what
    the engine conditions and masks.
    """
    count = max(1, int(frames or 0))
    if int(frames or 0) <= 0:
        return 0
    return (count - 1) // LATENT_FRAME_DIVISOR + LATENT_FRAME_OFFSET


def video_tokens(frames: int, width: int, height: int) -> int:
    """DiT video tokens for a segment of this shape."""
    latent = latent_frames(frames)
    cols = max(0, int(width or 0)) // SPATIAL_STRIDE
    rows = max(0, int(height or 0)) // SPATIAL_STRIDE
    return latent * cols * rows


def picture_tokens(pictures: int, ref_long_edge: int, aspect: float = PICTURE_ASPECT) -> int:
    """DiT tokens one or more reference pictures add at this long edge.

    A picture is resized so its long edge is ``ref_long_edge`` and then
    patchified on the same 32 px grid, which is why the reference size matters
    almost as much as the segment length.
    """
    edge = max(0, int(ref_long_edge or 0))
    count = max(0, int(pictures or 0))
    if edge <= 0 or count <= 0:
        return 0
    cols = max(1, edge // SPATIAL_STRIDE)
    rows = max(1, int(round((edge / aspect) / SPATIAL_STRIDE)))
    return cols * rows * count


def attention_workspace_gb(tokens: int, kb_per_token: float = ATTENTION_KB_PER_TOKEN) -> float:
    """Bytes one attention workspace for ``tokens`` tokens needs, in GiB."""
    return max(0.0, float(tokens or 0)) * float(kb_per_token) * 1024.0 / _GB


def bytes_to_gb(value: Any) -> float:
    try:
        return float(value or 0) / _GB
    except (TypeError, ValueError):
        return 0.0


def device_free_gb(device: int | None = None) -> float | None:
    """Free device memory right now, or None when it cannot be read.

    Lazy torch import keeps this module plain-Python importable, and every
    failure returns None: this is called from OOM handlers, where raising a
    second error would hide the first one.
    """
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        index = torch.cuda.current_device() if device is None else int(device)
        free, _total = torch.cuda.mem_get_info(index)
        return float(free) / _GB
    except Exception:  # noqa: BLE001 - diagnostics only
        return None


def shape_from(
    segment: Any,
    plan: Any = None,
    *,
    context_frames: int = 0,
    label: str = "",
) -> "SegmentShape | None":
    """Best-effort shape for a segment/plan pair, or None when unknowable.

    Used by the OOM handlers, which run while an exception is propagating: every
    attribute read is defensive so a missing field costs the extra detail, never
    the original error.
    """
    try:
        frames = int(getattr(segment, "frame_count", 0) or 0)
        if frames <= 0:
            return None
        width = int(getattr(plan, "width", 0) or 0) or int(getattr(segment, "width", 0) or 0)
        height = int(getattr(plan, "height", 0) or 0) or int(getattr(segment, "height", 0) or 0)
        edge = int(getattr(plan, "ref_max_size", 0) or 0)
        pictures = len(getattr(segment, "refs", None) or [])
        index = int(getattr(segment, "timeline_index", getattr(segment, "index", 0)) or 0)
        return SegmentShape(
            index=index,
            frames=frames,
            width=width,
            height=height,
            pictures=pictures,
            ref_long_edge=edge,
            context_frames=max(0, int(context_frames or 0)),
            label=label or f"S{index + 1}",
        )
    except Exception:  # noqa: BLE001 - diagnostics only
        return None


def suggestions_for(shape: "SegmentShape | None", baselines: dict[str, Any] | None = None) -> list[str]:
    """Fixes for ``shape``, reading the machine's tier when not supplied."""
    if shape is None or int(shape.frames or 0) <= 0:
        return []
    if baselines is None:
        try:
            from .machine_profile import collect_machine_profile

            baselines = collect_machine_profile().get("baselines") or {}
        except Exception:  # noqa: BLE001 - advice must never raise on the OOM path
            baselines = {}
    try:
        return suggest_fit(shape, baselines or {})
    except Exception:  # noqa: BLE001
        return []


@dataclass(frozen=True)
class SegmentShape:
    """One segment's cost-relevant shape."""

    index: int = 0
    frames: int = 0
    width: int = 0
    height: int = 0
    pictures: int = 0
    ref_long_edge: int = 0
    #: Extra frames the sampler sees beyond the segment length (Motion Context
    #: rows plus any source lead-in). Reported separately so the message can
    #: explain the difference between "what you asked for" and "what is sampled".
    context_frames: int = 0
    label: str = ""

    @property
    def sampled_frames(self) -> int:
        return max(0, int(self.frames or 0)) + max(0, int(self.context_frames or 0))

    @property
    def tokens(self) -> int:
        return (video_tokens(self.sampled_frames, self.width, self.height)
                + picture_tokens(self.pictures, self.ref_long_edge))

    @property
    def attention_gb(self) -> float:
        return attention_workspace_gb(self.tokens)

    def describe(self) -> str:
        label = self.label or f"S{self.index + 1}"
        edge = f", {self.pictures} ref(s) at {self.ref_long_edge} px" if self.pictures else ""
        context = (f" ({self.sampled_frames} sampled frames incl. {self.context_frames} context)"
                   if self.context_frames else "")
        return (f"{label}: {self.frames} frames{context} at "
                f"{self.width}x{self.height}{edge}")


@dataclass
class BudgetReport:
    """The verdict for a whole plan, with the numbers that produced it."""

    verdict: str = "unknown"          # ok | tight | over | unknown
    reason: str = ""
    worst: SegmentShape | None = None
    worst_ratio: float = 0.0
    worst_attention_gb: float = 0.0
    budget_gb: float = 0.0
    free_gb: float | None = None
    total_gb: float | None = None
    resident_gb: float = 0.0
    baseline_tokens: int = 0
    baseline_frames: int = 0
    segments: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        worst = self.worst
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "budget_gb": round(self.budget_gb, 2),
            "free_gb": None if self.free_gb is None else round(self.free_gb, 2),
            "total_gb": None if self.total_gb is None else round(self.total_gb, 2),
            "resident_gb": round(self.resident_gb, 2),
            "baseline_frames": self.baseline_frames,
            "baseline_tokens": self.baseline_tokens,
            "ratio": round(self.worst_ratio, 2),
            "attention_gb": round(self.worst_attention_gb, 2),
            "segment": None if worst is None else {
                "index": worst.index,
                "label": worst.label or f"S{worst.index + 1}",
                "frames": worst.frames,
                "context_frames": worst.context_frames,
                "sampled_frames": worst.sampled_frames,
                "width": worst.width,
                "height": worst.height,
                "pictures": worst.pictures,
                "ref_long_edge": worst.ref_long_edge,
                "tokens": worst.tokens,
            },
            "segments": self.segments,
            "notes": list(self.notes),
            "suggestions": list(self.suggestions),
        }


def baseline_tokens(baselines: dict[str, Any], pictures: int = 0) -> int:
    """Tokens of the shape the machine's tier is tuned for."""
    frames = int(baselines.get("segment_frames") or 0)
    width = int(baselines.get("width") or 0)
    height = int(baselines.get("height") or 0)
    edge = int(baselines.get("ref_max_size") or 0)
    return video_tokens(frames, width, height) + picture_tokens(pictures, edge)


def evaluate(
    shapes: Iterable[SegmentShape],
    *,
    baselines: dict[str, Any] | None = None,
    total_gb: float | None = None,
    free_gb: float | None = None,
    resident_gb: float = 0.0,
    reserve_gb: float = DEFAULT_RESERVE_GB,
    selected_only: bool = True,
) -> BudgetReport:
    """Judge a plan's segments against the machine they will run on.

    ``free_gb`` is the strongest signal and is used when known: the failure this
    module exists for was a *placement* failure (2.99 GiB wanted, 63 MiB free),
    not a total-capacity failure. Without it the verdict falls back to the tier
    ratio, which is a shape comparison rather than a capacity one.
    """
    shapes = [s for s in shapes if int(s.frames or 0) > 0]
    report = BudgetReport(
        free_gb=None if free_gb is None else float(free_gb),
        total_gb=None if total_gb is None else float(total_gb),
        resident_gb=float(resident_gb or 0.0),
    )
    if not shapes:
        report.verdict = "unknown"
        report.reason = "No segment shape to check."
        return report

    if total_gb is not None:
        report.budget_gb = max(0.0, float(total_gb) - float(reserve_gb))
    if free_gb is not None:
        report.budget_gb = max(0.0, float(free_gb))

    base = baseline_tokens(baselines or {}, pictures=shapes[0].pictures)
    report.baseline_tokens = base
    report.baseline_frames = int((baselines or {}).get("segment_frames") or 0)

    worst = max(shapes, key=lambda s: s.tokens)
    report.worst = worst
    report.worst_ratio = (worst.tokens / base) if base else 0.0
    report.worst_attention_gb = worst.attention_gb
    report.segments = [
        {
            "index": s.index,
            "label": s.label or f"S{s.index + 1}",
            "frames": s.frames,
            "sampled_frames": s.sampled_frames,
            "tokens": s.tokens,
            "ratio": round((s.tokens / base) if base else 0.0, 2),
            "attention_gb": round(s.attention_gb, 2),
        }
        for s in shapes
    ]

    # 1. Placement: can one attention workspace be allocated at all?
    if free_gb is not None and report.worst_attention_gb > max(0.0, float(free_gb)):
        report.verdict = "over"
        report.reason = (
            f"{worst.describe()} needs about {report.worst_attention_gb:.1f} GB of attention "
            f"workspace in one piece, and only {float(free_gb):.1f} GB is free right now. "
            "This is the shape that fails with 'ran out of VRAM during H3 sampling'."
        )
    elif base <= 0:
        # No machine profile to compare against: report the cost, refuse to judge.
        report.verdict = "unknown"
        report.reason = (
            f"{worst.describe()} needs about {report.worst_attention_gb:.1f} GB of attention "
            "workspace; no machine profile is available to compare that against."
        )
    elif report.worst_ratio > RATIO_OVER:
        report.verdict = "over"
        report.reason = (
            f"{worst.describe()} is {report.worst_ratio:.2f}x the shape this machine's tier is "
            f"tuned for ({report.baseline_frames} frames). Expect a CUDA out-of-memory in sampling."
        )
    elif report.worst_ratio > RATIO_TIGHT:
        report.verdict = "tight"
        report.reason = (
            f"{worst.describe()} is {report.worst_ratio:.2f}x the shape this machine's tier is "
            "tuned for; it can fit, but attention is the first thing to run out of room."
        )
    else:
        report.verdict = "ok"
        report.reason = (
            f"{worst.describe()} is within the shape this machine's tier is tuned for "
            f"({report.baseline_frames} frames, {report.worst_ratio:.2f}x its tokens)."
        )

    if free_gb is not None:
        report.notes.append(
            f"Free right now: {float(free_gb):.1f} GB of "
            f"{'unknown' if total_gb is None else format(float(total_gb), '.1f') + ' GB'}."
        )
    if resident_gb:
        report.notes.append(
            f"Models referenced by the graph: {float(resident_gb):.1f} GB of weights. ComfyUI "
            "stages and unloads them between phases, so this is context rather than a sum."
        )
    if worst.context_frames:
        report.notes.append(
            f"{worst.label or 'The worst segment'} renders {worst.frames} frames but the sampler "
            f"sees {worst.sampled_frames} ({worst.context_frames} Motion Context rows)."
        )

    for suggestion in suggest_fit(worst, baselines or {}):
        report.suggestions.append(suggestion)
    return report


def suggest_fit(shape: SegmentShape, baselines: dict[str, Any]) -> list[str]:
    """Concrete, minimal changes that bring ``shape`` back inside the tier.

    Ordered by how little they change the picture: reference size first (it is a
    conditioning input, not the render), then segment length, then canvas.
    """
    out: list[str] = []
    base = baseline_tokens(baselines, pictures=shape.pictures)
    if not base or shape.tokens <= base * RATIO_TIGHT:
        return out

    target_edge = int(baselines.get("ref_max_size") or 0)
    if target_edge and shape.ref_long_edge and shape.ref_long_edge > target_edge:
        trimmed = SegmentShape(
            index=shape.index, frames=shape.frames, width=shape.width, height=shape.height,
            pictures=shape.pictures, ref_long_edge=target_edge,
            context_frames=shape.context_frames, label=shape.label,
        )
        if trimmed.tokens <= base * RATIO_TIGHT:
            out.append(
                f"Set reference size to {target_edge} px (this machine's baseline) - the "
                "references alone are adding "
                f"{shape.tokens - trimmed.tokens} tokens at {shape.ref_long_edge} px."
            )
            return out
        out.append(
            f"Set reference size to {target_edge} px: brings this shape to "
            f"{trimmed.tokens / base:.2f}x."
        )

    max_frames = int(baselines.get("max_segment_frames") or 0)
    if max_frames and shape.frames > max_frames:
        out.append(
            f"Render at most {max_frames} frames per segment on this machine "
            f"(this one is {shape.frames})."
        )

    default_frames = int(baselines.get("segment_frames") or 0)
    if default_frames and shape.frames > default_frames:
        out.append(
            f"The tier's default is {default_frames} frames; split this segment rather than "
            "rendering it whole."
        )

    width = int(baselines.get("width") or 0)
    height = int(baselines.get("height") or 0)
    if width and height and (shape.width > width or shape.height > height):
        out.append(
            f"Drop the canvas to {width}x{height}: attention cost tracks tokens, and tokens "
            "track pixels."
        )
    return out


def calibrate_attention_kb_per_token(
    *,
    tokens: int,
    workspace_gb: float,
    previous: float = ATTENTION_KB_PER_TOKEN,
    weight: float = 0.5,
) -> float:
    """Blend one observed measurement into the coefficient.

    Kept here so the number has a home and a test: a run that reports its
    sequence length and its attention workspace can refine the estimate instead
    of leaving a constant that was fitted to a single failure.
    """
    if tokens <= 0 or workspace_gb <= 0:
        return float(previous)
    observed = (float(workspace_gb) * _GB) / (float(tokens) * 1024.0)
    weight = min(1.0, max(0.0, float(weight)))
    return float(previous) * (1.0 - weight) + observed * weight


def oom_message(
    stage: str,
    *,
    shape: SegmentShape | None = None,
    free_gb: float | None = None,
    suggestions: Iterable[str] = (),
    tail: str = "",
) -> str:
    """The message every OOM handler raises, with the numbers attached.

    Attribution is the whole point: "ran out of VRAM during H3 sampling" told the
    user nothing about which segment shape caused it or what to change, and the
    same sentence was produced by four different code paths.
    """
    parts = [f"Motion Director ran out of VRAM during {stage}."]
    if shape is not None and int(shape.frames or 0) > 0:
        parts.append(
            f"This segment was {shape.describe()}"
            + (f" - about {shape.tokens} video tokens, needing roughly "
               f"{shape.attention_gb:.1f} GB of attention workspace in one allocation."
               if shape.tokens else ".")
        )
        if free_gb is not None:
            parts.append(f"Free at the failure point: about {float(free_gb):.1f} GB.")
    for suggestion in suggestions:
        parts.append(suggestion)
    if not list(suggestions):
        parts.append(
            "Reduce the segment length, the reference size or the canvas; Motion Context rows "
            "count towards the same budget, and keeping clear_vram_between_segments enabled "
            "leaves more room for the next attempt."
        )
    if tail:
        parts.append(tail)
    return " ".join(parts)
