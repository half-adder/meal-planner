"""Render scaled recipes section for meal plan output."""

from __future__ import annotations

import re
from pathlib import Path

from meal_planner.models import MealPlan, Recipe
from meal_planner.scaler import scale_recipe


def extract_directions(file_path: Path) -> str | None:
    """Extract the Directions section from a recipe markdown file."""
    try:
        text = file_path.read_text()
    except OSError:
        return None

    # Strip YAML frontmatter
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            text = text[end + 3:]

    # Find ### Directions (or ## Directions)
    match = re.search(r"^#{2,3}\s+Directions\s*$", text, re.MULTILINE)
    if not match:
        return None

    start = match.end()
    # Capture until next heading of same or higher level, or EOF
    next_heading = re.search(r"^#{2,3}\s+", text[start:], re.MULTILINE)
    if next_heading:
        directions = text[start : start + next_heading.start()]
    else:
        directions = text[start:]

    return directions.strip() or None


def _load_recipe_with_ingredients(file_path: Path) -> Recipe | None:
    """Load a recipe from disk, returning it only if it has parsed ingredients."""
    from meal_planner.indexer import parse_recipe_file

    recipe = parse_recipe_file(file_path)
    if recipe and recipe.parsed_ingredients:
        return recipe
    return None


def render_plan_recipes(plan: MealPlan, cooking_path: Path) -> str:
    """Render a '## Recipes' section with scaled ingredients and directions.

    Each unique (recipe_name, servings) pair appears once.
    """
    # Collect unique (recipe_name, servings) preserving order
    seen: set[tuple[str, float]] = set()
    recipe_specs: list[tuple[str, float, Recipe]] = []
    for slot in plan.slots:
        if slot.recipe is None:
            continue
        key = (slot.recipe.name, slot.servings)
        if key not in seen:
            seen.add(key)
            recipe_specs.append((slot.recipe.name, slot.servings, slot.recipe))

    if not recipe_specs:
        return ""

    lines = ["## Recipes", ""]

    for name, servings, slot_recipe in recipe_specs:
        # Load full recipe from disk (need parsed_ingredients)
        recipe = _load_recipe_with_ingredients(slot_recipe.file_path)
        if recipe is None:
            lines.append(f"### {name} ({servings:.1f}x)")
            lines.append("")
            lines.append("*Recipe ingredients not available. Run `meal-planner index` first.*")
            lines.append("")
            continue

        # Scale ingredients
        base_servings = recipe.servings or 1
        target_servings = servings * base_servings
        data = scale_recipe(recipe, target_servings)

        lines.append(f"### {name} ({servings:.1f}x)")
        lines.append("")

        # Ingredients
        lines.append("#### Ingredients")
        lines.append("")
        for section in data["sections"]:
            if section["section"]:
                lines.append(f"**{section['section']}**")
                lines.append("")
            for item in section["items"]:
                qty = item["scaled_qty_display"]
                unit = f" {item['unit']}" if item["unit"] else ""
                notes = f", {item['notes']}" if item["notes"] else ""
                if qty:
                    lines.append(f"- {qty}{unit} {item['item']}{notes}")
                else:
                    lines.append(f"- {item['item']}{notes}")
            lines.append("")

        # Directions
        directions = extract_directions(slot_recipe.file_path)
        if directions:
            lines.append("#### Directions")
            lines.append("")
            lines.append(directions)
            lines.append("")

    return "\n".join(lines)
