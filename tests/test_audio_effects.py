"""Director audio room simulation and effect chain (director.audio_effects).

These tests exist mainly to pin the three defects that made the third-party
``ComfyUI-Audio_Quality_Enhancer`` node unusable here:

1. it read ``waveform[0, 0]`` and returned MONO from a stereo input,
2. it returned the ORIGINAL audio after a failed run, so a broken SoX was
   indistinguishable from success,
3. it round-tripped through PCM_16.

The real-SoX tests skip when SoX is absent, so the suite stays green on a bare
checkout while still proving the behaviour wherever the tool is installed.
"""

from __future__ import annotations

import shutil

import pytest
import torch

from mmx_pkg.director.audio_effects import (
    ROOM_PRESETS,
    AudioEffectsChain,
    AudioEffectsError,
    RoomSpec,
    apply_audio_effects,
    chain_from_config,
    find_sox,
    resolve_room,
    room_names,
)
from mmx_pkg.director.audio_refine_config import (
    DEFAULT_AUDIO_REFINE,
    audio_refine_is_active,
    normalize_audio_refine,
    normalize_room_name,
)

SAMPLE_RATE = 32000
HAVE_SOX = shutil.which("sox") is not None
needs_sox = pytest.mark.skipif(not HAVE_SOX, reason="SoX is not installed")


def _tone(samples: int = 8000, channels: int = 2, batch: int = 1) -> dict:
    """Stereo tone with deliberately different content per channel."""
    t = torch.arange(samples, dtype=torch.float32) / SAMPLE_RATE
    rows = []
    for b in range(batch):
        chans = [
            0.4 * torch.sin(2 * torch.pi * (440 + 110 * c + b) * t) for c in range(channels)
        ]
        rows.append(torch.stack(chans, dim=0))
    return {
        "waveform": torch.stack(rows, dim=0).contiguous(),
        "sample_rate": SAMPLE_RATE,
    }


# --------------------------------------------------------------------------
# Contract: stereo survives
# --------------------------------------------------------------------------


@needs_sox
def test_reverb_preserves_stereo_channels():
    """The third-party node collapsed this to 1 channel. It must stay 2."""
    audio = _tone()
    out = apply_audio_effects(audio, AudioEffectsChain(room=ROOM_PRESETS["bathroom"]))

    assert out is not None
    assert tuple(out["waveform"].shape) == (1, 2, 8000)
    left, right = out["waveform"][0, 0], out["waveform"][0, 1]
    assert not torch.allclose(left, right), "channel content was merged"


@needs_sox
def test_reverb_preserves_sample_rate_and_length():
    audio = _tone(samples=12000)
    out = apply_audio_effects(audio, AudioEffectsChain(room=ROOM_PRESETS["hall"]))

    assert out["sample_rate"] == SAMPLE_RATE
    assert int(out["waveform"].shape[-1]) == 12000


@needs_sox
def test_reverb_actually_changes_the_signal():
    audio = _tone()
    out = apply_audio_effects(audio, AudioEffectsChain(room=ROOM_PRESETS["cathedral"]))

    dry = audio["waveform"]
    wet = out["waveform"]
    assert not torch.allclose(dry, wet, atol=1e-6), "reverb was a no-op"
    # A reverberant tail adds energy to a steady tone.
    assert float(wet.abs().max()) != pytest.approx(float(dry.abs().max()), abs=1e-6)


@needs_sox
def test_mono_input_stays_mono():
    audio = _tone(channels=1)
    out = apply_audio_effects(audio, AudioEffectsChain(room=ROOM_PRESETS["bedroom"]))
    assert tuple(out["waveform"].shape) == (1, 1, 8000)


@needs_sox
def test_batch_items_are_processed_independently():
    audio = _tone(batch=3)
    out = apply_audio_effects(audio, AudioEffectsChain(room=ROOM_PRESETS["bar"]))

    assert tuple(out["waveform"].shape) == (3, 2, 8000)
    # Each batch item carried a different frequency, so all three stay distinct.
    assert not torch.allclose(out["waveform"][0], out["waveform"][1])


# --------------------------------------------------------------------------
# Contract: failures are loud, not silent
# --------------------------------------------------------------------------


@needs_sox
def test_sox_failure_raises_instead_of_returning_original():
    """The third-party node returned the untouched input here."""
    audio = _tone()
    with pytest.raises(AudioEffectsError):
        apply_audio_effects(
            audio,
            AudioEffectsChain(room=ROOM_PRESETS["hall"]),
            sox_path="/bin/false",  # exists and is executable, always exits non-zero
        )


def test_missing_sox_raises_with_install_hint():
    with pytest.raises(AudioEffectsError) as excinfo:
        find_sox("/nonexistent/path/to/sox")
    assert "sox" in str(excinfo.value).lower()


def test_unusable_sample_rate_raises():
    audio = {"waveform": torch.zeros(1, 2, 100), "sample_rate": 0}
    with pytest.raises(AudioEffectsError):
        apply_audio_effects(audio, AudioEffectsChain(room=ROOM_PRESETS["hall"]))


def test_non_3d_waveform_raises():
    audio = {"waveform": torch.zeros(2, 3, 4, 5), "sample_rate": SAMPLE_RATE}
    with pytest.raises(AudioEffectsError):
        apply_audio_effects(audio, AudioEffectsChain(room=ROOM_PRESETS["hall"]))


# --------------------------------------------------------------------------
# Pass-through paths that must NOT reach the toolchain
# --------------------------------------------------------------------------


def test_empty_audio_passes_through_without_invoking_sox():
    audio = {"waveform": torch.zeros(1, 2, 0), "sample_rate": SAMPLE_RATE}
    assert apply_audio_effects(audio, AudioEffectsChain(room=ROOM_PRESETS["hall"])) is audio


def test_dry_chain_is_a_noop():
    assert AudioEffectsChain(room=ROOM_PRESETS["dry"]).is_noop
    assert AudioEffectsChain().is_noop
    assert not AudioEffectsChain(room=ROOM_PRESETS["bathroom"]).is_noop
    assert not AudioEffectsChain(gain_db=-3.0).is_noop
    assert not AudioEffectsChain(normalize=True).is_noop


def test_none_chain_passes_through():
    audio = _tone()
    assert apply_audio_effects(audio, None) is audio


# --------------------------------------------------------------------------
# SoX parameter construction
# --------------------------------------------------------------------------


def test_room_spec_emits_six_positional_parameters():
    args = RoomSpec(58, 24, 26, 85, 6, 1).sox_args()
    assert args[0] == "reverb"
    assert len(args) == 7  # effect name + six parameters


def test_pre_delay_is_a_bare_number_not_a_unit_suffixed_string():
    """SoX rejects ``20ms``: "pre_delay `20ms' is not a number"."""
    args = RoomSpec(50, 50, 50, 50, 20, 0).sox_args()
    assert "20" in args
    assert not any(token.endswith("ms") for token in args)


def test_dry_room_emits_no_reverb_arguments():
    assert RoomSpec(0, 50, 0, 50, 0, 0).sox_args() == []
    assert RoomSpec(50, 50, 0, 50, 0, 0).sox_args() == []  # zero room scale is dry


def test_gain_uses_limiter_only_for_positive_boost():
    assert AudioEffectsChain(gain_db=6.0).sox_args() == ["gain", "-l", "6"]
    assert AudioEffectsChain(gain_db=-6.0).sox_args() == ["gain", "-6"]


def test_chain_orders_reverb_before_level():
    """Gaining before reverb would let the tail push the result into clipping."""
    args = AudioEffectsChain(room=ROOM_PRESETS["hall"], normalize=True, gain_db=-3.0).sox_args()
    assert args.index("reverb") < args.index("gain")


# --------------------------------------------------------------------------
# Room lookup
# --------------------------------------------------------------------------


def test_unknown_room_resolves_to_none_so_callers_can_report_it():
    assert resolve_room("not_a_room") is None


@pytest.mark.parametrize(
    "scene_word,expected",
    [
        ("shower", "bathroom"),
        ("tiled", "bathroom"),
        ("pub", "bar"),
        ("van", "car"),
        ("forest", "outdoor"),
        ("church", "cathedral"),
        ("none", "dry"),
        ("Bedroom", "bedroom"),
    ],
)
def test_scene_words_map_to_presets(scene_word, expected):
    spec = resolve_room(scene_word)
    assert spec is not None
    assert spec == ROOM_PRESETS[expected]


@pytest.mark.parametrize("blank", ["", None, "   "])
def test_blank_room_means_no_opinion_not_dry(blank):
    """Otherwise an unset scene field would silently override the global room."""
    assert resolve_room(blank) is None


def test_room_names_cover_every_preset():
    assert set(room_names()) == set(ROOM_PRESETS)


# --------------------------------------------------------------------------
# Config plumbing
# --------------------------------------------------------------------------


def test_normalize_clamps_out_of_range_values():
    cfg = normalize_audio_refine(
        {"enabled": True, "reverberance": 500, "hf_damping": -80, "gain_db": 999, "pre_delay_ms": -5}
    )
    assert cfg["reverberance"] == 100.0
    assert cfg["hf_damping"] == 0.0
    assert cfg["gain_db"] == 20.0
    assert cfg["pre_delay_ms"] == 0.0


def test_normalize_defaults_when_given_junk():
    cfg = normalize_audio_refine("not a dict")
    assert cfg["enabled"] is False
    assert cfg["room"] == ""
    assert cfg["reverberance"] == DEFAULT_AUDIO_REFINE["reverberance"]


def test_normalize_drops_unknown_room_name():
    assert normalize_room_name("swimming_pool") == ""
    assert normalize_room_name("Bathroom") == "bathroom"
    assert normalize_room_name("  car  ") == "car"


def test_disabled_config_builds_no_chain():
    assert chain_from_config({"enabled": False}) is None
    assert chain_from_config(None) is None


def test_scene_room_overrides_the_global_choice():
    """A bathroom scene and a bedroom scene in one render must not share a space."""
    cfg = normalize_audio_refine({"enabled": True, "room": "bedroom"})

    global_chain = chain_from_config(cfg)
    scene_chain = chain_from_config(cfg, room_override="bathroom")

    assert global_chain is not None and global_chain.room == ROOM_PRESETS["bedroom"]
    assert scene_chain is not None and scene_chain.room == ROOM_PRESETS["bathroom"]


def test_unrecognised_scene_room_falls_back_to_the_global_choice():
    cfg = normalize_audio_refine({"enabled": True, "room": "hall"})
    chain = chain_from_config(cfg, room_override="swimming_pool")
    assert chain is not None and chain.room == ROOM_PRESETS["hall"]


def test_explicit_values_used_when_no_preset_named():
    cfg = normalize_audio_refine(
        {"enabled": True, "room": "", "reverberance": 33, "hf_damping": 22, "room_scale": 44}
    )
    chain = chain_from_config(cfg)
    assert chain is not None and chain.room is not None
    assert chain.room.reverberance == 33.0
    assert chain.room.hf_damping == 22.0
    assert chain.room.room_scale == 44.0


def test_is_active_detects_real_work():
    assert not audio_refine_is_active({"enabled": False})
    assert not audio_refine_is_active({"enabled": True, "room": "dry", "reverb_enabled": False})
    assert audio_refine_is_active({"enabled": True, "room": "bathroom"})
    assert audio_refine_is_active({"enabled": True, "room": "dry", "gain_db": -4})


def test_room_never_joins_the_segment_cache_fingerprint():
    """Tuning a room must never invalidate a segment cache.

    The room is applied at final output assembly, after every segment cache has
    been written, so no room setting can change a per-segment artefact.
    """
    from mmx_pkg.director.postprocess_config import postprocess_cache_fingerprint

    for config in (
        {},
        {"audio_refine": {"enabled": True, "room": "bathroom"}},
        {"audio_refine": {"enabled": True, "room": "hall", "gain_db": 3}},
        {"audio_refine": {"enabled": True, "room": "dry", "reverb_enabled": False}},
    ):
        assert postprocess_cache_fingerprint(config)["audio_refine"] is False


def test_a_legacy_per_segment_field_is_ignored():
    """Saved configs from before the option was removed must still load."""
    legacy = normalize_audio_refine(
        {"enabled": True, "room": "bathroom", "per_segment": True}
    )

    assert "per_segment" not in legacy
    assert legacy["room"] == "bathroom"
