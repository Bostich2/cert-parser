from __future__ import annotations

import logging
from collections.abc import Callable
from contextvars import ContextVar
from datetime import datetime

logger = logging.getLogger("sert_parser")

_steps: ContextVar[list[str] | None] = ContextVar("lookup_steps", default=None)
_sink: ContextVar[Callable[[str], None] | None] = ContextVar("lookup_step_sink", default=None)
_STEP_TIME_SEP = "\t"


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def start_steps() -> list[str]:
    items: list[str] = []
    _steps.set(items)
    return items


def current_steps() -> list[str]:
    return list(_steps.get() or [])


def set_step_sink(callback: Callable[[str], None] | None) -> None:
    _sink.set(callback)


def log_step(message: str) -> None:
    logger.info(message)
    stamped = f"{datetime.now():%H:%M:%S}{_STEP_TIME_SEP}{message}"
    items = _steps.get()
    if items is not None:
        items.append(stamped)
    sink = _sink.get()
    if sink is not None:
        sink(stamped)
