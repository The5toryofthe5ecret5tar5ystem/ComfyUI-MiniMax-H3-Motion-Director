# MiniMax H3 Motion Director - machine profile detection.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""What this machine is, and what that means for Motion Director defaults.

Detection is *advisory*: it proposes starting points for new content and gives the
Settings panel something honest to show. It never rewrites a project - a resolution
or segment-length change invalidates segment caches, so only an explicit "apply"
does that (see ``web/js/minimax_motion_settings.mjs``).

Two facts drive the baselines:

* how much VRAM the device actually has, and how much of it is *free right now*
  (another process holding the GPU is common on this box - an Ollama server used to
  hold 16 GB - so a machine can be a 24 GB card with an 8 GB budget);
* which attention backends actually import. SageAttention is compiled against a
  specific torch ABI and ComfyKitchen's int8 kernels are compiled for specific SM
  versions, so "installed" and "usable" are different questions.

Every baseline below is pre-snapped to the two grids H3 enforces: width/height on
the 32 px canvas multiple, segment lengths on the 17k+5 frame grid.
"""

from __future__ import annotations

import platform
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Baseline tiers
# ---------------------------------------------------------------------------

# Ordered smallest first; ``max_vram_gb`` is inclusive.
BASELINE_TIERS: tuple[dict[str, Any], ...] = (
    {
        "id": "small",
        "label": "Compact",
        "max_vram_gb": 12.0,
        "note": "Starter GPUs and shared VRAM. Short segments, one reference image.",
        "baselines": {
            "megapixels": 0.4,
            "width": 832,
            "height": 480,
            "segment_frames": 124,  # 5.17 s
            "max_segment_frames": 175,  # 7.29 s
            "ref_max_size": 640,
        },
    },
    {
        "id": "medium",
        "label": "Mid",
        "max_vram_gb": 20.0,
        "note": "16 GB cards. Standard segment length, two references.",
        "baselines": {
            "megapixels": 0.6,
            "width": 1024,
            "height": 576,
            "segment_frames": 175,  # 7.29 s
            "max_segment_frames": 243,  # 10.13 s
            "ref_max_size": 768,
        },
    },
    {
        "id": "large",
        "label": "Large",
        "max_vram_gb": 32.0,
        "note": "24-32 GB cards. 10 s segments at 1 MP, several references.",
        "baselines": {
            "megapixels": 1.0,
            "width": 1344,
            "height": 768,
            "segment_frames": 243,  # 10.13 s
            "max_segment_frames": 362,  # 15.08 s
            "ref_max_size": 1024,
        },
    },
    {
        "id": "xl",
        "label": "Workstation",
        "max_vram_gb": 1.0e9,
        "note": "33 GB and up. Long segments and full-size references.",
        "baselines": {
            "megapixels": 1.4,
            "width": 1600,
            "height": 896,
            "segment_frames": 362,  # 15.08 s
            "max_segment_frames": 498,  # 20.75 s, the largest 17k+5 value under 512
            "ref_max_size": 1280,
        },
    },
)

TIER_IDS: tuple[str, ...] = tuple(tier["id"] for tier in BASELINE_TIERS)

# A GPU that is already mostly held by something else cannot be trusted to run the
# tier its total VRAM implies, so the recommendation drops one tier below this.
BUSY_FREE_VRAM_RATIO = 0.6


def tier_for_vram(total_vram_gb: float | None) -> dict[str, Any]:
    """The tier whose band contains ``total_vram_gb`` (``small`` when unknown)."""
    if total_vram_gb is None:
        return BASELINE_TIERS[0]
    try:
        value = float(total_vram_gb)
    except (TypeError, ValueError):
        return BASELINE_TIERS[0]
    for tier in BASELINE_TIERS:
        if value <= float(tier["max_vram_gb"]):
            return tier
    return BASELINE_TIERS[-1]


def _downgrade(tier: dict[str, Any], steps: int = 1) -> dict[str, Any]:
    index = max(0, TIER_IDS.index(str(tier["id"])) - steps)
    return BASELINE_TIERS[index]


def baselines_for_vram(
    total_vram_gb: float | None,
    *,
    free_vram_gb: float | None = None,
) -> dict[str, Any]:
    """Baselines for a device, plus the reason when the free VRAM is smaller.

    ``free_vram_gb`` is what is available *now*. When something else is holding
    most of the card, the one-tier downgrade is the honest answer: the numbers are
    the ones that will actually finish.
    """
    tier = tier_for_vram(total_vram_gb)
    baselines = dict(tier["baselines"])
    downgraded = False
    reason = ""
    if (
        total_vram_gb
        and free_vram_gb is not None
        and float(total_vram_gb) > 0
        and float(free_vram_gb) < float(total_vram_gb) * BUSY_FREE_VRAM_RATIO
    ):
        source = _downgrade(tier)
        baselines = dict(source["baselines"])
        downgraded = True
        reason = (
            f"Only {float(free_vram_gb):.1f} GB of {float(total_vram_gb):.1f} GB is free, "
            "so this starts one tier lower. Close whatever else is holding the GPU "
            "to use the full profile."
        )
    return {
        "tier": tier["id"],
        "tier_label": tier["label"],
        "tier_note": tier["note"],
        "baselines": baselines,
        "downgraded": downgraded,
        "downgrade_reason": reason,
        "source_tier": tier["id"] if not downgraded else _downgrade(tier)["id"],
    }


# ---------------------------------------------------------------------------
# Backend probes
# ---------------------------------------------------------------------------

_BACKEND_CACHE: dict[str, dict[str, Any]] = {}


def _module_version(name: str) -> str | None:
    try:
        from importlib.metadata import version

        return str(version(name))
    except Exception:
        return None


def _probe(key: str, module_name: str, *, extra: Any = None) -> dict[str, Any]:
    """Import one optional backend module and report what happened.

    ``key`` is the name the settings/UI use; ``module_name`` is what gets imported
    (they differ for ``sage`` / ``sageattention``). ``extra`` is a callable
    receiving the imported module and returning a detail string; anything it raises
    is reported as the error - a module that imports but blows up on first use is
    exactly the case this is meant to catch.
    """
    entry: dict[str, Any] = {"name": key, "available": False, "version": None, "detail": "", "error": ""}
    try:
        module = __import__(module_name)
    except Exception as exc:
        entry["error"] = f"{type(exc).__name__}: {exc}"
        if key == "comfy_kitchen":
            # ComfyUI ships it as a dependency of the attention nodes; a missing
            # kitchen just means those nodes are not installed either.
            entry["detail"] = "not installed"
        return entry
    entry["available"] = True
    entry["version"] = getattr(module, "__version__", None) or _module_version(module_name)
    if callable(extra):
        try:
            entry["detail"] = str(extra(module) or "")
        except Exception as exc:
            entry["available"] = False
            entry["error"] = f"{type(exc).__name__}: {exc}"
    return entry


def _kitchen_detail(module: Any) -> str:
    probe = getattr(module, "int8_attention_is_available", None)
    if not callable(probe):
        return "installed (no int8 attention probe)"
    return "int8 attention available" if probe() else "int8 attention NOT available on this GPU"


def _sdpa_detail() -> dict[str, Any]:
    entry: dict[str, Any] = {"name": "sdpa", "available": False, "version": None, "detail": "", "error": ""}
    try:
        import torch

        entry["available"] = True
        entry["version"] = str(getattr(torch, "__version__", "") or "") or None
        parts = []
        for label, probe in (
            ("flash", "flash_sdp_enabled"),
            ("mem-efficient", "mem_efficient_sdp_enabled"),
            ("math", "math_sdp_enabled"),
        ):
            enabled = getattr(torch.backends.cuda, probe, None)
            try:
                parts.append(f"{label}={'on' if callable(enabled) and enabled() else 'off'}")
            except Exception:
                parts.append(f"{label}=?")
        entry["detail"] = "PyTorch SDPA (" + ", ".join(parts) + ")"
    except Exception as exc:
        entry["error"] = f"{type(exc).__name__}: {exc}"
    return entry


def probe_backends(*, refresh: bool = False) -> dict[str, dict[str, Any]]:
    """Availability of every attention backend a Director workflow can select.

    Cached per process: importing sageattention/comfy_kitchen is not free, and the
    answer cannot change without a restart.
    """
    if _BACKEND_CACHE and not refresh:
        return {key: dict(value) for key, value in _BACKEND_CACHE.items()}
    probes = {
        "sdpa": _sdpa_detail(),
        "sage": _probe("sage", "sageattention"),
        "comfy_kitchen": _probe("comfy_kitchen", "comfy_kitchen", extra=_kitchen_detail),
        "xformers": _probe("xformers", "xformers"),
        "flash_attn": _probe("flash_attn", "flash_attn"),
        "triton": _probe("triton", "triton"),
    }
    _BACKEND_CACHE.clear()
    _BACKEND_CACHE.update(probes)
    return {key: dict(value) for key, value in probes.items()}


# ---------------------------------------------------------------------------
# Device + runtime
# ---------------------------------------------------------------------------

_PACK_ROOT = Path(__file__).resolve().parent.parent


def pack_version() -> str:
    """The pack version from ``pyproject.toml`` (single source of truth)."""
    try:
        import re

        text = (_PACK_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'^\s*version\s*=\s*"([^"]+)"', text, re.MULTILINE)
        if match:
            return match.group(1)
    except Exception:
        pass
    return "unknown"


def _comfyui_version() -> str:
    try:
        import comfyui_version  # type: ignore[import-not-found]

        return str(getattr(comfyui_version, "__version__", "") or "") or "unknown"
    except Exception:
        return "unknown"


def detect_devices(*, refresh: bool = False) -> list[dict[str, Any]]:
    """Every CUDA device, with the VRAM numbers the baselines are picked from."""
    devices: list[dict[str, Any]] = []
    try:
        import torch
    except Exception as exc:
        return [{"index": 0, "name": f"unavailable ({type(exc).__name__})", "available": False}]
    try:
        if not torch.cuda.is_available():
            return [{"index": 0, "name": "CPU / no CUDA device", "available": False}]
        for index in range(torch.cuda.device_count()):
            entry: dict[str, Any] = {"index": index, "available": True}
            try:
                props = torch.cuda.get_device_properties(index)
                entry["name"] = str(getattr(props, "name", f"cuda:{index}"))
                entry["capability"] = f"{getattr(props, 'major', '?')}.{getattr(props, 'minor', '?')}"
                total_bytes = int(getattr(props, "total_memory", 0) or 0)
            except Exception as exc:
                entry["name"] = f"cuda:{index}"
                entry["capability"] = "?"
                entry["probe_error"] = f"{type(exc).__name__}: {exc}"
                total_bytes = 0
            free_bytes = 0
            try:
                free_bytes, total_now = torch.cuda.mem_get_info(index)
                total_bytes = int(total_now) or total_bytes
            except Exception:
                free_bytes = 0
            entry["total_vram_gb"] = round(total_bytes / (1024**3), 2) if total_bytes else None
            entry["free_vram_gb"] = round(int(free_bytes) / (1024**3), 2) if free_bytes else None
            entry["baselines"] = baselines_for_vram(entry["total_vram_gb"], free_vram_gb=entry["free_vram_gb"])
            devices.append(entry)
    except Exception as exc:
        return [{"index": 0, "name": f"probe failed ({type(exc).__name__})", "available": False, "error": str(exc)}]
    return devices or [{"index": 0, "name": "no CUDA device", "available": False}]


def collect_machine_profile(
    *,
    refresh: bool = False,
    device_index: int = 0,
    vram_gb_override: float | None = None,
) -> dict[str, Any]:
    """The full detected picture: runtime versions, devices, backends, baselines.

    ``device_index`` and ``vram_gb_override`` come from the stored settings, so a
    user who knows their card better than the driver does is believed.
    """
    devices = detect_devices()
    selected = None
    for entry in devices:
        if int(entry.get("index", -1)) == int(device_index):
            selected = entry
            break
    selected = selected or devices[0]

    total = selected.get("total_vram_gb")
    free = selected.get("free_vram_gb")
    if vram_gb_override:
        # An explicit override replaces the total only: the free figure still comes
        # from the driver, because that is what the render will actually get.
        total = float(vram_gb_override)
    baselines = baselines_for_vram(total, free_vram_gb=free)

    try:
        import torch

        torch_version = str(getattr(torch, "__version__", "") or "unknown")
        cuda_version = str(getattr(getattr(torch, "version", None), "cuda", "") or "unknown")
    except Exception:
        torch_version = "unavailable"
        cuda_version = "unavailable"

    return {
        "pack_version": pack_version(),
        "comfyui_version": _comfyui_version(),
        "python_version": platform.python_version(),
        "torch_version": torch_version,
        "cuda_version": cuda_version,
        "platform": platform.platform(),
        "device_index": int(device_index),
        "device": {
            "index": int(selected.get("index", 0)),
            "name": str(selected.get("name", "unknown")),
            "capability": selected.get("capability"),
            "total_vram_gb": total,
            "free_vram_gb": free,
            "available": bool(selected.get("available", False)),
            "vram_gb_override": float(vram_gb_override) if vram_gb_override else None,
        },
        "devices": [
            {key: value for key, value in entry.items() if key != "baselines"} for entry in devices
        ],
        "backends": probe_backends(refresh=refresh),
        "tier": baselines["tier"],
        "tier_label": baselines["tier_label"],
        "tier_note": baselines["tier_note"],
        "baselines": baselines["baselines"],
        "downgraded": baselines["downgraded"],
        "downgrade_reason": baselines["downgrade_reason"],
    }


__all__ = [
    "BASELINE_TIERS",
    "TIER_IDS",
    "baselines_for_vram",
    "collect_machine_profile",
    "detect_devices",
    "pack_version",
    "probe_backends",
    "tier_for_vram",
]
