# MiniMax H3 Motion Director - let the prompt enhancer see a RefMod character.
# Copyright (C) 2026 WakaSoft. GPL-3.0. See LICENSE.

"""Read a RefMod's character so captions can be grounded in it.

A RefMod arrives at the Director as an unnamed latent blob that is appended to
``minimax_refs`` *after* text encoding, so the prompt never describes it and the
text encoder never sees it. That is deliberate - but it left the enhancer unable to
answer the two questions the guide still wants answered for a RefMod window
(docs/PROMPT_WRITING_GUIDE.md section 6.4):

* the ``wardrobe:`` line, which must MATCH whatever the mod shows, and
* an optional 2-4 word clue ("the auburn-haired woman").

Neither is a description of her face - prose about identity fights the reference
instead of helping it. Both need pixels, and this module is where pixels come from.
Three sources, cheapest first:

1. **The mod's own latents.** An ``encode``-mode mod stores what it was built from
   (a real H3 video-VAE encode, e.g. ``[1, 24, 4, 96, 54]`` = four 1536x864 frames),
   so decoding member 0 with the H3 video VAE returns the character images. This
   works for any mod, including one somebody else made, and needs no guessing about
   where the source files went. A ``training``-mode mod is refused: its latent is an
   averaged thumbnail, and a blurry blob cannot tell clothing from a wall.
2. **The metadata**, which is free (safetensors header only): name, kind, mode,
   description, tags, latent shape. The pack's own prompt_hint uses ``description``;
   it is used here the same way - as author-supplied text, never as invention.
3. **A file or folder** the caller points at (``input/`` relative or absolute), for
   when the character images are still on disk.

The decode reuses ComfyUI's own VAE plumbing (``comfy.sd.VAE`` + its ModelPatcher),
so the VAE participates in ComfyUI's VRAM accounting, respects ``--cpu-vae``, and
falls back to tiled decoding instead of dying when the card is busy.
"""

from __future__ import annotations

import io
import json
import logging
import os

from PIL import Image

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.lib")

MOD_SUFFIX = ".safetensors"
IMAGE_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
)
# RefMod metadata keys, in the order the standalone format and bundles use them.
META_KEYS = ("refmod_meta", "audio_refmod_meta")

# Defaults sized for a caption, not for a render: the model answers "what is she
# wearing" from a few hundred pixels, and the vision path re-encodes to JPEG anyway.
DEFAULT_MAX_FRAMES = 2
DEFAULT_MAX_EDGE = 768
DEFAULT_JPEG_QUALITY = 88

# Both H3 VAEs match, and the audio one must not be picked for a visual mod.
_VIDEO_VAE_HINTS = ("minimax_h3_video_vae",)

# Escape hatch for a layout the scans below do not cover (a mounted drive, a
# portable install, a renamed file that still is the H3 video VAE).
VAE_ENV_VAR = "MINIMAX_H3_REFMOD_VAE"


def _folder_paths():
    import folder_paths  # imported lazily: the pack imports offline in tests

    return folder_paths


def _models_dir() -> str:
    try:
        return _folder_paths().models_dir
    except Exception:
        return ""


def mod_search_dirs() -> list[str]:
    """Every place a mod may live, mirroring the RefMod pack's own search order.

    Kept in this pack rather than imported from ``ComfyUI-MiniMaxH3Mod``: loading
    another custom node pack by path breaks when it is moved, renamed or split.
    """
    dirs: list[str] = []
    try:
        for path in _folder_paths().get_folder_paths("refmods") or []:
            if path and path not in dirs:
                dirs.append(path)
    except Exception:
        pass
    base = _models_dir()
    for extra in ("refmods", "mods", os.path.join("refmods", "people")):
        candidate = os.path.join(base, extra) if base else ""
        if candidate and os.path.isdir(candidate) and candidate not in dirs:
            dirs.append(candidate)
    return dirs


def read_mod_metadata(path: str) -> dict | None:
    """The mod's metadata block, read from the safetensors header (no tensors)."""
    if not path or not os.path.isfile(path):
        return None
    try:
        from safetensors import safe_open
    except Exception:
        return None
    try:
        with safe_open(path, framework="pt") as handle:
            header = handle.metadata() or {}
            keys = list(handle.keys())
    except Exception as exc:  # corrupt file, wrong format, permission
        log.debug("RefMod metadata read failed for %s: %s", path, exc)
        return None
    for key in META_KEYS:
        raw = header.get(key)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        if isinstance(data, dict):
            data.setdefault("_tensor_keys", keys)
            return data
    return None


def _member_tensor_keys(meta: dict | None) -> list[tuple[str, dict]]:
    """(tensor key, member metadata) pairs for the visual members, in order."""
    tensor_keys = list((meta or {}).get("_tensor_keys") or ["latent"])
    members = (meta or {}).get("members")
    if isinstance(members, list) and members:
        pairs = []
        for index, member in enumerate(members):
            if not isinstance(member, dict):
                continue
            if str(member.get("kind") or "") not in ("image", "video"):
                continue
            key = tensor_keys[index] if index < len(tensor_keys) else f"ref_{index}"
            if key in tensor_keys:
                pairs.append((key, member))
        return pairs
    # Standalone mod: one tensor, kind from the metadata itself.
    if str((meta or {}).get("kind") or "video") in ("image", "video"):
        key = tensor_keys[0] if tensor_keys else "latent"
        return [(key, dict(meta or {}))]
    return []


def describe_mod(path: str) -> dict:
    """Free summary of a mod file, for the panel and the response note."""
    meta = read_mod_metadata(path) or {}
    pool = str(meta.get("pool") or "")
    return {
        "path": path,
        "name": str(meta.get("name") or os.path.splitext(os.path.basename(path))[0]),
        "kind": str(meta.get("kind") or ""),
        "mode": str(meta.get("mode") or ""),
        "concept_type": str(meta.get("concept_type") or ""),
        "description": str(meta.get("description") or ""),
        "tags": [str(tag) for tag in (meta.get("tags") or [])],
        "pool": pool,
        "summary": " - ".join(part for part in (pool, "; ".join(meta.get("tags") or [])) if part),
    }


def _refmod_files() -> list[str]:
    found: list[str] = []
    for directory in mod_search_dirs():
        for root, subdirs, files in os.walk(directory):
            subdirs[:] = sorted(sub for sub in subdirs if not sub.startswith("."))
            for name in sorted(files):
                if name.endswith(MOD_SUFFIX):
                    found.append(os.path.join(root, name))
    return found


def list_refmods() -> list[dict]:
    """List usable mods (visual only) for the panel's picker.

    Mods without valid metadata are skipped rather than listed: ``models/refmods``
    also holds other formats, and the RefMod pack's own dropdown filters the same
    way. A mod whose metadata says ``audio`` has no character to describe.
    """
    out: list[dict] = []
    for path in _refmod_files():
        meta = read_mod_metadata(path)
        if not meta or str(meta.get("kind") or "") == "audio":
            continue
        root = ""
        for directory in mod_search_dirs():
            if os.path.commonpath([os.path.abspath(path), os.path.abspath(directory)]) == os.path.abspath(directory):
                root = directory
                break
        relative = os.path.relpath(path, root) if root else os.path.basename(path)
        entry = describe_mod(path)
        entry["id"] = relative[: -len(MOD_SUFFIX)] if relative.endswith(MOD_SUFFIX) else relative
        entry["mode"] = entry["mode"] or "encode"
        entry["pooled"] = entry["mode"] == "training"
        out.append(entry)
    out.sort(key=lambda item: item["id"].lower())
    return out


def _images_in(directory: str, limit: int) -> list[str]:
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return []
    out: list[str] = []
    for name in names:
        if os.path.splitext(name)[1].lower() in IMAGE_SUFFIXES:
            out.append(os.path.join(directory, name))
        if len(out) >= limit:
            break
    return out


def resolve_mod(spec: str) -> str | None:
    """A mod name (``people/elf_girl``) or path to its .safetensors file."""
    text = str(spec or "").strip()
    if not text:
        return None
    candidates: list[str] = []
    if os.path.isabs(text):
        candidates.append(text)
    else:
        candidates.append(os.path.join(_models_dir(), text) if _models_dir() else "")
        for directory in mod_search_dirs():
            candidates.append(os.path.join(directory, text))
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and candidate.endswith(MOD_SUFFIX):
            return candidate
    for candidate in candidates:
        if candidate and os.path.isfile(candidate + MOD_SUFFIX):
            return candidate + MOD_SUFFIX
    return None


def resolve_source(spec: str, *, limit: int = 8) -> tuple[str, object, str]:
    """Resolve a character spec to ``("mod", path)``, ``("images", [paths])`` or an error.

    Order matters: a mod file wins over a folder of the same name, because the mod
    is the thing the prompt will not describe (that is why it needs captioning at
    all). Everything else is treated as ``input/``-relative unless absolute.
    """
    text = str(spec or "").strip()
    if not text:
        return "", None, "No RefMod character given."

    direct = os.path.join(_folder_paths().get_input_directory(), text) if not os.path.isabs(text) else text
    for candidate in (text, direct):
        if candidate and os.path.isfile(candidate) and candidate.lower().endswith(MOD_SUFFIX):
            return "mod", candidate, ""
        if candidate and os.path.isdir(candidate):
            images = _images_in(candidate, limit)
            if images:
                return "images", images, ""
            return "", None, f"No image files in folder: {candidate}"
        if candidate and os.path.isfile(candidate) and os.path.splitext(candidate)[1].lower() in IMAGE_SUFFIXES:
            return "images", [candidate], ""

    mod = resolve_mod(text)
    if mod:
        return "mod", mod, ""
    return "", None, (
        f"Nothing found for RefMod character '{text}'. Give a mod name under "
        "models/refmods (for example 'people/elf_girl'), or a path to an image, a "
        "folder of images, or a .safetensors mod file."
    )


def _vae_candidates(directory: str) -> list[str]:
    """Every file under a vae directory that could be the H3 video VAE."""
    found: list[str] = []
    if not directory or not os.path.isdir(directory):
        return found
    for root, subdirs, files in os.walk(directory):
        subdirs[:] = sorted(sub for sub in subdirs if not sub.startswith("."))
        for name in sorted(files):
            if not name.endswith(".safetensors"):
                continue
            if any(hint in name.lower() for hint in _VIDEO_VAE_HINTS):
                found.append(os.path.join(root, name))
    return found


def _extra_vae_dirs() -> list[str]:
    """VAE directories the running server uses but a bare import may not know.

    ``folder_paths`` only holds the paths it was configured with, so an
    ``extra_model_paths.yaml`` that points ``vae`` at a second models tree (the
    Easy-Install layout) is invisible to anything that imports ``folder_paths``
    without going through ComfyUI's startup. The file is read here for that one key
    rather than pulling in a YAML dependency: only a plain ``vae: <path>`` line in a
    relative or absolute form is honoured, which is all those configs contain.
    """
    dirs: list[str] = []
    try:
        base = _folder_paths().base_path
    except Exception:
        base = ""
    if not base:
        return dirs
    config = os.path.join(base, "extra_model_paths.yaml")
    if not os.path.isfile(config):
        return dirs
    try:
        with open(config, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                stripped = line.strip()
                if stripped.startswith("#") or not stripped.lower().startswith("vae:"):
                    continue
                value = stripped.split(":", 1)[1].strip().strip("'\"")
                if not value:
                    continue
                if not os.path.isabs(value):
                    value = os.path.normpath(os.path.join(base, value))
                if os.path.isdir(value) and value not in dirs:
                    dirs.append(value)
    except OSError:
        return dirs
    return dirs


def pick_video_vae(name: str = "") -> tuple[str, str, str]:
    """(full path, display name, error) for the H3 video VAE, preferring fp16.

    Order: an explicit request, then ``folder_paths`` (what the live server indexes),
    then an environment override, then the filesystem. The fallbacks matter because
    the same pack has to work inside ComfyUI and in a plain script, and the search is
    limited to names that identify this VAE so a checkpoint in the same tree can
    never be picked.
    """
    wanted = str(name or "").strip()

    def _match(path: str) -> bool:
        base_name = os.path.basename(path).lower()
        return wanted.lower() in (base_name, os.path.splitext(base_name)[0])

    entries: list[str] = []
    try:
        entries = list(_folder_paths().get_filename_list("vae"))
    except Exception:
        entries = []
    matches = [
        entry for entry in entries
        if any(hint in os.path.basename(entry).lower() for hint in _VIDEO_VAE_HINTS)
    ]
    if wanted:
        matches = [entry for entry in matches if _match(entry)] or matches
    if matches:
        matches.sort(key=lambda entry: (0 if "fp16" in entry.lower() else 1, entry))
        for entry in matches:
            try:
                resolved = _folder_paths().get_full_path("vae", entry) or ""
            except Exception:
                resolved = ""
            if resolved:
                return resolved, entry, ""
    if wanted and not matches:
        # A user-typed name that is not in the index may still be a real file.
        if os.path.isfile(wanted):
            return wanted, os.path.basename(wanted), ""

    override = os.environ.get(VAE_ENV_VAR, "").strip()
    if override:
        if os.path.isfile(override):
            return override, os.path.basename(override), ""
        return "", wanted, f"{VAE_ENV_VAR} points at a missing file: {override}"

    directories: list[str] = []
    try:
        directories.extend(_folder_paths().get_folder_paths("vae") or [])
    except Exception:
        pass
    base = _models_dir()
    if base:
        parent = os.path.dirname(base)
        for candidate in (
            os.path.join(base, "vae"),
            os.path.join(parent, "models", "vae"),
            os.path.join(os.path.dirname(parent), "models", "vae"),
        ):
            if candidate not in directories:
                directories.append(candidate)
    for candidate in _extra_vae_dirs():
        if candidate not in directories:
            directories.append(candidate)

    found: list[str] = []
    for directory in directories:
        for path in _vae_candidates(directory):
            if path not in found:
                found.append(path)
    if wanted:
        found = [path for path in found if _match(path)] or found
    if found:
        found.sort(key=lambda path: (0 if "fp16" in os.path.basename(path).lower() else 1, path))
        return found[0], os.path.basename(found[0]), ""
    if wanted:
        return "", wanted, f"VAE '{wanted}' is not installed."
    return "", "", (
        "The MiniMax H3 video VAE is not installed, so the RefMod's stored frames "
        "cannot be decoded. Install it under models/vae, or point the panel at the "
        "character's images instead."
    )


def _latent_for_member(path: str, key: str, frames: int):
    """Load one member's latent, clamped to ``frames`` temporal steps."""
    import torch
    from safetensors import safe_open

    with safe_open(path, framework="pt", device="cpu") as handle:
        if key not in handle.keys():
            raise ValueError(f"RefMod member '{key}' is missing.")
        latent = handle.get_tensor(key)
    latent = latent.detach().to(torch.float16)
    if latent.ndim != 5:
        raise ValueError(f"Unsupported RefMod latent shape {tuple(latent.shape)}.")
    # [B, C, T, H, W]; one latent frame decodes to the first stored image.
    take = max(1, min(int(frames), int(latent.shape[2])))
    return latent[:, :, :take]


def decode_mod_frames(
    path: str,
    *,
    frames: int = DEFAULT_MAX_FRAMES,
    vae_name: str = "",
    member: int = 0,
) -> tuple[list, dict, str]:
    """Decode a mod's stored visual member into PIL frames.

    Returns ``(frame_list, info, error)``. ComfyUI's VAE object manages device
    placement, offloading and the tiled fallback, so a busy card degrades instead of
    raising; anything that still fails comes back as a readable error string.
    """
    info = describe_mod(path)
    meta = read_mod_metadata(path) or {}
    if not meta:
        return [], info, f"'{os.path.basename(path)}' is not a RefMod file."
    pairs = _member_tensor_keys(meta)
    if not pairs:
        return [], info, "This RefMod has no stored image or video reference."
    mode = str(meta.get("mode") or "encode")
    if mode == "training":
        return [], info, (
            "This RefMod was built in training mode, so its stored reference is an "
            "averaged thumbnail - decoding it would give a blurry blob, not a "
            "describable character. Point the panel at the character's images instead."
        )
    if member < 0 or member >= len(pairs):
        member = 0
    key, member_meta = pairs[member]
    info["member"] = member
    info["member_kind"] = str(member_meta.get("kind") or "")
    info["member_pool"] = str(member_meta.get("pool") or "")

    vae_file, vae_label, error = pick_video_vae(vae_name)
    if error:
        return [], info, error

    import torch
    import comfy.model_management as model_management
    import comfy.sd
    import comfy.utils

    try:
        latent = _latent_for_member(path, key, frames)
    except Exception as exc:
        return [], info, f"{type(exc).__name__}: {exc}"

    vae = None
    try:
        vae = comfy.sd.VAE(sd=comfy.utils.load_torch_file(vae_file))
        pixels = vae.decode(latent)
    except torch.cuda.OutOfMemoryError:
        return [], info, (
            "Ran out of VRAM decoding the RefMod (the H3 video VAE needs room on "
            "the card). Free VRAM and retry, or point the panel at the character's "
            "images instead."
        )
    except Exception as exc:
        return [], info, f"{type(exc).__name__}: {exc}"
    finally:
        del vae
        try:
            model_management.soft_empty_cache()
        except Exception:
            pass

    if pixels is None or getattr(pixels, "numel", lambda: 0)() == 0:
        return [], info, "The RefMod decoded to nothing."
    array = pixels.detach().float().cpu().numpy()
    frames_out = [array[index] for index in range(array.shape[0])]
    info["decoded"] = len(frames_out)
    info["vae"] = vae_label or os.path.basename(vae_file)
    return frames_out, info, ""


def _frame_to_b64(frame, *, max_edge: int, quality: int) -> str:
    import numpy as np

    array = np.asarray(frame)
    if array.ndim == 4:
        array = array[0]
    array = np.clip(array[..., :3], 0.0, 1.0)
    image = Image.fromarray((array * 255.0).astype("uint8"), mode="RGB")
    longest = max(image.size)
    if max_edge and longest > max_edge:
        scale = max_edge / float(longest)
        image = image.resize(
            (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
            Image.LANCZOS,
        )
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    import base64

    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _read_image_file_b64(path: str, *, max_edge: int, quality: int) -> str:
    image = Image.open(path).convert("RGB")
    longest = max(image.size)
    if max_edge and longest > max_edge:
        scale = max_edge / float(longest)
        image = image.resize(
            (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
            Image.LANCZOS,
        )
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    import base64

    return base64.b64encode(buffer.getvalue()).decode("ascii")


def character_images_b64(
    spec: str,
    *,
    max_frames: int = DEFAULT_MAX_FRAMES,
    max_edge: int = DEFAULT_MAX_EDGE,
    quality: int = DEFAULT_JPEG_QUALITY,
    vae_name: str = "",
) -> tuple[list[str], dict, str]:
    """Character images for the caption, from a mod or from files.

    Returns ``(images_b64, info, error)``. ``info`` always carries what is known
    about the source, including the mod's own metadata, so the caller can report it
    even when the decode fails.
    """
    max_frames = max(1, int(max_frames or DEFAULT_MAX_FRAMES))
    kind, payload, error = resolve_source(spec, limit=max_frames)
    if error:
        return [], {}, error
    if kind == "mod":
        frames, info, error = decode_mod_frames(
            payload, frames=max_frames, vae_name=vae_name
        )
        if error:
            return [], info, error
        images: list[str] = []
        for frame in frames:
            try:
                images.append(_frame_to_b64(frame, max_edge=max_edge, quality=quality))
            except Exception as exc:
                log.debug("RefMod frame encode failed: %s", exc)
        info["source"] = "mod"
        if not images:
            return [], info, "The RefMod frames could not be encoded for the model."
        return images, info, ""

    images = []
    for path in list(payload)[:max_frames]:
        try:
            images.append(_read_image_file_b64(path, max_edge=max_edge, quality=quality))
        except Exception as exc:
            log.debug("Character image read failed for %s: %s", path, exc)
    if not images:
        return [], {}, "None of the character images could be read."
    return images, {"source": "files", "files": list(payload)[:max_frames]}, ""
