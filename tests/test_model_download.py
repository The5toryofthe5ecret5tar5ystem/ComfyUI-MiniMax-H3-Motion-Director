"""Download progress accounting for the prompt enhancer panel.

`hf_hub_download` blocks with no progress callback, so the panel's progress bar is
fed by measuring the filesystem: bytes staged in
`<target>/.cache/huggingface/download` plus the finished file once it is moved out.
These tests pin that arithmetic, the phase machine, and the staleness guard that
stops a dead transfer's leftovers from showing a bar forever.
"""

from __future__ import annotations

import os
import time

import pytest

from mmx_pkg.lib import model_download


@pytest.fixture(autouse=True)
def _clean_state():
    model_download.reset()
    yield
    model_download.reset()


def _staging_file(target, name="abc.incomplete", size=250):
    staging = target / ".cache" / "huggingface" / "download"
    staging.mkdir(parents=True, exist_ok=True)
    path = staging / name
    path.write_bytes(b"x" * size)
    return path


def test_percent_tracks_staged_bytes(tmp_path):
    model_download.begin(
        model_id="q5", label="Q5_K (19.5 GB)", target_dir=tmp_path,
        expected_bytes=1000, filenames=["model.gguf"],
    )
    assert model_download.snapshot()["percent"] == 0.0

    _staging_file(tmp_path, size=250)
    snap = model_download.snapshot()
    assert snap["active"] is True
    assert snap["bytes"] == 250
    assert snap["percent"] == 25.0


def test_finished_file_is_counted_once(tmp_path):
    """The staged copy is moved out, so a finished file must not double count."""
    model_download.begin(
        model_id="q5", label="Q5_K", target_dir=tmp_path,
        expected_bytes=1000, filenames=["model.gguf"],
    )
    staged = _staging_file(tmp_path, size=400)
    (tmp_path / "model.gguf").write_bytes(b"y" * 400)
    staged.unlink()  # hf_hub_download moves the staged bytes to the final name

    snap = model_download.snapshot()
    assert snap["bytes"] == 400
    assert snap["percent"] == 40.0


def test_both_files_are_counted_during_the_vision_phase(tmp_path):
    model_download.begin(
        model_id="q5", label="Q5_K", target_dir=tmp_path,
        expected_bytes=1000, filenames=["model.gguf", "mmproj.gguf"],
    )
    (tmp_path / "model.gguf").write_bytes(b"y" * 700)
    _staging_file(tmp_path, name="mmproj.incomplete", size=100)
    model_download.set_phase("vision")

    snap = model_download.snapshot()
    assert snap["phase"] == "vision"
    assert snap["bytes"] == 800
    assert snap["percent"] == 80.0


def test_finish_and_fail_mark_the_transfer_done(tmp_path):
    model_download.begin(
        model_id="q5", label="Q5_K", target_dir=tmp_path,
        expected_bytes=1000, filenames=["model.gguf"],
    )
    assert model_download.is_active() is True
    model_download.finish()
    snap = model_download.snapshot()
    assert snap["active"] is False and snap["done"] is True and snap["phase"] == "done"

    model_download.begin(
        model_id="q5", label="Q5_K", target_dir=tmp_path,
        expected_bytes=1000, filenames=["model.gguf"],
    )
    model_download.fail("HTTP 500")
    snap = model_download.snapshot()
    assert snap["active"] is False and snap["done"] is True
    assert snap["error"] == "HTTP 500"


def test_rate_and_eta_use_sampled_bytes(tmp_path, monkeypatch):
    """A second poll with more bytes on disk yields a rate and a finite ETA."""
    clock = {"t": 0.0}
    monkeypatch.setattr(model_download.time, "monotonic", lambda: clock["t"])

    model_download.begin(
        model_id="q5", label="Q5_K", target_dir=tmp_path,
        expected_bytes=1000, filenames=["model.gguf"],
    )
    _staging_file(tmp_path, size=100)
    clock["t"] = 10.0
    first = model_download.snapshot()
    assert first["rate_bps"] == 0.0  # one sample cannot say anything yet

    clock["t"] = 20.0
    _staging_file(tmp_path, size=300)
    second = model_download.snapshot()
    assert second["rate_bps"] == pytest.approx(20.0, rel=1e-3)
    assert second["eta_seconds"] is not None
    assert second["eta_seconds"] == pytest.approx(700 / 20.0, rel=1e-3)


def test_untracked_staging_is_reported_only_while_fresh(tmp_path, monkeypatch):
    """A leftover staging file from a dead process must not look like progress."""
    monkeypatch.setattr(
        "mmx_pkg.lib.prompt_local_models.download_dir", lambda root=None: tmp_path,
    )
    staged = _staging_file(tmp_path, size=500)

    fresh = model_download.snapshot()
    assert fresh["active"] is True and fresh["fallback"] is True
    assert fresh["bytes"] == 500 and fresh["percent"] is None

    old = time.time() - (model_download._STALE_SECONDS + 30)
    os.utime(staged, (old, old))
    stale = model_download.snapshot()
    assert stale["active"] is False and stale["bytes"] == 0


def test_no_state_and_no_staging_is_quiet(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "mmx_pkg.lib.prompt_local_models.download_dir", lambda root=None: tmp_path,
    )
    snap = model_download.snapshot()
    assert snap == {
        "active": False, "done": False, "fallback": False, "model_id": "", "label": "",
        "phase": "", "bytes": 0, "expected_bytes": 0, "percent": None,
        "rate_bps": 0.0, "eta_seconds": None, "error": "",
    }
