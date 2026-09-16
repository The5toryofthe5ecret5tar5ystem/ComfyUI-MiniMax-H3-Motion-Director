"""Resident learned-latent upscaler (opt-in VRAM trade).

A non-cached upscale call runs after the H3 DiT is unloaded, so it is a full
load -> free cycle. `latent_upscale_cache_model` keeps the built model on the
device instead, which is opt-in because it holds that VRAM for the rest of the
session. These tests pin the cache key, the single-entry bound, and the release
paths without needing a real checkpoint (which is why they drive the helpers
directly rather than going through run_h3_latent_upscaler).
"""

from __future__ import annotations

import pytest
import torch
import torch.nn as nn

from director.h3_latent_upscaler_runtime import (
    _release_resident_model,
    _resident_model,
    _store_resident_model,
    clear_resident_model,
    has_resident_model,
)

CPU = torch.device("cpu")


@pytest.fixture(autouse=True)
def _clean_resident():
    clear_resident_model()
    yield
    clear_resident_model()


def _model() -> nn.Module:
    return nn.Linear(2, 2).eval().requires_grad_(False)


def test_nothing_is_resident_by_default():
    assert has_resident_model() is False
    assert _resident_model("/tmp/upscaler.safetensors", torch.float16, CPU) is None


def test_round_trip_returns_the_same_model(tmp_path):
    path = str(tmp_path / "upscaler.safetensors")
    model = _model()
    _store_resident_model(path, torch.float16, CPU, model, "3d")

    assert has_resident_model() is True
    hit = _resident_model(path, torch.float16, CPU)
    assert hit is not None
    resident, variant = hit
    assert resident is model
    assert variant == "3d"


def test_precision_and_device_are_part_of_the_key(tmp_path):
    path = str(tmp_path / "upscaler.safetensors")
    _store_resident_model(path, torch.float16, CPU, _model(), "3d")

    assert _resident_model(path, torch.bfloat16, CPU) is None
    assert _resident_model(path, torch.float16, torch.device("meta")) is None
    assert _resident_model(str(tmp_path / "other.safetensors"), torch.float16, CPU) is None


def test_only_one_model_is_held(tmp_path):
    first = str(tmp_path / "a.safetensors")
    second = str(tmp_path / "b.safetensors")
    _store_resident_model(first, torch.float16, CPU, _model(), "3d")
    _store_resident_model(second, torch.float16, CPU, _model(), "3d")

    assert _resident_model(first, torch.float16, CPU) is None
    assert _resident_model(second, torch.float16, CPU) is not None


def test_release_reports_whether_anything_was_freed(tmp_path):
    path = str(tmp_path / "upscaler.safetensors")
    _store_resident_model(path, torch.float16, CPU, _model(), "3d")

    assert clear_resident_model() is True
    assert has_resident_model() is False
    # Nothing left to free the second time.
    assert clear_resident_model() is False
    assert _release_resident_model() is False


def _read(relative: str) -> str:
    from pathlib import Path

    return Path(relative).read_text(encoding="utf-8")


def test_upscale_call_does_not_delete_a_kept_model():
    """The whole point of the flag: the caller must not drop the resident model.

    Driving this for real needs a checkpoint with a matching architecture, so the
    wiring is pinned in source instead.
    """
    source = _read("director/h3_latent_upscaler_runtime.py")
    assert "if not keep_resident:" in source
    assert "keep_resident = True" in source
    assert "_store_resident_model(path, dtype, dev, model, selected)" in source
    assert "_release_resident_model()" in source


def test_flag_is_threaded_from_the_refine_config_to_the_runtime():
    integration = _read("director/h3_learned_latent.py")
    assert "cache_model: bool = False" in integration
    assert "cache_model=bool(cache_model)" in integration

    refine = _read("director/refine_sampling.py")
    assert 'cache_model=bool(config.get("latent_upscale_cache_model"))' in refine
