"""Cache manager + diagnostics routes: safe deletion, active-run guard, bundles."""

from __future__ import annotations

import json
import time

import pytest

from mmx_pkg.director import motion_settings as ms
from mmx_pkg.director import settings_routes as sr


@pytest.fixture()
def caches(tmp_path, monkeypatch):
    """Fake output dir + a settings store, both isolated per test."""
    output = tmp_path / "output"
    (output / "minimax_seg_cache" / "dir").mkdir(parents=True)
    (output / "minimax_seg_cache" / "other").mkdir(parents=True)
    (output / "minimax_motion_context_cache" / "dir").mkdir(parents=True)

    def fake_output_directory():
        output.mkdir(parents=True, exist_ok=True)
        return str(output)

    monkeypatch.setattr(sr.folder_paths, "get_output_directory", fake_output_directory)
    monkeypatch.setattr(ms, "_user_directory", lambda: tmp_path)
    monkeypatch.setattr(ms, "settings_root", lambda: tmp_path / "minimax_h3_motion_director")
    return output


def _write_segment_cache(output, node: str, index: int, size: int = 32) -> None:
    node_dir = output / "minimax_seg_cache" / node
    node_dir.mkdir(parents=True, exist_ok=True)
    (node_dir / f"seg_{index:04d}.pt").write_bytes(b"x" * size)
    (node_dir / f"seg_{index:04d}.meta.json").write_text("{}", encoding="utf-8")


def _write_manifest(output, node: str, state: str, *, updated: int | None = None, done: int = 0):
    node_dir = output / "minimax_seg_cache" / node
    node_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "state": state,
        "segment_total": 6,
        "updated": int(time.time()) if updated is None else int(updated),
        "done": {str(i): {"timeline_index": i} for i in range(done)},
    }
    (node_dir / "run_manifest.json").write_text(json.dumps(payload), encoding="utf-8")


def test_cache_report_sizes_counts_and_runs(caches):
    _write_segment_cache(caches, "dir", 0, size=100)
    _write_segment_cache(caches, "dir", 1, size=50)
    _write_manifest(caches, "dir", "done", done=2)

    report = sr.cache_report()
    assert report["output_dir"] == str(caches)
    kinds = {kind["id"]: kind for kind in report["kinds"]}
    assert set(kinds) == {"segments", "motion_context", "first_pass"}
    segments = kinds["segments"]
    rows = {row["node"]: row for row in segments["nodes"]}
    # The .pt payloads are what the size is about; the tiny meta/manifest JSON in the
    # same folder is counted too, so only the payload is asserted exactly.
    assert rows["dir"]["bytes"] >= 150
    assert rows["dir"]["segments"] == 2
    assert rows["dir"]["state"] == "done"
    assert rows["dir"]["done"] == 2
    assert rows["other"]["bytes"] == 0
    assert rows["other"]["segments"] == 0
    assert kinds["motion_context"]["exists"] is True
    assert kinds["first_pass"]["exists"] is False
    assert report["total_bytes"] >= 150
    assert report["total_gb"] == 0.0
    # Biggest first, so the list opens on what is worth clearing.
    assert segments["nodes"][0]["node"] == "dir"


def test_clear_one_node_frees_only_that_node(caches):
    _write_segment_cache(caches, "dir", 0, size=100)
    _write_segment_cache(caches, "other", 0, size=10)
    result = sr.clear_cache(kind="segments", node="dir")
    assert result["removed"] == ["dir"]
    assert result["bytes"] >= 100
    assert result["gb"] == 0.0
    assert not (caches / "minimax_seg_cache" / "dir").exists()
    assert (caches / "minimax_seg_cache" / "other").exists()


def test_clear_all_keeps_the_root(caches):
    _write_segment_cache(caches, "dir", 0)
    _write_segment_cache(caches, "other", 0)
    result = sr.clear_cache(kind="segments", all_nodes=True)
    assert sorted(result["removed"]) == ["dir", "other"]
    root = caches / "minimax_seg_cache"
    assert root.is_dir()
    assert list(root.iterdir()) == []


def test_clear_refuses_while_a_run_is_active(caches):
    _write_segment_cache(caches, "dir", 0)
    _write_manifest(caches, "dir", "running", done=1)
    with pytest.raises(ms.MotionSettingsError) as excinfo:
        sr.clear_cache(kind="segments", node="dir")
    assert "running render" in str(excinfo.value)
    assert (caches / "minimax_seg_cache" / "dir").is_dir()
    # ... and a stale "running" does not block cleanup forever.
    _write_manifest(caches, "dir", "running", updated=int(time.time()) - 7200, done=1)
    assert sr.clear_cache(kind="segments", node="dir")["removed"] == ["dir"]


def test_clear_rejects_traversal_and_unknown_kinds(caches):
    _write_segment_cache(caches, "dir", 0)
    with pytest.raises(ms.MotionSettingsError):
        sr.clear_cache(kind="segments", node="../dir")
    with pytest.raises(ms.MotionSettingsError):
        sr.clear_cache(kind="secrets", all_nodes=True)
    with pytest.raises(ms.MotionSettingsError):
        sr.clear_cache(kind="segments")
    with pytest.raises(ms.MotionSettingsError):
        sr.clear_cache(kind="segments", node="missing")
    assert (caches / "minimax_seg_cache" / "dir").is_dir()


def test_diagnostics_bundle_is_complete_and_serializable(caches):
    _write_segment_cache(caches, "dir", 0, size=64)
    _write_manifest(caches, "dir", "stopped", done=1)
    bundle = sr.diagnostics_bundle()
    json.dumps(bundle)
    assert bundle["pack"]["version"] not in {None, ""}
    assert bundle["machine"]["tier"] in {"small", "medium", "large", "xl"}
    assert bundle["settings"]["schema_version"] == ms.SCHEMA_VERSION
    assert bundle["cache"]["total_gb"] == 0.0  # 64 bytes rounds to zero    assert [row["node"] for row in bundle["runs"]] == ["dir"]
    assert bundle["runs"][0]["state"] == "stopped"
    assert {"sdpa", "sage", "comfy_kitchen"} <= set(bundle["machine"]["backends"])


def test_settings_route_payload_contains_detected_and_effective(caches):
    payload = sr._settings_payload(ms.STORE.load(), sr._machine_without_settings())
    assert payload["settings"]["schema_version"] == ms.SCHEMA_VERSION
    assert payload["machine"]["tier"] in {"small", "medium", "large", "xl"}
    assert payload["detected_baselines"]["segment_frames"] % 17 == 5
    assert payload["defaults"]["baselines"]["segment_frames"] == payload["detected_baselines"]["segment_frames"]
    assert payload["path"].endswith("settings.json")
