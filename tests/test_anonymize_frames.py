# MiniMax H3 Motion Director - hiding the source performer from the action caption.
# Copyright (C) 2026 WakaSoft. GPL-3.0. See LICENSE.

"""The identity-inverting composite, ported from the Character Remake workflow.

The action caption reads the source window, which contains the performer being
replaced. The instruction asks the caption model not to describe her, and usually
that holds - but a specific woman in front of a vision model sometimes gets
described anyway, and that text then fights the replacement reference. Inverting the
subject region removes the identity from the pixels instead; pose, silhouette and
background survive, which is everything the action caption needs.

These tests use a stub segmenter: no model download, no inference, just the geometry
(the subject region gets inverted, the rest does not) and the fallback paths, which
are the part that must never break a caption.
"""

from __future__ import annotations

import base64
import io
import sys
import types

import numpy as np
from PIL import Image

# Prefer ComfyUI's real module: this suite imports it through PYTHONPATH, and
# installing a stub here would hand a fake to every test collected afterwards.
try:
    import folder_paths  # noqa: F401
except ImportError:  # pragma: no cover - only on a box without ComfyUI
    _stub = types.ModuleType("folder_paths")
    _stub.get_input_directory = lambda: "/tmp"
    _stub.get_output_directory = lambda: "/tmp"
    _stub.get_temp_directory = lambda: "/tmp"
    _stub.models_dir = "/tmp/models"
    _stub.base_path = "/tmp"
    _stub.folder_names_and_paths = {}
    _stub.get_folder_paths = lambda kind: []
    _stub.get_filename_list = lambda kind: []
    _stub.get_full_path = lambda kind, name: None
    sys.modules["folder_paths"] = _stub

import pytest  # noqa: E402

from mmx_pkg.lib import anonymize_frames  # noqa: E402 - after the stub
from mmx_pkg.lib.h3_prompt_caption import build_from_images  # noqa: E402


def _frame(background: int = 30, subject: int = 200) -> str:
    """A frame with a bright square subject on a dark background, as JPEG b64."""
    arr = np.full((64, 64, 3), background, dtype="uint8")
    arr[16:48, 16:48] = subject
    buffer = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buffer, format="JPEG", quality=95)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _decode(b64: str) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")).astype("float32")


@pytest.fixture()
def stub_rembg(monkeypatch):
    """A rembg stand-in whose mask is the bright square in `_frame`."""
    module = types.ModuleType("rembg")

    def new_session(name):  # noqa: ARG001 - the real API takes a model name
        return object()

    def remove(image, session=None, only_mask=False):  # noqa: ARG001
        arr = np.asarray(image.convert("L"))
        mask = np.where(arr > 110, 255, 0).astype("uint8")
        return Image.fromarray(mask, mode="L") if only_mask else image

    module.new_session = new_session
    module.remove = remove
    monkeypatch.setitem(sys.modules, "rembg", module)
    anonymize_frames.reset_session()
    yield module
    anonymize_frames.reset_session()


def test_subject_region_is_inverted_and_background_is_not(stub_rembg):
    images, info, error = anonymize_frames.invert_subject_regions([_frame()])
    assert error == "" and info["method"] == "subject inverted"
    arr = _decode(images[0])
    # Interior of the subject: inverted (200 -> ~55). Corners: untouched (30).
    assert arr[32, 32].mean() == pytest.approx(255 - 200, abs=6)
    assert arr[2, 2].mean() == pytest.approx(30, abs=4)
    assert arr[-3, -3].mean() == pytest.approx(30, abs=4)


def test_only_the_requested_number_of_frames_is_touched(stub_rembg):
    first, second = _frame(), _frame(subject=180)
    images, info, error = anonymize_frames.invert_subject_regions([first, second], frames=1)
    assert error == "" and info["frames"] == 1
    assert images[1] == second, "frames past the cap pass through untouched"
    assert images[0] != first


def test_missing_rembg_returns_the_original_frames_with_a_reason(monkeypatch):
    monkeypatch.setitem(sys.modules, "rembg", None)
    anonymize_frames.reset_session()
    frame = _frame()
    images, info, error = anonymize_frames.invert_subject_regions([frame])
    assert images == [frame], "the caption must still be possible"
    assert info["method"] == "none"
    assert "rembg is not installed" in error
    anonymize_frames.reset_session()


def test_a_mask_that_covers_everything_is_refused(stub_rembg):
    """Inverting a whole frame hides the action too, so it is not a subject mask."""
    arr = np.full((32, 32, 3), 240, dtype="uint8")
    buffer = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buffer, format="JPEG", quality=95)
    frame = base64.b64encode(buffer.getvalue()).decode("ascii")
    images, info, error = anonymize_frames.invert_subject_regions([frame])
    assert images == [frame]
    assert info["method"] == "none"
    assert "whole frame" in error


def test_an_empty_frame_list_is_not_an_error_path():
    images, info, error = anonymize_frames.invert_subject_regions([])
    assert images == [] and info == {}
    assert "No frames" in error


def test_build_from_images_can_hide_the_performer_before_the_action_caption(
    stub_rembg, monkeypatch,
):
    """The action caption must receive inverted frames, not the originals."""
    seen: dict = {}

    def fake_enhance(**kwargs):
        seen["images"] = list(kwargs.get("images_b64") or [])
        return "She crosses the room.", None

    import mmx_pkg.lib.prompt_enhancer as prompt_enhancer

    monkeypatch.setattr(prompt_enhancer, "enhance_prompt_sync", fake_enhance)
    original = _frame()
    result, error = build_from_images(
        recipe="source_edit",
        url="", model="m", api_format="local",
        user_prompt="The lamp turns on.",
        source_images=[original],
        hide_performer=True,
    )
    assert error is None
    assert seen["images"] and seen["images"][0] != original
    assert _decode(seen["images"][0])[32, 32].mean() == pytest.approx(55, abs=8)
    assert "performer-hidden" in result.skipped


def test_a_failed_mask_is_reported_and_the_caption_still_runs(monkeypatch):
    monkeypatch.setitem(sys.modules, "rembg", None)
    anonymize_frames.reset_session()
    seen: dict = {}

    def fake_enhance(**kwargs):
        seen["images"] = list(kwargs.get("images_b64") or [])
        return "She crosses the room.", None

    import mmx_pkg.lib.prompt_enhancer as prompt_enhancer

    monkeypatch.setattr(prompt_enhancer, "enhance_prompt_sync", fake_enhance)
    original = _frame()
    result, error = build_from_images(
        recipe="source_edit",
        url="", model="m", api_format="local",
        user_prompt="The lamp turns on.",
        source_images=[original],
        hide_performer=True,
    )
    anonymize_frames.reset_session()
    assert error is None, "a mask failure must not lose the caption"
    assert seen["images"] == [original], "the original frames are sent instead"
    assert "performer-visible" in result.skipped, "and the caller is told"


def test_hiding_is_off_by_default(monkeypatch):
    seen: dict = {}

    def fake_enhance(**kwargs):
        seen["images"] = list(kwargs.get("images_b64") or [])
        return "She crosses the room.", None

    import mmx_pkg.lib.prompt_enhancer as prompt_enhancer

    monkeypatch.setattr(prompt_enhancer, "enhance_prompt_sync", fake_enhance)
    original = _frame()
    result, error = build_from_images(
        recipe="source_edit",
        url="", model="m", api_format="local",
        user_prompt="The lamp turns on.",
        source_images=[original],
    )
    assert error is None
    assert seen["images"] == [original]
    assert "performer-hidden" not in result.skipped
    assert "performer-visible" not in result.skipped
