# MiniMax H3 Motion Director - run-scoped verbose logging control.
# Distributed under GPL-3.0; see repository LICENSE.

"""Enable or disable verbose (DEBUG) logging for one Director run.

The Director node carries a ``verbose_logging`` widget, so the choice travels
with the workflow. Environment overrides win over the widget so a whole server
can be switched without editing workflows:

* ``MINIMAX_DIRECTOR_VERBOSE=1`` (also true/on/yes) forces verbose on
* ``MINIMAX_DIRECTOR_VERBOSE=0`` (also false/off/no) forces it off

Only the pack's own loggers are touched, and the decision is re-applied at the
start of every run, so the level always matches the run in progress. A run that
dies mid-flight simply leaves the loggers verbose until the next run lands;
nothing is leaked and no per-exception bookkeeping is needed.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.director.verbosity")

PACK_LOGGER_PREFIX = "ComfyUI-MiniMax-H3-Motion-Director"
ENV_OVERRIDE = "MINIMAX_DIRECTOR_VERBOSE"

# logger name -> level before we raised it, so OFF restores exactly what was
# there rather than assuming NOTSET.
_TOUCHED: dict[str, int] = {}


def _env_value() -> str:
    return str(os.environ.get(ENV_OVERRIDE, "")).strip().lower()


def verbose_requested(widget_value: bool = False) -> bool:
    """Effective verbose flag: the environment override wins over the widget."""
    value = _env_value()
    if value in {"1", "true", "on", "yes"}:
        return True
    if value in {"0", "false", "off", "no"}:
        return False
    return bool(widget_value)


def _pack_loggers() -> list[logging.Logger]:
    found: list[logging.Logger] = []
    for name, item in list(logging.Logger.manager.loggerDict.items()):
        if name != PACK_LOGGER_PREFIX and not name.startswith(PACK_LOGGER_PREFIX + "."):
            continue
        if isinstance(item, logging.Logger):
            found.append(item)
    parent = logging.getLogger(PACK_LOGGER_PREFIX)
    if parent not in found:
        # The parent matters twice over: it is the logger the report lines use,
        # and any pack logger created later (first import of a module) inherits
        # this level, so late loggers are verbose too.
        found.append(parent)
    return found


def apply_director_verbose(widget_value: bool = False) -> bool:
    """Set the pack's loggers to DEBUG (or restore them) for the current run.

    Returns the effective value, so the caller can report it. Never raises.
    """
    try:
        enabled = verbose_requested(widget_value)
        for logger in _pack_loggers():
            if enabled:
                if logger.name not in _TOUCHED:
                    _TOUCHED[logger.name] = logger.level
                if logger.level == logging.NOTSET or logger.level > logging.DEBUG:
                    logger.setLevel(logging.DEBUG)
            else:
                previous = _TOUCHED.pop(logger.name, None)
                if previous is not None:
                    logger.setLevel(previous)
        if enabled:
            log.info(
                "Verbose logging enabled for this run (Motion Director loggers at "
                "DEBUG; set %s=0 to force it off).",
                ENV_OVERRIDE,
            )
        return enabled
    except Exception as exc:  # noqa: BLE001 - logging must never fail a run
        log.debug("Verbose logging toggle failed: %s", exc)
        return False


__all__ = [
    "ENV_OVERRIDE",
    "PACK_LOGGER_PREFIX",
    "apply_director_verbose",
    "verbose_requested",
]
