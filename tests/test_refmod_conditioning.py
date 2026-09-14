"""RefMod reference plumbing for the Director node.

``Apply H3 RefMod`` (ComfyUI-MiniMaxH3Mod) appends its reference latents to
``minimax_refs`` - the same key the official ReferenceToVideo node fills - so a
connected CONDITIONING can contribute references to the Director.

The Director builds its own per-segment conditioning, so only that reference
payload is usable: the connected prompt and target latent were built for a
different prompt and frame size and are discarded. These tests pin the harvest /
append contract, including the ordering that RefMod's step curve depends on
(it indexes ``cond_video_latents`` positionally: keyframes first, then refs in
``minimax_refs`` order).
"""

from __future__ import annotations

import pytest

from mmx_pkg.nodes.conditioning import (
    append_refmod_references,
    harvest_refmod_refs,
)


def _entry(metadata=None, tensor=None, extra=None):
    """A native ComfyUI conditioning entry: [tensor, metadata, *extra]."""
    parts = [tensor if tensor is not None else "tex", dict(metadata or {})]
    if extra:
        parts.extend(extra)
    return parts


def _refmod_block(name="alice", latent="latent_tensor"):
    return {"refmod": True, "name": name, "latent": latent}


def native_ref(name="native"):
    return {"name": name, "latent": "native_latent_tensor"}


# --- harvest ---------------------------------------------------------------


def test_harvest_empty_inputs():
    assert harvest_refmod_refs(None) == []
    assert harvest_refmod_refs([]) == []


def test_harvest_collects_refmod_blocks():
    conditioning = [
        _entry({"minimax_refs": [native_ref(), _refmod_block()]}),
    ]

    blocks = harvest_refmod_refs(conditioning)

    assert len(blocks) == 2
    assert blocks[0]["name"] == "native"
    assert blocks[1]["refmod"] is True
    assert blocks[1]["name"] == "alice"


def test_harvest_reads_every_entry():
    conditioning = [
        _entry({"minimax_refs": [_refmod_block("a")]}),
        _entry({"minimax_refs": [_refmod_block("b")]}),
    ]

    assert [b["name"] for b in harvest_refmod_refs(conditioning)] == ["a", "b"]


def test_harvest_skips_malformed_and_handles_missing_key():
    conditioning = [
        _entry({}),  # no minimax_refs at all
        _entry({"minimax_refs": ["not-a-dict", None, _refmod_block("kept")]}),
        "not-an-entry",
        [],
    ]

    blocks = harvest_refmod_refs(conditioning)

    assert [b["name"] for b in blocks] == ["kept"]


def test_harvest_returns_copies():
    """The same list is handed to every segment; callers must not alias it."""
    source = _refmod_block()
    conditioning = [_entry({"minimax_refs": [source]})]

    blocks = harvest_refmod_refs(conditioning)
    blocks[0]["name"] = "mutated"
    blocks.append(_refmod_block("extra"))

    assert source["name"] == "alice"
    assert len(conditioning[0][1]["minimax_refs"]) == 1


def test_harvest_rejects_a_non_native_conditioning():
    """The sibling pack's conditioning object is not a ref-block container."""
    with pytest.raises(ValueError, match="native ComfyUI CONDITIONING"):
        harvest_refmod_refs("MINIMAX_H3_COND-object")


# --- append ----------------------------------------------------------------


def test_append_is_a_noop_without_blocks():
    conditioning = [_entry({"minimax_refs": [native_ref()]})]

    assert append_refmod_references(conditioning, []) is conditioning
    assert append_refmod_references(conditioning, None) is conditioning


def test_append_puts_refmod_blocks_after_native_refs():
    """RefMod's step curve walks cond_video_latents positionally in refs order."""
    conditioning = [_entry({"minimax_refs": [native_ref("one"), native_ref("two")]})]

    merged = append_refmod_references(conditioning, [_refmod_block("mod")])
    names = [ref["name"] for ref in merged[0][1]["minimax_refs"]]

    assert names == ["one", "two", "mod"], "native refs must stay first"


def test_append_applies_to_every_entry():
    conditioning = [
        _entry({"minimax_refs": [native_ref()]}),
        _entry({"minimax_refs": []}),
    ]

    merged = append_refmod_references(conditioning, [_refmod_block()])

    assert len(merged[0][1]["minimax_refs"]) == 2
    assert len(merged[1][1]["minimax_refs"]) == 1


def test_append_preserves_other_metadata_and_extra_elements():
    conditioning = [_entry({"minimax_refs": [], "minimax_frame_count": 5}, extra=["tail"])]

    merged = append_refmod_references(conditioning, [_refmod_block()])

    assert merged[0][1]["minimax_frame_count"] == 5
    assert merged[0][2] == "tail"
    assert merged[0][0] == "tex"


def test_append_does_not_share_block_dicts_between_entries():
    """A future in-place edit on one segment must not leak into the others."""
    conditioning = [_entry({}), _entry({})]

    merged = append_refmod_references(conditioning, [_refmod_block()])
    merged[0][1]["minimax_refs"][0]["name"] = "edited"

    assert merged[1][1]["minimax_refs"][0]["name"] == "alice"


def test_append_does_not_mutate_the_input_conditioning():
    original = _entry({"minimax_refs": [native_ref()]})
    conditioning = [original]

    append_refmod_references(conditioning, [_refmod_block()])

    assert original[1]["minimax_refs"] == [native_ref()]
    assert len(conditioning[0][1]["minimax_refs"]) == 1


def test_append_rejects_invalid_shapes():
    with pytest.raises(ValueError, match="non-empty positive conditioning"):
        append_refmod_references([], [_refmod_block()])
    with pytest.raises(ValueError, match="invalid shape"):
        append_refmod_references(["not-an-entry"], [_refmod_block()])


# --- round trip ------------------------------------------------------------


def test_harvest_then_append_round_trip():
    """The Director's real flow: harvest once, append to each segment."""
    connected = [
        _entry({"minimax_refs": [_refmod_block("hero")]}, tensor="refmod_prompt_embed"),
    ]
    blocks = harvest_refmod_refs(connected)

    segment_conditioning = [
        _entry({"minimax_refs": [native_ref("segment_ref")]}, tensor="segment_prompt_embed")
    ]
    merged = append_refmod_references(segment_conditioning, blocks)

    refs = merged[0][1]["minimax_refs"]
    assert [r["name"] for r in refs] == ["segment_ref", "hero"]
    # The Director keeps its own prompt embedding, not the connected one.
    assert merged[0][0] == "segment_prompt_embed"
