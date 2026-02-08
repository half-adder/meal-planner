"""Recipe indexing: parse frontmatter, extract ingredients, normalize fields."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

import frontmatter

from meal_planner.models import (
    IngredientSection,
    ParsedIngredient,
    Recipe,
)

logger = logging.getLogger(__name__)


def normalize_servings(raw: str | int | float | None) -> int | None:
    """Parse varied servings formats into an integer.

    Handles: "Serves 4", "4", "4 servings", "Servings: 4",
    "4 to 6 servings" (midpoint), "1 Bowl" -> 1, "" -> None.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return int(raw) if raw > 0 else None

    s = str(raw).strip()
    if not s:
        return None

    # "Serves 4", "Servings: 4"
    m = re.search(r"(?:serves?|servings?:?)\s*(\d+)", s, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # "4 to 6 servings" or "4-6 servings"
    m = re.match(r"(\d+)\s*(?:to|-)\s*(\d+)", s)
    if m:
        return (int(m.group(1)) + int(m.group(2))) // 2

    # "4 servings", "4 portions", "4 bowls"
    m = re.match(r"(\d+)\s*\w*", s)
    if m:
        val = int(m.group(1))
        if val > 0:
            return val

    return None


def normalize_time(raw: str | int | float | None) -> int | None:
    """Parse varied time formats into integer minutes.

    Handles: "10 minutes", "5 mins", "5 min", 15, "3 hours",
    "1 hour 30 minutes", "" -> None.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return int(raw) if raw > 0 else None

    s = str(raw).strip()
    if not s:
        return None

    total = 0

    # Hours
    m = re.search(r"(\d+)\s*(?:hours?|hrs?|h)\b", s, re.IGNORECASE)
    if m:
        total += int(m.group(1)) * 60

    # Minutes
    m = re.search(r"(\d+)\s*(?:minutes?|mins?|m)\b", s, re.IGNORECASE)
    if m:
        total += int(m.group(1))

    if total > 0:
        return total

    # Bare number
    m = re.match(r"(\d+)$", s)
    if m:
        return int(m.group(1))

    return None


def extract_ingredients_section(content: str) -> str | None:
    """Extract the raw ingredients text from markdown body.

    Looks for ## Ingredients or ### Ingredients and captures everything
    until the next heading of equal or higher level.
    """
    lines = content.split("\n")
    in_section = False
    section_level = 0
    result: list[str] = []

    for line in lines:
        # Check for ingredients heading
        m = re.match(r"^(#{2,3})\s+Ingredients", line, re.IGNORECASE)
        if m and not in_section:
            in_section = True
            section_level = len(m.group(1))
            continue

        if in_section:
            # Check if we hit another heading at same or higher level
            heading_match = re.match(r"^(#{1,%d})\s+" % section_level, line)
            if heading_match:
                break
            result.append(line)

    if not result:
        return None

    text = "\n".join(result).strip()
    return text if text else None


def compute_ingredients_hash(raw_ingredients: str) -> str:
    """Compute a stable hash of raw ingredient text."""
    normalized = raw_ingredients.strip().lower()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def parse_recipe_file(file_path: Path) -> Recipe | None:
    """Parse a single recipe markdown file into a Recipe object."""
    try:
        post = frontmatter.load(file_path)
    except Exception:
        return None

    meta = post.metadata
    if meta.get("type") != "recipe":
        return None

    name = file_path.stem

    # Extract raw ingredients from body
    raw_ingredients = extract_ingredients_section(post.content)

    # Parse existing parsed_ingredients from frontmatter if present
    parsed_ingredients: list[IngredientSection] = []
    if "parsed_ingredients" in meta and meta["parsed_ingredients"]:
        for section_data in meta["parsed_ingredients"]:
            if isinstance(section_data, dict):
                items = []
                for item_data in section_data.get("items", []):
                    items.append(
                        ParsedIngredient(
                            qty=item_data.get("qty"),
                            unit=item_data.get("unit"),
                            item=item_data.get("item", ""),
                            notes=item_data.get("notes"),
                        )
                    )
                parsed_ingredients.append(
                    IngredientSection(
                        section=section_data.get("section"),
                        items=items,
                    )
                )

    # Parse rating
    rating = None
    raw_rating = meta.get("rating")
    if raw_rating:
        try:
            rating = float(raw_rating)
        except (ValueError, TypeError):
            pass

    # Parse dietary tags
    dietary_tags = meta.get("dietary_tags", []) or []
    if isinstance(dietary_tags, str):
        dietary_tags = [t.strip() for t in dietary_tags.split(",")]

    # Parse categories
    categories = meta.get("categories", []) or []
    if isinstance(categories, str):
        categories = [c.strip() for c in categories.split(",")]

    return Recipe(
        name=name,
        file_path=file_path,
        calories=_to_float(meta.get("calories")),
        protein_g=_to_float(meta.get("protein_g")),
        fat_g=_to_float(meta.get("fat_g")),
        carbs_g=_to_float(meta.get("carbs_g")),
        fiber_g=_to_float(meta.get("fiber_g")),
        servings=normalize_servings(meta.get("servings")),
        prep_time_min=normalize_time(meta.get("prep_time")),
        cook_time_min=normalize_time(meta.get("cook_time")),
        total_time_min=normalize_time(meta.get("total_time")),
        meal_type=_to_str(meta.get("meal_type")),
        cuisine=_to_str(meta.get("cuisine")),
        main_ingredient=_to_str(meta.get("main_ingredient")),
        cooking_method=_to_str(meta.get("cooking_method")),
        dietary_tags=dietary_tags,
        categories=categories,
        rating=rating,
        quick_recipe=bool(meta.get("quick_recipe")),
        tried=bool(meta.get("tried")),
        favorite=bool(meta.get("favorite")),
        last_made=_to_str(meta.get("last_made")),
        parsed_ingredients=parsed_ingredients,
        ingredients_hash=meta.get("ingredients_hash"),
        raw_ingredients=raw_ingredients,
    )


def _to_float(val: object) -> float | None:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _to_str(val: object) -> str | None:
    if val is None or val == "":
        return None
    return str(val).strip()


def discover_recipe_files(cooking_path: Path, limit: int | None = None) -> list[Path]:
    """Find all .md files in the cooking directory."""
    files = sorted(cooking_path.glob("*.md"))
    if limit:
        files = files[:limit]
    return files


def run_index(
    cooking_path: Path,
    dry_run: bool = False,
    limit: int | None = None,
    force: bool = False,
    skip_api: bool = False,
) -> None:
    """Run the index command."""
    files = discover_recipe_files(cooking_path, limit=limit)

    stats = {
        "total_files": len(files),
        "parsed_ok": 0,
        "parse_errors": 0,
        "with_ingredients": 0,
        "with_nutrition": 0,
        "with_parsed_ingredients": 0,
        "servings_parsed": 0,
        "servings_unparseable": 0,
    }

    recipes: list[Recipe] = []

    for f in files:
        recipe = parse_recipe_file(f)
        if recipe is None:
            stats["parse_errors"] += 1
            logger.debug("SKIP (not a recipe or parse error): %s", f.name)
            continue

        stats["parsed_ok"] += 1
        recipes.append(recipe)

        if recipe.raw_ingredients:
            stats["with_ingredients"] += 1
        if recipe.calories is not None and recipe.protein_g is not None:
            stats["with_nutrition"] += 1
        if recipe.parsed_ingredients:
            stats["with_parsed_ingredients"] += 1
        if recipe.servings is not None:
            stats["servings_parsed"] += 1
        else:
            stats["servings_unparseable"] += 1

        logger.debug(
            "%s: servings=%s cal=%s protein=%s time=%smin ingredients=%s",
            recipe.name,
            recipe.servings,
            recipe.calories,
            recipe.protein_g,
            recipe.total_time_min,
            "yes" if recipe.raw_ingredients else "no",
        )

    if dry_run:
        print(json.dumps(stats, indent=2))
        return

    # If not dry_run and not skip_api, we'll do Haiku parsing (Task 2)
    if not skip_api:
        from meal_planner.haiku_parser import parse_all_ingredients

        parse_all_ingredients(recipes, cooking_path, force=force)
    else:
        logger.info("Skipping API parsing (--skip-api)")

    print(json.dumps(stats, indent=2))
