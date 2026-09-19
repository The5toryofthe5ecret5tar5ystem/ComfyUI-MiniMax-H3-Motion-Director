"""App-wide Motion Director settings: defaults, validation, store round-trip."""

from __future__ import annotations

import json

import pytest

from mmx_pkg.director import motion_settings as ms


MACHINE = {
    "tier": "large",
    "baselines": {
        "megapixels": 1.0,
        "width": 1344,
        "height": 768,
        "segment_frames": 243,
        "max_segment_frames": 362,
        "ref_max_size": 1024,
    },
}


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(ms, "_user_directory", lambda: tmp_path)
    monkeypatch.setattr(ms, "settings_root", lambda: tmp_path / "minimax_h3_motion_director")
    return ms.MotionSettingsStore()


def test_defaults_follow_the_detected_tier():
    settings = ms.default_settings(MACHINE)
    assert settings["baselines"]["segment_frames"] == 243
    assert settings["baselines"]["max_segment_frames"] == 362
    assert settings["baselines"]["width"] == 1344
    assert settings["machine"]["profile"] == ms.PROFILE_AUTO
    # A field the tier does not know keeps its own default.
    assert settings["baselines"]["aspect_ratio"] == ms.DEFAULT_ASPECT_RATIO
    assert settings["run"]["auto_save_workflow"] is True


def test_frame_baselines_land_on_the_h3_grid():
    settings = ms.normalize_settings(
        {"baselines": {"segment_frames": 1, "max_segment_frames": 5000}}, machine=MACHINE
    )
    assert settings["baselines"]["segment_frames"] % 17 == 5
    assert settings["baselines"]["max_segment_frames"] % 17 == 5
    assert settings["baselines"]["max_segment_frames"] <= 512
    # Already-aligned values are not nudged around.
    kept = ms.normalize_settings({"baselines": {"segment_frames": 362}}, machine=MACHINE)
    assert kept["baselines"]["segment_frames"] == 362


def test_unknown_values_are_dropped_and_clamped():
    settings = ms.normalize_settings(
        {
            "schema_version": 99,
            "machine": {"profile": "nonsense", "device_index": -4, "vram_gb_override": 100000},
            "baselines": {
                "aspect_ratio": "77:9",
                "megapixels": 999,
                "width": 1001,
                "height": 13,
                "segment_frames": 1000,
                "max_segment_frames": 5,
                "ref_max_size": 5,
                "export_mode": "everything",
                "continuity_overlap_frames": 400,
                "nonsense": True,
            },
            "run": {"auto_save_workflow": "yes", "keep_models_resident": 1},
            "app": {"locale": "de"},
            "cache": {"warn_over_gb": -3},
            "surprise": {"deep": {"nested": 1}},
        },
        machine=MACHINE,
    )
    assert settings["schema_version"] == ms.SCHEMA_VERSION
    assert settings["machine"]["profile"] == ms.PROFILE_AUTO
    assert settings["machine"]["device_index"] == 0
    assert settings["machine"]["vram_gb_override"] == 1024.0
    assert settings["baselines"]["aspect_ratio"] == ms.DEFAULT_ASPECT_RATIO
    assert settings["baselines"]["megapixels"] == 16.0
    assert settings["baselines"]["width"] % 32 == 0 and settings["baselines"]["width"] <= 8192
    # A nonsense dimension snaps up to the smallest canvas multiple, while an
    # explicit 0 still means "derive it from aspect + megapixels".
    assert settings["baselines"]["height"] == 32
    assert ms.snap_dimension(0) == 0
    assert settings["baselines"]["segment_frames"] <= 512
    assert settings["baselines"]["max_segment_frames"] >= settings["baselines"]["segment_frames"]
    assert settings["baselines"]["ref_max_size"] == 32
    assert settings["baselines"]["export_mode"] == "all"
    assert settings["baselines"]["continuity_overlap_frames"] == 81
    assert settings["run"]["auto_save_workflow"] is True
    assert settings["run"]["keep_models_resident"] is True
    assert settings["app"]["locale"] == "auto"
    assert settings["cache"]["warn_over_gb"] == 0.0
    assert "surprise" not in settings
    assert "nonsense" not in settings["baselines"]


def test_store_round_trip_and_deep_patch(store):
    assert store.load(machine=MACHINE)["baselines"]["segment_frames"] == 243

    saved = store.save({"baselines": {"megapixels": 0.6}}, machine=MACHINE)
    assert saved["baselines"]["megapixels"] == 0.6
    # A patch touches only what it names.
    assert saved["baselines"]["segment_frames"] == 243
    assert saved["updated_at"] > 0

    again = store.load(machine=MACHINE)
    assert again["baselines"]["megapixels"] == 0.6
    raw = json.loads(ms.settings_path().read_text(encoding="utf-8"))
    assert raw["baselines"]["megapixels"] == 0.6


def test_store_rejects_bad_patch_and_survives_missing_file(store):
    with pytest.raises(ms.MotionSettingsError):
        store.save(["not", "an", "object"], machine=MACHINE)
    ms.settings_path().unlink(missing_ok=True)
    assert store.load(machine=MACHINE)["baselines"]["segment_frames"] == 243


def test_reset_baselines_returns_to_the_detected_tier(store):
    store.save({"baselines": {"segment_frames": 124, "megapixels": 0.4}}, machine=MACHINE)
    reset = store.save(None, machine=MACHINE, reset_baselines=True)
    assert reset["baselines"]["segment_frames"] == 243
    assert reset["baselines"]["megapixels"] == 1.0
    assert reset["machine"]["profile"] == ms.PROFILE_AUTO


def test_corrupt_file_is_reported_rather_than_silently_reset(store):
    store.save({"baselines": {"megapixels": 0.5}}, machine=MACHINE)
    ms.settings_path().write_text("{not json", encoding="utf-8")
    with pytest.raises(ms.MotionSettingsError) as excinfo:
        store.load(machine=MACHINE)
    assert "unreadable" in str(excinfo.value)


def test_valid_frame_baselines_are_left_alone():
    settings = ms.normalize_settings({"baselines": {"segment_frames": 362}}, machine=MACHINE)
    assert settings["baselines"]["segment_frames"] == 362
    assert settings["baselines"]["max_segment_frames"] == 362
