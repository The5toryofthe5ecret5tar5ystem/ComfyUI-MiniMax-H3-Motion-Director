"""Resume reuse policy (director.segment_cache segment_reusable + resolve).

A segment can be reused without re-sampling only when its full decoded cache is
fingerprint-valid and, for audio-generating runs, its full audio cache is valid
too.  Editing any input (here: the prompt) makes the cache stale so the segment
re-samples.  ``resolve_resume_from_index`` returns the first non-reusable
segment in run order.
"""

from __future__ import annotations

import uuid

import pytest
import torch

import folder_paths
from mmx_pkg.director import segment_cache
from mmx_pkg.director.plan import DirectorPlan, SegmentPlan


@pytest.fixture
def out_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(folder_paths, "get_output_directory", lambda: str(tmp_path))
    return tmp_path


def _seg(index: int, prompt: str) -> SegmentPlan:
    return SegmentPlan(
        index=index, start_frame=index * 4, end_frame=index * 4 + 4,
        prompt=prompt, task_type="t2v", task_key="t2v", use_global=True,
    )


def _plan(*segs: SegmentPlan) -> DirectorPlan:
    return DirectorPlan(
        frame_rate=24.0, total_frames=len(segs) * 4, width=64, height=64,
        ref_max_size=64, output_mode="fixed", source_width=64, source_height=64,
        global_task_type="t2v", global_task_key="t2v", global_prompt="",
        global_refs=[], segments=list(segs),
        source_video=torch.zeros((1, 3, 8, 8)), edit_mode="segment", raw={},
    )


def _audio() -> dict:
    return {"waveform": torch.zeros((1, 1, 16000)), "sample_rate": 24000}


def _node() -> str:
    return f"cache_test_{uuid.uuid4().hex[:10]}"


def test_missing_cache_not_reusable(out_dir) -> None:
    node = _node()
    seg = _seg(0, "alpha")
    plan = _plan(seg)
    assert segment_cache.segment_reusable(node, seg, plan, audio_generate=False) is False
    assert segment_cache.segment_reusable(node, seg, plan, audio_generate=True) is False


def test_video_cache_reusable_when_audio_off(out_dir) -> None:
    node = _node()
    seg = _seg(0, "alpha")
    plan = _plan(seg)
    segment_cache.save_segment_cache(node, seg, plan, torch.zeros((4, 64, 64, 3)))
    assert segment_cache.segment_cache_status(node, seg, plan) == "hit"
    assert segment_cache.segment_reusable(node, seg, plan, audio_generate=False) is True


def test_audio_generate_requires_full_audio_cache(out_dir) -> None:
    node = _node()
    seg = _seg(0, "alpha")
    plan = _plan(seg)
    segment_cache.save_segment_cache(node, seg, plan, torch.zeros((4, 64, 64, 3)))
    # Video present but no audio cache -> not reusable for an audio run.
    assert segment_cache.segment_reusable(node, seg, plan, audio_generate=True) is False
    # With the audio cache it becomes reusable.
    segment_cache.save_segment_audio_cache(node, seg, plan, _audio())
    assert segment_cache.segment_reusable(node, seg, plan, audio_generate=True) is True


def test_stale_prompt_invalidates(out_dir) -> None:
    node = _node()
    seg = _seg(0, "alpha")
    plan = _plan(seg)
    segment_cache.save_segment_cache(node, seg, plan, torch.zeros((4, 64, 64, 3)))
    assert segment_cache.segment_reusable(node, seg, plan, audio_generate=False) is True
    # Editing the prompt changes the fingerprint -> cache is stale -> re-sample.
    edited = _seg(0, "alpha but different")
    assert segment_cache.segment_reusable(node, edited, plan, audio_generate=False) is False


def test_resolve_resume_from_index_prefix_only(out_dir) -> None:
    node = _node()
    seg0 = _seg(0, "alpha")
    seg1 = _seg(1, "beta")
    seg2 = _seg(2, "gamma")
    plan = _plan(seg0, seg1, seg2)
    segment_cache.save_segment_cache(node, seg0, plan, torch.zeros((4, 64, 64, 3)))
    segment_cache.save_segment_cache(node, seg1, plan, torch.zeros((4, 64, 64, 3)))
    # 0,1 cached; 2 missing -> resume from 2.
    assert segment_cache.resolve_resume_from_index(
        node, plan.segments, plan, audio_generate=False,
    ) == 2


def test_resolve_resume_from_index_interior_gap(out_dir) -> None:
    node = _node()
    seg0 = _seg(0, "alpha")
    seg1 = _seg(1, "beta")
    seg2 = _seg(2, "gamma")
    plan = _plan(seg0, seg1, seg2)
    segment_cache.save_segment_cache(node, seg0, plan, torch.zeros((4, 64, 64, 3)))
    segment_cache.save_segment_cache(node, seg2, plan, torch.zeros((4, 64, 64, 3)))
    # 1 is missing -> resume from 1 even though 2 is cached (2 re-samples too,
    # preserving continuity).
    assert segment_cache.resolve_resume_from_index(
        node, plan.segments, plan, audio_generate=False,
    ) == 1


def test_resolve_resume_from_index_all_cached(out_dir) -> None:
    node = _node()
    seg0 = _seg(0, "alpha")
    seg1 = _seg(1, "beta")
    plan = _plan(seg0, seg1)
    segment_cache.save_segment_cache(node, seg0, plan, torch.zeros((4, 64, 64, 3)))
    segment_cache.save_segment_cache(node, seg1, plan, torch.zeros((4, 64, 64, 3)))
    assert segment_cache.resolve_resume_from_index(
        node, plan.segments, plan, audio_generate=False,
    ) == 2
