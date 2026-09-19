"""Workflow-metadata policy for exported videos: precedence, guards, real strip."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from mmx_pkg.director import video_metadata as vm


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


def test_unknown_policies_fall_back_to_auto():
    for value in (None, "", "yes", "TRUE ", 42, ["auto"]):
        assert vm.normalize_embed_policy(value) == "auto"
    for value in ("auto", "ALWAYS", " never "):
        assert vm.normalize_embed_policy(value) in vm.EMBED_CHOICES


def test_auto_follows_comfyuis_own_flag(monkeypatch):
    monkeypatch.setattr(vm, "comfyui_disabled", lambda: False)
    decision = vm.resolve("auto", app_policy="auto")
    assert decision["embed"] is True
    assert decision["comfyui_disabled"] is False
    assert decision["effective"] == "embed"

    monkeypatch.setattr(vm, "comfyui_disabled", lambda: True)
    decision = vm.resolve("auto", app_policy="auto")
    assert decision["embed"] is False
    assert decision["effective"] == "strip"


def test_explicit_choices_override_the_flag(monkeypatch):
    monkeypatch.setattr(vm, "comfyui_disabled", lambda: True)
    assert vm.resolve("always", app_policy="never")["embed"] is True
    monkeypatch.setattr(vm, "comfyui_disabled", lambda: False)
    assert vm.resolve("never", app_policy="always")["embed"] is False


def test_per_save_value_wins_over_the_app_setting(monkeypatch):
    monkeypatch.setattr(vm, "comfyui_disabled", lambda: False)
    decision = vm.resolve("never", app_policy="always")
    assert decision["embed"] is False
    assert decision["policy"] == "never"
    assert decision["source"] == "save-config"


def test_missing_or_junk_save_value_uses_the_app_setting(monkeypatch):
    monkeypatch.setattr(vm, "comfyui_disabled", lambda: False)
    for requested in (None, "", "sometimes"):
        decision = vm.resolve(requested, app_policy="never")
        assert decision["embed"] is False, requested
        assert decision["policy"] == "never"
        assert decision["source"] == "settings"

    # ... and an app setting that is itself the default is reported as "default".
    assert vm.resolve(None, app_policy="auto")["source"] == "default"


def test_metadata_payload_contents(monkeypatch):
    monkeypatch.setattr(vm, "comfyui_disabled", lambda: False)
    extra = {"workflow": {"nodes": []}, "some": 1}
    prompt = {"3": {"class_type": "KSampler"}}
    payload = vm.metadata_for(extra, prompt, "auto")
    assert payload == {"workflow": {"nodes": []}, "some": 1, "prompt": prompt}
    # Nothing to write is None, not an empty dict.
    assert vm.metadata_for(None, None, "auto") is None
    assert vm.metadata_for(extra, prompt, "never") is None


# ---------------------------------------------------------------------------
# Output-folder guard
# ---------------------------------------------------------------------------


@pytest.fixture()
def output_root(tmp_path, monkeypatch):
    root = tmp_path / "output"
    (root / "mm-director" / "2026-09-19").mkdir(parents=True)
    (root / "mm-director" / "2026-09-19" / "clip_00001_.mp4").write_bytes(b"not really a video")
    monkeypatch.setattr(
        vm,
        "resolve_output_file",
        vm.resolve_output_file,
    )
    import folder_paths

    monkeypatch.setattr(folder_paths, "get_directory_by_type", lambda kind: str(root), raising=False)
    monkeypatch.setattr(folder_paths, "get_output_directory", lambda: str(root), raising=False)
    return root


def test_resolve_output_file_accepts_names_and_subfolders(output_root):
    direct = vm.resolve_output_file("mm-director/2026-09-19/clip_00001_.mp4")
    assert direct.is_file()
    split = vm.resolve_output_file("clip_00001_.mp4", subfolder="mm-director/2026-09-19")
    assert split == direct


def test_resolve_output_file_refuses_escapes(output_root):
    for name in ("../secrets.mp4", "/etc/passwd", "mm-director/../../escape.mp4", ""):
        with pytest.raises(ValueError):
            vm.resolve_output_file(name)
    with pytest.raises(FileNotFoundError):
        vm.resolve_output_file("mm-director/missing.mp4")


# ---------------------------------------------------------------------------
# Strip (real ffmpeg)
# ---------------------------------------------------------------------------


def _ffmpeg() -> str | None:
    return vm._ffmpeg_path()


def _write_video_with_metadata(path: Path, frames: int = 6) -> None:
    """Tiny mp4 carrying workflow/prompt tags, written the way ComfyUI writes them.

    ``movflags=use_metadata_tags`` is what makes isobmff keep keys ffmpeg does not
    know (``workflow``, ``prompt``); ComfyUI sets it for every mp4/mov it writes,
    which is exactly why an exported Director video can restore the project.
    """
    import av
    import numpy as np

    with av.open(str(path), mode="w", options={"movflags": "use_metadata_tags"}) as container:
        container.metadata["workflow"] = json.dumps({"nodes": [], "extra": {"timeline": "x"}})
        container.metadata["prompt"] = json.dumps({"3": {"class_type": "KSampler"}})
        stream = container.add_stream("libx264", rate=12)
        stream.width = 64
        stream.height = 64
        stream.pix_fmt = "yuv420p"
        for _ in range(frames):
            array = np.zeros((64, 64, 3), dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(array, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)


needs_ffmpeg = pytest.mark.skipif(_ffmpeg() is None, reason="ffmpeg is not installed")


@needs_ffmpeg
def test_strip_removes_the_workflow_tags_and_keeps_the_stream(tmp_path):
    # Written through PyAV, exactly like ComfyUI's own Save Video: ffmpeg's CLI would
    # drop unknown keys unless it is told -movflags use_metadata_tags, which is why
    # the fixture must not be an ffmpeg one-liner.
    source = tmp_path / "with_meta.mp4"
    _write_video_with_metadata(source)
    before = vm._ffprobe_tags(source)
    assert "workflow" in before and "prompt" in before, "the fixture must embed metadata"

    result = vm.strip_file(source)
    target = Path(result["path"])
    assert result["ok"] is True
    assert target.is_file() and target.name == "with_meta_clean.mp4"
    assert result["embedded_before"] is True
    assert result["embedded_after"] is False
    assert {"workflow", "prompt"} <= set(result["removed_tags"])
    assert result["after_bytes"] > 0

    # Streams survive the remux (no re-encode).
    probe = subprocess.run(
        [shutil.which("ffprobe"), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(target)],
        capture_output=True,
        timeout=120,
        check=True,
    )
    assert probe.stdout.decode().strip() == "video"


@needs_ffmpeg
def test_strip_refuses_double_stripping_and_missing_files(tmp_path):
    already = tmp_path / "clip_clean.mp4"
    _write_video_with_metadata(already)
    with pytest.raises(ValueError) as excinfo:
        vm.strip_file(already)
    assert "already" in str(excinfo.value)
    with pytest.raises(FileNotFoundError):
        vm.strip_file(tmp_path / "missing.mp4")


def test_strip_reports_a_missing_ffmpeg(tmp_path, monkeypatch):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"x")
    monkeypatch.setattr(vm, "_ffmpeg_path", lambda: None)
    with pytest.raises(ValueError) as excinfo:
        vm.strip_file(source)
    assert "ffmpeg" in str(excinfo.value)


def test_strip_never_reads_the_terminal(tmp_path, monkeypatch):
    """ffmpeg must not inherit a TTY stdin.

    A background process that reads the terminal is stopped by SIGTTIN, and a stopped
    process ignores the timeout's SIGTERM - so an unattended strip would hang forever
    instead of failing. Both the command (``-nostdin``) and the Popen (DEVNULL) have to
    say so.
    """
    source = tmp_path / "clip.mp4"
    _write_video_with_metadata(source)
    calls: list[tuple] = []

    real_run = subprocess.run

    def spy(command, **kwargs):
        calls.append((list(command), kwargs))
        return real_run(command, **{**kwargs, "capture_output": True})

    monkeypatch.setattr(vm.subprocess, "run", spy)
    vm.strip_file(source)
    assert calls, "the strip must run a subprocess"
    for command, kwargs in calls:
        assert kwargs.get("stdin") is subprocess.DEVNULL, f"terminal stdin leaked to {command[0]}"
        assert kwargs.get("capture_output") is True
    ffmpeg_calls = [command for command, _ in calls if "-map_metadata" in command]
    assert len(ffmpeg_calls) == 1, "the remux must run exactly once"
    assert "-nostdin" in ffmpeg_calls[0], "ffmpeg itself must be told not to read stdin"



# ---------------------------------------------------------------------------
# Save-config plumbing
# ---------------------------------------------------------------------------


def test_save_config_carries_and_validates_the_choice():
    from mmx_pkg.director.video_export import normalize_save_config

    assert normalize_save_config({})["embed_metadata"] == "auto"
    assert normalize_save_config({"embed_metadata": "never"})["embed_metadata"] == "never"
    assert normalize_save_config({"embed_metadata": "ALWAYS"})["embed_metadata"] == "always"
    assert normalize_save_config({"embed_metadata": "sometimes"})["embed_metadata"] == "auto"


def test_default_postprocess_config_documents_the_key():
    from mmx_pkg.director.postprocess_config import (
        DEFAULT_POSTPROCESS_CONFIG,
        POSTPROCESS_CONFIG_VERSION,
        normalize_postprocess_config,
    )

    assert DEFAULT_POSTPROCESS_CONFIG["save"]["embed_metadata"] == "auto"
    config = normalize_postprocess_config(json.dumps({"save": {"embed_metadata": "never"}}))
    assert config["save"]["embed_metadata"] == "never"
    assert config["version"] == POSTPROCESS_CONFIG_VERSION
    # A v9/v10 document (no such key) still normalizes.
    legacy = normalize_postprocess_config(json.dumps({"version": 9, "save": {"crf": 20}}))
    assert legacy["save"]["embed_metadata"] == "auto"
    assert legacy["save"]["crf"] == 20
