"""Resume popup cache preview (director.resume_state.segment_cache_preview)."""

from __future__ import annotations

import json
import uuid

import pytest

import folder_paths
from mmx_pkg.director import resume_state


@pytest.fixture
def out_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(folder_paths, "get_output_directory", lambda: str(tmp_path))
    return tmp_path


def _node() -> str:
    return f"preview_{uuid.uuid4().hex[:10]}"


def _write_meta(node: str, index: int, *, width: int = 1152, height: int = 640,
                ref_max: int = 1152, output_mode: str = "fixed", complete: bool = True,
                prompt: str = "hello world", start: int = 0, end: int = 100) -> None:
    root = resume_state.segment_cache_dir(node)
    assert root is not None
    meta = {
        "index": index, "start": start, "end": end, "prompt": prompt,
        "task_key": "r2v", "width": width, "height": height,
        "ref_max": ref_max, "output_mode": output_mode,
        "refs": ["img0", "img1"], "ref_audios": ["aud0:voice.wav"], "ref_videos": [],
    }
    (root / f"seg_{index:04d}.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    if complete:
        (root / f"seg_{index:04d}.pt").write_bytes(b"\x00")


def test_preview_lists_cached_segments_with_settings(out_dir) -> None:
    node = _node()
    _write_meta(node, 0, width=1152, height=640, ref_max=1152)
    _write_meta(node, 1, width=1152, height=640, ref_max=1152)
    _write_meta(node, 2, width=1152, height=640, ref_max=1152, complete=False)

    preview = resume_state.segment_cache_preview(node)
    assert [item["index"] for item in preview] == [0, 1, 2]
    assert [item["complete"] for item in preview] == [True, True, False]
    assert preview[0]["width"] == 1152
    assert preview[0]["height"] == 640
    assert preview[0]["ref_max"] == 1152
    assert preview[0]["output_mode"] == "fixed"
    assert preview[0]["task_key"] == "r2v"
    assert preview[0]["prompt_chars"] == len("hello world")
    assert preview[0]["refs"] == ["img0", "img1"]
    assert preview[0]["ref_audios"] == ["aud0:voice.wav"]
    assert preview[2]["complete"] is False


def test_preview_empty_and_unknown_node(out_dir) -> None:
    node = _node()
    assert resume_state.segment_cache_preview(node) == []
    assert resume_state.segment_cache_preview(None) == []


def test_preview_sorted_by_index(out_dir) -> None:
    node = _node()
    _write_meta(node, 4)
    _write_meta(node, 0)
    _write_meta(node, 2)
    preview = resume_state.segment_cache_preview(node)
    assert [item["index"] for item in preview] == [0, 2, 4]
