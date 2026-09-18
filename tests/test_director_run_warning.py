"""Live per-segment run warnings (director.progress).

Warnings used to be collected and only rendered into the final execution report,
so Character Replace degrading to plain rv2v stayed invisible until every
segment had already rendered - the user paid for the whole run before learning
it had done the wrong thing. These tests pin the live event the UI now listens
for, and the payload the banner and the segment marker read.
"""

from __future__ import annotations

import sys
import types

import pytest

from mmx_pkg.director.progress import report_director_warning


class _FakeServerInstance:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict, str | None]] = []
        self.client_id = "client-1"

    def send_sync(self, event, payload, client_id=None) -> None:  # noqa: ANN001
        self.sent.append((event, payload, client_id))


@pytest.fixture
def fake_server(monkeypatch):
    """Stand in for ComfyUI's ``server`` module, which is imported lazily."""
    instance = _FakeServerInstance()
    module = types.ModuleType("server")
    module.PromptServer = type("PromptServer", (), {"instance": instance})
    monkeypatch.setitem(sys.modules, "server", module)
    return instance


def test_noop_without_node_id(fake_server):
    # No node means no websocket to talk to; it must not reach for the server.
    report_director_warning(None, segment_index=0, code="replace_fallback")
    assert fake_server.sent == []


def test_emits_the_event_the_frontend_listens_for(fake_server):
    report_director_warning(
        "42",
        segment_index=2,
        timeline_segment_index=2,
        code="replace_fallback",
        detail="mask window unavailable for this segment",
    )
    assert len(fake_server.sent) == 1
    event, payload, client_id = fake_server.sent[0]
    assert event == "minimax_motion_director_warning"
    assert client_id == "client-1"


def test_payload_carries_both_indices(fake_server):
    # The plan index drives progress, the timeline index drives the row marker,
    # and they differ whenever the run is partial (Run selection).
    report_director_warning(
        "42",
        segment_index=0,
        timeline_segment_index=4,
        code="replace_fallback",
        detail="reason",
    )
    payload = fake_server.sent[0][1]
    assert payload["node_id"] == "42"
    assert payload["segment_index"] == 0
    assert payload["timeline_segment_index"] == 4
    # 1-based companion for display, so the UI never has to remember to add one.
    assert payload["timeline_segment"] == 5
    assert payload["code"] == "replace_fallback"
    assert payload["detail"] == "reason"


def test_timeline_index_is_optional(fake_server):
    report_director_warning("42", segment_index=1, code="something_else")
    payload = fake_server.sent[0][1]
    assert "timeline_segment_index" not in payload
    assert "timeline_segment" not in payload
    assert payload["detail"] == ""


def test_missing_detail_defaults_to_empty_string(fake_server):
    # The UI branches on the reason, so it must never be None.
    report_director_warning("42", segment_index=0, code="x", detail=None)
    assert fake_server.sent[0][1]["detail"] == ""


def test_send_failure_is_swallowed(monkeypatch):
    # A dead websocket must not take the render down with it.
    module = types.ModuleType("server")

    class _Boom:
        def send_sync(self, *_args, **_kwargs):
            raise RuntimeError("socket closed")

    module.PromptServer = type("PromptServer", (), {"instance": _Boom()})
    monkeypatch.setitem(sys.modules, "server", module)
    report_director_warning("42", segment_index=0, code="replace_fallback")
