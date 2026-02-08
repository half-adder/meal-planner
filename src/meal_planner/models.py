"""Shared data models for the meal planner."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class PrepStyle(Enum):
    BATCH = "batch"
    FRESH = "fresh"
    LEFTOVER = "leftover"


class MealType(Enum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"


@dataclass
class ParsedIngredient:
    qty: float | None
    unit: str | None
    item: str
    notes: str | None = None


@dataclass
class IngredientSection:
    section: str | None
    items: list[ParsedIngredient]


@dataclass
class Recipe:
    name: str
    file_path: Path
    # Nutrition per serving
    calories: float | None = None
    protein_g: float | None = None
    fat_g: float | None = None
    carbs_g: float | None = None
    fiber_g: float | None = None
    # Metadata
    servings: int | None = None
    prep_time_min: int | None = None
    cook_time_min: int | None = None
    total_time_min: int | None = None
    meal_type: str | None = None
    cuisine: str | None = None
    main_ingredient: str | None = None
    cooking_method: str | None = None
    dietary_tags: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    rating: float | None = None
    quick_recipe: bool = False
    tried: bool = False
    favorite: bool = False
    last_made: str | None = None
    # Parsed ingredients (populated by Haiku)
    parsed_ingredients: list[IngredientSection] = field(default_factory=list)
    ingredients_hash: str | None = None
    # Raw ingredient text (used before parsing)
    raw_ingredients: str | None = None


@dataclass
class MealSlot:
    day: int  # 0-indexed day of the plan
    day_name: str
    meal_type: MealType
    prep_style: PrepStyle
    recipe: Recipe | None = None
    servings: float = 1.0
    calories: float = 0.0
    protein_g: float = 0.0


@dataclass
class MealPlan:
    start_date: str
    end_date: str
    days: int
    calories_target: int
    protein_target: int
    slots: list[MealSlot] = field(default_factory=list)

    def slots_for_day(self, day: int) -> list[MealSlot]:
        return [s for s in self.slots if s.day == day]

    def day_calories(self, day: int) -> float:
        return sum(s.calories for s in self.slots_for_day(day))

    def day_protein(self, day: int) -> float:
        return sum(s.protein_g for s in self.slots_for_day(day))
