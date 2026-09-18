"""Frames for the caption come from the segment's own slice, not the whole file.

``extract_input_video_frames_b64`` sampled the source video uniformly across the
file, so in a Character Replace project every window's action caption saw the same
three moments of the footage - none of them the window being replaced. The window is
now passed through as seconds and the samples stay inside it (first and last frame
belong to the neighbouring windows, so they are skipped as before).

The window arithmetic is a pure helper; the ffmpeg side is exercised too, but only
when ffmpeg is on the box, and always against a temp directory rather than the
install's own input folder.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest
from PIL import Image

try:
    from mmx_pkg.director import prompt_enhance_media as media
except ImportError as exc:  # pragma: no cover - environment guard
    pytest.skip(f"Director package unavailable: {exc}", allow_module_level=True)


# --- the stamp arithmetic ---------------------------------------------------


def test_no_window_keeps_the_whole_file_behaviour():
    stamps, in_window = media.window_sample_stamps(
        num_frames=3, fps=24.0, duration=100.0, total_frames=2400
    )
    assert in_window is False
    assert stamps == pytest.approx([25.0, 50.0, 75.0]), "same interior spread as before"


def test_a_window_is_sampled_inside_itself():
    stamps, in_window = media.window_sample_stamps(
        num_frames=3,
        fps=24.0,
        duration=100.0,
        total_frames=2400,
        start_sec=10.0,
        end_sec=20.0,
    )
    assert in_window is True
    assert len(stamps) == 3
    assert all(10.0 < stamp < 20.0 for stamp in stamps), stamps
    assert stamps == pytest.approx([12.5, 15.0, 17.5]), "interior, evenly spaced"


def test_a_window_at_the_end_of_the_video_is_not_pushed_past_the_duration():
    stamps, in_window = media.window_sample_stamps(
        num_frames=2, fps=24.0, duration=20.0, total_frames=480, start_sec=19.0, end_sec=20.0
    )
    assert in_window is True
    assert all(stamp <= 20.0 for stamp in stamps)
    assert stamps == pytest.approx([19.333333, 19.666667], abs=1e-4)


def test_a_degenerate_window_falls_back_to_the_file():
    for start, end in ((10.0, 10.0), (20.0, 10.0), (5.0, 0.0)):
        stamps, in_window = media.window_sample_stamps(
            num_frames=2, fps=24.0, duration=100.0, total_frames=2400,
            start_sec=start, end_sec=end,
        )
        assert in_window is False, (start, end)
        assert len(stamps) == 2


def test_a_window_past_the_end_of_the_file_falls_back_to_the_file():
    stamps, in_window = media.window_sample_stamps(
        num_frames=2, fps=24.0, duration=30.0, total_frames=720, start_sec=40.0, end_sec=50.0
    )
    assert in_window is False
    assert len(stamps) == 2


def test_one_frame_is_still_the_middle_of_the_window():
    stamps, in_window = media.window_sample_stamps(
        num_frames=1, fps=24.0, duration=100.0, total_frames=2400, start_sec=0.0, end_sec=10.0
    )
    assert in_window is True
    assert stamps == pytest.approx([5.0])


# --- the ffmpeg path --------------------------------------------------------


def _ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg"))


@pytest.fixture()
def tiny_video(tmp_path, monkeypatch):
    """A two-second test clip inside a temp 'input' directory."""
    if not _ffmpeg_available():
        pytest.skip("ffmpeg not installed")
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    clip = input_dir / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "testsrc=duration=2:size=64x64:rate=24",
            "-pix_fmt", "yuv420p", str(clip),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    monkeypatch.setattr(media.folder_paths, "get_input_directory", lambda: str(input_dir))
    return clip


def test_frames_are_extracted_and_a_window_changes_them(tiny_video):
    whole, err = media.extract_input_video_frames_b64("clip.mp4", num_frames=3)
    assert err is None and len(whole) == 3

    windowed, err = media.extract_input_video_frames_b64(
        "clip.mp4", num_frames=3, start_sec=1.0, end_sec=2.0
    )
    assert err is None and len(windowed) == 3
    # A testsrc clip changes every second, so a window in the second half cannot
    # return the same first frame as the whole-file spread.
    assert windowed[0] != whole[0]


def test_a_missing_file_is_reported(tiny_video):
    frames, err = media.extract_input_video_frames_b64("nope.mp4", num_frames=2)
    assert frames == []
    assert err and "not found" in err.lower()


def test_escaping_the_input_directory_is_refused(tiny_video):
    frames, err = media.extract_input_video_frames_b64("../clip.mp4", num_frames=2)
    assert frames == []
    assert err == "Invalid filename"


# --- reading a reference picture -------------------------------------------


def test_a_reference_in_a_subfolder_and_in_outputs(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    (input_dir / "refs").mkdir(parents=True)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    image = Image.new("RGB", (8, 8), (200, 30, 30))
    image.save(input_dir / "refs" / "face.png")
    image.save(output_dir / "render.png")
    monkeypatch.setattr(media.folder_paths, "get_input_directory", lambda: str(input_dir))
    monkeypatch.setattr(media.folder_paths, "get_output_directory", lambda: str(output_dir))

    # Name only: the slot's own subfolder is what makes it readable.
    b64, err = media.load_input_image_b64("face.png")
    assert b64 is None and err and "not found" in err.lower()

    b64, err = media.load_input_image_b64("face.png", subfolder="refs")
    assert err is None and b64

    b64, err = media.load_input_image_b64("render.png", kind="output")
    assert err is None and b64


def test_escaping_is_refused_for_both_parts(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    monkeypatch.setattr(media.folder_paths, "get_input_directory", lambda: str(input_dir))

    assert media.load_input_image_b64("../secret.png", subfolder="refs")[1] == "Invalid filename"
    assert media.load_input_image_b64("face.png", subfolder="../../etc")[1] == "Invalid subfolder"
    assert media.load_input_image_b64("")[1] == "No filename"


# --- the route hands both through -------------------------------------------


def test_the_route_accepts_a_window_and_an_image_location():
    import pathlib

    import mmx_pkg.director.prompt_enhance_routes as routes

    text = pathlib.Path(routes.__file__).read_text(encoding="utf-8")
    assert "start_sec = _as_seconds(data.get(\"start_sec\", data.get(\"startSec\")))" in text
    assert "end_sec = _as_seconds(data.get(\"end_sec\", data.get(\"endSec\")))" in text
    assert "start_sec=start_sec," in text and "end_sec=end_sec," in text
    assert 'kind=data.get("type") or data.get("kind") or "input",' in text
    assert "num_frames = min(max(int(data.get(\"num_frames\") or 3), 1), MAX_VISION_FRAMES)" in text


def test_a_junk_timestamp_is_treated_as_no_window():
    import mmx_pkg.director.prompt_enhance_routes as routes

    assert routes._as_seconds(None) is None
    assert routes._as_seconds("") is None
    assert routes._as_seconds("later") is None
    assert routes._as_seconds(float("nan")) is None
    assert routes._as_seconds(float("inf")) is None
    assert routes._as_seconds(-4) == 0.0, "clamped, not rejected"
    assert routes._as_seconds("12.5") == 12.5
