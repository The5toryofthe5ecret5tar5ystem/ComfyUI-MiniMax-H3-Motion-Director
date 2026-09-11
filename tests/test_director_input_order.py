"""Freeze the Director node's input order before anyone restructures it.

This is the precondition item 6 (collapsing the widget surface) asks for: *freeze the
indices; add/remove only at the end, and assert the mapping in a test first*.

Why it matters: the node's custom frontend reads its own state positionally in places
(``widgets_values[N]``) and mirrors ``timeline_data`` across three sites. Inserting or
removing an entry in the middle shifts every later position, so a saved workflow silently
rehydrates the wrong values. Adding at the end, or changing a default in place, is safe.

The order below was extracted from the live ``/object_info`` response, not transcribed by
hand, and it is the *declaration* order (required, then optional). Note it is not the same
as the runtime ``widgets_values`` positions: ``model``/``video_vae``/``audio_vae``/``clip``/
``sampler``/``sigmas``/``director_inputs`` are connection or custom inputs, not widgets, so
positions diverge once ComfyUI converts inputs to widgets.

Also worth knowing: `docs/ROADMAP_UX.md` and older notes referred to ``timeline_data`` as
``widgets_values[11]``. It is index **14** of the declaration order today. That drift is
precisely what this test exists to surface.
"""

from __future__ import annotations

import pytest

# (group, name) in declaration order - required block first, then optional.
# EXTRACTED from MiniMaxH3MotionDirector.INPUT_TYPES(), not transcribed by hand.
#
# NOTE the served view differs by two entries: GET /object_info drops `i2v_groups` and
# `r2v_groups` (popped in nodes/director_inputs.py) because they are internal group inputs
# the Mixed path consumes, and it exposes `director_inputs`, which INPUT_TYPES() does not
# list here. Also note `mmx_postprocess_group` is not declared at all - the frontend
# postprocess UI adds it.
EXPECTED_INPUT_ORDER: list[tuple[str, str]] = [
    ("required", "model"),
    ("required", "video_vae"),
    ("required", "audio_vae"),
    ("required", "clip"),
    ("required", "task_type"),
    ("required", "global_prompt"),
    ("required", "bd_grp_sample"),
    ("required", "cfg"),
    ("required", "seed"),
    ("required", "frame_rate"),
    ("required", "width"),
    ("required", "height"),
    ("required", "ref_max_size"),
    ("required", "total_frames"),
    ("required", "timeline_data"),
    ("optional", "i2v_groups"),
    ("optional", "r2v_groups"),
    ("optional", "bd_grp_motion"),
    ("optional", "motion_context_enabled"),
    ("optional", "context_length"),
    ("optional", "source_overlap_frames"),
    ("optional", "audio_context_enabled"),
    ("optional", "color_reanchor_enabled"),
    ("optional", "bd_grp_advanced"),
    ("optional", "steps"),
    ("optional", "sampler_name"),
    ("optional", "scheduler"),
    ("optional", "shift_video"),
    ("optional", "shift_audio"),
    ("optional", "sampler"),
    ("optional", "sigmas"),
    ("optional", "bd_grp_perf"),
    ("optional", "clear_vram_between_segments"),
    ("optional", "export_source_images"),
    ("optional", "bd_grp_experimental"),
    ("optional", "pin_renorm_enabled"),
    ("optional", "postprocess_config"),
    ("optional", "bd_grp_audio_refine"),
    ("optional", "audio_refine_enabled"),
    ("optional", "audio_refine_steps"),
    ("optional", "audio_refine_denoise"),
]

# Section headers the frontend actively collapses (minimax_director_sections_core.mjs).
MANAGED_SECTIONS = {"bd_grp_sample", "bd_grp_motion", "mmx_postprocess_group", "bd_grp_perf"}

# Group headers declared in INPUT_TYPES. `mmx_postprocess_group` is added by the frontend
# postprocess UI rather than declared here, so it is absent from this list.
DECLARED_GROUP_HEADERS = [
    "bd_grp_sample",
    "bd_grp_motion",
    "bd_grp_advanced",
    "bd_grp_perf",
    "bd_grp_experimental",
    "bd_grp_audio_refine",
]


def _declared_order() -> list[tuple[str, str]]:
    """The node's input order as it would be reported to the frontend."""
    from mmx_pkg.nodes.director import MiniMaxH3MotionDirector

    spec = MiniMaxH3MotionDirector.INPUT_TYPES()
    order: list[tuple[str, str]] = []
    for group in ("required", "optional"):
        for name in spec.get(group, {}):
            order.append((group, name))
    return order


def test_input_order_matches_the_frozen_mapping():
    actual = _declared_order()
    expected_names = [name for _group, name in EXPECTED_INPUT_ORDER]
    actual_names = [name for _name_group, name in ((g, n) for g, n in actual)]
    assert actual_names == expected_names, (
        "The Director node's input order changed.\n"
        f"  expected: {expected_names}\n"
        f"  actual:   {actual_names}\n"
        "Inputs are read positionally in places (widgets_values[N]) and timeline_data is "
        "mirrored across three sites, so inserting or removing a mid-list entry shifts "
        "every later position and silently rehydrates saved workflows with wrong values. "
        "Add new inputs at the END of their block, or update this table as a deliberate "
        "act with a migration for existing workflows."
    )


def test_required_and_optional_blocks_are_unchanged():
    actual = _declared_order()
    assert [group for group, _name in actual] == [group for group, _name in EXPECTED_INPUT_ORDER], (
        "An input moved between the required and optional blocks. That changes where it "
        "sits in widgets_values just as much as reordering does."
    )


# Pinned declaration indices of the section headers. A header that moves changes which
# widgets it visually owns.
EXPECTED_GROUP_INDEX = {
    "bd_grp_sample": 6,
    "bd_grp_motion": 17,
    "bd_grp_advanced": 23,
    "bd_grp_perf": 31,
    "bd_grp_experimental": 34,
    "bd_grp_audio_refine": 37,
}


def test_group_header_positions_are_stable():
    names = [name for _group, name in _declared_order()]
    actual = {name: names.index(name) for name in EXPECTED_GROUP_INDEX}
    assert actual == EXPECTED_GROUP_INDEX, (
        "Section header positions moved; each header must stay immediately above the "
        "widgets it groups.\n"
        f"  expected: {EXPECTED_GROUP_INDEX}\n"
        f"  actual:   {actual}"
    )


def test_every_declared_group_header_is_accounted_for():
    """A group header nobody manages is a header with no collapse behaviour.

    This is the item-6 gap: the sections module manages four sections, and
    `bd_grp_advanced` / `bd_grp_experimental` are handled by the sampling UI because the
    sampling source toggles them. `bd_grp_audio_refine` is referenced by **no** frontend
    module, so its three widgets are always visible and cannot be collapsed.

    Pinned rather than fixed: adding it to the section system changes the default surface
    (its widgets would start collapsed), which needs browser verification.
    """
    declared = set(DECLARED_GROUP_HEADERS)
    unmanaged = declared - MANAGED_SECTIONS - {"bd_grp_advanced", "bd_grp_experimental"}
    assert unmanaged == {"bd_grp_audio_refine"}, (
        "The set of group headers with no frontend owner changed.\n"
        f"  unmanaged now: {sorted(unmanaged)}\n"
        "If you just added a header, wire it into a section or hide it. If you wired one "
        "up, remove it from this expectation deliberately."
    )


@pytest.mark.parametrize("name", DECLARED_GROUP_HEADERS)
def test_group_headers_are_declared_as_bdgroup(name: str):
    """Group headers must stay BDGROUP-typed, not become real widgets."""
    from mmx_pkg.nodes.director import MiniMaxH3MotionDirector

    spec = MiniMaxH3MotionDirector.INPUT_TYPES()
    entry = None
    for group in ("required", "optional"):
        if name in spec.get(group, {}):
            entry = spec[group][name]
            break
    assert entry is not None, f"{name} is no longer declared"
    assert entry[0] == "BDGROUP", f"{name} is typed {entry[0]!r}, expected 'BDGROUP'"
