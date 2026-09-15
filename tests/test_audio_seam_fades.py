"""Seam fades for finished audio (lib.audio_io, CPU).

Audio trimmed to a frame boundary normally stops mid-waveform, and the step from
that sample to silence is an audible click; the same happens at the head when
the source starts mid-cycle. ``fade_audio_seams`` ramps both edges, and
``fade_audio_chunk_boundaries`` does the same for the joins between
concatenated chunks.
"""

from __future__ import annotations

import torch

from mmx_pkg.lib.audio_io import fade_audio_chunk_boundaries, fade_audio_seams

SR = 44100


def test_seams_ramp_both_edges_and_keep_length():
    wave = torch.ones(1, 2, SR)  # 1 s of DC: without fades both ends step to 0
    out = fade_audio_seams(wave, SR)
    assert out.shape == wave.shape
    assert float(out[0, 0, 0]) == 0.0
    assert float(out[0, 0, -1]) == 0.0
    # Middle is untouched, so the fade is not a level change.
    assert float(out[0, 0, SR // 2]) == 1.0


def test_seams_fade_length_is_three_milliseconds():
    wave = torch.ones(1, 1, SR)
    out = fade_audio_seams(wave, SR)
    count = int(round(SR * 3 / 1000))  # 3 ms of ramp
    assert float(out[0, 0, 0]) == 0.0
    # Halfway up the ramp should read about half scale...
    assert abs(float(out[0, 0, count // 2]) - 0.5) < 0.02
    # ...and by the end of the ramp the signal is back to full scale.
    assert float(out[0, 0, count]) == 1.0


def test_seams_do_not_mutate_the_input():
    wave = torch.ones(1, 1, 1000)
    fade_audio_seams(wave, SR)
    assert float(wave.min()) == 1.0


def test_seams_tolerate_degenerate_inputs():
    assert fade_audio_seams(torch.zeros(1, 1, 0), SR).shape[-1] == 0
    assert fade_audio_seams(torch.ones(1, 1, 3), SR).shape[-1] == 3
    # A zero/invalid rate must pass through rather than divide by zero.
    assert float(fade_audio_seams(torch.ones(1, 1, 100), 0).max()) == 1.0
    assert float(fade_audio_seams(torch.ones(1, 1, 100), SR, fade_ms=0).max()) == 1.0


def test_chunk_boundaries_fade_the_join_only():
    a = torch.ones(1, 2, 1000) * 0.5
    b = torch.ones(1, 2, 1000) * 0.5
    fa, fb = fade_audio_chunk_boundaries([a, b], SR)
    assert float(fa[0, 0, -1]) == 0.0  # tail of the first chunk
    assert float(fb[0, 0, 0]) == 0.0  # head of the second
    assert float(fa[0, 0, 0]) == 0.5  # outer edges untouched by this helper
    assert float(fb[0, 0, -1]) == 0.5


def test_chunk_boundaries_noop_for_a_single_chunk():
    a = torch.ones(1, 1, 100)
    out = fade_audio_chunk_boundaries([a], SR)
    assert len(out) == 1
    assert float(out[0][0, 0, 0]) == 1.0
