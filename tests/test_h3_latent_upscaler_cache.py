"""Learned-latent upscale: decoded checkpoint cache + device release.

The upscale stage reloads its checkpoint on every call, and a full safetensors
read plus a per-tensor float8 -> fp16 conversion per call is pure churn across a
long ComfyUI session. These tests pin the cache (hit, file-change invalidation,
bound) and the read-only contract the cache relies on.
"""

from __future__ import annotations

import os

import pytest
import torch

from director.h3_latent_upscaler_runtime import (
    _STATE_CACHE,
    _STATE_CACHE_LIMIT,
    _load_checkpoint,
    clear_checkpoint_cache,
)


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_checkpoint_cache()
    yield
    clear_checkpoint_cache()


def _write_checkpoint(path, value: float = 1.0) -> None:
    from safetensors.torch import save_file

    save_file({"conv_in.weight": torch.full((1, 1), value, dtype=torch.float32)}, str(path))


def test_repeated_loads_are_served_from_the_cache(tmp_path):
    ckpt = tmp_path / "upscaler.safetensors"
    _write_checkpoint(ckpt)

    first = _load_checkpoint(str(ckpt))
    second = _load_checkpoint(str(ckpt))

    # Identity, not equality: the second call must not re-read the file.
    assert second is first
    assert float(second["conv_in.weight"].item()) == 1.0


def test_cache_miss_after_the_file_changes(tmp_path):
    ckpt = tmp_path / "upscaler.safetensors"
    _write_checkpoint(ckpt, 1.0)
    first = _load_checkpoint(str(ckpt))

    _write_checkpoint(ckpt, 2.0)
    # A same-second rewrite trick keeps the size identical; force a distinct
    # mtime so the key genuinely changes on filesystems with coarse stamps.
    os.utime(ckpt, (0, 0))

    second = _load_checkpoint(str(ckpt))
    assert second is not first
    assert float(second["conv_in.weight"].item()) == 2.0


def test_missing_file_is_reported_not_cached(tmp_path):
    missing = tmp_path / "nope.safetensors"
    with pytest.raises(Exception):
        _load_checkpoint(str(missing))
    assert not _STATE_CACHE


def test_cache_is_bounded(tmp_path):
    paths = []
    for index in range(_STATE_CACHE_LIMIT + 2):
        path = tmp_path / f"upscaler{index}.safetensors"
        _write_checkpoint(path, float(index))
        paths.append(path)
        _load_checkpoint(str(path))

    assert len(_STATE_CACHE) == _STATE_CACHE_LIMIT
    # The newest entries survive, the oldest were evicted.
    newest = _load_checkpoint(str(paths[-1]))
    assert float(newest["conv_in.weight"].item()) == float(len(paths) - 1)


def test_clear_checkpoint_cache_forces_a_reload(tmp_path):
    ckpt = tmp_path / "upscaler.safetensors"
    _write_checkpoint(ckpt)
    first = _load_checkpoint(str(ckpt))
    clear_checkpoint_cache()
    assert not _STATE_CACHE
    assert _load_checkpoint(str(ckpt)) is not first


def test_decoded_state_is_not_mutated_by_model_build(tmp_path):
    """The cache hands the same dict out, so building a model must not alter it."""
    from director.h3_latent_upscaler_runtime import build_model_for_checkpoint

    ckpt = tmp_path / "upscaler.safetensors"
    _write_checkpoint(ckpt)
    state = _load_checkpoint(str(ckpt))
    snapshot = {key: value.clone() for key, value in state.items()}

    with pytest.raises(Exception):
        # Not a full upscaler layout, but the shape/short-circuit paths still
        # read the state before failing, which is what we are pinning.
        build_model_for_checkpoint(state)

    assert set(state) == set(snapshot)
    for key, value in snapshot.items():
        assert torch.equal(state[key], value)
