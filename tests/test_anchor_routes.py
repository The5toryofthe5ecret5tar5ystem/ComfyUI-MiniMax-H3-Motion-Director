"""Anchor strip routes: registration table, disk scanning, actions, preflight.

The executor writes the anchor PNGs (`director/anchor_ladder.py`); these routes
are what the strip UI reads and mutates them through. Pinned here:

* the exact method/path table (the frontend's ``fetchApi`` literals are matched
  against it by ``scripts/qa_readiness.py``),
* that listing tolerates missing/unreadable cache directories and ignores
  unrelated files,
* that approve/reject only touch sidecars, delete/clear only remove PNGs+JSON,
* that the preflight numbers are computed from the timeline, not from disk.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path

import pytest

# `folder_paths` is a ComfyUI core module. The suite normally runs with ComfyUI
# on PYTHONPATH; stub it when it is absent so route import never fails.
try:  # pragma: no cover - environment dependent
    import folder_paths as _folder_paths  # noqa: F401
except Exception:  # noqa: BLE001
    _stub = types.ModuleType("folder_paths")
    _stub.get_output_directory = lambda: "/tmp/mmx-anchor-test-output"  # type: ignore[attr-defined]
    sys.modules["folder_paths"] = _stub

from mmx_pkg.director import anchor_ladder
from mmx_pkg.director.anchor_routes import (  # noqa: E402
    BASE,
    anchors_action,
    anchors_list,
    anchors_plan,
    anchors_plan_route,
    register_anchor_routes,
)

ANCHOR_DIR = Path("minimax_seg_cache") / "42" / "anchors"


class _RouteTable:
    """Modern table: exposes add_route(method, path, handler)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def add_route(self, method, path, handler):
        self.calls.append((method, path))


class _DecoratorTable:
    """Older table: only per-method decorator factories."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def _make(self, method):
        def factory(path):
            def decorate(handler):
                self.calls.append((method, path))
                return handler

            return decorate

        return factory

    def __getattr__(self, name):
        if name in {"get", "post", "patch", "delete"}:
            return self._make(name.upper())
        raise AttributeError(name)


class _QueryRequest:
    def __init__(self, **query):
        self.query = query


class _JsonRequest:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def _payload(response) -> dict:
    return json.loads(response.text)


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #
def test_anchor_routes_registered_on_both_table_shapes():
    for table in (_RouteTable(), _DecoratorTable()):
        register_anchor_routes(table)
        assert table.calls == [
            ("GET", BASE),
            ("POST", BASE + "/action"),
            ("POST", BASE + "/plan"),
        ]


def test_frontend_literals_match_registered_paths():
    """qa_readiness.ct_routes segment-matches these; keep the shapes stable."""
    table = _RouteTable()
    register_anchor_routes(table)
    frontend = [
        "/minimax/motion-director/anchors?node_id=42",
        "/minimax/motion-director/anchors/action",
        "/minimax/motion-director/anchors/plan",
    ]
    for path in frontend:
        clean = path.split("?")[0]
        assert any(
            clean.strip("/").startswith(route.strip("/")) or route.strip("/").startswith(clean.strip("/"))
            for _, route in table.calls
        ), path


# --------------------------------------------------------------------------- #
# disk listing
# --------------------------------------------------------------------------- #
def _seed_anchor(root: Path, index: int, seed: int, *, status: str = "ready",
                 variant: int = 1, frames: int = 22, beat: str = "holds") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    png = root / anchor_ladder.anchor_file_name(index, seed, variant=variant, chunk_frames=frames)
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    item = anchor_ladder.AnchorItem(
        index=index, seed=seed, beat=beat, chunk_frames=frames, variant=variant, path=str(png)
    )
    anchor_ladder.write_sidecar(png, item, status=status)
    return png


@pytest.fixture()
def anchor_dir(tmp_path, monkeypatch):
    out = tmp_path / "output"
    out.mkdir()
    monkeypatch.setattr(
        "mmx_pkg.director.anchor_routes.folder_paths.get_output_directory", lambda: str(out)
    )
    root = out / ANCHOR_DIR
    return root


def test_list_reports_items_sidecar_status_and_view_urls(anchor_dir):
    _seed_anchor(anchor_dir, 0, 4242, status="approved", beat="opens")
    _seed_anchor(anchor_dir, 1, 4243)
    (anchor_dir / "notes.txt").write_text("ignore me", encoding="utf-8")
    (anchor_dir / "A99_s1_v1_f22.json").write_text("{}", encoding="utf-8")  # orphan sidecar

    data = _payload(_run(anchors_list(_QueryRequest(node_id="42"))))

    assert data["ok"] is True
    assert data["available"] is True
    assert [item["index"] for item in data["items"]] == [0, 1]
    assert data["counts"] == {"items": 2, "boundaries": 2, "approved": 1, "rejected": 0}
    first = data["items"][0]
    assert first["status"] == "approved"
    assert first["beat"] == "opens"
    assert first["chunkFrames"] == 22
    assert first["fileName" if "fileName" in first else "file"] == "A00_s4242_v1_f22.png"
    assert first["url"].startswith("/view?")
    assert "type=output" in first["url"]
    assert "subfolder=minimax_seg_cache%2F42%2Fanchors" in first["url"]


def test_list_tolerates_missing_directory(anchor_dir):
    data = _payload(_run(anchors_list(_QueryRequest(node_id="42"))))
    assert data["ok"] is True
    assert data["available"] is False
    assert data["items"] == []


# --------------------------------------------------------------------------- #
# actions
# --------------------------------------------------------------------------- #
def test_approve_and_reject_only_rewrite_the_sidecar(anchor_dir):
    png = _seed_anchor(anchor_dir, 0, 4242)
    before = png.stat().st_mtime_ns

    data = _payload(_run(anchors_action(_JsonRequest({"node_id": "42", "action": "approve", "index": 0}))))
    assert data["sidecarsWritten"] == 1
    assert data["items"][0]["status"] == "approved"
    assert json.loads(Path(str(png) + ".json").read_text())["status"] == "approved"
    assert png.stat().st_mtime_ns == before  # PNG untouched

    data = _payload(_run(anchors_action(_JsonRequest({"node_id": "42", "action": "reject", "index": 0}))))
    assert data["items"][0]["status"] == "rejected"
    assert data["items"][0]["rejected"] is True


def test_action_validation_errors(anchor_dir):
    _seed_anchor(anchor_dir, 0, 4242)

    unknown = _run(anchors_action(_JsonRequest({"node_id": "42", "action": "explode"})))
    assert unknown.status == 400
    assert "Unknown action" in _payload(unknown)["error"]

    missing_index = _run(anchors_action(_JsonRequest({"node_id": "42", "action": "delete"})))
    assert missing_index.status == 400

    no_file = _run(anchors_action(_JsonRequest({"node_id": "42", "action": "approve", "index": 7})))
    assert no_file.status == 404
    assert "No rendered anchor" in _payload(no_file)["error"]


def test_delete_removes_every_seed_and_variant_of_one_boundary(anchor_dir):
    _seed_anchor(anchor_dir, 0, 4242)
    _seed_anchor(anchor_dir, 0, 9001, variant=2)
    _seed_anchor(anchor_dir, 1, 4243)

    data = _payload(_run(anchors_action(_JsonRequest({"node_id": "42", "action": "delete", "index": 0}))))

    assert [item["index"] for item in data["items"]] == [1]
    assert data["removed"] == 4  # two PNGs + two sidecars
    assert not list(anchor_dir.glob("A00_*"))


def test_clear_and_prune(anchor_dir):
    _seed_anchor(anchor_dir, 0, 4242)
    _seed_anchor(anchor_dir, 1, 4243)
    # Sidecars are named '<anchor>.png.json', so an orphan is a sidecar whose
    # PNG was deleted (by hand or by a crashed run).
    orphan = anchor_dir / "A77_s5_v1_f22.png.json"
    orphan.write_text("{}", encoding="utf-8")

    pruned = _payload(_run(anchors_action(_JsonRequest({"node_id": "42", "action": "prune"}))))
    assert pruned["removed"] == 1
    assert not orphan.exists()
    assert len(pruned["items"]) == 2

    cleared = _payload(_run(anchors_action(_JsonRequest({"node_id": "42", "action": "clear"}))))
    assert cleared["items"] == []
    assert cleared["removed"] == 4


# --------------------------------------------------------------------------- #
# preflight plan
# --------------------------------------------------------------------------- #
def _timeline(*lengths, anchors=None, context=False):
    segments = []
    for index, length in enumerate(lengths):
        seg = {"id": f"s{index}", "length": length, "refs": {"images": [{"file": "a.png"}]}}
        if context and index > 0:
            seg["contextLink"] = {"visual": True}
        segments.append(seg)
    timeline = {
        "global": {"refs": {"images": [{"file": "ref.png"}]}},
        "segments": segments,
    }
    if anchors is not None:
        timeline["anchors"] = anchors
    return timeline


def test_plan_is_off_without_an_anchors_block(anchor_dir):
    data = anchors_plan("42", _timeline(243, 243), width=1120, height=640)
    assert data["enabled"] is False
    assert data["mode"] == "off"
    assert data["boundaries"] == 3
    assert data["renders"] == 0
    # The worst-fill number is still reported so the strip can compare passes.
    assert data["worstFillFrames"] == 243
    assert data["worstFillWorkspaceGb"] > 0


def test_plan_reports_boundaries_missing_and_workspace(anchor_dir):
    _seed_anchor(anchor_dir, 0, 4242, status="approved")
    timeline = _timeline(
        243,
        175,
        243,
        anchors={"mode": "soft", "chunkFrames": 22, "beats": ["opens", "mid", "", "closes"]},
    )

    data = anchors_plan("42", timeline, width=1120, height=640, ref_long_edge=768)

    assert data["enabled"] is True
    assert data["mode"] == "soft"
    assert data["boundaries"] == 4
    assert data["renders"] == 4
    assert data["chunkFrames"] == 22
    assert data["missing"] == [1, 2, 3]
    assert data["boundariesOnDisk"] == 1
    assert data["approved"] == 1
    assert data["refPictures"] == 1
    assert data["anchorTokens"] > 0
    assert data["anchorWorkspaceGb"] > 0
    assert data["worstFillWorkspaceGb"] > data["anchorWorkspaceGb"]
    assert data["beats"][0] == "opens"


def test_plan_counts_context_rows_in_the_worst_fill(anchor_dir):
    plain = anchors_plan("42", _timeline(175), width=1120, height=640)
    linked = _timeline(175, anchors={"mode": "soft"})
    linked["segments"][0]["contextLink"] = {"visual": True}
    with_context = anchors_plan("42", linked, width=1120, height=640)
    assert with_context["worstFillFrames"] == 175 + 22
    assert plain["worstFillFrames"] == 175
    assert with_context["worstFillTokens"] > plain["worstFillTokens"]


def test_plan_uses_segment_anchor_prompt_for_beats(anchor_dir):
    """A segment's ``anchorPrompt`` is the pose it ENDS on (boundary i+1)."""
    timeline = _timeline(175, 175, anchors={"mode": "soft"})
    timeline["segments"][0]["anchorPrompt"] = "she turns toward the window"
    data = anchors_plan("42", timeline, width=640, height=384)
    assert data["boundaries"] == 3
    assert data["beats"][1] == "she turns toward the window"
    assert data["beats"][0] == ""  # boundary 0 is the opening pose (anchors.open)


def test_plan_previews_the_composed_prompt_for_every_boundary(anchor_dir):
    """The per-boundary prompt editor needs the text even while the ladder is off."""
    timeline = _timeline(175, 175, anchors={"mode": "off"})
    timeline["segments"][0]["prompt"] = (
        "summary:\nA.\ndetailed_description:\nShe lifts the cup and sets it down."
    )
    timeline["segments"][1]["prompt"] = (
        "summary:\nB.\ndetailed_description:\nShe reaches toward the lens."
    )

    data = anchors_plan("42", timeline, width=640, height=384)

    assert data["enabled"] is False          # off means off - only the preview is built
    previews = data["boundaryText"]
    assert len(previews) == 3
    middle = previews[1]
    assert middle["fromLabel"] == "Shot 1" and middle["toLabel"] == "Shot 2"
    assert "sets it down" in middle["fromTail"]
    assert "reaches toward the lens" in middle["toHead"]
    assert "sets it down" in middle["prompt"]          # composed, token-free
    assert "{from_tail}" in middle["body"]              # the editable body keeps them
    assert middle["bodyAuto"] == middle["body"]
    assert middle["override"] is False


def test_plan_preview_marks_a_per_boundary_override(anchor_dir):
    timeline = _timeline(175, anchors={"mode": "soft", "prompts": ["MINE {beat}"]})
    timeline["segments"][0]["prompt"] = "detailed_description:\nShe reaches."

    data = anchors_plan("42", timeline, width=640, height=384)

    first = data["boundaryText"][0]
    assert first["override"] is True
    assert first["body"] == "MINE {beat}"
    assert "MINE" not in first["bodyAuto"]
    assert data["promptSource"] == ""


def test_plan_route_accepts_string_and_object_payloads(anchor_dir):
    timeline = _timeline(175, anchors={"mode": "soft"})
    as_string = _payload(
        _run(anchors_plan_route(_JsonRequest({"node_id": "42", "timeline_data": json.dumps(timeline),
                                              "width": 1120, "height": 640})))
    )
    as_object = _payload(
        _run(anchors_plan_route(_JsonRequest({"node_id": "42", "timeline_data": timeline,
                                              "width": 1120, "height": 640})))
    )
    assert as_string["boundaries"] == as_object["boundaries"] == 2
    assert as_string["anchorTokens"] == as_object["anchorTokens"]

    broken = _run(anchors_plan_route(_JsonRequest({"node_id": "42", "timeline_data": "{oops"})))
    assert broken.status == 400
    assert "not valid JSON" in _payload(broken)["error"]
