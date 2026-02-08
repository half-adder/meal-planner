"""Haiku-powered ingredient parsing (Task 2 - stub)."""

from __future__ import annotations

import sys
from pathlib import Path

from meal_planner.models import Recipe


def parse_all_ingredients(
    recipes: list[Recipe],
    cooking_path: Path,
    force: bool = False,
    verbose: bool = False,
) -> None:
    """Parse ingredients for all recipes using Claude Haiku. Stub for Task 2."""
    print("Haiku ingredient parsing not yet implemented. Use --skip-api or --dry-run.", file=sys.stderr)
