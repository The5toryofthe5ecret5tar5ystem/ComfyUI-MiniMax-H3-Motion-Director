"""The video timeline attaches the Common References the way every builder does.

The shared block is a *pool*, not a fallback. Picking one list or the other - the
segment's own if it had any, otherwise the whole shared block - silently dropped
the shared identity from every window that carried a reference of its own, and it
left the prompt's ``<Picture N>`` tags pointing at pictures the render never sent.
Both builders now run the same compile, so the tags, the exclusions, the render and
the enhancer's vision pass all agree on which picture is slot 1.

These tests call the real helpers (with real tensors) and pin the wiring, because
the timeline builder itself needs a source video to run.
"""

from __future__ import annotations

import base64
import io
import pathlib

import pytest
from PIL import Image

try:
    from mmx_pkg.director.plan import (
        REFERENCE_PICTURE_TASKS,
        _load_refs,
        merge_common_references,
        parse_refmod_enabled,
    )
    from mmx_pkg.director.effective_refs import resolve_semantic_tokens
    from mmx_pkg.nodes.conditioning import refmod_refs_for_segment
except ImportError as exc:  # pragma: no cover - environment guard
    pytest.skip(f"Director package unavailable: {exc}", allow_module_level=True)


def _png_b64() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 30)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _picture(asset_id: str, index: int = 0) -> dict:
    return {"index": index, "assetId": asset_id, "imageB64": _png_b64(), "imageFile": ""}


COMMON = {
    "refs": [_picture("common-a", 0), _picture("common-b", 1)],
    "refAudios": [],
    "refVideos": [],
}


def _merge(timeline=None, seg_data=None, task="rv2v", pictures=None):
    return merge_common_references(
        timeline if timeline is not None else {"r2vCommon": COMMON},
        seg_data if seg_data is not None else {},
        task,
        pictures=_load_refs(pictures if pictures is not None else [_picture("local-a", 0)]),
        audios=[],
    )


# --- the merge itself -------------------------------------------------------


def test_shared_pictures_come_first_then_the_segments_own():
    pictures, _audios, _videos, _video_audios, tags = _merge()

    assert [p.index for p in pictures] == [0, 1, 2], "renumbered densely from zero"
    assert tags[("picture", "common-a")] == "<Picture 1>"
    assert tags[("picture", "common-b")] == "<Picture 2>"
    assert tags[("picture", "local-a")] == "<Picture 3>", (
        "the window's own picture follows the shared ones, which is the numbering "
        "the mention picker writes into the prompt"
    )


def test_a_window_with_its_own_picture_still_gets_the_shared_ones():
    """The old rule dropped the block here - the bug this replaces."""
    pictures, *_ = _merge(pictures=[_picture("local-a", 0), _picture("local-b", 1)])
    assert len(pictures) == 4


def test_a_disabled_shared_asset_is_left_out_and_the_rest_renumber():
    pictures, _audios, _videos, _video_audios, tags = _merge(
        seg_data={"excludedCommonAssetIds": ["common-a"]}
    )
    assert [p.index for p in pictures] == [0, 1]
    assert ("picture", "common-a") not in tags
    assert tags[("picture", "common-b")] == "<Picture 1>"
    assert tags[("picture", "local-a")] == "<Picture 2>"


def test_use_common_assets_false_means_the_pool_not_the_segment():
    pictures, _audios, _videos, _video_audios, tags = _merge(
        seg_data={"useCommonAssets": False}
    )
    assert len(pictures) == 1
    assert tags == {("picture", "local-a"): "<Picture 1>"}


def test_the_official_picture_limit_is_enforced_with_a_usable_message():
    many = {"refs": [_picture(f"common-{i}", i) for i in range(9)], "refAudios": []}
    with pytest.raises(ValueError) as excinfo:
        _merge(timeline={"r2vCommon": many})
    message = str(excinfo.value)
    assert "Picture" in message and "at most" in message
    assert "Disable Common assets or remove Local assets" in message


def test_an_empty_pool_and_an_empty_segment_stay_empty():
    pictures, _audios, _videos, _video_audios, tags = _merge(
        timeline={"r2vCommon": {"refs": []}}, pictures=[]
    )
    assert pictures == [] and tags == {}


def test_the_task_set_matches_the_frontend():
    # Mirrors web/js/minimax_gen_timeline.js `taskUsesReferenceImages`.
    assert REFERENCE_PICTURE_TASKS == {"r2v", "r2i", "rv2v", "vrc2v", "vi2v"}


# --- per-segment RefMod switch ----------------------------------------------


@pytest.mark.parametrize(
    "seg_data,expected",
    [
        ({}, True),
        ({"refmodEnabled": True}, True),
        ({"refmodEnabled": False}, False),
        ({"refmod_enabled": False}, False),
        ({"refmod": {"enabled": False}}, False),
        ({"refmod": {"enabled": True}}, True),
        ({"refmod": "nonsense"}, True),
        (None, True),
    ],
)
def test_parse_refmod_enabled(seg_data, expected):
    assert parse_refmod_enabled(seg_data) is expected


class _Segment:
    def __init__(self, enabled=True):
        if enabled is not None:
            self.refmod_enabled = enabled


def test_refmod_refs_follow_the_segment_switch():
    blocks = [{"latent": "x"}]
    assert refmod_refs_for_segment(blocks, _Segment(True)) == blocks
    assert refmod_refs_for_segment(blocks, _Segment(False)) == []
    assert refmod_refs_for_segment(blocks, _Segment(None)) == blocks, "absent means on"
    assert refmod_refs_for_segment([], _Segment(True)) == []


def test_refmod_refs_are_copied_not_shared():
    blocks = [{"latent": "x"}]
    out = refmod_refs_for_segment(blocks, _Segment(True))
    assert out == blocks and out is not blocks


# --- semantic mentions on the timeline --------------------------------------


def test_semantic_tokens_resolve_when_the_segment_can_and_stay_otherwise():
    prompt = "She wears {{mmx-ref:picture:common-a}} and {{mmx-ref:picture:gone}}."
    out = resolve_semantic_tokens(prompt, {("picture", "common-a"): "<Picture 1>"})
    assert "<Picture 1>" in out
    assert "{{mmx-ref:picture:gone}}" in out, (
        "a mention that outlived its file must not kill the render - the prompt-batch "
        "builder raises, the timeline keeps it as written"
    )


# --- wiring -----------------------------------------------------------------


def test_the_timeline_loop_runs_the_merge_and_carries_the_result():
    import mmx_pkg.director.plan as plan

    text = pathlib.Path(plan.__file__).read_text(encoding="utf-8")
    assert "seg_task_key in REFERENCE_PICTURE_TASKS" in text, "the merge is task-gated"
    assert "= merge_common_references(" in text, "and it is the shared compile"
    assert "reference_tags=reference_tags," in text
    assert "refmod_enabled=parse_refmod_enabled(seg_data)," in text


def test_both_builders_carry_the_refmod_switch():
    from mmx_pkg.director import gen_timeline

    text = pathlib.Path(gen_timeline.__file__).read_text(encoding="utf-8")
    assert "refmod_enabled=parse_refmod_enabled(seg_data)," in text


def test_the_executor_filters_refmods_per_segment():
    from mmx_pkg.director import executor_core_legacy

    text = pathlib.Path(executor_core_legacy.__file__).read_text(encoding="utf-8")
    assert text.count("refmod_refs_for_segment(refmod_refs,") == 2, (
        "both conditioning sites - the segment and the Source Bridge - must honour "
        "the per-segment switch"
    )
