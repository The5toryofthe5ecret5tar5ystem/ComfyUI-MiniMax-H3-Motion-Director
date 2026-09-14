"""Preview clip transport tests.

Results used to be delivered as every frame base64-encoded as JPEG over the
ComfyUI websocket - measured at ~11.9 MB for a 243-frame segment, parsed
synchronously on the browser main thread, which is what stalled the Results page.
These tests pin the replacement contract: one small all-intra H.264 clip in the
temp directory plus a /view URL, with the legacy frame array kept as a fallback
so a broken encoder can never lose a result.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import types

import numpy as np
import pytest
import torch

from director import preview_clip

av = pytest.importorskip("av", reason="PyAV is required to encode preview clips")


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    preview_clip.cleanup_previews("pytest_node")


def _frames(count: int = 8, height: int = 48, width: int = 64) -> torch.Tensor:
    """A deterministic clip that changes every frame, in the executor's layout."""
    base = torch.zeros(count, height, width, 3)
    for index in range(count):
        base[index, :, :, 0] = index / max(1, count - 1)
        base[index, :, :, 1] = torch.linspace(0, 1, width)
    return base


def test_writes_playable_all_intra_clip():
    frames = _frames()

    info = preview_clip.write_preview_clip(
        frames, 24.0, node_id="pytest_node", key="seg0"
    )

    assert info is not None, "encoder should produce a clip for a normal tensor"
    assert info["preview_type"] == "temp"
    assert info["preview_frame_count"] == frames.shape[0]
    assert info["preview_bytes"] > 0
    assert info["preview_url"].startswith("/view?filename=seg0.mp4")
    assert "type=temp" in info["preview_url"]

    path = preview_clip.preview_root() / "pytest_node" / info["preview_filename"]
    assert path.is_file()

    if shutil.which("ffprobe") is None:
        pytest.skip("ffprobe unavailable; cannot verify keyframe density")

    # Frame-accurate scrubbing depends on every frame being a keyframe.
    keyframes = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "frame=key_frame", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    ).stdout.split()

    assert len(keyframes) == frames.shape[0]
    assert all(value.startswith("1") for value in keyframes), "clip must be all-intra"


def test_url_is_unique_per_call():
    """ComfyUI's /view sets no Cache-Control, so a re-render must not be cacheable."""
    first = preview_clip.write_preview_clip(
        _frames(4), 24.0, node_id="pytest_node", key="seg0"
    )
    second = preview_clip.write_preview_clip(
        _frames(4), 24.0, node_id="pytest_node", key="seg0"
    )

    assert first and second
    assert first["preview_url"] != second["preview_url"]


def test_degenerate_inputs_return_none():
    """A failure must be signalled, never raised into the executor."""
    assert preview_clip.write_preview_clip(
        None, 24.0, node_id="pytest_node", key="a"
    ) is None
    assert preview_clip.write_preview_clip(
        torch.zeros(0, 48, 64, 3), 24.0, node_id="pytest_node", key="b"
    ) is None


def test_odd_dimensions_are_cropped_for_yuv420p():
    frames = _frames(4, height=31, width=45)

    info = preview_clip.write_preview_clip(
        frames, 24.0, node_id="pytest_node", key="odd"
    )

    assert info is not None
    assert info["preview_width"] % 2 == 0
    assert info["preview_height"] % 2 == 0


def test_cleanup_removes_only_that_node():
    preview_clip.write_preview_clip(_frames(4), 24.0, node_id="pytest_node", key="x")
    kept = preview_clip.write_preview_clip(_frames(4), 24.0, node_id="other_node", key="y")

    assert kept is not None
    removed = preview_clip.cleanup_previews("pytest_node")

    assert removed == 1
    assert (preview_clip.preview_root() / "other_node" / kept["preview_filename"]).is_file()

    preview_clip.cleanup_previews("other_node")


def test_build_result_preview_prefers_clip(monkeypatch):
    calls: list[object] = []

    def fake_encode(frame):
        calls.append(frame)
        return "b64"

    kwargs = preview_clip.build_result_preview(
        _frames(6), 24.0, node_id="pytest_node", key="seg0", frame_to_b64=fake_encode
    )

    assert "preview" in kwargs
    assert "frames" not in kwargs, "the base64 frame array must not be sent alongside a clip"
    assert kwargs["width"] == 64
    assert kwargs["height"] == 48
    assert len(calls) == 1, "only the poster frame should be JPEG encoded"


def test_build_result_preview_falls_back_to_frames(monkeypatch):
    """If encoding is unavailable the result must still reach the UI."""
    monkeypatch.setattr(preview_clip, "write_preview_clip", lambda *a, **k: None)

    kwargs = preview_clip.build_result_preview(
        _frames(6), 24.0, node_id="pytest_node", key="seg0",
        frame_to_b64=lambda frame: "b64",
    )

    assert "preview" not in kwargs
    assert len(kwargs["frames"]) == 6
    assert kwargs["image_b64"] == "b64"


def test_build_result_preview_handles_empty():
    kwargs = preview_clip.build_result_preview(
        torch.zeros(0, 48, 64, 3), 24.0, node_id="pytest_node", key="e",
        frame_to_b64=lambda frame: "b64",
    )

    assert kwargs["image_b64"] == ""
    assert "preview" not in kwargs


def test_progress_payload_carries_clip_and_omits_frames(monkeypatch):
    """End-to-end: the websocket payload the UI receives must be clip-shaped."""
    sent: dict = {}

    class FakePromptServer:
        def __init__(self):
            self.client_id = "client"

        def send_sync(self, event, payload, sid=None):
            sent["event"] = event
            sent["payload"] = payload

    # progress.py resolves PromptServer lazily via ``from server import
    # PromptServer``. Injecting a stub module keeps this test independent of
    # importing ComfyUI's real server (which pulls in latent_preview and other
    # heavy, order-sensitive imports).
    fake_server = types.ModuleType("server")
    fake_server.PromptServer = FakePromptServer
    FakePromptServer.instance = FakePromptServer()
    monkeypatch.setitem(sys.modules, "server", fake_server)

    from director.progress import report_director_segment_preview

    kwargs = preview_clip.build_result_preview(
        _frames(5), 24.0, node_id="pytest_node", key="seg0",
        frame_to_b64=lambda frame: "poster",
    )

    report_director_segment_preview(
        "pytest_node", segment_index=0, fps=24.0, **kwargs
    )

    payload = sent["payload"]
    assert sent["event"] == "minimax_motion_director_preview"
    assert payload["preview_url"]
    assert payload["preview_frame_count"] == 5
    assert payload["image_b64"] == "poster"
    assert "frames" not in payload, "the multi-megabyte frame array must be gone"
    assert payload["fps"] == 24.0
