"""Recipe filtering and scoring for meal suggestions."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from meal_planner.config import load_config
from meal_planner.indexer import discover_recipe_files, parse_recipe_file
from meal_planner.models import Recipe

logger = logging.getLogger(__name__)

# Meal type aliases: what frontmatter values count for each meal
MEAL_TYPE_MAP = {
    "breakfast": {"breakfast"},
    "lunch": {"lunch", "main course", "soup"},
    "dinner": {"dinner", "main course", "soup", "curry"},
    "snack": {"snack", "appetizer", "dessert", "side", "side dish"},
}


@dataclass
class ScoredRecipe:
    recipe: Recipe
    score: float
    suggested_servings: float
    breakdown: dict


def matches_meal_type(recipe: Recipe, meal_type: str) -> bool:
    """Check if a recipe matches a meal type, considering aliases and categories."""
    if not meal_type:
        return True

    meal_type = meal_type.lower()
    valid_types = MEAL_TYPE_MAP.get(meal_type, {meal_type})

    # Check meal_type field
    if recipe.meal_type and recipe.meal_type.lower() in valid_types:
        return True

    # Check categories
    for cat in recipe.categories:
        if cat.lower() in valid_types:
            return True

    return False


def matches_dietary_tags(recipe: Recipe, required_tags: list[str]) -> bool:
    """Check if recipe has all required dietary tags."""
    if not required_tags:
        return True
    recipe_tags = {t.lower() for t in recipe.dietary_tags}
    return all(t.lower() in recipe_tags for t in required_tags)


def matches_cuisine(recipe: Recipe, cuisine: str) -> bool:
    """Check if recipe matches cuisine (substring match)."""
    if not cuisine:
        return True
    if not recipe.cuisine:
        return False
    return cuisine.lower() in recipe.cuisine.lower()


def matches_time(recipe: Recipe, max_time: int | None) -> bool:
    """Check if recipe total time is within limit."""
    if max_time is None:
        return True
    total = recipe.total_time_min
    if total is None:
        # If no time info, include it (don't exclude unknowns)
        return True
    return total <= max_time


def is_excluded(recipe: Recipe, exclude_names: list[str]) -> bool:
    """Check if recipe name matches any exclusion."""
    if not exclude_names:
        return False
    name_lower = recipe.name.lower()
    return any(ex.lower() in name_lower for ex in exclude_names)


def filter_recipes(
    recipes: list[Recipe],
    meal_type: str | None = None,
    max_time: int | None = None,
    cuisine: str | None = None,
    dietary_tags: list[str] | None = None,
    exclude: list[str] | None = None,
    min_protein: float | None = None,
    max_calories: float | None = None,
) -> list[Recipe]:
    """Apply hard filters to recipe list."""
    result = []
    for r in recipes:
        if meal_type and not matches_meal_type(r, meal_type):
            continue
        if not matches_time(r, max_time):
            continue
        if cuisine and not matches_cuisine(r, cuisine):
            continue
        if dietary_tags and not matches_dietary_tags(r, dietary_tags):
            continue
        if exclude and is_excluded(r, exclude):
            continue
        if (
            min_protein is not None
            and r.protein_g is not None
            and r.protein_g < min_protein
        ):
            continue
        if (
            max_calories is not None
            and r.calories is not None
            and r.calories > max_calories
        ):
            continue
        result.append(r)
    return result


def compute_pantry_overlap(recipe: Recipe, pantry_items: list[str]) -> float:
    """Score 0-1 for how many recipe ingredients overlap with pantry."""
    if not pantry_items or not recipe.parsed_ingredients:
        return 0.0

    pantry_lower = {p.lower() for p in pantry_items}
    total_items = 0
    matched = 0

    for section in recipe.parsed_ingredients:
        for item in section.items:
            total_items += 1
            item_lower = item.item.lower()
            if any(p in item_lower or item_lower in p for p in pantry_lower):
                matched += 1

    return matched / total_items if total_items > 0 else 0.0


def score_macro_fit(
    recipe: Recipe,
    target_calories: int | None,
    target_protein: int | None,
) -> tuple[float, float]:
    """Score how well a recipe fits macro targets at various serving counts.

    Returns (best_score 0-1, best_servings).
    Tests 1x, 1.5x, 2x, 3x servings.
    """
    if recipe.calories is None and recipe.protein_g is None:
        return 0.5, 1.0  # No data, neutral score

    best_score = 0.0
    best_servings = 1.0

    for servings in [1.0, 1.5, 2.0, 3.0]:
        cal_score = 0.0
        pro_score = 0.0

        if target_calories and recipe.calories:
            actual_cal = recipe.calories * servings
            cal_deviation = abs(actual_cal - target_calories) / target_calories
            cal_score = max(0, 1 - cal_deviation)

        if target_protein and recipe.protein_g:
            actual_pro = recipe.protein_g * servings
            pro_deviation = abs(actual_pro - target_protein) / target_protein
            pro_score = max(0, 1 - pro_deviation)

        # Weight protein fit slightly higher
        combined = (
            (cal_score * 0.4 + pro_score * 0.6)
            if (target_calories and target_protein)
            else max(cal_score, pro_score)
        )

        if combined > best_score:
            best_score = combined
            best_servings = servings

    return best_score, best_servings


def score_recipe(
    recipe: Recipe,
    pantry_items: list[str] | None = None,
    target_calories: int | None = None,
    target_protein: int | None = None,
) -> ScoredRecipe:
    """Score a recipe on multiple dimensions (0-100 total)."""
    breakdown = {}

    # Pantry overlap (0-30)
    pantry_score = compute_pantry_overlap(recipe, pantry_items or []) * 30
    breakdown["pantry"] = round(pantry_score, 1)

    # Rating (0-20)
    if recipe.rating and recipe.rating > 0:
        rating_score = min(recipe.rating / 5.0, 1.0) * 20
    else:
        rating_score = 10.0  # Neutral for unrated
    breakdown["rating"] = round(rating_score, 1)

    # Recency avoidance (0-15)
    recency_score = 15.0  # Default: never made = full score
    if recipe.last_made:
        try:
            last_date = datetime.strptime(recipe.last_made, "%Y-%m-%d")
            days_ago = (datetime.now() - last_date).days
            if days_ago < 7:
                recency_score = 0.0
            elif days_ago < 14:
                recency_score = 5.0
            elif days_ago < 30:
                recency_score = 10.0
        except ValueError:
            pass
    breakdown["recency"] = round(recency_score, 1)

    # Macro fit (0-20)
    macro_score_norm, best_servings = score_macro_fit(
        recipe, target_calories, target_protein
    )
    macro_score = macro_score_norm * 20
    breakdown["macro_fit"] = round(macro_score, 1)

    # Variety bonus (0-15) — static per recipe, variety across results handled externally
    variety_score = 10.0  # Base
    if recipe.tried:
        variety_score += 2.5
    if recipe.favorite:
        variety_score += 2.5
    breakdown["variety"] = round(variety_score, 1)

    total = pantry_score + rating_score + recency_score + macro_score + variety_score

    return ScoredRecipe(
        recipe=recipe,
        score=round(total, 1),
        suggested_servings=best_servings,
        breakdown=breakdown,
    )


def load_all_recipes(cooking_path: Path) -> list[Recipe]:
    """Load all recipe files into Recipe objects."""
    files = discover_recipe_files(cooking_path)
    recipes = []
    for f in files:
        r = parse_recipe_file(f)
        if r:
            recipes.append(r)
    return recipes


def suggest_recipes(
    cooking_path: Path,
    meal_type: str | None = None,
    max_time: int | None = None,
    cuisine: str | None = None,
    dietary_tags: list[str] | None = None,
    exclude: list[str] | None = None,
    available_ingredients: list[str] | None = None,
    target_calories: int | None = None,
    target_protein: int | None = None,
    min_protein: float | None = None,
    max_calories: float | None = None,
    limit: int = 10,
) -> list[ScoredRecipe]:
    """Filter and rank recipes, returning top N suggestions."""
    all_recipes = load_all_recipes(cooking_path)

    # Hard filters
    filtered = filter_recipes(
        all_recipes,
        meal_type=meal_type,
        max_time=max_time,
        cuisine=cuisine,
        dietary_tags=dietary_tags,
        exclude=exclude,
        min_protein=min_protein,
        max_calories=max_calories,
    )

    # Score each
    scored = [
        score_recipe(
            r,
            pantry_items=available_ingredients,
            target_calories=target_calories,
            target_protein=target_protein,
        )
        for r in filtered
    ]

    # Sort by score descending
    scored.sort(key=lambda s: s.score, reverse=True)

    return scored[:limit]


def format_table(scored: list[ScoredRecipe]) -> str:
    """Format scored recipes as a readable table."""
    lines = []
    header = f"{'#':<3} {'Score':<6} {'Svgs':<5} {'Cal':<6} {'Pro':<6} {'Time':<6} {'Recipe'}"
    lines.append(header)
    lines.append("-" * len(header))

    for i, sr in enumerate(scored, 1):
        r = sr.recipe
        cal = f"{r.calories:.0f}" if r.calories else "?"
        pro = f"{r.protein_g:.0f}g" if r.protein_g else "?"
        time_str = f"{r.total_time_min}m" if r.total_time_min else "?"
        lines.append(
            f"{i:<3} {sr.score:<6.1f} {sr.suggested_servings:<5.1f} "
            f"{cal:<6} {pro:<6} {time_str:<6} {r.name}"
        )

    return "\n".join(lines)


def format_json(scored: list[ScoredRecipe]) -> str:
    """Format scored recipes as JSON."""
    data = []
    for sr in scored:
        r = sr.recipe
        data.append(
            {
                "name": r.name,
                "file": str(r.file_path),
                "calories": r.calories,
                "protein_g": r.protein_g,
                "servings": r.servings,
                "total_time_min": r.total_time_min,
                "meal_type": r.meal_type,
                "cuisine": r.cuisine,
                "suggested_servings": sr.suggested_servings,
                "score": sr.score,
                "score_breakdown": sr.breakdown,
            }
        )
    return json.dumps(data, indent=2)


def run_suggest(
    cooking_path: Path,
    meal_type: str | None = None,
    max_time: int | None = None,
    cuisine: str | None = None,
    dietary_tags: str | None = None,
    exclude: str | None = None,
    available_ingredients: str | None = None,
    target_calories: int | None = None,
    target_protein: int | None = None,
    min_protein: int | None = None,
    max_calories: int | None = None,
    limit: int = 10,
    output_format: str = "table",
) -> None:
    """CLI entry point for suggest command."""
    tags = [t.strip() for t in dietary_tags.split(",")] if dietary_tags else None
    excl = [e.strip() for e in exclude.split(",")] if exclude else None
    ingredients = (
        [i.strip() for i in available_ingredients.split(",")]
        if available_ingredients
        else None
    )

    scored = suggest_recipes(
        cooking_path,
        meal_type=meal_type,
        max_time=max_time,
        cuisine=cuisine,
        dietary_tags=tags,
        exclude=excl,
        available_ingredients=ingredients,
        target_calories=target_calories,
        target_protein=target_protein,
        min_protein=float(min_protein) if min_protein else None,
        max_calories=float(max_calories) if max_calories else None,
        limit=limit,
    )

    if not scored:
        logger.warning("No recipes match the given filters")
        return

    if output_format == "json":
        print(format_json(scored))
    else:
        print(format_table(scored))
