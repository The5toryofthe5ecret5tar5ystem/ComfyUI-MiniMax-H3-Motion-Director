"""A source clip that is not on the H3 frame grid must not silently disable the masked replace.

Field bug (2026-09-15): a 97-frame source clip samples at the aligned length of 107
frames, the inpaint branch required ``visible_clip_frames == num_frames`` and gave
up, so the segment rendered as a plain window with no keep region - the whole clip
was regenerated and nothing of the source background survived.

The fix pads/trims the window *and its mask* to the sample length (repeat-last
padding, the same convention the reference-clip alignment already uses).
"""

from __future__ import annotations

import torch

from director.replace_engine import align_replace_window_to_sample, fit_frames_to_length


def _frames(t: int, h: int = 8, w: int = 6) -> torch.Tensor:
    base = torch.arange(t, dtype=torch.float32).view(t, 1, 1)
    return base.expand(t, h, w).clone().unsqueeze(-1).expand(t, h, w, 3).clone()


def _mask(t: int, h: int = 8, w: int = 6) -> torch.Tensor:
    base = torch.arange(t, dtype=torch.float32).view(t, 1, 1)
    return base.expand(t, h, w).clone()


def test_fit_frames_pads_with_last_frame_and_trims():
    frames = _frames(4)
    padded = fit_frames_to_length(frames, 6)
    assert tuple(padded.shape) == (6, 8, 6, 3)
    assert torch.equal(padded[:4], frames)
    assert torch.equal(padded[4], frames[-1])
    assert torch.equal(padded[5], frames[-1])

    trimmed = fit_frames_to_length(frames, 2)
    assert tuple(trimmed.shape) == (2, 8, 6, 3)
    assert torch.equal(trimmed, frames[:2])

    same = fit_frames_to_length(frames, 4)
    assert same is frames


def test_mask_3d_pads_and_trims_like_frames():
    mask = _mask(4)
    padded = fit_frames_to_length(mask, 6)
    assert tuple(padded.shape) == (6, 8, 6)
    assert torch.equal(padded[4], mask[-1])
    assert tuple(fit_frames_to_length(mask, 2).shape) == (2, 8, 6)


def test_equal_length_returns_inputs_untouched():
    frames, mask = _frames(5), _mask(5)
    state = {"mask_vis": mask, "grow": 0, "feather": 1.0}
    out_frames, out_state = align_replace_window_to_sample(frames, state, 5)
    assert out_frames is frames
    assert out_state is state


def test_short_window_pads_window_and_mask_in_step():
    frames, mask = _frames(3), _mask(3)
    state = {
        "mask_vis": mask,
        "sanitized_reference": _frames(7),
        "grow": 1,
        "feather": 0.5,
    }
    out_frames, out_state = align_replace_window_to_sample(frames, state, 5)
    assert tuple(out_frames.shape) == (5, 8, 6, 3)
    assert torch.equal(out_frames[3], frames[-1])
    assert tuple(out_state["mask_vis"].shape) == (5, 8, 6)
    assert torch.equal(out_state["mask_vis"][4], mask[-1])
    # The anchor motion reference keeps its own (longer) alignment.
    assert out_state["sanitized_reference"] is state["sanitized_reference"]
    # Unrelated state keys survive, and the caller's dict is not mutated.
    assert out_state["grow"] == 1 and out_state["feather"] == 0.5
    assert "mask_vis" in state and tuple(state["mask_vis"].shape) == (3, 8, 6)


def test_long_window_trims_window_and_mask():
    frames, mask = _frames(9), _mask(9)
    out_frames, out_state = align_replace_window_to_sample(
        frames, {"mask_vis": mask}, 4
    )
    assert tuple(out_frames.shape) == (4, 8, 6, 3)
    assert torch.equal(out_frames, frames[:4])
    assert tuple(out_state["mask_vis"].shape) == (4, 8, 6)


def test_mask_frame_count_is_normalised_independently():
    frames, mask = _frames(4), _mask(9)
    out_frames, out_state = align_replace_window_to_sample(
        frames, {"mask_vis": mask}, 6
    )
    assert tuple(out_frames.shape) == (6, 8, 6, 3)
    assert tuple(out_state["mask_vis"].shape) == (6, 8, 6)


def test_missing_state_returns_window_unchanged():
    frames = _frames(3)
    out_frames, out_state = align_replace_window_to_sample(frames, None, 7)
    assert out_frames is frames
    assert out_state is None


def test_executor_uses_the_alignment_instead_of_disabling():
    """Pin the call site: the inpaint branch must align, not fall back."""
    import pathlib

    src = pathlib.Path("director/executor_core_legacy.py").read_text(encoding="utf-8")
    assert "align_replace_window_to_sample(" in src, (
        "the masked branch must align the window to the sample length"
    )
    assert "source window length does not match the H3 sample length" not in src, (
        "the old length-mismatch fallback must be gone"
    )
