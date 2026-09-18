"""A swapped RefMod must invalidate cached segments and cached motion context.

The harvested RefMod blocks are appended to every segment's conditioning, so they
change the picture. They arrive through the *conditioning* rather than the
timeline, though, and nothing in the cache fingerprints looked at them: two
different mods at the same retention produced byte-identical fingerprints. So
swapping the mod silently reused latents generated with the previous one, and the
old identity bled into the new render.

These tests pin the identity itself, and that both caches now key on it.
"""

from __future__ import annotations

import torch

from mmx_pkg.director.context_identity import generation_environment_identity
from mmx_pkg.director.plan import DirectorPlan, SegmentPlan
from mmx_pkg.director.segment_cache import segment_cache_fingerprint
from mmx_pkg.nodes.conditioning import refmod_digest


def _block(value: float = 0.5, **overrides) -> dict:
    """A minimal visual RefMod block, shaped like ``H3RefMod.ref_block`` output."""
    block = {
        "kind": "image",
        "latent_h": 4,
        "latent_w": 6,
        "latent": torch.full((1, 24, 4, 4, 6), value),
    }
    block.update(overrides)
    return block


def _audio_block(value: float = 0.25) -> dict:
    return {"kind": "audio", "ref_audio_t": 8, "audio_latent": torch.full((1, 1, 8), value)}


# --- the identity itself --------------------------------------------------


def test_no_blocks_has_no_digest():
    assert refmod_digest(None) == ""
    assert refmod_digest([]) == ""


def test_the_digest_is_stable_across_calls():
    blocks = [_block()]
    assert refmod_digest(blocks) == refmod_digest([_block()])


def test_a_different_latent_changes_the_digest():
    # The whole point: two mods differ in their latent, and only their latent.
    assert refmod_digest([_block(0.5)]) != refmod_digest([_block(0.9)])


def test_a_different_pooled_shape_changes_the_digest():
    assert refmod_digest([_block()]) != refmod_digest([_block(latent_h=8)])


def test_a_different_kind_changes_the_digest():
    assert refmod_digest([_block()]) != refmod_digest([_block(kind="video")])


def test_block_order_matters():
    # Blocks are positional downstream (the step curve indexes them), so swapping
    # the order of two mods is a different generation.
    a, b = _block(0.2), _block(0.8)
    assert refmod_digest([a, b]) != refmod_digest([b, a])


def test_audio_blocks_are_covered():
    # Audio bundles carry audio_latent instead of latent.
    assert refmod_digest([_audio_block(0.25)]) != refmod_digest([_audio_block(0.75)])
    assert refmod_digest([_audio_block()]) != ""


def test_non_dict_entries_are_ignored():
    assert refmod_digest(["nonsense", None, _block()]) == refmod_digest([_block()])


def test_a_non_tensor_latent_still_yields_a_shape_digest():
    # Nothing to hash, but the shape alone still distinguishes most mods, and a
    # blank digest would silently disable invalidation.
    bare = {"kind": "image", "latent_h": 4, "latent_w": 6, "latent": "not-a-tensor"}
    assert refmod_digest([bare]) != ""
    assert refmod_digest([bare]) != refmod_digest([_block()])


def test_hashing_failure_is_loud_rather_than_silently_blank(monkeypatch, capsys):
    def _boom(self):
        raise RuntimeError("cannot materialise")

    monkeypatch.setattr(torch.Tensor, "numpy", _boom)

    result = refmod_digest([_block()])

    assert result == "unavailable", (
        "a failure must not return '' - a blank digest would look identical to "
        "'no RefMod connected' and reuse another mod's cache"
    )
    assert "could not fingerprint" in capsys.readouterr().out


# --- the caches must key on it --------------------------------------------


def _seg(index: int, prompt: str) -> SegmentPlan:
    return SegmentPlan(
        index=index, start_frame=index * 4, end_frame=index * 4 + 4,
        prompt=prompt, task_type="rv2v", task_key="rv2v", use_global=True,
    )


def _plan(digest: str) -> DirectorPlan:
    segs = [_seg(0, "alpha")]
    return DirectorPlan(
        frame_rate=24.0, total_frames=4, width=64, height=64,
        ref_max_size=64, output_mode="fixed", source_width=64, source_height=64,
        global_task_type="rv2v", global_task_key="rv2v", global_prompt="",
        global_refs=[], segments=segs,
        source_video=torch.zeros((1, 3, 8, 8)), edit_mode="segment", raw={},
        refmod_digest=digest,
    )


def test_a_swapped_mod_changes_the_segment_cache_fingerprint():
    """The regression: swapping the mod must not reuse the previous mod's latents."""
    seg = _seg(0, "alpha")
    before = segment_cache_fingerprint(seg, _plan("aaaa1111"))
    after = segment_cache_fingerprint(seg, _plan("bbbb2222"))

    assert before != after
    assert before["refmod_digest"] == "aaaa1111"
    assert after["refmod_digest"] == "bbbb2222"


def test_the_same_mod_keeps_the_fingerprint():
    # The flip side: re-running an unchanged project must still hit the cache.
    seg = _seg(0, "alpha")
    assert segment_cache_fingerprint(seg, _plan("aaaa1111")) == \
        segment_cache_fingerprint(seg, _plan("aaaa1111"))


def test_no_refmod_leaves_the_fingerprint_untouched():
    # The key appearing at all is the change, so a project with no RefMod must not
    # invalidate its existing caches just because the field now exists.
    seg = _seg(0, "alpha")
    assert "refmod_digest" not in segment_cache_fingerprint(seg, _plan(""))
    assert "refmod_digest" not in generation_environment_identity(_plan(""), {})


def test_the_generation_environment_carries_the_digest():
    # The motion-context cache digests the environment, so a swapped mod has to
    # invalidate cached context too - not just the per-segment cache.
    before = generation_environment_identity(_plan("aaaa1111"), {})
    after = generation_environment_identity(_plan("bbbb2222"), {})

    assert before["refmod_digest"] == "aaaa1111"
    assert before != after
