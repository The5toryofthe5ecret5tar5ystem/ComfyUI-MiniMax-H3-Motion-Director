# Portions derived from ComfyUI_MiniMaxH3_Director
# Copyright AIMixer and contributors
# Originally licensed under Apache License 2.0
# Modified for MiniMax H3 Motion Director, 2026-08-09
# This derivative project is distributed under GPL-3.0.
# See NOTICE and LICENSES/Apache-2.0-AIMixer.txt.

"""MiniMax H3 conditioning — delegates to ComfyUI official MiniMaxH3 nodes."""

from __future__ import annotations

import torch

from ..lib.image_prep import fit_canvas, preflight_h3_visual_conditioning
from ..lib.ref_images import MAX_REFERENCE_IMAGES, REF_IMAGE_KEY_PREFIX, flatten_reference_kwargs
from ..lib.task_modes import TASK_DESCRIPTIONS, infer_task
from ..patches.markers import MC_KEY


def _encode_source_bridge_anchor(vae, frame, *, width: int, height: int):
    if not isinstance(frame, torch.Tensor) or frame.ndim != 4 or int(frame.shape[0]) != 1:
        raise ValueError("Source Bridge anchor must be one IMAGE frame [1,H,W,C].")
    resized = fit_canvas(frame, int(width), int(height))
    encoded = vae.encode(resized)
    if not isinstance(encoded, torch.Tensor) or encoded.ndim != 5:
        raise ValueError(
            "Source Bridge video VAE must return [B,C,T,H,W], got %r."
            % (getattr(encoded, "shape", type(encoded)),)
        )
    if int(encoded.shape[2]) != 1:
        raise ValueError(
            "Source Bridge single-frame anchor encoded to %d temporal steps; expected 1."
            % int(encoded.shape[2])
        )
    return encoded


def append_minimax_keyframe_anchors(
    conditioning,
    *,
    vae,
    first_frame,
    last_frame,
    frame_count: int,
    width: int,
    height: int,
):
    """Append H3-native first/last anchors after ReferenceToVideo conditioning.

    The official reference node builds ``minimax_refs`` and the target latent
    first.  This helper then adds two keyframes on the existing H3 layout: frame
    0 from the left nominal generation and frame 4 from the right generation.
    """
    if int(frame_count) != 5:
        raise ValueError("Source Bridge anchors require exactly 5 target frames.")
    if not isinstance(conditioning, (list, tuple)) or not conditioning:
        raise ValueError("Source Bridge positive conditioning is empty.")

    first_latent = _encode_source_bridge_anchor(
        vae, first_frame, width=width, height=height
    )
    last_latent = _encode_source_bridge_anchor(
        vae, last_frame, width=width, height=height
    )
    keyframes = [
        {
            "resolved_frame_index": 0,
            MC_KEY: 0,
            "latent": first_latent,
        },
        {
            "resolved_frame_index": 0,
            MC_KEY: 4,
            "latent": last_latent,
        },
    ]

    merged = []
    for entry in conditioning:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            raise ValueError("Source Bridge conditioning entry has an invalid shape.")
        metadata = dict(entry[1] or {})
        if metadata.get("minimax_keyframes"):
            raise ValueError(
                "Source Bridge conditioning already contains MiniMax keyframes; "
                "refusing to overwrite them."
            )
        # Keep the exact refs payload that the official ReferenceToVideo node
        # produced; h3_layout.py already supports refs + marked keyframes.
        metadata["minimax_keyframes"] = [dict(item) for item in keyframes]
        metadata["minimax_frame_count"] = 5
        merged.append([entry[0], metadata, *entry[2:]])
    return merged


def harvest_refmod_refs(conditioning) -> list:
    """Collect RefMod reference blocks from a connected CONDITIONING.

    ``Apply H3 RefMod`` (ComfyUI-MiniMaxH3Mod) appends its reference latents to
    ``minimax_refs`` - the same key the official ReferenceToVideo node fills - so
    a connected conditioning can contribute references here.

    Only that reference payload is kept. The prompt and the target latent in the
    connected conditioning were built for a different prompt and a different
    frame size than this node's per-segment conditioning, so they are discarded:
    appending the refs to each segment's own conditioning is what makes them
    take effect. Returns ``[]`` when nothing usable is connected.

    Blocks are returned as shallow copies because the same list is handed to
    every segment. They are read-only downstream (RefMod's step curve rebuilds
    rather than mutates), but copying stops a future in-place edit from leaking
    across segments.
    """
    if not conditioning:
        return []
    if not isinstance(conditioning, (list, tuple)):
        raise ValueError(
            "refmod_conditioning must be a native ComfyUI CONDITIONING. Wire it "
            "through Apply H3 RefMod (conditioning in, conditioning out); the "
            "ComfyUI-MiniMaxH3 pack conditioning object is not supported."
        )

    blocks: list = []
    for entry in conditioning:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        metadata = entry[1]
        if not isinstance(metadata, dict):
            continue
        for item in metadata.get("minimax_refs") or []:
            if isinstance(item, dict):
                blocks.append(dict(item))
    return blocks


def refmod_digest(blocks) -> str:
    """Stable identity for a set of harvested RefMod blocks.

    The blocks are appended to every segment's conditioning, so swapping a mod
    changes the picture - but they arrive through the conditioning rather than
    the timeline, so nothing else in a cache fingerprint notices the change. Two
    different mods at the same retention produced byte-identical fingerprints,
    which meant changing the mod silently reused latents generated with the
    previous one and the old identity bled into the new render.

    The tensors actually fed to the DiT are hashed rather than any file name,
    because by this point a mod is an unnamed latent blob: there is no name to
    compare. Strength is folded in implicitly, since it is applied to the latent
    before it gets here.
    """
    if not blocks:
        return ""
    try:
        import hashlib

        import torch

        parts: list[str] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            # Shape first: it is cheap and distinguishes two mods that happen to
            # hash identically in content but are pooled differently.
            parts.append("|".join(
                str(block.get(key, ""))
                for key in ("kind", "latent_h", "latent_w", "latent_t", "ref_audio_t")
            ))
            for key in ("latent", "audio_latent"):
                tensor = block.get(key)
                if not isinstance(tensor, torch.Tensor) or tensor.numel() == 0:
                    continue
                arr = (
                    tensor.detach()
                    .to(device="cpu", dtype=torch.float32)
                    .contiguous()
                    .numpy()
                )
                parts.append(hashlib.sha256(arr.tobytes()).hexdigest())
        if not parts:
            return ""
        joined = "\n".join(parts).encode("utf-8")
        return hashlib.sha256(joined).hexdigest()[:16]
    except Exception as exc:  # pragma: no cover - defensive
        # Returning a constant marker (rather than "") keeps the value stable
        # across runs while still differing from a real digest, so a failure here
        # invalidates caches instead of silently reusing another mod's output.
        print(f"[RefMod] could not fingerprint the harvested blocks: {exc}")
        return "unavailable"


def _refmod_metadata_keys(conditioning) -> list:
    """The metadata keys actually present on a connected conditioning."""
    seen: set = set()
    try:
        for entry in conditioning:
            if (isinstance(entry, (list, tuple)) and len(entry) >= 2
                    and isinstance(entry[1], dict)):
                seen.update(entry[1].keys())
    except TypeError:
        pass
    return sorted(seen)


def harvest_and_report_refmods(conditioning) -> list:
    """Harvest RefMod blocks and say which of the three wiring states we are in.

    Shared by every Director entry point. There is more than one: the registered
    node's ``execute`` lives in ``nodes/director_inputs.py`` and overrides the one
    in ``nodes/director.py``, so the wiring has to be applied through a common
    helper rather than repeated per class - repeating it is exactly how the two
    silently diverged before.

    All three states are printed rather than logged, because they must survive
    whatever log level ComfyUI is configured with, and two of them used to print
    nothing at all: a RefMod that was never wired and a RefMod that was wired but
    carried nothing looked identical from the console, and both looked like "the
    mod had no effect". The empty case dumps the metadata keys it saw so a wrong
    key name is visible instead of silent.

    Returns ``[]`` when nothing usable is connected.
    """
    if conditioning is None:
        print(
            "[RefMod] refmod_conditioning is NOT connected - no RefMod references "
            "are used by any segment."
        )
        return []

    blocks = harvest_refmod_refs(conditioning)
    if blocks:
        # Print the digest, not just the count. A count cannot tell two different
        # mods apart, which is exactly how "I switched mods and the old identity
        # is still showing" became invisible: the log looked identical either way.
        # The mod's name is not available here - it arrives as an unnamed latent
        # blob, and the label->name map stays on the RefMod node's other output.
        print(
            f"[RefMod] {len(blocks)} reference block(s) harvested from "
            f"refmod_conditioning and appended to every segment. "
            f"Mod digest {refmod_digest(blocks) or 'unavailable'} - this is part of "
            "the segment and motion-context cache keys, so swapping the mod "
            "invalidates cached work instead of reusing the previous mod."
        )
        return blocks

    print(
        "[RefMod] refmod_conditioning IS connected but carried no reference blocks, "
        "so nothing was appended. Check that Apply H3 RefMod receives a mod and that "
        "its retention is above 0."
    )
    print(
        "[RefMod]   conditioning metadata keys seen: "
        f"{_refmod_metadata_keys(conditioning)}"
    )
    return blocks


def append_refmod_references(conditioning, blocks):
    """Append RefMod reference blocks to already-built segment conditioning.

    Mirrors :func:`append_minimax_keyframe_anchors`: the official reference node
    has already produced ``minimax_refs`` and the target latent, and these blocks
    are concatenated onto that list. RefMod marks every block with
    ``refmod=True`` so its step-curve wrapper only re-mixes what it injected and
    leaves this node's own references untouched.

    RefMod blocks go after the native refs, which is the order the step curve's
    positional latent lookup expects.
    """
    if not blocks:
        return conditioning
    if not isinstance(conditioning, (list, tuple)) or not conditioning:
        raise ValueError("RefMod references require non-empty positive conditioning.")

    merged = []
    for entry in conditioning:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            raise ValueError("RefMod conditioning entry has an invalid shape.")
        metadata = dict(entry[1] or {})
        metadata["minimax_refs"] = list(metadata.get("minimax_refs") or []) + [
            dict(block) for block in blocks
        ]
        merged.append([entry[0], metadata, *entry[2:]])
    return merged


def _shared_optional_inputs() -> dict:
    return {
        "first_frame": (
            "IMAGE",
            {"tooltip": "Optional first keyframe (i2v / fl2v)."},
        ),
        "last_frame": (
            "IMAGE",
            {"tooltip": "Optional last keyframe (fl2v)."},
        ),
        **{
            f"{REF_IMAGE_KEY_PREFIX}{index}": (
                "IMAGE",
                {
                    "tooltip": (
                        f"Reference image for <Picture {index + 1}> in prompt (r2v). "
                        "Native aspect; H3 ref_image_size applies at encode time."
                    ),
                },
            )
            for index in range(MAX_REFERENCE_IMAGES)
        },
        "ref_image_size": (
            ["match", "max"],
            {
                "default": "match",
                "tooltip": "Reference image sizing for MiniMaxH3ReferenceToVideo.",
            },
        ),
    }


def _load_minimax_nodes():
    try:
        from comfy_extras.nodes_minimax_h3 import (
            MiniMaxH3ImageToVideo,
            MiniMaxH3ReferenceToVideo,
        )
    except ImportError as exc:
        raise RuntimeError(
            "MiniMaxH3MotionDirector requires ComfyUI official MiniMax H3 nodes "
            "(comfy_extras.nodes_minimax_h3). Upgrade to ComfyUI with PR #15224 merged."
        ) from exc
    return MiniMaxH3ImageToVideo, MiniMaxH3ReferenceToVideo


def _unpack_positive_latent(out):
    args = None
    if hasattr(out, "args"):
        args = out.args
    elif isinstance(out, (tuple, list)):
        args = out
    if args and len(args) >= 2:
        return args[0], args[1]
    raise RuntimeError(f"MiniMax H3 conditioning returned unexpected output: {type(out)!r}")


def _reference_images_dict_from_kwargs(kwargs: dict) -> dict | None:
    nested = kwargs.get("ref_images")
    if isinstance(nested, dict) and nested:
        out = {k: v for k, v in nested.items() if v is not None}
        return out or None

    refs = flatten_reference_kwargs(kwargs)
    out: dict[str, object] = {}
    for key, value in refs.items():
        if value is None:
            continue
        idx = key.removeprefix(REF_IMAGE_KEY_PREFIX)
        out[f"ref_image_{idx}"] = value
    return out or None


def _reference_videos_dict(ref_videos: dict | None) -> dict | None:
    if not ref_videos:
        return None
    out = {k: v for k, v in ref_videos.items() if v is not None}
    return out or None


def _task_hint(task_key: str, ref_images, ref_videos) -> str:
    ref_image_count = len(ref_images or {})
    ref_video_count = len(ref_videos or {})
    mode = infer_task(ref_image_count, ref_video_count)
    hint = f"{task_key or mode.value} — {TASK_DESCRIPTIONS[mode]} (MiniMax H3)"
    if ref_image_count or ref_video_count:
        hint += f" (~{ref_image_count} ref image(s), {ref_video_count} ref video(s))"
    return hint


def run_minimax_conditioning(
    *,
    clip,
    vae,
    audio_vae,
    prompt: str,
    width: int,
    height: int,
    length: int,
    task_key: str,
    first_frame=None,
    last_frame=None,
    ref_images=None,
    ref_videos=None,
    ref_video_audios=None,
    ref_audios=None,
    ref_image_size: str = "match",
    **kwargs,
):
    """Build positive conditioning + AV latent via official MiniMax H3 nodes."""
    ref_images = ref_images or _reference_images_dict_from_kwargs(kwargs)
    ref_videos = _reference_videos_dict(ref_videos)
    for name, frames in (ref_videos or {}).items():
        preflight_h3_visual_conditioning(
            frames,
            task_key=task_key,
            path=f"reference_video:{name}",
        )

    MiniMaxH3ImageToVideo, MiniMaxH3ReferenceToVideo = _load_minimax_nodes()

    use_reference = (
        task_key in {"r2v", "v2v", "rv2v"}
        or ref_images
        or ref_videos
        or ref_audios
        or ref_video_audios
    )

    if use_reference:
        if audio_vae is None:
            raise ValueError("MiniMax H3 r2v/v2v/rv2v / reference conditioning requires audio_vae.")
        out = MiniMaxH3ReferenceToVideo.execute(
            clip=clip,
            prompt=prompt,
            width=width,
            height=height,
            length=length,
            ref_image_size=ref_image_size,
            vae=vae,
            audio_vae=audio_vae,
            ref_images=ref_images,
            ref_videos=ref_videos,
            ref_video_audios=ref_video_audios,
            ref_audios=ref_audios,
        )
    else:
        out = MiniMaxH3ImageToVideo.execute(
            clip=clip,
            vae=vae,
            prompt=prompt,
            width=width,
            height=height,
            length=length,
            first_frame=first_frame,
            last_frame=last_frame,
        )

    positive, latent = _unpack_positive_latent(out)
    hint = _task_hint(task_key, ref_images, ref_videos)
    return positive, [], latent, hint


class MiniMaxH3MotionDirectorConditioning:
    """Thin wrapper around official MiniMax H3 conditioning (positive + latent)."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "clip": ("CLIP",),
                "vae": ("VAE",),
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "width": ("INT", {"default": 864, "min": 32, "max": 8192, "step": 32}),
                "height": ("INT", {"default": 480, "min": 32, "max": 8192, "step": 32}),
                "length": ("INT", {"default": 124, "min": 5, "max": 3600, "step": 17}),
            },
            "optional": {
                "audio_vae": ("VAE", {"tooltip": "Required for r2v / v2v / rv2v / reference video+audio."}),
                **_shared_optional_inputs(),
            },
        }

    RETURN_TYPES = ("CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "latent")
    FUNCTION = "apply"
    CATEGORY = "MiniMaxH3"

    def apply(self, clip, vae, prompt, width, height, length, audio_vae=None, **kwargs):
        positive, _, latent, _ = run_minimax_conditioning(
            clip=clip,
            vae=vae,
            audio_vae=audio_vae,
            prompt=prompt,
            width=width,
            height=height,
            length=length,
            task_key="r2v" if kwargs.get("ref_images") or any(
                k.startswith(REF_IMAGE_KEY_PREFIX) for k in kwargs
            ) else "t2v",
            **kwargs,
        )
        return positive, latent


class MiniMaxH3MotionDirectorPlannerConditioning:
    """Official MiniMax H3 conditioning plus task_mode string for planning UIs."""

    @classmethod
    def INPUT_TYPES(cls):
        base = MiniMaxH3MotionDirectorConditioning.INPUT_TYPES()
        return base

    RETURN_TYPES = ("CONDITIONING", "LATENT", "STRING")
    RETURN_NAMES = ("positive", "latent", "task_mode")
    FUNCTION = "apply"
    CATEGORY = "MiniMaxH3"

    def apply(self, clip, vae, prompt, width, height, length, audio_vae=None, **kwargs):
        positive, _, latent, hint = run_minimax_conditioning(
            clip=clip,
            vae=vae,
            audio_vae=audio_vae,
            prompt=prompt,
            width=width,
            height=height,
            length=length,
            task_key="r2v" if kwargs.get("ref_images") or any(
                k.startswith(REF_IMAGE_KEY_PREFIX) for k in kwargs
            ) else "t2v",
            **kwargs,
        )
        return positive, latent, hint
