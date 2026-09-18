"""Pre-flight validation of the Character Replace mask source (director.preflight).

A `frames` mask that cannot be loaded is not a preference, it is a guaranteed
fallback: ``prepare_replace_window`` returns None, the window renders as plain
rv2v, and the run only says so after every segment has been paid for. The
validator is the only place that can catch it before the GPU bill, so these
tests pin both the fatal cases and the coverage warning.
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from mmx_pkg.director.preflight import (
    _mask_frame_indices,
    _resolve_mask_dir,
    _static_checks,
)


def _write_mask_frames(root, indices) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for frame_index in indices:
        img = np.full((8, 8), 255, dtype=np.uint8)
        Image.fromarray(img, mode="L").save(root / f"frame_{frame_index:08d}.png")


def _segment(replace: dict, *, start: int = 0, length: int = 4) -> dict:
    return {
        "id": "s1",
        "start": start,
        "length": length,
        "frameCount": length,
        "prompt": "a prompt",
        "refs": [],
        "refAudios": [],
        "refVideos": [],
        "replace": replace,
    }


def _timeline(segments: list[dict]) -> dict:
    # replaceMode skips the H3 grid warning, keeping the codes under test clean.
    return {"replaceMode": True, "segments": segments}


def _codes(segments: list[dict]) -> list[str]:
    issues: list = []
    _static_checks(_timeline(segments), "rv2v", issues)
    return [i["code"] for i in issues]


def _mask_issues(segments: list[dict]) -> list[dict]:
    issues: list = []
    _static_checks(_timeline(segments), "rv2v", issues)
    return [i for i in issues if i["code"].startswith("replace_")]


# --- the fatal cases: a frames mask that can never load -------------------


def test_frames_mask_without_folder_is_an_error():
    issues = _mask_issues([_segment({"enabled": True, "mask": {"kind": "frames", "dir": ""}})])
    assert [i["code"] for i in issues] == ["replace_mask_dir_missing"]
    assert issues[0]["severity"] == "error"
    # The message has to name the way out, not just the problem.
    assert "sam3" in issues[0]["message"]


def test_frames_mask_with_missing_folder_is_an_error():
    issues = _mask_issues(
        [_segment({"enabled": True, "mask": {"kind": "frames", "dir": "/nope/not/here"}})]
    )
    assert [i["code"] for i in issues] == ["replace_mask_dir_not_found"]


def test_frames_mask_with_no_frames_is_an_error(tmp_path):
    tmp_path.joinpath("empty").mkdir()
    issues = _mask_issues(
        [_segment({"enabled": True, "mask": {"kind": "frames", "dir": str(tmp_path / "empty")}})]
    )
    assert [i["code"] for i in issues] == ["replace_mask_dir_empty"]


def test_unknown_mask_kind_is_an_error():
    issues = _mask_issues([_segment({"enabled": True, "mask": {"kind": "none"}})])
    assert [i["code"] for i in issues] == ["replace_mask_unsupported"]
    assert issues[0]["severity"] == "error"


# --- the passing cases ----------------------------------------------------


def test_frames_mask_covering_the_window_is_clean(tmp_path):
    _write_mask_frames(tmp_path, range(4))
    issues = _mask_issues(
        [_segment({"enabled": True, "mask": {"kind": "frames", "dir": str(tmp_path)}})]
    )
    assert issues == []


def test_disabled_window_is_not_checked_at_all(tmp_path):
    # Nothing to validate: the engine never reads the mask for a disabled window.
    issues = _mask_issues(
        [_segment({"enabled": False, "mask": {"kind": "frames", "dir": ""}})]
    )
    assert issues == []


def test_sam3_without_prompt_is_still_an_error():
    issues = _mask_issues([_segment({"enabled": True, "mask": {"kind": "sam3"}, "sam_prompts": []})])
    assert [i["code"] for i in issues] == ["replace_sam3_prompt"]


def test_sam3_with_prompt_is_clean():
    issues = _mask_issues(
        [_segment({"enabled": True, "mask": {"kind": "sam3"}, "sam_prompts": ["the woman"]})]
    )
    assert issues == []


# --- the quiet one: a window that is only partly covered ------------------


def test_partially_covered_window_warns_but_does_not_block(tmp_path):
    # Runtime drops the WHOLE window to rv2v when any frame is absent, so a
    # partial set is worth saying out loud - but it is not a hard error, because
    # the window still renders (just without Character Replace).
    _write_mask_frames(tmp_path, range(2))
    issues = _mask_issues(
        [
            _segment(
                {"enabled": True, "mask": {"kind": "frames", "dir": str(tmp_path)}},
                start=0,
                length=4,
            )
        ]
    )
    assert [i["code"] for i in issues] == ["replace_mask_gap"]
    assert issues[0]["severity"] == "warning"
    assert "2 of 4" in issues[0]["message"]


def test_mask_offset_rebases_the_window(tmp_path):
    # A rebased mask set writes file frame_i for source frame `offset + i`, so a
    # window starting at source frame 100 with offset 100 is held in files 0..3.
    # The lookup has to match load_mask_window or this reports a phantom gap.
    _write_mask_frames(tmp_path, range(4))
    mask = {"kind": "frames", "dir": str(tmp_path), "offset": 100}
    issues = _mask_issues([_segment({"enabled": True, "mask": mask}, start=100, length=4)])
    assert issues == []


def test_mask_offset_is_actually_applied(tmp_path):
    # Same rebased folder, but the windows thinks it is un-rebased: the lookup
    # must land on 100..103 and find nothing, proving the offset is honoured
    # rather than ignored.
    _write_mask_frames(tmp_path, range(4))
    mask = {"kind": "frames", "dir": str(tmp_path), "offset": 0}
    issues = _mask_issues([_segment({"enabled": True, "mask": mask}, start=100, length=4)])
    assert [i["code"] for i in issues] == ["replace_mask_gap"]


# --- directory resolution must agree with the runtime --------------------


def test_relative_mask_dir_resolves_against_the_input_directory(tmp_path, monkeypatch):
    _write_mask_frames(tmp_path / "scene-1", range(2))
    monkeypatch.setattr(
        "mmx_pkg.director.preflight.folder_paths.get_input_directory",
        lambda: str(tmp_path),
    )
    assert _resolve_mask_dir("scene-1") == str(tmp_path / "scene-1")
    # A relative path that does not exist must not be reported as resolvable.
    assert _resolve_mask_dir("scene-missing") is None


def test_blank_and_missing_dirs_do_not_resolve():
    assert _resolve_mask_dir("") is None
    assert _resolve_mask_dir("   ") is None
    assert _resolve_mask_dir(None) is None


def test_frame_indices_ignores_non_mask_files(tmp_path):
    _write_mask_frames(tmp_path, [0, 2])
    tmp_path.joinpath("sidecar.json").write_text("{}", encoding="utf-8")
    tmp_path.joinpath("notes.txt").write_text("hi", encoding="utf-8")
    assert _mask_frame_indices(str(tmp_path)) == {0, 2}
    # A missing directory must not raise; the caller reports it instead.
    assert _mask_frame_indices(str(tmp_path / "nope")) == set()
