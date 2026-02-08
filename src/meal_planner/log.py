"""Logging setup with Rich handler and shared stderr console."""

from __future__ import annotations

import logging
from pathlib import Path

from rich.console import Console

stderr_console = Console(stderr=True)


def setup_logging(level: str = "info", log_file: Path | None = None) -> None:
    """Configure the meal_planner logger with RichHandler and optional file output."""
    from rich.logging import RichHandler

    logger = logging.getLogger("meal_planner")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()

    rich_handler = RichHandler(
        console=stderr_console,
        show_path=False,
        markup=False,
        rich_tracebacks=True,
    )
    rich_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.addHandler(rich_handler)

    if log_file is not None:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
        )
        logger.addHandler(file_handler)
