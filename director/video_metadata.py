# MiniMax H3 Motion Director - workflow metadata policy for exported videos.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Whether a saved video carries the ComfyUI workflow, and why.

ComfyUI's own exit is the default: ``Save Video`` (and this pack's save path, which
mirrors it) embeds ``workflow`` + ``prompt`` unless ComfyUI was launched with
``--disable-metadata``. That is worth keeping - for this pack the workflow *is* the
project (timeline, per-segment prompts, references), so dragging the exported mp4
back onto the canvas restores the job.

It is also worth being able to turn off, because those two tags carry the prompt
text, model and LoRA names and local paths into every copy of the file. So the
policy has three states:

* ``auto``   - follow ComfyUI (the default);
* ``always`` - embed even when that flag is set;
* ``never``  - strip, even when ComfyUI would embed.

The app-wide Settings own ``auto``/``always``/``never``; a single save can override
it (the Results page passes its own value), and the strip helper cleans up files
that were written before the choice existed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

EMBED_CHOICES: tuple[str, ...] = ("auto", "always", "never")
DEFAULT_EMBED = "auto"

# Bounded: the workflow of a Director project is a handful of MB at worst, and an
# unbounded subprocess is a hang waiting to happen.
_FFMPEG_TIMEOUT_SECONDS = 600


def normalize_embed_policy(value: Any) -> str:
    """Coerce a stored/spoofed policy into one of the three accepted values."""
    text = str(value or "").strip().lower()
    return text if text in EMBED_CHOICES else DEFAULT_EMBED


def comfyui_disabled() -> bool:
    """True when ComfyUI was launched with ``--disable-metadata``."""
    try:
        from comfy.cli_args import args

        return bool(getattr(args, "disable_metadata", False))
    except Exception:
        return False


def app_setting_policy() -> str:
    """The app-wide policy from the Setup panel (``auto`` when unreadable)."""
    try:
        from .motion_settings import STORE

        settings = STORE.load()
        return normalize_embed_policy((settings.get("export") or {}).get("embed_workflow"))
    except Exception:
        return DEFAULT_EMBED


def resolve(policy: Any = None, *, app_policy: str | None = None) -> dict[str, Any]:
    """Decide whether to embed, and name the reason.

    Precedence: the per-save value, then the app-wide setting, then ComfyUI. An
    unknown value falls back to the app setting so a typo cannot silently strip
    somebody's project out of a render.
    """
    requested = str(policy or "").strip().lower()
    source = "save-config"
    if requested not in EMBED_CHOICES:
        requested = app_policy if app_policy is not None else app_setting_policy()
        source = "settings" if requested != DEFAULT_EMBED else "default"
    requested = normalize_embed_policy(requested)
    disabled = comfyui_disabled()
    if requested == "always":
        embed = True
    elif requested == "never":
        embed = False
    else:
        embed = not disabled
    return {
        "policy": requested,
        "embed": bool(embed),
        "source": source,
        "comfyui_disabled": bool(disabled),
        "effective": "embed" if embed else "strip",
    }


def metadata_for(
    extra_pnginfo: Any,
    prompt: Any,
    policy: Any = None,
    *,
    app_policy: str | None = None,
) -> dict[str, Any] | None:
    """The metadata dict to hand to ``video.save_to`` (``None`` = write none)."""
    decision = resolve(policy, app_policy=app_policy)
    if not decision["embed"]:
        return None
    metadata: dict[str, Any] = dict(extra_pnginfo or {})
    if prompt is not None:
        metadata["prompt"] = prompt
    return metadata or None


# ---------------------------------------------------------------------------
# Stripping an already-saved file
# ---------------------------------------------------------------------------


def _ffmpeg_path() -> str | None:
    """Reuse the locator the pack already uses for audio (PATH, then imageio)."""
    try:
        from ..lib.audio_io import _ffmpeg_bin

        found = _ffmpeg_bin()
        if found:
            return found
    except Exception:
        pass
    return shutil.which("ffmpeg")


def _ffprobe_tags(video: Path) -> dict[str, str]:
    """Container tags of a file, so the caller can report what was removed."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {}
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v", "error",
                # ffprobe has no -nostdin (it would swallow the next option); the
                # DEVNULL below is what keeps it off the terminal.
                "-show_entries", "format_tags",
                "-of", "json",
                str(video),
            ],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            return {}
        payload = json.loads(result.stdout.decode("utf-8", "replace") or "{}")
    except Exception:
        return {}
    tags = (payload.get("format") or {}).get("tags") or {}
    return {str(key).lower(): str(value) for key, value in tags.items()}


def resolve_output_file(name: Any, *, subfolder: Any = "", kind: str = "output") -> Path:
    """Resolve a saved file inside one of ComfyUI's media roots.

    Anything that escapes the root (``..``, an absolute path, a different drive) is
    refused, so the strip endpoint cannot be pointed at arbitrary files.
    """
    import folder_paths

    raw = str(name or "").strip().replace("\\", "/")
    if not raw:
        raise ValueError("A file name is required.")
    if raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
        raise ValueError("Only files inside ComfyUI's output folder can be cleaned.")
    sub = str(subfolder or "").strip().replace("\\", "/")
    relative = f"{sub}/{raw}" if sub else raw
    if any(part in {"..", ""} for part in relative.split("/")):
        raise ValueError("Invalid file path.")

    try:
        root = Path(folder_paths.get_directory_by_type(kind) or folder_paths.get_output_directory())
    except Exception:
        root = Path(folder_paths.get_output_directory())
    candidate = (root / relative).resolve()
    root_resolved = root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("Only files inside ComfyUI's output folder can be cleaned.") from exc
    if not candidate.is_file():
        raise FileNotFoundError(f"File not found: {candidate}")
    return candidate


def strip_file(path: str | Path, *, suffix: str = "_clean") -> dict[str, Any]:
    """Remux a video without its metadata tags (streams are copied, not re-encoded).

    Returns a report the panel can show: the new file, its size, and which tags
    disappeared. Raises ValueError with a usable message when ffmpeg is missing or
    the input is not a readable media file.
    """
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"File not found: {source}")
    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        raise ValueError("ffmpeg is required to strip metadata (install FFmpeg or imageio-ffmpeg).")

    stem = source.stem
    if stem.endswith(suffix):
        raise ValueError("That file already looks like a stripped copy.")
    target = source.with_name(f"{stem}{suffix}{source.suffix}")
    if target.exists():
        target = source.with_name(f"{stem}{suffix}-{os.getpid()}{source.suffix}")

    before = _ffprobe_tags(source)
    command = [
        ffmpeg,
        "-v", "error",
        "-nostdin",
        "-y",
        "-i", str(source),
        "-map", "0",
        "-c", "copy",
        "-map_metadata", "-1",
        str(target),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=_FFMPEG_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        target.unlink(missing_ok=True)
        raise ValueError(f"ffmpeg timed out after {_FFMPEG_TIMEOUT_SECONDS}s.") from exc
    if result.returncode != 0:
        target.unlink(missing_ok=True)
        message = result.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ValueError(f"ffmpeg failed: {message[-1] if message else 'unknown error'}")

    after = _ffprobe_tags(target)
    removed = sorted(key for key in before if key not in after)
    return {
        "ok": True,
        "source": str(source),
        "path": str(target),
        "filename": target.name,
        "removed_tags": removed,
        "before_bytes": source.stat().st_size,
        "after_bytes": target.stat().st_size,
        "embedded_before": any(key in before for key in ("workflow", "prompt")),
        "embedded_after": any(key in after for key in ("workflow", "prompt")),
    }


__all__ = [
    "DEFAULT_EMBED",
    "EMBED_CHOICES",
    "app_setting_policy",
    "comfyui_disabled",
    "metadata_for",
    "normalize_embed_policy",
    "resolve",
    "resolve_output_file",
    "strip_file",
]
