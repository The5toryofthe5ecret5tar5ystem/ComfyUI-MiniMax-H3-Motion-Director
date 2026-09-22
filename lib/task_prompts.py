# Portions derived from ComfyUI_MiniMaxH3_Director
# Copyright AIMixer and contributors
# Originally licensed under Apache License 2.0
# Modified for MiniMax H3 Motion Director, 2026-08-09
# This derivative project is distributed under GPL-3.0.
# See NOTICE and LICENSES/Apache-2.0-AIMixer.txt.

"""MiniMax H3 task_type labels and combo options (freeform Qwen prompts — no T5 system prefix)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskPromptSpec:
    key: str
    label: str
    system_prompt: str
    description_zh: str


TASK_PROMPT_SPECS: tuple[TaskPromptSpec, ...] = (
    TaskPromptSpec(
        "default",
        "默认通用",
        "",
        "MiniMax H3 使用 Qwen3-VL 自由提示词，无需 T5 系统前缀。",
    ),
    TaskPromptSpec(
        "t2v",
        "文生视频(Text to Video)",
        "",
        "文生音视频；无首帧/参考图。",
    ),
    TaskPromptSpec(
        "i2v",
        "图生视频(Start image to video)",
        "",
        "首帧图生音视频（ImageToVideo + first_frame）。",
    ),
    TaskPromptSpec(
        "fl2v",
        "首尾帧生视频(First + last frame)",
        "",
        "首帧+尾帧约束（ImageToVideo + first_frame + last_frame）。",
    ),
    TaskPromptSpec(
        "r2v",
        "参考主体生视频(Reference images to video)",
        "",
        "分组参考改视频（类似首尾帧分组）：每组可上传图片1–9、音频1–3、视频1–3；"
        "提示词用 <Picture N> / <Video K> / <Audio J>。源视频时间轴剪辑请用 v2v/rv2v。",
    ),
    TaskPromptSpec(
        "v2v",
        "视频转视频(Source video only)",
        "",
        "上传源视频后按时间轴分段编辑；每段源画面作为 <Video 1> 送入 ReferenceToVideo（无参考图槽）。",
    ),
    TaskPromptSpec(
        "rv2v",
        "参考素材改视频(Source video + references)",
        "",
        "源视频时间轴编辑，可选参考图（图片1–9）与参考音频（音频1–3）；"
        "每段源画面为 <Video 1>，参考图用 <Picture N>，参考音频用 <Audio J>；无参考素材时等同 v2v。",
    ),
    TaskPromptSpec(
        "mixed",
        "混合模式(Mixed, per-segment)",
        "",
        "同一时间线逐段选择 T2V / I2V / FL2V / R2V / Source Video。"
        "Mixed 是 Director 元模式，每段执行前会编译成现有 H3 后端任务。",
    ),
    TaskPromptSpec(
        "r2flv",
        "Ref2va + FL2v Hybrid 混合(References + first/last keyframes)",
        "",
        "r2v 的参考图/参考音频 + fl2v 的首尾帧关键帧约束二合一：每段照常吃 Common References"
        "（图片1-9 / 音频1-3）与 <Picture N> 提示词，同时把两端用边界锚点图钉成 H3 关键帧"
        "（首帧=开边界锚点，末帧=闭边界锚点）；锚点是分段用自己的参考素材预渲染并审核过"
        "的边界姿态图，因此身份、房间与声音保持 r2va 体验，而插值由首尾关键帧引导。"
        "锚点缺失的一端自动跳过（回退为纯 r2v 软参考）。",
    ),
)

TASK_PROMPT_BY_KEY = {spec.key: spec for spec in TASK_PROMPT_SPECS}
HIDDEN_TASK_TYPE_KEYS: frozenset[str] = frozenset()


def task_type_option_label(spec: TaskPromptSpec) -> str:
    return f"{spec.key} — {spec.label}"


def task_type_combo_options() -> tuple[list[str], dict]:
    options = [
        task_type_option_label(spec)
        for spec in TASK_PROMPT_SPECS
        if spec.key not in HIDDEN_TASK_TYPE_KEYS and spec.key != "default"
    ]
    default_spec = TASK_PROMPT_BY_KEY["t2v"]
    return options, {
        "default": task_type_option_label(default_spec),
        "tooltip": (
            "MiniMax H3 Director 支持 t2v / i2v / fl2v / r2v / v2v / rv2v / mixed / r2flv。"
            "Mixed 为逐段元模式；其 Segment 会编译成现有 H3 task，不会把 mixed 送进模型。"
            "r2flv（Ref2va + FL2v Hybrid）在 R2V 参考与参考音频之上，把边界锚点自动钉成"
            "H3 首尾关键帧（首帧=0，末帧=末帧索引）。"
            "提示词直接送入 MiniMaxH3ImageToVideo 或 MiniMaxH3ReferenceToVideo（内部 tokenize）。"
        ),
    }


def resolve_task_key(task_type_value: str) -> str:
    value = task_type_value.split(",[object Object]", 1)[0].strip()
    if " · " in value:
        value = value.split(" · ", 1)[0].strip()
    for sep in (" — ", " —— ", " - ", " – "):
        if sep in value:
            return value.split(sep, 1)[0].strip()
    return value


def get_task_prompt_spec(task_type_value: str) -> TaskPromptSpec:
    key = resolve_task_key(task_type_value)
    return TASK_PROMPT_BY_KEY.get(key, TASK_PROMPT_BY_KEY["default"])


def apply_task_system_prompt(task_type_value: str, positive_prompt: str) -> str:
    """H3 nodes tokenize raw user prompt — no system prefix injection."""
    del task_type_value
    return positive_prompt
