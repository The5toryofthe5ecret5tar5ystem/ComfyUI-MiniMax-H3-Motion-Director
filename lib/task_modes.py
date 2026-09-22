# Portions derived from ComfyUI_MiniMaxH3_Director
# Copyright AIMixer and contributors
# Originally licensed under Apache License 2.0
# Modified for MiniMax H3 Motion Director, 2026-08-09
# This derivative project is distributed under GPL-3.0.
# See NOTICE and LICENSES/Apache-2.0-AIMixer.txt.

"""MiniMax H3 task-mode inference from connected inputs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MiniMaxH3Task(str, Enum):
    T2V = "t2v"
    I2V = "i2v"
    FL2V = "fl2v"
    R2V = "r2v"
    V2V = "v2v"
    RV2V = "rv2v"
    R2FLV = "r2flv"


TASK_DESCRIPTIONS = {
    MiniMaxH3Task.T2V: "Text-to AV (no keyframes or references)",
    MiniMaxH3Task.I2V: "Image-to AV — first keyframe conditioning",
    MiniMaxH3Task.FL2V: "First+last keyframe AV",
    MiniMaxH3Task.R2V: "Reference-to AV — subject images (+ optional tags) in prompt",
    MiniMaxH3Task.V2V: "Video edit — source timeline clip as <Video 1> reference",
    MiniMaxH3Task.RV2V: "Video edit with reference images — source <Video 1> + <Picture N>",
    MiniMaxH3Task.R2FLV: "Ref2va + FL2v Hybrid — references with boundary anchors pinned as first/last keyframes",
}


SUPPORTED_TASK_KEYS = frozenset(t.value for t in MiniMaxH3Task)


@dataclass(frozen=True)
class TaskSummary:
    mode: MiniMaxH3Task
    ref_image_count: int
    ref_video_count: int

    @property
    def label(self) -> str:
        return self.mode.value

    @property
    def description(self) -> str:
        return TASK_DESCRIPTIONS[self.mode]


def infer_task(ref_image_count: int, ref_video_count: int = 0) -> MiniMaxH3Task:
    if ref_video_count > 0 or ref_image_count > 0:
        return MiniMaxH3Task.R2V
    return MiniMaxH3Task.T2V
