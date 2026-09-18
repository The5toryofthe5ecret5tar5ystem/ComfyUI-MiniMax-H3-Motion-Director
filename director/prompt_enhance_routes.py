# Portions derived from ComfyUI_MiniMaxH3_Director
# Copyright AIMixer and contributors
# Originally licensed under Apache License 2.0
# Modified for MiniMax H3 Motion Director, 2026-08-09
# This derivative project is distributed under GPL-3.0.
# See NOTICE and LICENSES/Apache-2.0-AIMixer.txt.

"""HTTP routes for MiniMax H3 Motion Director LLM prompt enhancement."""

from __future__ import annotations

import asyncio
import html
import logging
from pathlib import Path

from aiohttp import web

from ..lib.h3_prompt_caption import CAPTION_RECIPES
from ..lib.h3_prompt_polish import is_polish_mode
from ..lib.h3_prompt_recipes import recipe_options, resolve_recipe
from ..lib.h3_prompt_rules import h3_rules_enabled
from ..lib.prompt_enhance_templates import (
    DETAILED_MIN_TOTAL_HAN,
    OUTPUT_LANGUAGE_EN,
    build_character_detail_directive,
    count_han_chars,
    get_enhance_template,
    is_character_feature_enhance_enabled,
    normalize_output_language,
)
from ..lib.prompt_enhancer import (
    API_FORMAT_LOCAL,
    API_FORMAT_OLLAMA,
    API_FORMAT_OPENAI_COMPAT,
    DEFAULT_API_FORMAT,
    DEFAULT_OPENAI_COMPAT_MODE,
    OPENAI_COMPAT_MODE_LLAMA_SWAP,
    coerce_llm_model,
    coerce_llm_url,
    default_model_for_format,
    default_url_for_format,
    enhance_prompt_sync,
    infer_api_format,
    list_llm_models,
    llama_swap_unload_endpoint,
    llm_headers,
    llm_unload_endpoint,
    normalize_openai_compat_mode,
)
from ..lib.task_prompts import resolve_task_key
from .prompt_enhance_media import (
    extract_input_video_frames_b64,
    is_replace_task_prompt,
    load_input_image_b64,
)

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.director")


def _engine_state_for(api_format: str) -> dict | None:
    """Engine/residency snapshot for the panel, local backend only.

    The panel keeps one engine note (which backend loaded, which model is resident,
    how much VRAM is free). Returning it with the responses that can change it
    means the note is never stale after an enhancement or an unload - and a stale
    note is what makes a correct "nothing was resident" read as a lie.
    """
    if api_format != API_FORMAT_LOCAL:
        return None
    from ..lib.prompt_local_runtime import engine_info

    try:
        return engine_info()
    except Exception as exc:  # noqa: BLE001 - reporting must not fail a request
        log.debug("engine info unavailable: %s", exc)
        return None


def _caption_note_for(caption_result, refmod_info: dict) -> str:
    """What the user should know about a caption-built prompt.

    Two cases earn a note: a RefMod window whose wardrobe line or clue could not be
    written (the guide is explicit that an unfilled wardrobe slot lets the model keep
    the source performer's outfit), and a mod whose own metadata was used.
    """
    parts: list[str] = []
    skipped = list(getattr(caption_result, "skipped", []) or [])
    if "performer-visible" in skipped:
        parts.append(
            "The source performer could not be hidden before the action caption "
            "(the subject could not be masked), so that caption saw her as she is."
        )
    if "wardrobe" in skipped:
        parts.append(
            "The RefMod character showed no clear outfit, so no wardrobe line was "
            "written - name it yourself if the mod's clothing must be kept."
        )
    if "clue" in skipped:
        parts.append("No short clue was added.")
    if (refmod_info or {}).get("source") == "mod":
        name = refmod_info.get("name") or "the RefMod"
        mode = refmod_info.get("mode") or "encode"
        parts.append(
            f"Character read from the RefMod '{name}' ({mode} mode, "
            f"{refmod_info.get('decoded', '?')} frame(s) decoded with "
            f"{refmod_info.get('vae') or 'the H3 video VAE'})."
        )
    return " ".join(parts)


async def director_refmod_list(request):
    """RefMods the panel can offer as a character source (metadata only, cheap).

    Header-only reads: listing a folder of mods must not load any tensors, and the
    panel calls this on open.
    """
    from ..lib.refmod_character import list_refmods, mod_search_dirs

    def _scan():
        return list_refmods(), mod_search_dirs()

    try:
        mods, dirs = await asyncio.to_thread(_scan)
    except Exception as exc:  # noqa: BLE001
        log.exception("RefMod scan failed")
        return web.json_response({"error": f"{type(exc).__name__}: {exc}"}, status=500)
    return web.json_response({"mods": mods, "search_dirs": dirs})


async def director_enhance_models(request):
    """List the models the panel can offer for the selected backend.

    Local mode answers from ComfyUI's own models/LLM tree (plus the curated
    download list), so the dropdown shows what the user actually has instead of
    a hardcoded name that may not exist on their machine.
    """
    try:
        data = await request.json()
    except Exception:
        data = {}

    raw_url = data.get("llm_url") or data.get("ollama_url")
    api_format = infer_api_format(
        raw_url or "",
        data.get("api_format") or data.get("llm_api_format") or DEFAULT_API_FORMAT,
    )

    if api_format == API_FORMAT_LOCAL:
        return await _local_models_response()

    raw_url = data.get("llm_url") or data.get("ollama_url")
    api_format = infer_api_format(raw_url or "", data.get("api_format") or data.get("llm_api_format") or DEFAULT_API_FORMAT)
    url = coerce_llm_url(raw_url, default=default_url_for_format(api_format))
    api_key = (data.get("api_key") or data.get("llm_api_key") or "").strip()
    models, err = await list_llm_models(url, api_format, api_key=api_key)
    if err:
        return web.json_response({"error": err}, status=502)
    return web.json_response({"models": models})


async def director_get_template(request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    task = resolve_task_key(data.get("task_type") or "default")
    output_language = data.get("output_language") or data.get("llm_output_language") or OUTPUT_LANGUAGE_EN
    return web.json_response({
        "template": get_enhance_template(task, output_language=output_language),
        "task_type": task,
    })


async def director_enhance_prompt(request):
    try:
        data = await request.json()
    except Exception as exc:
        return web.json_response({"error": f"Invalid JSON: {exc}"}, status=400)

    task_type = data.get("task_type") or "default"
    raw_url = data.get("llm_url") or data.get("ollama_url")
    api_format = infer_api_format(
        raw_url or "",
        data.get("api_format") or data.get("llm_api_format") or DEFAULT_API_FORMAT,
    )
    url = coerce_llm_url(raw_url, default=default_url_for_format(api_format))

    # Default the model per backend: a local model id comes from the catalog,
    # whereas the remote backends fall back to their own default model name.
    model = coerce_llm_model(
        (data.get("model") or data.get("llm_model") or "").strip(),
        default=default_model_for_format(api_format),
    )
    if not model:
        return web.json_response({"error": "No model selected"}, status=400)

    user_prompt = (data.get("prompt") or "").strip()
    if not user_prompt:
        return web.json_response({"error": "Empty prompt"}, status=400)

    openai_compat_mode = normalize_openai_compat_mode(
        data.get("openai_compat_mode")
        or data.get("llm_openai_compat_mode")
        or DEFAULT_OPENAI_COMPAT_MODE
    )
    api_key = (data.get("api_key") or data.get("llm_api_key") or "").strip()
    images = data.get("images") or []
    image_num = int(data.get("image_num") or max(1, len(images)))
    ref_slots_raw = data.get("ref_slots") or data.get("ref_slot_indices") or []
    ref_slots = [int(s) for s in ref_slots_raw if s is not None and str(s).strip() != ""]
    source_count = data.get("source_count", data.get("vision_source_count"))
    if source_count is not None:
        source_count = int(source_count)
    ref_video_count = int(data.get("ref_video_count") or data.get("vision_ref_video_count") or 0)
    custom_template = (data.get("custom_template") or "").strip()
    output_language = data.get("output_language") or data.get("llm_output_language") or OUTPUT_LANGUAGE_EN
    character_feature_enhance = data.get("character_feature_enhance")
    if character_feature_enhance is None:
        character_feature_enhance = data.get("llm_character_feature_enhance")
    if character_feature_enhance is None:
        character_feature_enhance = False
    unload_after = bool(data.get("unload_ollama") or data.get("llm_unload_after"))
    h3_rules = data.get("h3_rules")
    if h3_rules is None:
        h3_rules = data.get("llm_h3_rules")
    h3_rules_compact = data.get("h3_rules_compact")
    if h3_rules_compact is None:
        h3_rules_compact = data.get("llm_h3_rules_compact")
    h3_recipe = str(data.get("h3_recipe") or data.get("llm_h3_recipe") or "").strip()
    prompt_mode = str(data.get("prompt_mode") or "rewrite").strip().lower()
    # Wording only: the user's own prompt comes back reworded, with its headings,
    # tags and claims untouched. It is not a caption request and not a rewrite, so
    # it skips every block below that decides the shape of the answer.
    polish_mode = is_polish_mode(prompt_mode)

    audio_policy = str(data.get("audio_policy") or "").strip()
    # RefMod windows have no <Picture N> slots: the identity arrives as latents after
    # text encoding, so the captions must be grounded in the mod itself. The spec is a
    # mod name (people/elf_girl), an input/-relative image or folder, or a path.
    refmod_character = str(
        data.get("refmod_character") or data.get("llm_refmod_character") or ""
    ).strip()
    refmod_frames = int(data.get("refmod_frames") or 0)
    refmod_vae = str(data.get("refmod_vae") or "").strip()
    # i2v / fl2v carry fixed endpoint frames that are neither source frames nor
    # reference slots, so they travel separately and reach only the frame captions.
    frame_images = [img for img in (data.get("frame_images") or []) if img]
    hide_performer = bool(data.get("hide_performer") or data.get("llm_hide_performer"))
    resolved_recipe = resolve_recipe(
        h3_recipe,
        task_key=resolve_task_key(task_type),
        has_source=bool(source_count),
        replace=is_replace_task_prompt(user_prompt),
    )

    refmod_info: dict = {}

    def _character_images() -> list[str]:
        """Frames of the RefMod character, from the mod file or from images.

        Runs inside the caption thread: decoding a mod loads the H3 video VAE and is
        the only expensive part of caption mode that is not an LLM call. A failure
        here is raised rather than skipped - the caller asked for the character, and
        "no wardrobe line because the decode failed" is not something to discover
        from the output.
        """
        nonlocal refmod_info
        from ..lib.refmod_character import DEFAULT_MAX_FRAMES, character_images_b64

        images, info, error = character_images_b64(
            refmod_character,
            max_frames=refmod_frames or DEFAULT_MAX_FRAMES,
            vae_name=refmod_vae,
        )
        refmod_info = info or {}
        if error:
            raise ValueError(f"RefMod character '{refmod_character}': {error}")
        return images

    def _build_from_images():
        """Caption the images and assemble the block (see h3_prompt_caption).

        Ordering matters and is inherited from the workflow this ports: the vision
        payload is source frames first, then reference images, so the identity
        caption never sees the source performer and the action caption never sees
        the new character. RefMod frames are a third, separate group - they must not
        leak into the action caption either.
        """
        from ..lib.h3_prompt_caption import build_from_images

        frames = list(images[: max(0, int(source_count or 0))])
        refs = list(images[max(0, int(source_count or 0)) :]) if source_count else list(images)
        character: list[str] = []
        if resolved_recipe == "character_replace_refmod" and refmod_character:
            character = _character_images()
        return build_from_images(
            recipe=resolved_recipe,
            url=url,
            model=model,
            api_format=api_format,
            user_prompt=user_prompt,
            openai_compat_mode=openai_compat_mode,
            api_key=api_key,
            source_images=frames,
            reference_images=refs,
            character_images=character,
            frame_images=frame_images,
            hide_performer=bool(hide_performer),
            audio_policy=audio_policy or "source",
            output_language=output_language,
            unload_after=unload_after,
        )

    caption_mode_requested = prompt_mode in ("captions", "images", "from_images")
    caption_note = ""

    def _unload_after_report() -> dict | None:
        """Did "unload the model afterwards" actually leave nothing resident?

        The unload happens inside the enhancement (in the worker thread), so the
        only honest way to report it is to look at what is left afterwards: an
        empty cache means it ran, a resident model means it did not. Without this
        the panel could only say "done" - which is exactly what made a working
        unload and a broken one indistinguishable to the user.
        """
        if not (unload_after and api_format == API_FORMAT_LOCAL):
            return None
        from ..lib.prompt_local_runtime import free_vram_gb, resident_info

        left = resident_info() or {}
        return {
            "requested": True,
            "released": not left,
            "resident_path": str(left.get("model_path") or ""),
            "free_gb": free_vram_gb(),
        }
    if caption_mode_requested:
        if resolved_recipe not in CAPTION_RECIPES:
            # t2v has nothing to look at, and i2v/fl2v frames are not sent to the
            # enhancer today, so those recipes keep the rewrite path.
            caption_note = (
                "Building from images covers the replace, reference-segment and "
                f"source-edit recipes; recipe '{resolved_recipe}' was rewritten instead."
            )
        elif not images and not frame_images and not (
            resolved_recipe == "character_replace_refmod" and refmod_character
        ):
            # A RefMod window is the one recipe whose images need not come from the
            # segment: its character is in the mod, not in a <Picture N> slot.
            caption_note = (
                "Building from images needs the segment's source frames and reference "
                "images attached, a RefMod character for a RefMod window, or the "
                "endpoint frames for an i2v/fl2v segment; this request carried none, "
                "so it was rewritten."
            )
        else:
            try:
                caption_result, caption_err = await asyncio.to_thread(_build_from_images)
            except Exception as exc:  # noqa: BLE001
                log.exception("Caption build failed")
                caption_result, caption_err = None, f"{type(exc).__name__}: {exc}"
            if caption_result is not None:
                log.info(
                    "Prompt built from images (%s): %d chars "
                    "(identity %d, character %d, scene %d, action %d, skipped %s)",
                    resolved_recipe,
                    len(caption_result.text),
                    len(caption_result.identity),
                    len(caption_result.character),
                    len(caption_result.scene),
                    len(caption_result.action),
                    ",".join(caption_result.skipped) or "none",
                )
                if refmod_info:
                    log.info(
                        "RefMod character: source=%s name=%s mode=%s member=%s "
                        "decoded=%s (skipped: %s)",
                        refmod_info.get("source") or "mod",
                        refmod_info.get("name") or "-",
                        refmod_info.get("mode") or "-",
                        refmod_info.get("member", "-"),
                        refmod_info.get("decoded", "-"),
                        ",".join(caption_result.skipped) or "none",
                    )
                han = count_han_chars(caption_result.text)
                return web.json_response({
                    "response": caption_result.text,
                    "han_count": han,
                    "detailed_mode": False,
                    "character_feature_enhance": False,
                    "detail_target_han": None,
                    "detail_measure": len(caption_result.text.strip()),
                    "detail_unit": "chars",
                    "h3_rules": False,
                    "h3_recipe": resolved_recipe,
                    "prompt_mode": "captions",
                    "refmod": refmod_info,
                    "hide_performer": bool(hide_performer),
                    "unload_after": _unload_after_report(),
                    "engine": _engine_state_for(api_format),
                    "note": _caption_note_for(caption_result, refmod_info),
                })
            return web.json_response(
                {"error": caption_err or "Building the prompt from images failed"},
                status=502,
            )

    # enhance_prompt_sync is blocking by design (urllib for remote backends,
    # llama.cpp for local). Local generation runs for tens of seconds, so it goes
    # to a worker thread: on the event loop it would freeze the whole ComfyUI UI
    # for the duration.
    polish_report: dict = {}

    def _enhance():
        return enhance_prompt_sync(
            task_type=task_type,
            user_prompt=user_prompt,
            url=url,
            model=model,
            api_format=api_format,
            openai_compat_mode=openai_compat_mode,
            api_key=api_key,
            images_b64=images if images else None,
            image_num=image_num,
            custom_template=custom_template,
            output_language=output_language,
            character_feature_enhance=character_feature_enhance,
            vision_source_count=source_count,
            ref_slots=ref_slots or None,
            vision_ref_video_count=ref_video_count,
            unload_after=unload_after,
            h3_rules=h3_rules,
            h3_recipe=resolved_recipe,
            h3_rules_compact=h3_rules_compact,
            audio_policy=audio_policy,
            prompt_mode="polish" if polish_mode else "rewrite",
            polish_report=polish_report,
        )

    try:
        text, err = await asyncio.to_thread(_enhance)
    except Exception as exc:
        log.exception("Director enhance route failed")
        return web.json_response({"error": f"{type(exc).__name__}: {exc}"}, status=502)
    if err:
        return web.json_response({"error": err}, status=502)
    if not text:
        return web.json_response({"error": "Enhancement returned empty"}, status=502)
    task_key = resolve_task_key(task_type)
    feature_enhance = is_character_feature_enhance_enabled(character_feature_enhance)
    detail_directive = build_character_detail_directive(
        feature_enhance,
        output_language=output_language,
        task_key=task_key,
    )
    detailed_mode = feature_enhance and bool(detail_directive)
    han_count = count_han_chars(text)
    # The gate that decides whether a retry is worth it measures han for a Chinese
    # answer and plain characters otherwise; reporting the same number keeps the
    # panel from calling a 2000-character English answer "short".
    detailed_zh = normalize_output_language(output_language) == "zh"
    detail_measure = han_count if detailed_zh else len(text.strip())
    # The wording pass reports what its structure check found - nothing when the
    # tags and headings survived, a warning when they did not.
    note = str(polish_report.get("note") or caption_note) if polish_mode else caption_note
    return web.json_response({
        "response": text,
        "han_count": han_count,
        "detailed_mode": detailed_mode,
        "character_feature_enhance": feature_enhance,
        "detail_target_han": DETAILED_MIN_TOTAL_HAN if detailed_mode else None,
        "detail_measure": detail_measure,
        "detail_unit": "han" if detailed_zh else "chars",
        "h3_rules": h3_rules_enabled(h3_rules),
        "h3_rules_compact": h3_rules_enabled(h3_rules) and h3_rules_enabled(h3_rules_compact),
        "h3_recipe": resolved_recipe,
        "prompt_mode": "polish" if polish_mode else "rewrite",
        "polish": polish_report or None,
        "unload_after": _unload_after_report(),
        "engine": _engine_state_for(api_format),
        "note": note,
    })


MAX_VISION_FRAMES = 5


def _as_seconds(value) -> float | None:
    """A finite, non-negative timestamp, or None when the caller sent nothing usable."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return max(0.0, number)


async def director_extract_frames(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    filename = data.get("filename") or data.get("videoFile") or ""
    subfolder = data.get("subfolder") or ""
    num_frames = min(max(int(data.get("num_frames") or 3), 1), MAX_VISION_FRAMES)
    # A segment's window, when the caller knows one: the caption must describe the
    # slice being rendered, not three moments from elsewhere in the source.
    start_sec = _as_seconds(data.get("start_sec", data.get("startSec")))
    end_sec = _as_seconds(data.get("end_sec", data.get("endSec")))
    frames, err = extract_input_video_frames_b64(
        filename,
        subfolder=subfolder,
        num_frames=num_frames,
        start_sec=start_sec,
        end_sec=end_sec,
    )
    if err:
        status = 404 if "not found" in err.lower() else 500
        return web.json_response({"error": err}, status=status)
    return web.json_response({
        "frames": frames,
        "num_frames": len(frames),
        "in_window": bool(start_sec is not None and end_sec is not None and end_sec > start_sec),
    })


async def director_image_b64(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    filename = data.get("filename") or data.get("imageFile") or ""
    b64, err = load_input_image_b64(
        filename,
        subfolder=data.get("subfolder") or "",
        kind=data.get("type") or data.get("kind") or "input",
    )
    if err:
        status = 404 if "not found" in err.lower() else 400
        return web.json_response({"error": err}, status=status)
    return web.json_response({"image": b64})


async def director_unload_model(request):
    import aiohttp

    try:
        data = await request.json()
    except Exception:
        data = {}
    raw_url = data.get("llm_url") or data.get("ollama_url")
    api_format = infer_api_format(raw_url or "", data.get("api_format") or data.get("llm_api_format") or API_FORMAT_OLLAMA)
    url = coerce_llm_url(raw_url, default=default_url_for_format(api_format))
    raw_model = (data.get("model") or data.get("llm_model") or "").strip()

    if api_format == API_FORMAT_LOCAL:
        # A local model lives in ComfyUI's own process (lib/prompt_local_runtime), so
        # unloading it is a call into that runtime, not an HTTP request to a server.
        # Deliberately ahead of the model-name guard: handing VRAM back must not
        # depend on the panel still naming a model, and the runtime already knows
        # which one is resident.
        from ..lib.prompt_local_runtime import free_vram_gb, resident_info, unload_local_models

        resident = resident_info() or {}
        free_before = free_vram_gb()
        # Worker thread: closing a model collects garbage and empties the CUDA cache,
        # and neither belongs on the event loop that is also serving renders.
        released = await asyncio.to_thread(unload_local_models)
        free_after = free_vram_gb()
        return web.json_response(
            {
                "status": "unloaded",
                "provider": "Local (ComfyUI)",
                "model": Path(resident.get("model_path") or raw_model).name,
                # How many resident models were dropped. Zero is a valid answer (the
                # panel says so instead of claiming it freed memory that was never held).
                "released": released,
                # What was actually being held, and what the card looks like now. The
                # panel needs both to be honest: an empty cache is not the same claim
                # as "your VRAM is free", and ComfyUI's own render models are a
                # different thing from this one.
                "resident_path": str(resident.get("model_path") or ""),
                "free_gb_before": free_before,
                "free_gb_after": free_after,
                "engine": _engine_state_for(api_format),
            }
        )

    model = coerce_llm_model(raw_model)
    if not model:
        return web.json_response({"error": "No model selected"}, status=400)
    openai_compat_mode = normalize_openai_compat_mode(
        data.get("openai_compat_mode")
        or data.get("llm_openai_compat_mode")
        or DEFAULT_OPENAI_COMPAT_MODE
    )
    api_key = (data.get("api_key") or data.get("llm_api_key") or "").strip()

    if api_format == API_FORMAT_OLLAMA:
        endpoint = llm_unload_endpoint(url)
        payload = {"model": model, "keep_alive": 0}
        headers = None
        success_label = "Ollama"
    elif api_format == API_FORMAT_OPENAI_COMPAT and openai_compat_mode == OPENAI_COMPAT_MODE_LLAMA_SWAP:
        endpoint = llama_swap_unload_endpoint(url, model)
        payload = None
        headers = llm_headers(api_format, include_json=False, api_key=api_key)
        success_label = "llama-swap"
    else:
        return web.json_response({"error": "Current API format does not support model unload"}, status=400)

    try:
        async with aiohttp.ClientSession() as session:
            kwargs = {
                "timeout": aiohttp.ClientTimeout(total=10),
            }
            if payload is not None:
                kwargs["json"] = payload
            if headers:
                kwargs["headers"] = headers
            async with session.post(endpoint, **kwargs) as resp:
                if not (200 <= resp.status < 300):
                    text = await resp.text()
                    return web.json_response({"error": f"{success_label} HTTP {resp.status}: {text[:200]}"}, status=502)
                await resp.read()
        return web.json_response({"status": "unloaded", "model": model, "provider": success_label})
    except Exception as exc:
        return web.json_response({"error": f"{type(exc).__name__}: {exc}"}, status=502)


async def director_unload_ollama(request):
    return await director_unload_model(request)


async def _local_models_response():
    """Build the local model list without blocking the event loop.

    Enumerating a deep models/LLM tree can touch a network mount, so it runs in a
    worker thread.
    """
    def collect() -> dict:
        from ..lib.prompt_local_models import build_catalog, download_dir
        from ..lib.prompt_local_runtime import engine_info, resident_info, runtime_available

        catalog = build_catalog()
        ok, runtime_note = runtime_available()
        default = catalog.resolve_default()
        return {
            "models": [m.to_dict() for m in catalog.models],
            "default": catalog.default_id,
            "resolved_default": default.id if default else "",
            "installed_count": len(catalog.installed()),
            "runtime_available": ok,
            "runtime_note": runtime_note,
            "engine": engine_info(),
            "download_dir": str(download_dir()),
            "resident": resident_info(),
            "errors": catalog.errors,
        }

    payload = await asyncio.to_thread(collect)
    return web.json_response(payload)


async def director_download_model(request):
    """Fetch a catalog model into ComfyUI's models/LLM tree.

    The client is expected to have shown the size and got consent first; the
    `confirm` flag is the server-side enforcement of that, so a stray request
    cannot silently pull multiple gigabytes.
    """
    try:
        data = await request.json()
    except Exception as exc:
        return web.json_response({"error": f"Invalid JSON: {exc}"}, status=400)

    model_id = str(data.get("model") or data.get("model_id") or "").strip()
    if not model_id:
        return web.json_response({"error": "No model selected"}, status=400)
    if not data.get("confirm"):
        return web.json_response(
            {"error": "Download not confirmed. Show the size and ask the user first."},
            status=400,
        )

    def run_download() -> dict:
        from ..lib.model_download import begin, fail, finish, is_active, set_phase
        from ..lib.prompt_local_models import build_catalog, download_dir, free_disk_bytes

        catalog = build_catalog()
        entry = catalog.get(model_id)
        if entry is None:
            return {"error": f"Unknown local model id: {model_id}"}
        if entry.installed:
            return {"status": "already-installed", "path": entry.path}
        if not entry.downloadable:
            return {"error": f"{entry.label} has no download source configured."}

        target_dir = download_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        needed = entry.total_download_bytes
        free = free_disk_bytes(target_dir)
        if free and needed and free < needed * 1.1:
            return {
                "error": (
                    f"Not enough free disk space: {needed / 1e9:.1f} GB needed, "
                    f"{free / 1e9:.1f} GB free at {target_dir}."
                )
            }

        try:
            from huggingface_hub import hf_hub_download
        except Exception as exc:  # noqa: BLE001
            return {"error": f"huggingface_hub is not available: {exc}"}

        if is_active():
            # Two transfers sharing one staging folder would report each other's
            # bytes; the panel polls this route, so refuse rather than lie.
            return {"error": "Another download is already in progress. Wait for it to finish."}

        filenames = [entry.filename]
        if entry.vision and entry.mmproj_filename:
            filenames.append(entry.mmproj_filename)
        begin(
            model_id=entry.id,
            label=entry.label,
            target_dir=target_dir,
            expected_bytes=needed,
            filenames=filenames,
        )

        try:
            path = hf_hub_download(
                repo_id=entry.repo_id,
                filename=entry.filename,
                local_dir=str(target_dir),
            )
        except Exception as exc:  # noqa: BLE001
            fail(f"{type(exc).__name__}: {exc}")
            return {"error": f"Download failed: {type(exc).__name__}: {exc}"}

        mmproj_path = ""
        if entry.vision and entry.mmproj_filename:
            set_phase("vision")
            try:
                mmproj_path = hf_hub_download(
                    repo_id=entry.mmproj_repo_id or entry.repo_id,
                    filename=entry.mmproj_filename,
                    local_dir=str(target_dir),
                )
            except Exception as exc:  # noqa: BLE001 - text enhancement still works
                log.warning("Prompt enhancer: vision projector download failed: %s", exc)

        finish()
        return {"status": "downloaded", "path": str(path), "mmproj_path": str(mmproj_path or "")}

    payload = await asyncio.to_thread(run_download)
    status = 400 if payload.get("error") else 200
    return web.json_response(payload, status=status)


async def director_enhance_recipes(request):
    """The prompt recipes the panel's dropdown offers.

    Served from the pack rather than hardcoded in the frontend so the two cannot
    drift, and so a new recipe needs no JS change.
    """
    return web.json_response({"recipes": recipe_options()})


async def director_download_status(request):
    """Progress of the model download the panel is waiting on.

    hf_hub_download blocks inside its own thread for the whole transfer, so the
    bytes come from the download's staging folder rather than from a callback.
    """
    from ..lib.model_download import snapshot

    return web.json_response(await asyncio.to_thread(snapshot))



async def director_prompt_enhancer_setup(request):
    """Serve the local-engine setup guide from inside ComfyUI.

    The guide ships with the pack, so the link in the panel works offline and
    from private checkouts - no GitHub or documentation-site dependency.
    """
    from pathlib import Path

    doc = Path(__file__).resolve().parent.parent / "docs" / "PROMPT_ENHANCER_LOCAL_SETUP.md"
    try:
        body = doc.read_text(encoding="utf-8")
    except OSError as exc:
        body = f"Setup guide not found ({doc}): {exc}"
    page = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Prompt enhancer - local engine setup</title></head>"
        "<body style='background:#12151b;color:#d6dbe6;padding:24px;"
        "font:13px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace'>"
        f"<pre style='white-space:pre-wrap;max-width:900px'>{html.escape(body)}</pre>"
        "</body></html>"
    )
    return web.Response(text=page, content_type="text/html")


def register_prompt_enhance_routes(routes, register_route) -> None:
    register_route(routes, "POST", "/minimax/motion-director/enhance_models", director_enhance_models)
    register_route(routes, "GET", "/minimax/motion-director/prompt_enhancer_setup", director_prompt_enhancer_setup)
    register_route(routes, "POST", "/minimax/motion-director/get_template", director_get_template)
    register_route(routes, "POST", "/minimax/motion-director/enhance", director_enhance_prompt)
    register_route(routes, "POST", "/minimax/motion-director/extract_frames", director_extract_frames)
    register_route(routes, "POST", "/minimax/motion-director/image_b64", director_image_b64)
    register_route(routes, "POST", "/minimax/motion-director/unload_model", director_unload_model)
    register_route(routes, "POST", "/minimax/motion-director/unload_ollama", director_unload_ollama)
    register_route(routes, "POST", "/minimax/motion-director/download_model", director_download_model)
    register_route(routes, "GET", "/minimax/motion-director/download_status", director_download_status)
    register_route(routes, "GET", "/minimax/motion-director/enhance_recipes", director_enhance_recipes)
    register_route(routes, "GET", "/minimax/motion-director/refmod_list", director_refmod_list)
    log.info("MiniMax H3 Motion Director prompt-enhance HTTP routes registered")
