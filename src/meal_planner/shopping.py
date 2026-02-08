"""Shopping list generation from a meal plan."""

from __future__ import annotations

import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

from meal_planner.config import load_config
from meal_planner.indexer import parse_recipe_file, discover_recipe_files
from meal_planner.models import ParsedIngredient

logger = logging.getLogger(__name__)

# Section classification by keyword
SECTION_KEYWORDS = {
    "Produce": [
        "lettuce",
        "tomato",
        "onion",
        "garlic",
        "pepper",
        "carrot",
        "celery",
        "potato",
        "broccoli",
        "spinach",
        "kale",
        "cabbage",
        "zucchini",
        "mushroom",
        "avocado",
        "lemon",
        "lime",
        "ginger",
        "cilantro",
        "parsley",
        "basil",
        "mint",
        "green onion",
        "scallion",
        "jalapeño",
        "jalapeno",
        "cucumber",
        "corn",
        "peas",
        "bean sprout",
        "apple",
        "banana",
        "berry",
        "mango",
        "orange",
        "squash",
        "sweet potato",
        "cauliflower",
        "asparagus",
        "eggplant",
        "beet",
        "radish",
    ],
    "Meat & Seafood": [
        "chicken",
        "beef",
        "pork",
        "turkey",
        "salmon",
        "shrimp",
        "fish",
        "sausage",
        "bacon",
        "ground",
        "steak",
        "thigh",
        "breast",
        "drumstick",
        "lamb",
        "tilapia",
        "tuna",
        "crab",
        "meatball",
        "chorizo",
    ],
    "Dairy": [
        "cheese",
        "milk",
        "cream",
        "yogurt",
        "butter",
        "egg",
        "sour cream",
        "cream cheese",
        "mozzarella",
        "parmesan",
        "cheddar",
        "ricotta",
        "cottage cheese",
        "whipping cream",
        "half and half",
    ],
    "Pantry": [
        "rice",
        "pasta",
        "noodle",
        "flour",
        "sugar",
        "oil",
        "vinegar",
        "broth",
        "stock",
        "can",
        "canned",
        "beans",
        "lentil",
        "chickpea",
        "coconut milk",
        "tomato sauce",
        "tomato paste",
        "soy sauce",
        "tortilla",
        "bread",
        "bun",
        "pita",
        "wrap",
    ],
    "Spices & Condiments": [
        "salt",
        "pepper",
        "cumin",
        "paprika",
        "oregano",
        "thyme",
        "cinnamon",
        "chili powder",
        "curry",
        "turmeric",
        "cayenne",
        "nutmeg",
        "garlic powder",
        "onion powder",
        "bay leaf",
        "red pepper flake",
        "hot sauce",
        "sriracha",
        "mustard",
        "ketchup",
        "mayo",
        "mayonnaise",
        "honey",
        "maple syrup",
        "worcestershire",
    ],
    "Frozen": [
        "frozen",
        "ice cream",
    ],
}


def classify_section(item_name: str) -> str:
    """Classify an ingredient into a store section."""
    name_lower = item_name.lower()
    for section, keywords in SECTION_KEYWORDS.items():
        for kw in keywords:
            if kw in name_lower:
                return section
    return "Other"


def normalize_unit(unit: str | None) -> str:
    """Normalize unit names for aggregation."""
    if not unit:
        return ""
    u = unit.lower().strip().rstrip(".")
    aliases = {
        "tablespoon": "Tbsp",
        "tablespoons": "Tbsp",
        "tbsp": "Tbsp",
        "tbs": "Tbsp",
        "teaspoon": "tsp",
        "teaspoons": "tsp",
        "tsp": "tsp",
        "cup": "cup",
        "cups": "cup",
        "c": "cup",
        "ounce": "oz",
        "ounces": "oz",
        "oz": "oz",
        "pound": "lb",
        "pounds": "lb",
        "lb": "lb",
        "lbs": "lb",
        "can": "can",
        "cans": "can",
        "clove": "clove",
        "cloves": "clove",
        "slice": "slice",
        "slices": "slice",
        "piece": "piece",
        "pieces": "piece",
    }
    return aliases.get(u, unit)


def aggregate_ingredients(
    ingredient_lists: list[tuple[list[ParsedIngredient], float]],
    pantry_staples: list[str] | None = None,
) -> dict[str, list[dict]]:
    """Aggregate ingredients across recipes, grouped by store section.

    Args:
        ingredient_lists: list of (ingredients, scale_factor) tuples
        pantry_staples: items to subtract from the list

    Returns:
        dict of section -> list of {item, qty, unit, recipes}
    """
    pantry_set = {p.lower() for p in (pantry_staples or [])}

    # Aggregate by (normalized_item, unit)
    agg: dict[tuple[str, str], dict] = {}

    for ingredients, scale in ingredient_lists:
        for ing in ingredients:
            item_key = ing.item.lower().strip()

            # Skip pantry staples
            if any(p in item_key or item_key in p for p in pantry_set):
                continue

            unit = normalize_unit(ing.unit)
            key = (item_key, unit)

            if key not in agg:
                agg[key] = {
                    "item": ing.item.strip(),
                    "qty": 0.0,
                    "unit": unit,
                    "notes": [],
                }

            if ing.qty is not None:
                agg[key]["qty"] += ing.qty * scale
            if ing.notes and ing.notes not in agg[key]["notes"]:
                agg[key]["notes"].append(ing.notes)

    # Group by store section
    sections: dict[str, list[dict]] = defaultdict(list)
    for (_item_key, _unit), entry in sorted(agg.items()):
        section = classify_section(entry["item"])
        sections[section].append(entry)

    # Sort sections in preferred order
    ordered = {}
    section_order = [
        "Produce",
        "Meat & Seafood",
        "Dairy",
        "Pantry",
        "Spices & Condiments",
        "Frozen",
        "Other",
    ]
    for s in section_order:
        if s in sections:
            ordered[s] = sorted(sections[s], key=lambda x: x["item"].lower())
    return ordered


def format_qty(qty: float) -> str:
    """Format a quantity as a practical fraction or decimal."""
    if qty == 0:
        return ""

    # Common fractions
    fractions = {
        0.25: "1/4",
        0.33: "1/3",
        0.5: "1/2",
        0.67: "2/3",
        0.75: "3/4",
    }

    whole = int(qty)
    frac = qty - whole

    # Round fraction to nearest common value
    if frac > 0:
        closest = min(fractions.keys(), key=lambda f: abs(f - frac))
        if abs(closest - frac) < 0.1:
            frac_str = fractions[closest]
            if whole > 0:
                return f"{whole} {frac_str}"
            return frac_str

    if whole == qty:
        return str(whole)
    return f"{qty:.1f}"


def format_shopping_markdown(sections: dict[str, list[dict]]) -> str:
    """Format aggregated shopping list as markdown with checkboxes."""
    lines = ["# Shopping List", ""]

    for section, items in sections.items():
        lines.append(f"## {section}")
        lines.append("")
        for entry in items:
            qty_str = format_qty(entry["qty"]) if entry["qty"] > 0 else ""
            unit_str = f" {entry['unit']}" if entry["unit"] else ""
            notes_str = f" ({', '.join(entry['notes'])})" if entry["notes"] else ""
            if qty_str:
                lines.append(f"- [ ] {qty_str}{unit_str} {entry['item']}{notes_str}")
            else:
                lines.append(f"- [ ] {entry['item']}{notes_str}")
        lines.append("")

    return "\n".join(lines)


def format_shopping_json(sections: dict[str, list[dict]]) -> str:
    """Format aggregated shopping list as JSON."""
    return json.dumps(sections, indent=2)


def build_shopping_sections(
    plan_data: dict,
    cooking_path: Path,
    pantry_staples: list[str] | None = None,
) -> dict[str, list[dict]]:
    """Build aggregated shopping list sections from a plan JSON dict.

    Args:
        plan_data: plan JSON dict with a "slots" key
        cooking_path: path to the cooking/recipe directory
        pantry_staples: items to exclude from the list

    Returns:
        dict of section -> list of {item, qty, unit, notes}
    """
    # Build ingredient lists with scale factors
    ingredient_lists: list[tuple[list[ParsedIngredient], float]] = []

    # Group slots by recipe to combine servings
    recipe_servings: dict[str, float] = {}
    for slot in plan_data.get("slots", []):
        recipe_name = slot.get("recipe")
        if not recipe_name:
            continue
        servings = slot.get("servings", 1.0)
        recipe_servings[recipe_name] = recipe_servings.get(recipe_name, 0) + servings

    # Load each recipe's parsed ingredients
    recipe_files = {f.stem: f for f in discover_recipe_files(cooking_path)}

    for recipe_name, total_servings in recipe_servings.items():
        if recipe_name not in recipe_files:
            logger.warning("Recipe file not found: %s", recipe_name)
            continue

        recipe = parse_recipe_file(recipe_files[recipe_name])
        if not recipe or not recipe.parsed_ingredients:
            logger.warning("No parsed ingredients for: %s", recipe_name)
            continue

        # Scale factor: total_servings / base_servings
        base_servings = recipe.servings or 1
        scale = total_servings / base_servings

        # Flatten all ingredient sections
        all_items: list[ParsedIngredient] = []
        for section in recipe.parsed_ingredients:
            all_items.extend(section.items)

        ingredient_lists.append((all_items, scale))

    return aggregate_ingredients(ingredient_lists, pantry_staples or [])


def run_shopping_list(
    cooking_path: Path,
    vault_path: Path,
    plan_file: str | None = None,
    pantry: str | None = None,
    output_format: str = "markdown",
) -> None:
    """CLI entry point for shopping-list command."""
    config = load_config(vault_path)
    pantry_staples = config.get("pantry_staples", [])
    if pantry:
        pantry_staples = pantry_staples + [p.strip() for p in pantry.split(",")]

    # Load plan from file or stdin
    if plan_file:
        with open(plan_file) as f:
            plan_data = json.load(f)
    else:
        plan_data = json.load(sys.stdin)

    sections = build_shopping_sections(plan_data, cooking_path, pantry_staples)

    if not sections:
        logger.warning("No ingredients to list")
        return

    if output_format == "json":
        print(format_shopping_json(sections))
    else:
        print(format_shopping_markdown(sections))
