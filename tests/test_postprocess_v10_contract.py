"""Postprocess config contract (facade over the preserved v9 implementation).

Covers the v10 Face Refine cache-identity rule and the v11 ``audio_refine``
room/level section.
"""

from director.postprocess_config import (
    POSTPROCESS_CONFIG_VERSION,
    normalize_postprocess_config,
    postprocess_cache_fingerprint,
)


def test_postprocess_config_version_migrates_legacy_values():
    assert POSTPROCESS_CONFIG_VERSION == 11
    normalized = normalize_postprocess_config(
        {
            "version": 9,
            "face_refine": {
                "enabled": True,
                "mask_mode": "sam",
                "sam_model": "sam2_t.pt",
            },
            "global_refine": {"result_previews_enabled": True},
        }
    )
    assert normalized["version"] == 11
    assert normalized["face_refine"]["enabled"] is True
    assert normalized["face_refine"]["sam_model"] == "sam2_t.pt"
    assert normalized["global_refine"]["result_previews_enabled"] is True


def test_audio_refine_section_defaults_to_off():
    audio = normalize_postprocess_config({"version": 9})["audio_refine"]
    assert audio["enabled"] is False
    assert audio["sox_path"] == ""


def test_final_assembly_audio_does_not_change_cache_identity():
    """Turning a room on must not invalidate existing segment caches."""
    base = {
        "version": 11,
        "global_refine": {"enabled": True, "result_previews_enabled": False},
        "face_refine": {"enabled": True, "base_denoise": 0.45},
    }
    with_room = {**base, "audio_refine": {"enabled": True, "room": "bathroom"}}
    assert postprocess_cache_fingerprint(base) == postprocess_cache_fingerprint(with_room)


def test_a_legacy_per_segment_flag_cannot_change_cache_identity():
    """The room owns no per-segment artefact, so nothing about it may invalidate.

    ``per_segment`` used to put the room into the fingerprint while never
    affecting a single segment.  Configs saved back then still carry the flag,
    so it must stay inert rather than quietly re-enabling cache invalidation.
    """
    base = {"version": 11, "audio_refine": {"enabled": True, "room": "bathroom"}}
    legacy = {
        **base,
        "audio_refine": {"enabled": True, "room": "bathroom", "per_segment": True},
    }
    assert postprocess_cache_fingerprint(base) == postprocess_cache_fingerprint(legacy)


def test_face_refine_changes_cache_identity_but_result_preview_does_not():
    base = {
        "version": 9,
        "global_refine": {"enabled": True, "result_previews_enabled": False},
        "face_refine": {"enabled": True, "base_denoise": 0.45},
    }
    preview = {
        **base,
        "global_refine": {"enabled": True, "result_previews_enabled": True},
    }
    changed_face = {
        **base,
        "face_refine": {"enabled": True, "base_denoise": 0.55},
    }
    assert postprocess_cache_fingerprint(base) == postprocess_cache_fingerprint(preview)
    assert postprocess_cache_fingerprint(base) != postprocess_cache_fingerprint(changed_face)


def test_external_patch_opt_out_changes_cache_identity():
    """The opt-out can make refine skip, so it must be part of the identity."""
    base = {
        "version": 11,
        "global_refine": {"enabled": True, "allow_refine_on_external_patch": False},
    }
    opted_out = {
        "version": 11,
        "global_refine": {"enabled": True, "allow_refine_on_external_patch": True},
    }
    assert postprocess_cache_fingerprint(base) != postprocess_cache_fingerprint(opted_out)


def test_comparison_export_does_not_change_cache_identity():
    """Exporting a raw copy beside the processed video never changes frames."""
    base = {
        "version": 11,
        "global_refine": {"enabled": True, "export_comparison": False},
    }
    with_export = {
        "version": 11,
        "global_refine": {"enabled": True, "export_comparison": True},
    }
    normalized = normalize_postprocess_config(
        {"global_refine": {"export_comparison": "true"}}
    )
    assert normalized["global_refine"]["export_comparison"] is True
    assert postprocess_cache_fingerprint(base) == postprocess_cache_fingerprint(with_export)
