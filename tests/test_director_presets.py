"""Named Director presets: storage, validation and the filesystem boundary.

A preset is a settings blob (sampling / continuity / output widget groups plus the
shared reference block). It deliberately never contains segments or prompts, and the
browser never writes the index - the store does, atomically.

These tests pin the behaviour that would otherwise corrupt a user's preset library:
JSON-only payloads, ids that cannot escape the index directory, partial updates that
do not clobber untouched fields, and a corrupt index that fails loudly instead of
being silently replaced by an empty one.
"""

from __future__ import annotations

import json

import pytest

import folder_paths

from mmx_pkg.director.director_presets import (
    DirectorPresetError,
    DirectorPresetStore,
    presets_index_path,
    presets_root,
)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """A store rooted in a temp dir, so tests never touch the real user directory."""
    monkeypatch.setattr(folder_paths, "get_user_directory", lambda: str(tmp_path))
    return DirectorPresetStore()


def _payload(**overrides):
    base = {"steps": 14, "width": 960, "height": 544, "r2vCommon": {"refs": []}}
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


def test_save_then_read_round_trips_the_payload(store):
    saved = store.save_preset(name="Show standard", payload=_payload(), description="960x544")
    assert saved["name"] == "Show standard"
    assert saved["description"] == "960x544"
    assert saved["payload"] == _payload()
    assert saved["created_at"] > 0 and saved["updated_at"] > 0

    fetched = store.get_preset(saved["id"])
    assert fetched["payload"] == _payload()
    assert fetched["id"] == saved["id"]


def test_list_returns_metadata_only_and_newest_first(store):
    first = store.save_preset(name="Older", payload=_payload(steps=10))
    second = store.save_preset(name="Newer", payload=_payload(steps=20))

    listed = store.list_presets()
    assert [item["name"] for item in listed] == ["Newer", "Older"]
    # The list view must not ship every payload to the browser.
    assert all("payload" not in item for item in listed)
    assert {item["id"] for item in listed} == {first["id"], second["id"]}


def test_index_is_written_atomically_and_is_valid_json(store):
    store.save_preset(name="A", payload=_payload())
    path = presets_index_path()
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert len(data["presets"]) == 1
    # The temp file used for the atomic swap must not be left behind.
    assert not path.with_suffix(".json.tmp").exists()


def test_ids_are_unique_across_saves(store):
    ids = {store.save_preset(name=f"P{i}", payload=_payload())["id"] for i in range(10)}
    assert len(ids) == 10


# ---------------------------------------------------------------------------
# Payload validation
# ---------------------------------------------------------------------------


def test_payload_is_detached_from_the_caller(store):
    payload = _payload()
    saved = store.save_preset(name="Detached", payload=payload)
    # Mutating the caller's object afterwards must not reach stored state.
    payload["steps"] = 999
    payload["r2vCommon"]["refs"].append({"imageFile": "sneaky.png"})
    assert store.get_preset(saved["id"])["payload"] == _payload()


def test_payload_must_be_a_json_object(store):
    for bad in ([1, 2, 3], "steps", 14, True):
        with pytest.raises(DirectorPresetError):
            store.save_preset(name="Bad", payload=bad)


def test_non_finite_numbers_are_rejected(store):
    # NaN/Infinity are not valid JSON and would corrupt the index on write.
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(DirectorPresetError):
            store.save_preset(name="Bad", payload={"steps": bad})


def test_unserializable_payload_is_rejected(store):
    with pytest.raises(DirectorPresetError):
        store.save_preset(name="Bad", payload={"cb": object()})


def test_oversized_payload_is_rejected(store):
    with pytest.raises(DirectorPresetError) as excinfo:
        store.save_preset(name="Huge", payload={"blob": "x" * (300 * 1024)})
    assert "too large" in str(excinfo.value)


def test_empty_payload_is_allowed(store):
    # "Apply the sampling settings only" is a legitimate preset.
    saved = store.save_preset(name="Minimal", payload=None)
    assert store.get_preset(saved["id"])["payload"] == {}


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------


def test_name_is_required(store):
    for bad in (None, "", "   ", "\x00"):
        with pytest.raises(DirectorPresetError):
            store.save_preset(name=bad, payload=_payload())


def test_name_is_trimmed_truncated_and_null_stripped(store):
    saved = store.save_preset(name="  padded\x00" + "y" * 200 + "  ", payload=_payload())
    assert "\x00" not in saved["name"], "control characters must be stripped"
    assert saved["name"] == saved["name"].strip(), "outer whitespace must be trimmed"
    assert saved["name"].startswith("paddedy")
    assert len(saved["name"]) == 80


def test_duplicate_names_are_allowed(store):
    # Two presets may legitimately share a name; ids keep them distinct.
    a = store.save_preset(name="Same", payload=_payload(steps=1))
    b = store.save_preset(name="Same", payload=_payload(steps=2))
    assert a["id"] != b["id"]
    assert len(store.list_presets()) == 2


# ---------------------------------------------------------------------------
# Updates are partial
# ---------------------------------------------------------------------------


def test_renaming_does_not_touch_the_payload(store):
    saved = store.save_preset(name="Before", payload=_payload(steps=33))
    updated = store.update_preset(saved["id"], name="After")
    assert updated["name"] == "After"
    assert updated["payload"] == _payload(steps=33), "rename must not wipe the payload"


def test_updating_the_payload_does_not_touch_the_name(store):
    saved = store.save_preset(name="Keep me", payload=_payload(steps=1))
    updated = store.update_preset(saved["id"], payload=_payload(steps=2))
    assert updated["name"] == "Keep me"
    assert updated["payload"]["steps"] == 2


def test_empty_description_clears_it(store):
    saved = store.save_preset(name="P", payload=_payload(), description="old")
    assert store.update_preset(saved["id"], description="")["description"] == ""


def test_blank_rename_keeps_the_previous_name(store):
    saved = store.save_preset(name="Sticky", payload=_payload())
    assert store.update_preset(saved["id"], name="")["name"] == "Sticky"


def test_updated_at_advances_but_created_at_does_not(store):
    saved = store.save_preset(name="P", payload=_payload())
    updated = store.update_preset(saved["id"], name="P2")
    assert updated["created_at"] == saved["created_at"]
    assert updated["updated_at"] >= saved["updated_at"]


def test_update_unknown_id_is_not_found(store):
    with pytest.raises(DirectorPresetError) as excinfo:
        store.update_preset("0123456789abcdef", name="Nope")
    assert "not found" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def test_delete_removes_only_the_target(store):
    keep = store.save_preset(name="Keep", payload=_payload())
    drop = store.save_preset(name="Drop", payload=_payload())
    assert store.delete_preset(drop["id"]) == drop["id"]
    assert [item["id"] for item in store.list_presets()] == [keep["id"]]
    with pytest.raises(DirectorPresetError):
        store.get_preset(drop["id"])


def test_delete_unknown_id_is_not_found(store):
    with pytest.raises(DirectorPresetError) as excinfo:
        store.delete_preset("0123456789abcdef")
    assert "not found" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# The filesystem boundary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_id",
    [
        "../../etc/passwd",
        "..",
        "../sibling",
        "a/b",
        "a\\b",
        "preset.json",
        "",
        "   ",
        "x" * 65,
        "id with spaces",
        "id;rm -rf",
        "\x00",
    ],
)
def test_traversal_and_malformed_ids_are_rejected(store, bad_id):
    for call in (
        lambda: store.get_preset(bad_id),
        lambda: store.delete_preset(bad_id),
        lambda: store.update_preset(bad_id, name="X"),
    ):
        with pytest.raises(DirectorPresetError):
            call()


def test_everything_stays_inside_the_preset_root(store, tmp_path):
    saved = store.save_preset(name="Contained", payload=_payload())
    store.get_preset(saved["id"])
    index = presets_index_path().resolve()
    assert index.parent == presets_root().resolve()
    assert str(index).startswith(str(tmp_path.resolve()))
    # Nothing was created anywhere else in the user directory.
    assert [p.name for p in tmp_path.iterdir()] == ["minimax_h3_motion_director"]


# ---------------------------------------------------------------------------
# Corrupt / hostile index
# ---------------------------------------------------------------------------


def test_corrupt_index_fails_loudly_instead_of_resetting(store):
    store.save_preset(name="First", payload=_payload())
    presets_index_path().write_text("{not json", encoding="utf-8")

    with pytest.raises(DirectorPresetError) as excinfo:
        store.list_presets()
    # The message must name the file, or the user cannot recover.
    assert str(presets_index_path()) in str(excinfo.value)

    # Saving must also refuse, rather than overwrite a file it cannot read.
    with pytest.raises(DirectorPresetError):
        store.save_preset(name="Second", payload=_payload())
    assert presets_index_path().read_text(encoding="utf-8") == "{not json"


def test_index_with_wrong_shape_fails_loudly(store):
    presets_root().mkdir(parents=True, exist_ok=True)
    presets_index_path().write_text(json.dumps({"presets": "nope"}), encoding="utf-8")
    with pytest.raises(DirectorPresetError):
        store.list_presets()


def test_non_dict_entries_are_skipped_not_fatal(store):
    store.save_preset(name="Good", payload=_payload())
    path = presets_index_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["presets"].append("garbage")
    data["presets"].append(42)
    path.write_text(json.dumps(data), encoding="utf-8")

    assert [item["name"] for item in store.list_presets()] == ["Good"]


def test_missing_index_reads_as_empty(store):
    assert store.list_presets() == []
    assert not presets_index_path().exists()


def test_preset_limit_is_enforced(store, monkeypatch):
    import mmx_pkg.director.director_presets as module

    monkeypatch.setattr(module, "_MAX_PRESETS", 2)
    store.save_preset(name="A", payload=_payload())
    store.save_preset(name="B", payload=_payload())
    with pytest.raises(DirectorPresetError) as excinfo:
        store.save_preset(name="C", payload=_payload())
    assert "limit" in str(excinfo.value).lower()
    assert len(store.list_presets()) == 2
