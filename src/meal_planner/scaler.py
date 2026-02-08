"""Recipe scaling to target servings."""

from __future__ import annotations

import json
import sys
from difflib import SequenceMatcher
from pathlib import Path

from meal_planner.indexer import discover_recipe_files, parse_recipe_file
from meal_planner.models import Recipe


def fuzzy_match_recipe(name: str, cooking_path: Path) -> Recipe | None:
    """Find the best matching recipe by fuzzy name matching."""
    files = discover_recipe_files(cooking_path)
    name_lower = name.lower()

    best_match: tuple[float, Path | None] = (0.0, None)

    for f in files:
        stem_lower = f.stem.lower()

        # Exact match
        if stem_lower == name_lower:
            recipe = parse_recipe_file(f)
            if recipe:
                return recipe

        # Substring match gets a boost
        score = SequenceMatcher(None, name_lower, stem_lower).ratio()
        if name_lower in stem_lower or stem_lower in name_lower:
            score = max(score, 0.8)

        if score > best_match[0]:
            best_match = (score, f)

    if best_match[1] and best_match[0] > 0.4:
        return parse_recipe_file(best_match[1])

    return None


def round_to_fraction(qty: float) -> str:
    """Round a quantity to a practical cooking fraction."""
    if qty == 0:
        return "0"

    whole = int(qty)
    frac = qty - whole

    # Common fractions with thresholds
    fraction_map = [
        (0, ""),
        (1 / 8, "1/8"),
        (1 / 4, "1/4"),
        (1 / 3, "1/3"),
        (1 / 2, "1/2"),
        (2 / 3, "2/3"),
        (3 / 4, "3/4"),
        (1.0, ""),
    ]

    # Find closest fraction
    closest_val = 0
    closest_str = ""
    min_diff = float("inf")
    for val, s in fraction_map:
        diff = abs(frac - val)
        if diff < min_diff:
            min_diff = diff
            closest_val = val
            closest_str = s

    if closest_val >= 1.0:
        whole += 1
        closest_str = ""

    if whole > 0 and closest_str:
        return f"{whole} {closest_str}"
    elif whole > 0:
        return str(whole)
    elif closest_str:
        return closest_str
    else:
        return f"{qty:.2f}"


def scale_recipe(recipe: Recipe, target_servings: float) -> dict:
    """Scale a recipe to target servings, returning formatted data."""
    base_servings = recipe.servings or 1
    scale_factor = target_servings / base_servings

    scaled_sections = []
    for section in recipe.parsed_ingredients:
        scaled_items = []
        for item in section.items:
            scaled_qty = None
            qty_str = ""
            if item.qty is not None:
                scaled_qty = item.qty * scale_factor
                qty_str = round_to_fraction(scaled_qty)

            scaled_items.append({
                "item": item.item,
                "original_qty": item.qty,
                "original_unit": item.unit,
                "scaled_qty": scaled_qty,
                "scaled_qty_display": qty_str,
                "unit": item.unit or "",
                "notes": item.notes,
            })

        scaled_sections.append({
            "section": section.section,
            "items": scaled_items,
        })

    return {
        "name": recipe.name,
        "base_servings": base_servings,
        "target_servings": target_servings,
        "scale_factor": round(scale_factor, 2),
        "calories_per_serving": recipe.calories,
        "protein_per_serving": recipe.protein_g,
        "total_calories": round(recipe.calories * target_servings, 1) if recipe.calories else None,
        "total_protein": round(recipe.protein_g * target_servings, 1) if recipe.protein_g else None,
        "sections": scaled_sections,
    }


def format_scaled_markdown(data: dict) -> str:
    """Format scaled recipe as markdown."""
    lines = [
        f"# {data['name']} (Scaled to {data['target_servings']} servings)",
        "",
        f"**Base:** {data['base_servings']} servings | **Scale:** {data['scale_factor']}x",
    ]

    if data["calories_per_serving"]:
        lines.append(
            f"**Per serving:** {data['calories_per_serving']} cal, "
            f"{data['protein_per_serving'] or '?'}g protein"
        )
    if data["total_calories"]:
        lines.append(
            f"**Total:** {data['total_calories']} cal, "
            f"{data['total_protein'] or '?'}g protein"
        )
    lines.append("")

    lines.append("## Ingredients")
    lines.append("")

    for section in data["sections"]:
        if section["section"]:
            lines.append(f"**{section['section']}**")
            lines.append("")
        for item in section["items"]:
            qty = item["scaled_qty_display"]
            unit = f" {item['unit']}" if item["unit"] else ""
            notes = f" ({item['notes']})" if item["notes"] else ""
            if qty:
                lines.append(f"- {qty}{unit} {item['item']}{notes}")
            else:
                lines.append(f"- {item['item']}{notes}")
        lines.append("")

    return "\n".join(lines)


def format_scaled_json(data: dict) -> str:
    """Format scaled recipe as JSON."""
    return json.dumps(data, indent=2)


def run_scale(
    cooking_path: Path,
    recipe_name: str,
    servings: float,
    output_format: str = "markdown",
) -> None:
    """CLI entry point for scale command."""
    recipe = fuzzy_match_recipe(recipe_name, cooking_path)

    if not recipe:
        print(f"Recipe not found: {recipe_name}", file=sys.stderr)
        sys.exit(1)

    if not recipe.parsed_ingredients:
        print(f"Recipe '{recipe.name}' has no parsed ingredients. Run 'index' first.", file=sys.stderr)
        sys.exit(1)

    data = scale_recipe(recipe, servings)

    if output_format == "json":
        print(format_scaled_json(data))
    else:
        print(format_scaled_markdown(data))
