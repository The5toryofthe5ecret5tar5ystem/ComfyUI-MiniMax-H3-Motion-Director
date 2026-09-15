"""The Director's verbose logging toggle (node widget plus env override)."""

from __future__ import annotations

import logging

import director.verbosity as verbosity


def _pack_parent() -> logging.Logger:
    return logging.getLogger(verbosity.PACK_LOGGER_PREFIX)


def test_default_off_touches_nothing(monkeypatch):
    monkeypatch.delenv(verbosity.ENV_OVERRIDE, raising=False)
    parent = _pack_parent()
    before = parent.level
    assert verbosity.verbose_requested(False) is False
    assert verbosity.apply_director_verbose(False) is False
    assert parent.level == before


def test_widget_on_sets_pack_loggers_only(monkeypatch):
    monkeypatch.delenv(verbosity.ENV_OVERRIDE, raising=False)
    parent = _pack_parent()
    child = logging.getLogger(verbosity.PACK_LOGGER_PREFIX + ".director.verbosity_tests")
    stranger = logging.getLogger("some.other.pack.logger")
    stranger_before = stranger.level
    try:
        assert verbosity.apply_director_verbose(True) is True
        assert parent.level == logging.DEBUG
        assert child.level == logging.DEBUG
        assert stranger.level == stranger_before
    finally:
        assert verbosity.apply_director_verbose(False) is False
    assert child.level == logging.NOTSET
    assert stranger.level == stranger_before


def test_env_override_wins_over_widget(monkeypatch):
    monkeypatch.setenv(verbosity.ENV_OVERRIDE, "1")
    assert verbosity.verbose_requested(False) is True
    monkeypatch.setenv(verbosity.ENV_OVERRIDE, "yes")
    assert verbosity.verbose_requested(False) is True
    monkeypatch.setenv(verbosity.ENV_OVERRIDE, "0")
    assert verbosity.verbose_requested(True) is False
    monkeypatch.setenv(verbosity.ENV_OVERRIDE, "off")
    assert verbosity.verbose_requested(True) is False


def test_toggle_restores_the_previous_level(monkeypatch):
    monkeypatch.delenv(verbosity.ENV_OVERRIDE, raising=False)
    parent = _pack_parent()
    original = parent.level
    try:
        parent.setLevel(logging.WARNING)
        assert verbosity.apply_director_verbose(True) is True
        assert parent.level == logging.DEBUG
        assert verbosity.apply_director_verbose(True) is True
        assert parent.level == logging.DEBUG
    finally:
        verbosity.apply_director_verbose(False)
        parent.setLevel(original)
    assert parent.level == original


def test_toggle_never_raises(monkeypatch):
    monkeypatch.setattr(
        verbosity,
        "_pack_loggers",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert verbosity.apply_director_verbose(True) is False
