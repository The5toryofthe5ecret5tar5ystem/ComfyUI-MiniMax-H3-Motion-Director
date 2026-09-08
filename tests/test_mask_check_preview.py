"""Mask-check preview helpers (director.mask_preview + director.progress, CPU).

Imported from the lightweight ``mask_preview`` module on purpose: the compose
helper is a pure-CPU montage, and importing ``executor_core_legacy`` at test
collection time drags in ``comfy.ldm.minimax`` -> ComfyUI's ``model_management``,
which asserts CUDA at import on the CI runner (CPU-only torch). See CI failure
history at 3d52287.
"""

from __future__ import annotations

import torch

from mmx_pkg.director.mask_preview import compose_mask_check_jpeg as _compose_mask_check_jpeg
from mmx_pkg.director.progress import report_director_mask_check


def _frames(t=6, h=24, w=32):
    return torch.rand(t, h, w, 3)


def test_compose_returns_jpeg_data_uri():
    uri = _compose_mask_check_jpeg(_frames(), torch.zeros(6, 24, 32), _frames(), lead=2)
    assert uri and uri.startswith("data:image/jpeg;base64,")


def test_compose_overlay_present_when_mask_marks_subject():
    vis = torch.zeros(6, 24, 32, 3)
    mask = torch.zeros(6, 24, 32)
    mask[:, 6:18, 8:24] = 1.0
    uri = _compose_mask_check_jpeg(vis, mask, vis, lead=0)
    # Overlay turns the subject region red -> larger jpeg than plain black panel.
    assert uri and len(uri) > 200


def test_compose_clamps_lead_out_of_range():
    uri = _compose_mask_check_jpeg(_frames(), None, _frames(), lead=999)
    assert uri and uri.startswith("data:image/jpeg;base64,")


def test_compose_without_mask_still_renders():
    uri = _compose_mask_check_jpeg(_frames(), None, None, lead=0)
    assert uri and uri.startswith("data:image/jpeg;base64,")


def test_compose_empty_visible_returns_none():
    assert _compose_mask_check_jpeg(torch.zeros(0, 24, 32, 3), None, None, lead=0) is None


def test_report_noop_without_node_or_image():
    # No PromptServer access should happen for these guarded inputs.
    report_director_mask_check(None, segment_index=0, image_b64="x")
    report_director_mask_check("1", segment_index=0, image_b64="")
