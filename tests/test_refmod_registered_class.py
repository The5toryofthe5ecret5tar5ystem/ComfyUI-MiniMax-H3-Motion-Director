"""The RefMod wiring must exist on the Director class ComfyUI actually registers.

There are THREE classes named ``MiniMaxH3MotionDirector`` in this pack, chained by
inheritance and exported through ``nodes/__init__.py``:

    nodes/director.py          MiniMaxH3MotionDirector                    (base)
    nodes/director_inputs.py   MiniMaxH3MotionDirector(_BaseDirector)     (overrides execute)
    nodes/director_output.py   MiniMaxH3MotionDirector(_UnifiedDirector)  (registered)

``__init__.py`` imports ``director_output`` last, so *that* class is what ComfyUI
registers, and its ``execute`` delegates to ``director_inputs``. Adding the RefMod
harvest to ``nodes/director.py`` therefore changed nothing at runtime: the input was
still declared (INPUT_TYPES is inherited, so the socket appeared and accepted the
wire) but the effective ``execute`` had no ``refmod_conditioning`` parameter, so
ComfyUI dropped the incoming conditioning into ``**kwargs`` and the node reported
zero reference blocks. Meanwhile the console said "has no reference media", which
sent the search in entirely the wrong direction.

Nothing caught it because the tests imported ``nodes/director.py`` directly - the
file that was edited - rather than the class that runs.

These tests pin the effective class, not the file.
"""

from __future__ import annotations

import inspect

import pytest

try:
    from mmx_pkg.nodes.conditioning import harvest_and_report_refmods
    from mmx_pkg.nodes.director_inputs import MiniMaxH3MotionDirector as _InputsDirector
    from mmx_pkg.nodes.director_output import MiniMaxH3MotionDirector as RegisteredDirector
except ImportError as exc:  # pragma: no cover - environment guard
    pytest.skip(f"Director package unavailable: {exc}", allow_module_level=True)


# ---------------------------------------------------------------------------
# the registered class is the one that matters
# ---------------------------------------------------------------------------

def test_the_registered_director_is_the_output_subclass():
    """If this fails the export order changed and the other tests are moot."""
    assert issubclass(RegisteredDirector, _InputsDirector), (
        "the registered Director no longer descends from the inputs subclass; "
        "re-derive which execute() actually runs before trusting any RefMod wiring"
    )


def test_the_real_execute_accepts_refmod_conditioning():
    """The exact regression: the input was declared but the live execute ignored it.

    ``director_output`` only forwards, so ``director_inputs`` holds the signature
    that actually has to name every input.
    """
    params = inspect.signature(_InputsDirector.execute).parameters
    assert "refmod_conditioning" in params, (
        "the effective Director execute() has no refmod_conditioning parameter, so "
        "ComfyUI drops the connected conditioning into **kwargs. This is the bug that "
        "made a correctly-wired RefMod look unwired."
    )


def test_the_output_forwarder_cannot_drop_refmod_conditioning():
    """The registered class must stay a pure forwarder, or it will start dropping inputs."""
    source = inspect.getsource(RegisteredDirector.execute)
    assert "super().execute(*args, **kwargs)" in source, (
        "director_output.execute no longer forwards *args/**kwargs verbatim; every "
        "input it does not name explicitly is now silently dropped"
    )


def test_the_output_subclass_still_forwards_to_the_real_execute():
    """director_output.execute sets export_source_images=False then delegates."""
    source = inspect.getsource(RegisteredDirector.execute)
    assert "super().execute(" in source


# ---------------------------------------------------------------------------
# the shared helper
# ---------------------------------------------------------------------------

def test_not_connected_returns_empty_and_says_so(capsys):
    assert harvest_and_report_refmods(None) == []
    assert "NOT connected" in capsys.readouterr().out


def test_connected_without_refs_returns_empty_and_dumps_keys(capsys):
    """The state that used to be invisible."""
    conditioning = [["tensor", {"pooled_output": 1}]]
    assert harvest_and_report_refmods(conditioning) == []
    out = capsys.readouterr().out
    assert "IS connected but carried no reference blocks" in out
    assert "pooled_output" in out


def test_connected_with_refs_returns_them(capsys):
    conditioning = [["tensor", {"minimax_refs": [{"kind": "video", "latent": "z"}]}]]
    blocks = harvest_and_report_refmods(conditioning)
    assert len(blocks) == 1
    assert blocks[0]["kind"] == "video"
    assert "1 reference block(s) harvested" in capsys.readouterr().out
