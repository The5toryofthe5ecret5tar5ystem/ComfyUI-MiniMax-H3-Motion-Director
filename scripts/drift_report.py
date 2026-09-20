#!/usr/bin/env python3
# MiniMax H3 Motion Director - chain drift report.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Measure what a long chain does to the picture, from the files it produced.

Chaining is autoregressive: every segment conditions on the previous segment's
*decoded pixels*, which are themselves the output of a lossy encode/decode cycle.
Small errors therefore compound, and "quality drops over a long chain" is a real
effect with three different causes that need three different cures:

* **colour / exposure** - the render's own statistics shift hop by hop (the pack
  has ``color_reanchor`` for this; is it holding?),
* **detail** - high-frequency content is re-encoded each hop and softens,
* **structure / identity** - the subject is re-interpreted a little each time,
  so the drift is cumulative rather than random.

Taste cannot separate those, so this script does it with numbers. It is pure CPU
work over files that already exist: no model is loaded, no GPU is touched, and it
can run while a render is in progress. It reads each segment twice (the first N
and last N frames, downscaled) plus a strided sample of the middle for per-frame
statistics, then reports per-boundary metrics and the trend across the chain.

Usage::

    python scripts/drift_report.py                 # newest run in the output dir
    python scripts/drift_report.py --list          # what runs are available
    python scripts/drift_report.py --prefix 200820 # one specific run
    python scripts/drift_report.py --root DIR --out DIR
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np
from skimage.metrics import structural_similarity as ssim

SEGMENT_RE = re.compile(r"^(?P<run>\d{6})_(?P<index>\d{5})_\.mp4$", re.IGNORECASE)

DEFAULT_ROOT = Path("/home/wakapedia/WakaCloud/AI/output/mm-director")
DEFAULT_OUT = Path("/home/wakapedia/WakaCloud/AI/output/drift_report")

#: Frames read from each end of a segment for the seam metrics.
EDGE_FRAMES = 6
#: Working width for every metric (keeps a whole run to a couple of seconds).
WORK_WIDTH = 512
#: Centre-frame stride for the per-segment statistics.
STATS_STRIDE = 5
#: A seam is judged against each segment's own frame-to-frame change, because fast
#: content legitimately changes a lot per frame (SSIM well below 1.0), and a fixed
#: threshold would call a perfectly smooth join a break.
SEAM_SMOOTH_RATIO = 2.5
#: At or above this multiple of a normal frame step the join is visible.
SEAM_BREAK_RATIO = 5.0


@dataclass
class SegmentMetrics:
    index: int
    path: Path
    frames: int
    width: int
    height: int
    mean_rgb: tuple[float, float, float]
    std_rgb: tuple[float, float, float]
    sharpness: float
    noise: float
    #: Mean SSIM between adjacent frames inside this segment (its own motion).
    frame_step_ssim: float = 0.0
    hash_bits: int = 0
    hash_dist_to_first: int = 0
    first_frame: np.ndarray | None = field(default=None, repr=False)
    last_frame: np.ndarray | None = field(default=None, repr=False)

    @property
    def colour_span(self) -> float:
        return float(max(self.std_rgb) if self.std_rgb else 0.0)


@dataclass
class BoundaryMetrics:
    index: int
    ssim: float
    colour_delta: float
    sharpness_ratio: float
    pixel_mae: float
    #: The incoming segment's own frame-to-frame SSIM, and how many of those the
    #: join costs: 1.0 means the seam is indistinguishable from normal motion.
    step_ssim: float = 0.0
    step_ratio: float = 0.0


def _resize(frame: np.ndarray, width: int) -> np.ndarray:
    height = max(1, int(round(frame.shape[0] * width / max(1, frame.shape[1]))))
    return cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)


def _laplacian_variance(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _noise_estimate(gray: np.ndarray) -> float:
    """High-frequency residual: what a 3x3 median leaves behind."""
    residual = gray.astype(np.float32) - cv2.medianBlur(gray, 3).astype(np.float32)
    return float(residual.std())


def _dct_hash(gray: np.ndarray) -> int:
    """64-bit DCT hash of a frame: a model-free structure fingerprint."""
    small = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    dct = cv2.dct(small)[:8, :8]
    flat = dct.flatten()[1:]  # drop DC: brightness is measured separately
    median = float(np.median(flat))
    bits = 0
    for position, value in enumerate(flat):
        if value > median:
            bits |= 1 << position
    return bits


def _hamming(left: int, right: int) -> int:
    return int(bin(left ^ right).count("1"))


def read_segment(path: Path, index: int, *, width: int = WORK_WIDTH,
                 edge_frames: int = EDGE_FRAMES, stride: int = STATS_STRIDE) -> SegmentMetrics | None:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        return None
    first: list[np.ndarray] = []
    tail: deque[np.ndarray] = deque(maxlen=edge_frames)
    middle: list[np.ndarray] = []
    steps: list[float] = []
    previous: np.ndarray | None = None
    frame_count = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok or frame is None:
                break
            small = _resize(frame, width)
            frame_count += 1
            if len(first) < edge_frames:
                first.append(small)
            tail.append(small)
            if frame_count % stride == 0:
                middle.append(small)
                if previous is not None:
                    steps.append(float(ssim(cv2.cvtColor(previous, cv2.COLOR_BGR2GRAY),
                                            cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))))
            previous = small
    finally:
        capture.release()
    if not first or not middle:
        return None

    stack = np.stack(middle).astype(np.float32)
    means = stack.reshape(-1, 3).mean(axis=0)
    stds = stack.reshape(-1, 3).std(axis=0)
    grays = [cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) for frame in middle]
    sharpness = float(np.mean([_laplacian_variance(gray) for gray in grays]))
    noise = float(np.mean([_noise_estimate(gray) for gray in grays]))
    centre = cv2.cvtColor(middle[len(middle) // 2], cv2.COLOR_BGR2GRAY)

    return SegmentMetrics(
        index=index,
        path=path,
        frames=frame_count,
        width=int(first[0].shape[1]),
        height=int(first[0].shape[0]),
        mean_rgb=(float(means[2]), float(means[1]), float(means[0])),
        std_rgb=(float(stds[2]), float(stds[1]), float(stds[0])),
        sharpness=sharpness,
        noise=noise,
        frame_step_ssim=float(np.mean(steps)) if steps else 0.0,
        hash_bits=_dct_hash(centre),
        first_frame=np.stack(first).mean(axis=0).astype(np.uint8),
        last_frame=np.stack(list(tail)).mean(axis=0).astype(np.uint8),
    )


def compare(a: SegmentMetrics, b: SegmentMetrics) -> BoundaryMetrics:
    last = cv2.cvtColor(a.last_frame, cv2.COLOR_BGR2GRAY)
    first = cv2.cvtColor(b.first_frame, cv2.COLOR_BGR2GRAY)
    if last.shape != first.shape:
        first = cv2.resize(first, (last.shape[1], last.shape[0]), interpolation=cv2.INTER_AREA)
    score = float(ssim(last, first))
    colour = float(np.abs(np.asarray(a.mean_rgb) - np.asarray(b.mean_rgb)).mean())
    ratio = float(b.sharpness / a.sharpness) if a.sharpness else 0.0
    mae = float(np.abs(a.last_frame.astype(np.float32) - b.first_frame.astype(np.float32)).mean())
    step = float(b.frame_step_ssim) or float(a.frame_step_ssim)
    step_ratio = float((1.0 - score) / max(1e-9, 1.0 - step)) if 0.0 < step < 1.0 else 0.0
    return BoundaryMetrics(index=b.index, ssim=score, colour_delta=colour,
                           sharpness_ratio=ratio, pixel_mae=mae,
                           step_ssim=step, step_ratio=step_ratio)


def _slope(values: Iterable[float]) -> float:
    data = [float(v) for v in values]
    if len(data) < 2:
        return 0.0
    x = np.arange(len(data), dtype=np.float64)
    y = np.asarray(data, dtype=np.float64)
    denominator = float(((x - x.mean()) ** 2).sum())
    if denominator <= 0:
        return 0.0
    return float(((x - x.mean()) * (y - y.mean())).sum() / denominator)


def discover_runs(root: Path) -> dict[str, list[Path]]:
    """Group segment files by their run prefix, longest chain first."""
    runs: dict[str, list[Path]] = {}
    for path in sorted(root.glob("*/*.mp4")):
        match = SEGMENT_RE.match(path.name)
        if not match:
            continue
        runs.setdefault(match.group("run"), []).append(path)
    for paths in runs.values():
        paths.sort(key=lambda p: SEGMENT_RE.match(p.name).group("index"))  # type: ignore[union-attr]
    return dict(sorted(runs.items(), key=lambda item: (-len(item[1]), item[0])))


def build_report(segments: list[SegmentMetrics], boundaries: list[BoundaryMetrics]) -> dict[str, Any]:
    first = segments[0]
    colour_drift = [float(np.abs(np.asarray(s.mean_rgb) - np.asarray(first.mean_rgb)).mean())
                    for s in segments]
    sharpness_ratio = [float(s.sharpness / first.sharpness) if first.sharpness else 0.0
                       for s in segments]
    structure = [float(s.hash_dist_to_first) for s in segments]
    seams = [b.ssim for b in boundaries]
    step_baselines = [b.step_ssim for b in boundaries if 0.0 < b.step_ssim < 1.0]
    step_ratios = [b.step_ratio for b in boundaries if b.step_ratio > 0.0]

    report: dict[str, Any] = {
        "segments": len(segments),
        "boundaries": len(boundaries),
        "shape": f"{first.width}x{first.height}",
        "files": [str(s.path) for s in segments],
        "per_segment": [
            {
                "index": s.index,
                "frames": s.frames,
                "mean_rgb": [round(v, 1) for v in s.mean_rgb],
                "sharpness": round(s.sharpness, 1),
                "noise": round(s.noise, 2),
                "colour_drift": round(colour_drift[position], 2),
                "sharpness_vs_first": round(sharpness_ratio[position], 3),
                "frame_step_ssim": round(s.frame_step_ssim, 4),
                "structure_dist": s.hash_dist_to_first,
            }
            for position, s in enumerate(segments)
        ],
        "per_boundary": [
            {
                "index": b.index,
                "ssim": round(b.ssim, 4),
                "colour_delta": round(b.colour_delta, 2),
                "sharpness_ratio": round(b.sharpness_ratio, 3),
                "pixel_mae": round(b.pixel_mae, 2),
                "step_ssim": round(b.step_ssim, 4),
                "step_ratio": round(b.step_ratio, 2),
            }
            for b in boundaries
        ],
        "trends": {
            "colour_per_hop": round(_slope(colour_drift), 3),
            "sharpness_ratio_per_hop": round(_slope(sharpness_ratio), 5),
            "structure_per_hop": round(_slope(structure), 3),
            "seam_ssim_per_hop": round(_slope(seams), 5),
        },
        "totals": {
            "colour_drift_last": round(colour_drift[-1], 2),
            "sharpness_vs_first_last": round(sharpness_ratio[-1], 3),
            "structure_dist_last": structure[-1],
            "seam_ssim_min": round(float(min(seams)), 4) if seams else None,
            "seam_ssim_median": round(float(np.median(seams)), 4) if seams else None,
            "frame_step_ssim_median": round(float(np.median(step_baselines)), 4)
            if step_baselines else None,
            "seam_step_ratio_median": round(float(np.median(step_ratios)), 2) if step_ratios else None,
            "seam_step_ratio_max": round(float(max(step_ratios)), 2) if step_ratios else None,
        },
        "verdict": [],
    }

    findings: list[str] = report["verdict"]
    sharp_slope = report["trends"]["sharpness_ratio_per_hop"]
    colour_slope = report["trends"]["colour_per_hop"]
    structure_slope = report["trends"]["structure_per_hop"]
    if segments:
        softest = min(range(len(segments)), key=lambda i: sharpness_ratio[i])
        strongest = max(range(len(segments)), key=lambda i: colour_drift[i])
        findings.append(
            f"Detail: sharpness is {sharpness_ratio[-1]:.3f}x the first segment at the end "
            f"({sharp_slope * 100:+.2f}% per hop); the softest segment is #{segments[softest].index + 1} "
            f"({sharpness_ratio[softest]:.3f}x)."
        )
        findings.append(
            f"Colour/exposure: mean colour is {colour_drift[-1]:.1f}/255 away from the first segment "
            f"at the end ({colour_slope * 100:+.2f} levels per hop); worst is #{segments[strongest].index + 1}."
        )
        findings.append(
            f"Structure: the model-free frame fingerprint is {structure[-1]} bits (of 64) away from the "
            f"first segment at the end ({structure_slope * 100:+.2f} bits per hop)."
        )
        if seams and step_ratios:
            smooth = [b for b in boundaries if 0.0 < b.step_ratio <= SEAM_SMOOTH_RATIO]
            broken = [b for b in boundaries if b.step_ratio >= SEAM_BREAK_RATIO]
            worst = max((b for b in boundaries if b.step_ratio > 0.0), key=lambda b: b.step_ratio)
            findings.append(
                f"Continuity: seam SSIM median {np.median(seams):.4f} (min {min(seams):.4f}), while a "
                f"normal frame step inside these segments is {np.median(step_baselines):.4f} SSIM, so the "
                f"median join costs {np.median(step_ratios):.1f}x an ordinary frame change "
                f"({len(smooth)} of {len(boundaries)} within {SEAM_SMOOTH_RATIO:.1f}x, "
                f"{len(broken)} at or above {SEAM_BREAK_RATIO:.0f}x); worst is #{worst.index + 1} at "
                f"{worst.step_ratio:.1f}x with a colour delta of {worst.colour_delta:.1f} levels."
            )
        elif seams:
            findings.append(
                f"Continuity: seam SSIM median {np.median(seams):.4f}, minimum {min(seams):.4f} "
                f"(no frame-step baseline available to judge them against)."
            )
    return report


def write_chart(report: dict[str, Any], out_path: Path) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return False

    per_segment = report["per_segment"]
    per_boundary = report["per_boundary"]
    if not per_segment:
        return False

    xs = [row["index"] + 1 for row in per_segment]
    figure, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=False)

    axes[0].plot(xs, [row["colour_drift"] for row in per_segment], marker="o", color="#e08a3c")
    axes[0].set_title("Colour / exposure drift from segment 1 (levels out of 255)")
    axes[0].grid(alpha=0.3)

    axes[1].plot(xs, [row["sharpness_vs_first"] for row in per_segment], marker="o", color="#4aa8ff")
    axes[1].axhline(1.0, color="#888", linewidth=1, linestyle="--")
    axes[1].set_title("Sharpness relative to segment 1 (1.0 = unchanged)")
    axes[1].grid(alpha=0.3)

    if per_boundary:
        bx = [row["index"] + 1 for row in per_boundary]
        axes[2].plot(bx, [row["ssim"] for row in per_boundary], marker="o", color="#55cc86",
                     label="seam (last frame -> first frame)")
        steps = [row.get("step_ssim", 0.0) for row in per_boundary]
        if any(steps):
            axes[2].plot(bx, steps, marker="s", color="#4aa8ff", linestyle="--",
                         label="normal frame step inside the segment")
            axes[2].legend(loc="lower right", fontsize=8)
        axes[2].axhline(0.98, color="#c04040", linewidth=1, linestyle=":")
        axes[2].set_title("Seam SSIM vs the segment's own frame step (a seam on the dashed line is invisible)")
        axes[2].grid(alpha=0.3)

    axes[-1].set_xlabel("segment / boundary index")
    figure.tight_layout()
    figure.savefig(out_path, dpi=110)
    plt.close(figure)
    return True


def write_markdown(report: dict[str, Any], out_path: Path) -> None:
    lines = [
        "# Chain drift report",
        "",
        f"- segments analysed: **{report['segments']}** ({report['shape']})",
        f"- boundaries: **{report['boundaries']}**",
        "",
        "## Findings",
        "",
    ]
    lines += [f"- {item}" for item in report["verdict"]]
    lines += [
        "",
        "## Per segment",
        "",
        "| # | frames | mean RGB | sharpness | noise | colour drift | sharpness vs S1 | structure dist |",
        "|---:|---:|---|---:|---:|---:|---:|---:|",
    ]
    for row in report["per_segment"]:
        rgb = ", ".join(str(v) for v in row["mean_rgb"])
        lines.append(
            f"| {row['index'] + 1} | {row['frames']} | {rgb} | {row['sharpness']} | {row['noise']} | "
            f"{row['colour_drift']} | {row['sharpness_vs_first']} | {row['structure_dist']} |"
        )
    lines += [
        "",
        "## Per boundary",
        "",
        "| boundary | seam SSIM | frame step | x step | colour delta | sharpness ratio | pixel MAE |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["per_boundary"]:
        lines.append(
            f"| {row['index'] + 1} | {row['ssim']} | {row.get('step_ssim')} | {row.get('step_ratio')}x | "
            f"{row['colour_delta']} | {row['sharpness_ratio']} | {row['pixel_mae']} |"
        )
    lines += [
        "",
        "`x step` compares the seam with the frame-to-frame SSIM measured inside the incoming",
        f"segment: 1.0 means the join is indistinguishable from ordinary motion, "
        f"{SEAM_SMOOTH_RATIO:.1f}x and below is smooth,",
        f"{SEAM_BREAK_RATIO:.0f}x and above is a visible cut.",
    ]
    lines += ["", "## Trends", ""]
    for key, value in report["trends"].items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def analyse(paths: list[Path], *, width: int, edge_frames: int, stride: int) -> tuple[list, list]:
    segments: list[SegmentMetrics] = []
    for position, path in enumerate(paths):
        metrics = read_segment(path, position, width=width, edge_frames=edge_frames, stride=stride)
        if metrics is None:
            print(f"  ! skipped unreadable segment: {path.name}", file=sys.stderr)
            continue
        if segments:
            metrics.hash_dist_to_first = _hamming(metrics.hash_bits, segments[0].hash_bits)
        segments.append(metrics)
        print(f"  read {path.name}: {metrics.frames} frames, sharpness {metrics.sharpness:.0f}, "
              f"noise {metrics.noise:.2f}")
    boundaries = [compare(segments[i], segments[i + 1]) for i in range(len(segments) - 1)]
    return segments, boundaries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure drift across a rendered chain.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                        help="folder holding <date>/<time>_<index>_.mp4 outputs")
    parser.add_argument("--prefix", help="run prefix to analyse (e.g. 200820); default: the longest run")
    parser.add_argument("--files", nargs="*", type=Path, help="explicit segment files, in order")
    parser.add_argument("--list", action="store_true", help="list the runs found and exit")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where to write the report")
    parser.add_argument("--width", type=int, default=WORK_WIDTH, help="working width for the metrics")
    parser.add_argument("--edge-frames", type=int, default=EDGE_FRAMES)
    parser.add_argument("--stride", type=int, default=STATS_STRIDE)
    args = parser.parse_args(argv)

    runs = discover_runs(args.root)
    if args.list or (not args.files and not runs):
        if not runs:
            print(f"no segment files found under {args.root}", file=sys.stderr)
            return 1
        print(f"runs under {args.root} (longest first):")
        for name, paths in runs.items():
            print(f"  {name}: {len(paths)} segment(s), {paths[0].parent.name}")
        return 0

    if args.files:
        paths = list(args.files)
        label = "explicit files"
    else:
        label, paths = next(((name, files) for name, files in runs.items()
                             if name == args.prefix), (None, None)) if args.prefix else next(iter(runs.items()))
        if not paths:
            print(f"run '{args.prefix}' not found; use --list", file=sys.stderr)
            return 1
    if len(paths) < 2:
        print("need at least two segments to measure a chain", file=sys.stderr)
        return 1

    print(f"analysing run {label}: {len(paths)} segments")
    segments, boundaries = analyse(paths, width=args.width, edge_frames=args.edge_frames, stride=args.stride)
    if len(segments) < 2:
        print("not enough readable segments", file=sys.stderr)
        return 1

    report = build_report(segments, boundaries)
    report["run"] = label
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = f"{label}_drift"
    write_markdown(report, args.out / f"{stamp}.md")
    (args.out / f"{stamp}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    chart = write_chart(report, args.out / f"{stamp}.png")

    print()
    for line in report["verdict"]:
        print(f"  - {line}")
    print()
    print(f"report : {args.out / (stamp + '.md')}")
    print(f"json   : {args.out / (stamp + '.json')}")
    print(f"chart  : {args.out / (stamp + '.png')}" if chart else "chart  : (matplotlib unavailable)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
