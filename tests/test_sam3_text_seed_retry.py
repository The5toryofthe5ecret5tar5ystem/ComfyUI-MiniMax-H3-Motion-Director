"""Text-seed retry memory for the SAM3 auto mask (director.sam3_auto).

The full auto-mask plan is 5 passes over the whole window, roughly 2 minutes each
on a 260-frame clip. When text seeding misses, nothing about a later window makes
the same prompt more likely to land, so an unguarded chain spends hours
rediscovering the same nothing before every segment falls back anyway.

The segmentation call is replaced here, so the attempt POLICY is exercised for
real (which attempts run, what gets remembered) without loading SAM3 or a GPU.
"""

from __future__ import annotations

import pytest
import torch

from mmx_pkg.director import sam3_auto


@pytest.fixture(autouse=True)
def _clean_memory():
    sam3_auto.reset_auto_mask_memory()
    yield
    sam3_auto.reset_auto_mask_memory()


def _frames(t: int = 20) -> torch.Tensor:
    return torch.zeros(t, 8, 8, 3)


def _never_finds(monkeypatch, calls: list) -> None:
    """Every attempt reports 'no subject', which is what a text miss looks like."""
    monkeypatch.setattr(
        sam3_auto, "segment_window_frames",
        lambda *a, **k: (calls.append(1), None)[1],
    )


def test_memory_starts_empty():
    assert sam3_auto._TEXT_SEED_MISSES == {}


# --- the plan itself ------------------------------------------------------


def test_full_plan_is_five_attempts():
    # 3 anchors normal + relaxed retries on the two most robust anchors.
    assert len(sam3_auto.mask_attempt_plan(260)) == 5


def test_reset_hook_is_exported():
    assert "reset_auto_mask_memory" in sam3_auto.__all__


def test_a_missed_key_expires(monkeypatch):
    # The memory is a hint about a prompt that was not landing, not a permanent
    # verdict: the same prompt much later, or against different footage, must get
    # the full plan back.
    key = ("", "the woman")
    sam3_auto.note_text_seed_miss(key)
    assert sam3_auto.text_seed_is_known_miss(key) is True

    monkeypatch.setattr(sam3_auto, "_TEXT_SEED_MISS_TTL_SEC", 0.0)
    assert sam3_auto.text_seed_is_known_miss(key) is False
    assert key not in sam3_auto._TEXT_SEED_MISSES, "an expired key is dropped, not kept"


def test_the_memory_is_bounded(monkeypatch):
    monkeypatch.setattr(sam3_auto, "_TEXT_SEED_MISS_LIMIT", 4)
    for i in range(10):
        sam3_auto.note_text_seed_miss(("", f"prompt {i}"))
    assert len(sam3_auto._TEXT_SEED_MISSES) == 4
    # The newest are the ones kept.
    assert sam3_auto.text_seed_is_known_miss(("", "prompt 9")) is True


def test_an_unknown_key_is_not_a_known_miss():
    assert sam3_auto.text_seed_is_known_miss(("", "never seen")) is False


def test_no_frames_returns_early_without_touching_memory():
    # Guard rail: the early-out must not record a miss, or one malformed call
    # would silently downgrade every later window.
    result = sam3_auto.run_window_auto_mask(None)
    assert result["mask"] is None
    assert result["reason"] == "no source frames for auto SAM3 masking"
    assert sam3_auto._TEXT_SEED_MISSES == {}


# --- the policy ----------------------------------------------------------


def test_first_window_runs_the_full_plan_and_records_the_miss(monkeypatch):
    calls: list = []
    _never_finds(monkeypatch, calls)

    result = sam3_auto.run_window_auto_mask(_frames(), prompts=["the woman"])

    assert result["mask"] is None
    assert len(calls) == 5, "the first window must try the whole plan"
    assert sam3_auto.text_seed_is_known_miss(("", "the woman")) is True


def test_later_window_retries_only_the_strongest_anchors(monkeypatch):
    calls: list = []
    _never_finds(monkeypatch, calls)

    sam3_auto.run_window_auto_mask(_frames(), prompts=["the woman"])
    calls.clear()
    result = sam3_auto.run_window_auto_mask(_frames(), prompts=["the woman"])

    assert len(calls) == 2, "a known text miss must not repeat all five attempts"
    assert "strongest anchor" in result["reason"]
    assert "Quick test" not in result["reason"], (
        "a reduced retry after a miss must not be described as an interactive test"
    )


def test_a_different_prompt_restores_the_full_plan(monkeypatch):
    # The memory is keyed on the prompt, so a genuinely different prompt is a
    # fresh attempt policy rather than a repeat of the same doomed search.
    calls: list = []
    _never_finds(monkeypatch, calls)

    sam3_auto.run_window_auto_mask(_frames(), prompts=["the woman"])
    calls.clear()
    sam3_auto.run_window_auto_mask(_frames(), prompts=["a dancer in red"])

    assert len(calls) == 5


def test_a_different_checkpoint_restores_the_full_plan(monkeypatch):
    calls: list = []
    _never_finds(monkeypatch, calls)

    sam3_auto.run_window_auto_mask(_frames(), prompts=["the woman"], checkpoint="a.pt")
    calls.clear()
    sam3_auto.run_window_auto_mask(_frames(), prompts=["the woman"], checkpoint="b.pt")

    assert len(calls) == 5


def test_success_clears_the_recorded_miss(monkeypatch):
    calls: list = []
    _never_finds(monkeypatch, calls)
    sam3_auto.run_window_auto_mask(_frames(), prompts=["the woman"])
    assert sam3_auto._TEXT_SEED_MISSES

    # Now the subject is found: the prompt is not hopeless, so later windows must
    # get the full plan back.
    monkeypatch.setattr(
        sam3_auto, "segment_window_frames", lambda *a, **k: torch.ones(20, 8, 8)
    )
    result = sam3_auto.run_window_auto_mask(_frames(), prompts=["the woman"])

    assert result["mask"] is not None
    assert sam3_auto._TEXT_SEED_MISSES == {}


def test_default_prompt_misses_are_not_conflated_with_a_real_one(monkeypatch):
    # A window with no prompt falls back to the built-in default; that is a
    # different search from an explicit prompt, so the memory must key on the
    # prompt actually used. Deliberately not the default - using the default as
    # the "explicit" example would test nothing.
    other = "a dancer in red"
    assert other != sam3_auto.SAM3_DEFAULT_PROMPT

    calls: list = []
    _never_finds(monkeypatch, calls)

    sam3_auto.run_window_auto_mask(_frames())
    assert sam3_auto.text_seed_is_known_miss(("", sam3_auto.SAM3_DEFAULT_PROMPT)) is True
    assert sam3_auto.text_seed_is_known_miss(("", other)) is False

    calls.clear()
    sam3_auto.run_window_auto_mask(_frames(), prompts=[other])
    assert len(calls) == 5, "an explicit prompt after a default-prompt miss is a fresh try"


def test_explicit_quick_still_reports_as_a_test(monkeypatch):
    # `quick` has two causes; the interactive one must keep its own wording.
    calls: list = []
    _never_finds(monkeypatch, calls)

    result = sam3_auto.run_window_auto_mask(_frames(), prompts=["the woman"], quick=True)

    assert len(calls) == 2
    assert "Quick test" in result["reason"]
    assert sam3_auto.text_seed_is_known_miss(("", "the woman")) is True, (
        "a quick test that misses still tells us the prompt is not landing"
    )
