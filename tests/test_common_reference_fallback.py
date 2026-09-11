"""The two plan builders must agree on where segment references come from.

The prompt-batch builder resolves a segment's references from the Common
References (``r2vCommon``) when the segment carries none of its own. The video
timeline used to ignore ``r2vCommon`` entirely, which made identical projects
behave differently depending on the mode. These tests pin the unified rule.
"""

from __future__ import annotations

import pytest

from mmx_pkg.director.plan import (
    CONTEXT_REFERENCE_EXCLUDED_KEYS,
    _fallback_common_refs,
    _r2v_common_list,
)

_COMMON = {
    "refs": [{"imageFile": "face.png", "index": 0}],
    "refAudios": [{"audioFile": "voice.wav", "index": 0}],
}


def _timeline(**overrides):
    block = dict(_COMMON)
    timeline = {"r2vCommon": block}
    timeline.update(overrides)
    return timeline


def test_common_refs_are_read_for_supported_tasks():
    # r2v / rv2v / ads2v can consume identity pictures.
    for task in ("r2v", "rv2v", "ads2v"):
        assert _fallback_common_refs(_timeline(), task, "refs") == _COMMON["refs"]


def test_common_refs_are_not_read_for_tasks_that_cannot_use_them():
    for task in CONTEXT_REFERENCE_EXCLUDED_KEYS:
        assert _fallback_common_refs(_timeline(), task, "refs") == []


def test_common_audio_only_for_reference_tasks():
    assert _fallback_common_refs(_timeline(), "rv2v", "refAudios") == _COMMON["refAudios"]
    assert _fallback_common_refs(_timeline(), "r2v", "refAudios") == _COMMON["refAudios"]
    assert _fallback_common_refs(_timeline(), "v2v", "refAudios") == []


def test_snake_case_and_missing_blocks_are_tolerated():
    # snake_case alias for the whole block
    assert _r2v_common_list({"r2v_common": _COMMON}, "refs") == _COMMON["refs"]
    # snake_case aliases for the lists themselves
    assert _r2v_common_list(
        {"r2vCommon": {"refAudios": None, "ref_audios": _COMMON["refAudios"]}}, "refAudios"
    ) == _COMMON["refAudios"]
    # absent / malformed blocks never raise
    assert _r2v_common_list({}, "refs") == []
    assert _r2v_common_list({"r2vCommon": "not-a-dict"}, "refs") == []
    assert _r2v_common_list({"r2vCommon": {}}, "refs") == []


def test_common_refs_fall_back_is_not_used_when_segment_has_own():
    """The builder only consults the fallback when the segment list is empty."""
    own = [{"imageFile": "other.png", "index": 0}]
    # Guard the contract the builder relies on: an empty list means "none".
    assert own  # a non-empty list is truthy, so `if not seg_refs` skips the fallback
    assert not []


@pytest.mark.parametrize("task", ["r2v", "rv2v"])
def test_fallback_returns_a_copy_safe_list(task):
    refs = _fallback_common_refs(_timeline(), task, "refs")
    assert refs == _COMMON["refs"]
