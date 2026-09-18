# MiniMax H3 Motion Director - model download progress.
# Copyright (C) 2026 WakaSoft. GPL-3.0. See LICENSE.

"""Track an in-flight model download so the panel can show real progress.

`hf_hub_download` is a blocking call with no progress callback, and a catalog
quant is a 5-20 GB file, so the panel used to sit on "Downloading ..." for half an
hour with nothing moving. Progress is measured from the filesystem instead:
huggingface_hub stages bytes in `<target>/.cache/huggingface/download` and only
moves the finished file to `<target>/<filename>` at the end, so the staging size is
exactly what its own progress bar would show - without patching its internals.

State lives in this module, so it survives panel reloads (it dies with the ComfyUI
process, which also kills the download). One download at a time: `begin()` reports
the model already running so the route can refuse a second one rather than let two
transfers share the staging area and the numbers.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

# Bytes are sampled on every status poll; the rate uses this window so a stalled
# transfer reports a falling rate instead of the average since the start.
_RATE_WINDOW_SECONDS = 20.0

# A staging file nobody has written to for this long belongs to a download that
# died with the last ComfyUI process, not to one in flight.
_STALE_SECONDS = 60.0

_lock = threading.Lock()
_state: dict = {}
_samples: list[tuple[float, int]] = []


def _downloaded_bytes(target_dir: Path, filenames: list[str]) -> int:
    """Bytes on disk for this download: staged + finished files.

    A finished file is counted once: hf_hub_download moves it out of the staging
    area, so the two sets never overlap.
    """
    total = 0
    root = Path(target_dir)
    for name in filenames:
        if not name:
            continue
        try:
            candidate = root / name
            if candidate.is_file():
                total += candidate.stat().st_size
        except OSError:
            continue
    staging = root / ".cache" / "huggingface" / "download"
    try:
        for path in staging.rglob("*"):
            if not path.is_file() or path.suffix in (".lock", ".json"):
                continue
            try:
                total += path.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return total


def begin(
    *,
    model_id: str,
    label: str,
    target_dir: str | Path,
    expected_bytes: int,
    filenames: list[str],
) -> None:
    """Record a download that is about to start."""
    global _samples
    with _lock:
        _samples = []
        _state.clear()
        _state.update({
            "active": True,
            "model_id": str(model_id or ""),
            "label": str(label or ""),
            "target_dir": str(target_dir),
            "expected_bytes": max(0, int(expected_bytes or 0)),
            "filenames": [str(f) for f in filenames if f],
            "phase": "model",
            "started": time.monotonic(),
            "error": "",
            "done": False,
        })


def set_phase(phase: str) -> None:
    """Mark a phase change ("model" -> "vision" -> "done")."""
    with _lock:
        if _state:
            _state["phase"] = str(phase or "model")


def finish() -> None:
    with _lock:
        if _state:
            _state["active"] = False
            _state["done"] = True
            _state["phase"] = "done"


def fail(error: str) -> None:
    with _lock:
        if _state:
            _state["active"] = False
            _state["done"] = True
            _state["error"] = str(error or "download failed")


def is_active() -> bool:
    with _lock:
        return bool(_state.get("active"))


def snapshot() -> dict:
    """Progress for the current or last download.

    Returns `active: False` with an empty payload when nothing is tracked but a
    staging file still exists (a download that started before this process last
    restarted); `fallback: True` marks that case so the panel knows the percentage
    is unknown rather than zero.
    """
    with _lock:
        state = dict(_state) if _state else {}
        samples = list(_samples)

    if not state:
        return _untracked_snapshot()

    target_dir = Path(state.get("target_dir") or ".")
    got = _downloaded_bytes(target_dir, list(state.get("filenames") or []))
    expected = int(state.get("expected_bytes") or 0)

    now = time.monotonic()
    if state.get("active"):
        samples.append((now, got))
        cutoff = now - _RATE_WINDOW_SECONDS
        samples = [s for s in samples if s[0] >= cutoff]
        with _lock:
            _samples[:] = samples

    rate = 0.0
    if len(samples) >= 2 and samples[-1][0] > samples[0][0]:
        rate = (samples[-1][1] - samples[0][1]) / (samples[-1][0] - samples[0][0])
    if rate <= 0 and state.get("active"):
        # A single sample (the first poll) still deserves a rough ETA: fall back to
        # the average since the transfer started.
        elapsed = now - float(state.get("started") or now)
        if elapsed > 1.0 and got > 0:
            rate = got / elapsed

    percent = None
    eta_seconds = None
    if expected > 0:
        percent = max(0.0, min(100.0, got * 100.0 / expected))
        if rate > 1.0 and got < expected:
            eta_seconds = (expected - got) / rate

    return {
        "active": bool(state.get("active")),
        "done": bool(state.get("done")),
        "fallback": False,
        "model_id": state.get("model_id", ""),
        "label": state.get("label", ""),
        "phase": state.get("phase", "model"),
        "bytes": got,
        "expected_bytes": expected,
        "percent": None if percent is None else round(percent, 1),
        "rate_bps": round(rate, 1),
        "eta_seconds": None if eta_seconds is None else round(eta_seconds, 1),
        "error": state.get("error", ""),
    }


def _untracked_snapshot() -> dict:
    """Report staging bytes when nothing is tracked (download predates a restart).

    Only used by the panel to show that work is ongoing; without the catalog entry
    there is no expected size, so the percentage stays unknown. A staging file that
    has not been written recently is a leftover from a download that died with the
    process, and reporting it as active would leave a bar running forever.
    """
    empty = {
        "active": False, "done": False, "fallback": False, "model_id": "", "label": "",
        "phase": "", "bytes": 0, "expected_bytes": 0, "percent": None,
        "rate_bps": 0.0, "eta_seconds": None, "error": "",
    }
    try:
        from .prompt_local_models import download_dir

        staging = download_dir() / ".cache" / "huggingface" / "download"
        paths = [p for p in staging.rglob("*") if p.is_file() and p.suffix not in (".lock", ".json")]
    except Exception:  # noqa: BLE001 - folder_paths is absent outside ComfyUI
        return empty
    if not paths:
        return empty

    total = 0
    newest = 0.0
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        total += stat.st_size
        newest = max(newest, stat.st_mtime)
    if time.time() - newest > _STALE_SECONDS:
        return empty
    return {
        "active": True, "done": False, "fallback": True, "model_id": "", "label": "",
        "phase": "unknown", "bytes": total, "expected_bytes": 0, "percent": None,
        "rate_bps": 0.0, "eta_seconds": None, "error": "",
    }


def reset() -> None:
    """Drop all state (tests, and after a download finishes being reported)."""
    global _samples
    with _lock:
        _state.clear()
        _samples = []
