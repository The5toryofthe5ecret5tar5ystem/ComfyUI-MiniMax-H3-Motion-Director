"""Machine profile detection: tier mapping, busy-GPU downgrade, backend probes."""

from __future__ import annotations

from mmx_pkg.lib import machine_profile as mp


def test_tiers_cover_the_expected_cards():
    assert mp.tier_for_vram(None)["id"] == "small"
    assert mp.tier_for_vram(11.9)["id"] == "small"
    assert mp.tier_for_vram(12.0)["id"] == "small"
    assert mp.tier_for_vram(16.0)["id"] == "medium"
    assert mp.tier_for_vram(20.0)["id"] == "medium"
    assert mp.tier_for_vram(24.0)["id"] == "large"  # RTX 3090
    assert mp.tier_for_vram(32.0)["id"] == "large"  # RTX 5090
    assert mp.tier_for_vram(48.0)["id"] == "xl"
    assert mp.tier_for_vram("nonsense")["id"] == "small"


def test_every_tier_baseline_satisfies_the_h3_grids():
    for tier in mp.BASELINE_TIERS:
        baselines = tier["baselines"]
        for key in ("segment_frames", "max_segment_frames"):
            frames = int(baselines[key])
            assert frames % 17 == 5, f"{tier['id']}.{key} must be on the 17k+5 grid"
            assert 5 <= frames <= 512
        assert int(baselines["max_segment_frames"]) >= int(baselines["segment_frames"])
        for key in ("width", "height"):
            assert int(baselines[key]) % 32 == 0, f"{tier['id']}.{key} must be a canvas multiple"
        assert 0.1 <= float(baselines["megapixels"]) <= 16
    # Tiers only ever grow.
    order = [int(tier["baselines"]["segment_frames"]) for tier in mp.BASELINE_TIERS]
    assert order == sorted(order)


def test_busy_gpu_drops_one_tier_and_says_why():
    idle = mp.baselines_for_vram(24.0, free_vram_gb=23.0)
    assert idle["tier"] == "large" and idle["downgraded"] is False
    assert idle["downgrade_reason"] == ""

    busy = mp.baselines_for_vram(24.0, free_vram_gb=6.0)
    assert busy["tier"] == "large"  # the card is still reported as what it is
    assert busy["downgraded"] is True
    assert busy["baselines"]["segment_frames"] == 175  # medium tier numbers
    assert "6.0 GB of 24.0 GB is free" in busy["downgrade_reason"]


def test_small_card_cannot_downgrade_below_the_floor():
    floor = mp.baselines_for_vram(8.0, free_vram_gb=1.0)
    assert floor["downgraded"] is True
    assert floor["baselines"] == mp.BASELINE_TIERS[0]["baselines"]


def test_backend_probes_report_availability_without_raising():
    probes = mp.probe_backends(refresh=True)
    assert set(probes) == {"sdpa", "sage", "comfy_kitchen", "xformers", "flash_attn", "triton"}
    for name, entry in probes.items():
        assert entry["name"] == name
        assert isinstance(entry["available"], bool)
        assert isinstance(entry["detail"], str)
        assert isinstance(entry["error"], str)
    # Cached: a second call returns the same shape without re-importing.
    assert mp.probe_backends()["sdpa"]["available"] is True


def test_collect_profile_is_json_serializable_and_self_consistent():
    import json

    profile = mp.collect_machine_profile(refresh=False)
    json.dumps(profile)
    assert profile["tier"] in mp.TIER_IDS
    assert profile["pack_version"] != ""
    assert profile["device"]["total_vram_gb"] is None or profile["device"]["total_vram_gb"] > 0
    assert set(profile["baselines"]) >= {
        "megapixels",
        "width",
        "height",
        "segment_frames",
        "max_segment_frames",
        "ref_max_size",
    }


def test_override_replaces_only_the_total(monkeypatch):
    fake = {
        "index": 0,
        "available": True,
        "name": "Fake GPU",
        "capability": "8.6",
        "total_vram_gb": 8.0,
        "free_vram_gb": 7.5,
    }
    monkeypatch.setattr(mp, "detect_devices", lambda: [dict(fake)])
    profile = mp.collect_machine_profile(vram_gb_override=24.0)
    assert profile["device"]["total_vram_gb"] == 24.0
    assert profile["device"]["free_vram_gb"] == 7.5
    assert profile["tier"] == "large"
