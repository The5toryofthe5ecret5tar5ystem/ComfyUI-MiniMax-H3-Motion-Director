"""Room simulation and level post-processing for Director audio.

Backed by SoX, the same external-audio toolchain ``lib/audio_io`` already uses
for ffmpeg.  This replaces the third-party ``ComfyUI-Audio_Quality_Enhancer``
node, which had three defects that made it unsafe for this pipeline:

* **Channel loss.**  ComfyUI AUDIO is ``[batch, channels, samples]``; that node
  read ``waveform[0, 0]`` and returned mono.  H3 emits stereo and the whole AV
  latent layout is channel-aware, so stereo must survive untouched.
* **Silent failure.**  Every error path returned the *original* audio after a
  ``print``.  A missing or failing SoX therefore produced dry audio that was
  indistinguishable from success in a long multi-segment render.  Here every
  failure raises :class:`AudioEffectsError`.
* **16-bit round trip.**  ``soundfile`` defaults WAV to PCM_16, so that node
  quantised the track on every call.  The temp file here is 32-bit float.

Additionally the reverb length is pinned to the input sample count: SoX never
shifts the result, but a caller re-aligning audio to the picture must not have
to depend on that.

SoX ``reverb`` takes six positional parameters, all percentages except the
pre-delay (milliseconds, plain number, no unit suffix -- ``20ms`` is rejected):

    reverb [reverberance [HF-damping [room-scale [stereo-depth
            [pre-delay [wet-gain]]]]]]
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any

import numpy as np
import torch

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.audio_effects")

#: 32-bit float, so the temp-file round trip is lossless.  soundfile would
#: otherwise pick PCM_16 and quantise the track.
_WAV_SUBTYPE = "FLOAT"

#: SoX prints this for any WAVE_FORMAT_EXTENSIBLE file.  It is not an error.
_BENIGN_STDERR = ("wave header missing extended part of fmt chunk",)

#: Generous ceiling; a 10 minute 32 kHz stereo track reverberates in seconds.
_SOX_TIMEOUT_SECONDS = 900


class AudioEffectsError(RuntimeError):
    """Raised when the external audio toolchain cannot process a track."""


@dataclass(frozen=True)
class RoomSpec:
    """A SoX ``reverb`` parameter set.  All values are percentages except the delay."""

    reverberance: float = 0.0
    hf_damping: float = 50.0
    room_scale: float = 0.0
    stereo_depth: float = 50.0
    pre_delay_ms: float = 0.0
    wet_gain_db: float = 0.0

    @property
    def is_dry(self) -> bool:
        """True when this spec would add no audible space."""
        return self.reverberance <= 0.0 or self.room_scale <= 0.0

    def sox_args(self) -> list[str]:
        if self.is_dry:
            return []
        return [
            "reverb",
            f"{self.reverberance:g}",
            f"{self.hf_damping:g}",
            f"{self.room_scale:g}",
            f"{self.stereo_depth:g}",
            f"{self.pre_delay_ms:g}",
            f"{self.wet_gain_db:g}",
        ]


#: Named spaces. ``hf_damping`` is the knob that decides whether a room reads as
#: soft (curtains, carpet, bedding) or hard (tile, glass, concrete); the
#: third-party node hard-coded it at 50 and so could never reach either extreme.
ROOM_PRESETS: dict[str, RoomSpec] = {
    "dry":       RoomSpec(0.0, 50.0, 0.0, 50.0, 0.0, 0.0),
    "bedroom":   RoomSpec(26.0, 74.0, 30.0, 55.0, 10.0, -3.0),
    "bathroom":  RoomSpec(58.0, 24.0, 26.0, 85.0, 6.0, 1.0),
    "bar":       RoomSpec(46.0, 44.0, 62.0, 75.0, 24.0, -1.0),
    "office":    RoomSpec(30.0, 58.0, 44.0, 55.0, 18.0, -2.0),
    "car":       RoomSpec(34.0, 62.0, 22.0, 70.0, 4.0, 0.0),
    "hall":      RoomSpec(70.0, 40.0, 84.0, 88.0, 38.0, -1.0),
    "cathedral": RoomSpec(90.0, 28.0, 96.0, 96.0, 56.0, -1.0),
    "outdoor":   RoomSpec(14.0, 84.0, 62.0, 34.0, 44.0, -5.0),
}

#: Aliases so a scene can say what it means without knowing the preset names.
#: An EMPTY value is deliberately absent: it means "no opinion", not "dry", so
#: that an unset per-scene field falls through to the global room instead of
#: silently forcing the scene dry.
ROOM_ALIASES: dict[str, str] = {
    "none": "dry",
    "off": "dry",
    "silent": "dry",
    "studio": "dry",
    "booth": "dry",
    "bed": "bedroom",
    "bedchamber": "bedroom",
    "shower": "bathroom",
    "bath": "bathroom",
    "bathhouse": "bathroom",
    "toilet": "bathroom",
    "tiled": "bathroom",
    "pub": "bar",
    "tavern": "bar",
    "club": "bar",
    "kitchen": "office",
    "restaurant": "bar",
    "vehicle": "car",
    "van": "car",
    "outside": "outdoor",
    "street": "outdoor",
    "forest": "outdoor",
    "warehouse": "hall",
    "gym": "hall",
    "church": "cathedral",
    "temple": "cathedral",
}


def resolve_room(name: Any) -> RoomSpec | None:
    """Map a scene's ``room`` string to a :class:`RoomSpec`.

    Returns ``None`` both for an empty value ("no opinion": let the caller fall
    back to the global setting or its explicit values) and for an unrecognised
    one (so the caller can report the bad value).  Explicit ``none``/``dry``
    words still resolve to the dry preset, which is a real instruction.
    """
    key = str(name or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not key:
        return None
    return ROOM_PRESETS.get(ROOM_ALIASES.get(key, key))


def room_names() -> list[str]:
    """Preset names, ordered for a UI dropdown."""
    return list(ROOM_PRESETS)


@dataclass(frozen=True)
class AudioEffectsChain:
    """The full post-processing chain applied to one audio track.

    Order matters and is deliberate: reverb first, then level.  Normalising or
    gaining *before* reverb would let the reverberant tail push the result into
    clipping, because the reverb adds energy on top of the already-peaked dry
    signal (measured: 0.50 peak dry to 0.71 peak wet on a 440 Hz tone).
    """

    room: RoomSpec | None = None
    gain_db: float = 0.0
    normalize: bool = False
    use_limiter: bool = True

    @property
    def is_noop(self) -> bool:
        return (
            (self.room is None or self.room.is_dry)
            and (not self.normalize)
            and abs(self.gain_db) < 0.01
        )

    def sox_args(self) -> list[str]:
        args: list[str] = []
        if self.room is not None:
            args.extend(self.room.sox_args())
        if self.normalize:
            args.extend(["gain", "-n"])
        if abs(self.gain_db) >= 0.01:
            if self.gain_db > 0.0 and self.use_limiter:
                # -l clamps peaks rather than letting positive gain distort.
                args.extend(["gain", "-l", f"{self.gain_db:g}"])
            else:
                args.extend(["gain", f"{self.gain_db:g}"])
        return args


def find_sox(explicit: str = "") -> str:
    """Locate the SoX executable, raising a helpful error when absent."""
    candidate = str(explicit or "").strip()
    if candidate:
        found = shutil.which(candidate)
        if found:
            return found
        raise AudioEffectsError(
            f"SoX was not found at {candidate!r}. Leave the path empty to auto-detect, "
            f"or install it (Arch/CachyOS: sudo pacman -S sox)."
        )
    found = shutil.which("sox")
    if found:
        return found
    raise AudioEffectsError(
        "SoX is required for Director audio room simulation but was not found on PATH. "
        "Install it (Arch/CachyOS: sudo pacman -S sox) or disable the room effect."
    )


def _real_stderr(text: str) -> str:
    lines = [
        line
        for line in str(text or "").splitlines()
        if line.strip() and not any(benign in line for benign in _BENIGN_STDERR)
    ]
    return "\n".join(lines).strip()


def _fit_length(wave: np.ndarray, samples: int) -> np.ndarray:
    """Trim or zero-pad ``[frames, channels]`` back to an exact sample count."""
    have = int(wave.shape[0])
    if have == samples:
        return wave
    if have > samples:
        return wave[:samples, :]
    pad = np.zeros((samples - have, wave.shape[1]), dtype=wave.dtype)
    return np.concatenate([wave, pad], axis=0)


def _run_sox(
    sox: str,
    wave: np.ndarray,
    sample_rate: int,
    effects: list[str],
    workdir: str,
    tag: str,
) -> np.ndarray:
    """Round-trip one ``[frames, channels]`` block through SoX."""
    import soundfile as sf

    in_path = f"{workdir}/{tag}_in.wav"
    out_path = f"{workdir}/{tag}_out.wav"
    sf.write(in_path, wave, sample_rate, subtype=_WAV_SUBTYPE)

    command = [sox, in_path, out_path, *effects]
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=_SOX_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise AudioEffectsError(
            f"SoX timed out after {_SOX_TIMEOUT_SECONDS}s processing {wave.shape[0]} samples."
        ) from exc
    except OSError as exc:
        raise AudioEffectsError(f"Could not execute SoX at {sox!r}: {exc}") from exc

    if proc.returncode != 0:
        detail = _real_stderr(proc.stderr) or f"exit code {proc.returncode}"
        raise AudioEffectsError(f"SoX failed: {detail}")

    try:
        processed, _ = sf.read(out_path, always_2d=True)
    except Exception as exc:  # soundfile raises its own error types
        raise AudioEffectsError(f"SoX produced an unreadable output file: {exc}") from exc

    if processed.size == 0:
        raise AudioEffectsError("SoX produced an empty output track.")

    warned = _real_stderr(proc.stderr)
    if warned:
        log.debug("SoX stderr for %s: %s", tag, warned)

    return processed.astype(np.float32, copy=False)


def apply_audio_effects(
    audio: dict[str, Any] | None,
    chain: AudioEffectsChain | None,
    *,
    sox_path: str = "",
) -> dict[str, Any] | None:
    """Apply ``chain`` to a ComfyUI AUDIO dict, preserving channels and length.

    Empty or muted tracks pass through untouched rather than erroring: a silent
    segment is a legitimate state, not a toolchain failure.  Every *processing*
    failure raises :class:`AudioEffectsError`.
    """
    if chain is None or chain.is_noop:
        return audio
    if not isinstance(audio, dict):
        return audio

    wave = audio.get("waveform")
    if not isinstance(wave, torch.Tensor) or wave.numel() == 0:
        return audio

    work = wave.detach().to("cpu", torch.float32)
    if work.ndim == 1:
        work = work.unsqueeze(0)
    if work.ndim == 2:
        work = work.unsqueeze(0)
    if work.ndim != 3:
        raise AudioEffectsError(
            f"Unsupported waveform shape {tuple(wave.shape)}; expected [batch, channels, samples]."
        )

    sample_rate = int(audio.get("sample_rate") or 0)
    if sample_rate <= 0:
        raise AudioEffectsError(
            f"Audio carries an unusable sample rate ({audio.get('sample_rate')!r})."
        )

    sox = find_sox(sox_path)
    effects = chain.sox_args()
    batch, channels, samples = (int(v) for v in work.shape)

    blocks: list[np.ndarray] = []
    with tempfile.TemporaryDirectory(prefix="mmx_director_audio_") as workdir:
        for index in range(batch):
            # soundfile wants [frames, channels]; ComfyUI carries [channels, frames].
            block = work[index].transpose(0, 1).contiguous().numpy()
            out = _run_sox(sox, block, sample_rate, effects, workdir, f"b{index}")
            if int(out.shape[1]) != channels:
                raise AudioEffectsError(
                    f"SoX changed the channel count ({channels} -> {int(out.shape[1])})."
                )
            blocks.append(_fit_length(out, samples))

    merged = np.stack(blocks, axis=0) if len(blocks) > 1 else blocks[0][None, ...]
    result = torch.from_numpy(merged).transpose(1, 2).contiguous()
    return {
        "waveform": result.to(device=wave.device, dtype=wave.dtype),
        "sample_rate": sample_rate,
    }


def chain_from_config(
    config: dict[str, Any] | None,
    *,
    room_override: Any = None,
) -> AudioEffectsChain | None:
    """Build a chain from a normalised ``audio_refine`` config section.

    ``room_override`` lets a scene's own ``room`` field win over the global
    setting, which is what makes a bathroom scene and a bedroom scene in the
    same timeline differ without re-rendering either.
    """
    if not isinstance(config, dict) or not config.get("enabled"):
        return None

    room: RoomSpec | None = None
    if config.get("reverb_enabled", True):
        override = resolve_room(room_override)
        if override is not None:
            room = override
        else:
            preset = resolve_room(config.get("room"))
            if preset is not None:
                room = preset
            else:
                room = RoomSpec(
                    reverberance=float(config.get("reverberance") or 0.0),
                    hf_damping=float(config.get("hf_damping") or 50.0),
                    room_scale=float(config.get("room_scale") or 0.0),
                    stereo_depth=float(config.get("stereo_depth") or 50.0),
                    pre_delay_ms=float(config.get("pre_delay_ms") or 0.0),
                    wet_gain_db=float(config.get("wet_gain_db") or 0.0),
                )

    return AudioEffectsChain(
        room=room,
        gain_db=float(config.get("gain_db") or 0.0),
        normalize=bool(config.get("normalize")),
        use_limiter=bool(config.get("use_limiter", True)),
    )


__all__ = [
    "AudioEffectsChain",
    "AudioEffectsError",
    "ROOM_ALIASES",
    "ROOM_PRESETS",
    "RoomSpec",
    "apply_audio_effects",
    "chain_from_config",
    "find_sox",
    "resolve_room",
    "room_names",
]
