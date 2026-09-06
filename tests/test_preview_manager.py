"""Cadence-cap behavior of the live TAE preview manager.

The Director decodes a small animated clip from the sampler latent on the
sampling thread.  That decode is a side-channel preview: skipping it must never
change the generated output, only how often live preview frames are produced.
These tests lock down the policy (first + periodic + guaranteed-final) and the
legacy every-step escape hatch (``preview_min_interval_ms = 0``).
"""

from __future__ import annotations

from PIL import Image

from director.preview_manager import DirectorPreviewManager


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _counting_decoder(calls: list[int]):
    def decode(x0, **kwargs):
        calls.append(1)
        return [Image.new("RGB", (8, 8))]

    return decode


def _null_encoder(job, config):
    return None


def _null_sender(*args, **kwargs):
    return None


def _submit(manager, *, segment_index=0, stage="Generation", step, total_steps):
    return manager.submit(
        segment_index=segment_index,
        stage=stage,
        step=step,
        total_steps=total_steps,
        x0=object(),
    )


def _make_manager(clock: Clock, *, min_interval_ms: float) -> DirectorPreviewManager:
    # A large queue isolates the cadence-cap logic from the async worker: with
    # queue_size >= submitted jobs the bounded-queue drop path never triggers.
    return DirectorPreviewManager(
        "test-node",
        {"enabled": True},
        min_interval_ms=min_interval_ms,
        now=clock,
        decoder=_counting_decoder([]),
        encoder=_null_encoder,
        sender=_null_sender,
        queue_size=64,
    )


def test_interval_zero_preserves_legacy_every_step_behavior():
    clock = Clock()
    calls: list[int] = []
    manager = _make_manager(clock, min_interval_ms=0)
    manager.decoder = _counting_decoder(calls)
    try:
        for step in range(10):
            clock.advance(0.01)
            assert _submit(manager, step=step, total_steps=10) is True
        assert len(calls) == 10, "interval=0 must decode on every step (legacy)"
        assert manager.skipped == 0
    finally:
        manager.close()


def test_cadence_cap_keeps_first_and_final_step_only_when_steps_are_fast():
    clock = Clock()
    calls: list[int] = []
    manager = _make_manager(clock, min_interval_ms=400.0)
    manager.decoder = _counting_decoder(calls)
    try:
        # 10 fast steps, all within a 400 ms window.
        for step in range(10):
            clock.advance(0.01)
            _submit(manager, step=step, total_steps=10)
        assert len(calls) == 2, "only the first and the final step should decode"
        assert manager.skipped == 8
    finally:
        manager.close()


def test_cadence_cap_allows_periodic_updates_when_steps_are_slow():
    clock = Clock()
    calls: list[int] = []
    manager = _make_manager(clock, min_interval_ms=400.0)
    manager.decoder = _counting_decoder(calls)
    try:
        # Each step is 500 ms apart, so the cap never suppresses a decode.
        for step in range(10):
            clock.advance(0.5)
            _submit(manager, step=step, total_steps=10)
        assert len(calls) == 10
        assert manager.skipped == 0
    finally:
        manager.close()


def test_final_step_always_decodes_even_inside_the_interval():
    clock = Clock()
    calls: list[int] = []
    manager = _make_manager(clock, min_interval_ms=100000.0)  # never allows a 2nd
    manager.decoder = _counting_decoder(calls)
    try:
        _submit(manager, step=0, total_steps=6)  # first -> decode
        for step in range(1, 5):
            clock.advance(0.01)
            _submit(manager, step=step, total_steps=6)  # within window -> skip
        clock.advance(0.01)
        assert _submit(manager, step=5, total_steps=6) is True  # final -> decode
        assert len(calls) == 2
    finally:
        manager.close()


def test_first_step_of_a_new_stage_always_decodes():
    clock = Clock()
    calls: list[int] = []
    manager = _make_manager(clock, min_interval_ms=100000.0)
    manager.decoder = _counting_decoder(calls)
    try:
        _submit(manager, step=0, total_steps=6, stage="Generation")
        # A different stage begins immediately; its first step must decode too.
        assert _submit(manager, step=0, total_steps=6, stage="Global Refine") is True
        assert len(calls) == 2
    finally:
        manager.close()
