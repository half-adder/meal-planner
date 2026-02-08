"""Pin specification parsing, validation, and resolution."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from meal_planner.models import MealType, Recipe

logger = logging.getLogger(__name__)

DAY_NAMES_LOWER = [
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
]


class PinPattern(Enum):
    SINGLE = "single"
    ALL = "all"
    EVEN = "even"
    ODD = "odd"


@dataclass
class PinSpec:
    """A parsed pin specification."""
    day: int | None        # 0-indexed, or None for pattern-based
    meal_type: MealType
    recipe_query: str
    pattern: PinPattern


@dataclass
class ResolvedPin:
    """A pin with recipe found and candidate index determined."""
    days: list[int]
    meal_type: MealType
    recipe: Recipe
    candidate_index: int
    injected: bool = False


def parse_pin(raw: str) -> PinSpec:
    """Parse 'day:meal:Recipe Name' into a PinSpec.

    day: a day name, 'all', 'even', or 'odd'
    meal: breakfast, lunch, dinner, snack
    recipe: everything after the second colon
    """
    parts = raw.split(":", maxsplit=2)
    if len(parts) != 3:
        raise ValueError(
            f"Invalid pin format: '{raw}'. Expected 'day:meal:Recipe Name'"
        )

    day_str, meal_str, recipe_str = parts
    day_str = day_str.strip().lower()
    meal_str = meal_str.strip().lower()
    recipe_str = recipe_str.strip()

    if not recipe_str:
        raise ValueError(f"Empty recipe name in pin: '{raw}'")

    # Parse day/pattern
    if day_str == "all":
        pattern = PinPattern.ALL
        day = None
    elif day_str == "even":
        pattern = PinPattern.EVEN
        day = None
    elif day_str == "odd":
        pattern = PinPattern.ODD
        day = None
    elif day_str in DAY_NAMES_LOWER:
        pattern = PinPattern.SINGLE
        day = DAY_NAMES_LOWER.index(day_str)
    else:
        raise ValueError(
            f"Unknown day '{day_str}' in pin. "
            f"Use a day name, 'all', 'even', or 'odd'."
        )

    # Parse meal type
    try:
        meal_type = MealType(meal_str)
    except ValueError:
        valid = ", ".join(m.value for m in MealType)
        raise ValueError(
            f"Unknown meal type '{meal_str}' in pin. Valid: {valid}"
        )

    return PinSpec(day=day, meal_type=meal_type, recipe_query=recipe_str, pattern=pattern)


def expand_pin_days(pin: PinSpec, num_days: int) -> list[int]:
    """Expand a pin pattern into concrete day indices."""
    if pin.pattern == PinPattern.SINGLE:
        if pin.day is not None and pin.day < num_days:
            return [pin.day]
        return []
    elif pin.pattern == PinPattern.ALL:
        return list(range(num_days))
    elif pin.pattern == PinPattern.EVEN:
        return [d for d in range(num_days) if d % 2 == 0]
    elif pin.pattern == PinPattern.ODD:
        return [d for d in range(num_days) if d % 2 == 1]
    return []


def find_recipe(
    query: str,
    candidates: list[Recipe],
    all_recipes: list[Recipe],
) -> tuple[Recipe, int, bool]:
    """Find a recipe by name. Returns (recipe, index_in_candidates, was_injected).

    Search order: exact match in candidates, substring in candidates,
    exact in all_recipes (inject), substring in all_recipes (inject).
    """
    query_lower = query.lower()

    # Exact match in candidates
    for i, r in enumerate(candidates):
        if r.name.lower() == query_lower:
            return r, i, False

    # Substring match in candidates (prefer shortest name = most specific)
    matches = [(i, r) for i, r in enumerate(candidates) if query_lower in r.name.lower()]
    if matches:
        matches.sort(key=lambda x: len(x[1].name))
        return matches[0][1], matches[0][0], False

    # Exact match in all_recipes (will inject)
    for r in all_recipes:
        if r.name.lower() == query_lower:
            idx = len(candidates)
            candidates.append(r)
            return r, idx, True

    # Substring match in all_recipes (will inject)
    matches_all = [r for r in all_recipes if query_lower in r.name.lower()]
    if matches_all:
        matches_all.sort(key=lambda r: len(r.name))
        r = matches_all[0]
        idx = len(candidates)
        candidates.append(r)
        return r, idx, True

    raise ValueError(f"No recipe found matching '{query}'")


def resolve_pins(
    pins: list[PinSpec],
    candidates_by_meal: dict[str, list[Recipe]],
    all_recipes: list[Recipe],
    num_days: int,
    batch_breakfast: bool = False,
) -> list[ResolvedPin]:
    """Resolve all pins: find recipes, expand days, detect conflicts."""
    resolved: list[ResolvedPin] = []

    for pin in pins:
        # Batch breakfast validation
        if pin.meal_type == MealType.BREAKFAST and batch_breakfast:
            if pin.pattern != PinPattern.ALL:
                raise ValueError(
                    f"Cannot pin {pin.pattern.value} breakfast in batch mode. "
                    f"Use 'all:breakfast:{pin.recipe_query}' or set breakfast prep_style to fresh."
                )

        days = expand_pin_days(pin, num_days)
        meal_key = pin.meal_type.value
        candidates = candidates_by_meal.get(meal_key, [])

        recipe, idx, injected = find_recipe(pin.recipe_query, candidates, all_recipes)

        if recipe.calories is None:
            logger.warning(
                "Pinned recipe '%s' has no calorie data; nutrition optimization will be inaccurate",
                recipe.name,
            )

        resolved.append(ResolvedPin(
            days=days,
            meal_type=pin.meal_type,
            recipe=recipe,
            candidate_index=idx,
            injected=injected,
        ))

    # Conflict detection: same (day, meal_type) with different recipes
    slot_map: dict[tuple[int, str], str] = {}
    for rpin in resolved:
        for d in rpin.days:
            key = (d, rpin.meal_type.value)
            if key in slot_map and slot_map[key] != rpin.recipe.name:
                from meal_planner.planner import DAY_NAMES
                day_name = DAY_NAMES[d % 7] if d < 7 else f"day {d}"
                raise ValueError(
                    f"Conflicting pins for {day_name} {rpin.meal_type.value}: "
                    f"'{slot_map[key]}' vs '{rpin.recipe.name}'"
                )
            slot_map[key] = rpin.recipe.name

    return resolved
