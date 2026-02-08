"""Haiku-powered ingredient parsing with frontmatter caching."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import anthropic
import frontmatter

from meal_planner.indexer import compute_ingredients_hash
from meal_planner.models import IngredientSection, ParsedIngredient, Recipe

HAIKU_MODEL = "claude-haiku-4-5-20251001"

PARSE_PROMPT = """\
Parse these recipe ingredients into structured JSON. Return a JSON array of section objects.

Rules:
- Each section has "section" (string or null if no section header) and "items" (array)
- Each item has: "qty" (number or null), "unit" (string or null), "item" (string), "notes" (string or null)
- Convert fractions to decimals: 1/2 = 0.5, 1/3 = 0.333, 1/4 = 0.25, 2/3 = 0.667, 3/4 = 0.75, ⅓ = 0.333, ½ = 0.5
- For "1 (13.5oz) can coconut milk": qty=1, unit="can", item="coconut milk", notes="13.5oz"
- For "60 g (4 tablespoons) vegetable oil": qty=60, unit="g", item="vegetable oil", notes="4 tablespoons"
- For "salt and pepper to taste": qty=null, unit=null, item="salt and pepper", notes="to taste"
- For "Juice from 1/2 of a lemon": qty=0.5, unit="whole", item="lemon", notes="juiced"
- For "Pinch of kosher salt": qty=1, unit="pinch", item="kosher salt"
- Section headers include lines like "**For the Sauce:**", "**Crumb Mixture**", "Chicken + Marinade:", "Toppings (85%):" — extract just the meaningful name
- Skip empty lines and lines that are only "(Optional)" — attach optional to previous item's notes
- For lines with no quantity like "Kosher salt": qty=null, unit=null, item="kosher salt", notes=null

Return ONLY valid JSON, no markdown fences, no explanation.

Ingredients:
"""


def call_haiku(raw_ingredients: str) -> list[dict] | None:
    """Call Claude Haiku to parse raw ingredient text into structured JSON."""
    client = anthropic.Anthropic()

    try:
        response = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": PARSE_PROMPT + raw_ingredients,
                }
            ],
        )
        text = response.content[0].text.strip()

        # Strip markdown fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[: text.rfind("```")]
            text = text.strip()

        return json.loads(text)
    except (anthropic.APIError, json.JSONDecodeError, IndexError, KeyError) as e:
        print(f"  Haiku parse error: {e}", file=sys.stderr)
        return None


def parsed_to_frontmatter_format(sections: list[dict]) -> list[dict]:
    """Convert Haiku response into the YAML-friendly format for frontmatter."""
    result = []
    for section in sections:
        items = []
        for item in section.get("items", []):
            entry: dict = {
                "qty": item.get("qty"),
                "unit": item.get("unit"),
                "item": item.get("item", ""),
            }
            if item.get("notes"):
                entry["notes"] = item["notes"]
            items.append(entry)
        result.append(
            {
                "section": section.get("section"),
                "items": items,
            }
        )
    return result


def write_parsed_to_file(
    file_path: Path,
    parsed_ingredients: list[dict],
    ingredients_hash: str,
) -> None:
    """Write parsed_ingredients and ingredients_hash back to recipe frontmatter."""
    post = frontmatter.load(file_path)
    post.metadata["parsed_ingredients"] = parsed_ingredients
    post.metadata["ingredients_hash"] = ingredients_hash

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(frontmatter.dumps(post))
        f.write("\n")


def parse_all_ingredients(
    recipes: list[Recipe],
    cooking_path: Path,
    force: bool = False,
    verbose: bool = False,
) -> None:
    """Parse ingredients for all recipes using Claude Haiku."""
    need_parsing: list[Recipe] = []

    for recipe in recipes:
        if not recipe.raw_ingredients:
            continue

        current_hash = compute_ingredients_hash(recipe.raw_ingredients)

        if not force and recipe.ingredients_hash == current_hash and recipe.parsed_ingredients:
            if verbose:
                print(f"  SKIP (hash match): {recipe.name}", file=sys.stderr)
            continue

        recipe._pending_hash = current_hash  # type: ignore[attr-defined]
        need_parsing.append(recipe)

    if not need_parsing:
        print("All recipes already parsed. Use --force to re-parse.", file=sys.stderr)
        return

    print(f"Parsing {len(need_parsing)} recipes with Haiku...", file=sys.stderr)

    parsed_count = 0
    error_count = 0

    for i, recipe in enumerate(need_parsing):
        if verbose:
            print(
                f"  [{i + 1}/{len(need_parsing)}] {recipe.name}...",
                file=sys.stderr,
                end=" ",
            )

        sections = call_haiku(recipe.raw_ingredients)

        if sections is None:
            error_count += 1
            if verbose:
                print("FAILED", file=sys.stderr)
            continue

        fm_data = parsed_to_frontmatter_format(sections)
        current_hash = recipe._pending_hash  # type: ignore[attr-defined]

        write_parsed_to_file(recipe.file_path, fm_data, current_hash)

        parsed_count += 1
        if verbose:
            total_items = sum(len(s.get("items", [])) for s in sections)
            print(f"OK ({total_items} ingredients)", file=sys.stderr)

        # Small delay to avoid rate limits
        if i < len(need_parsing) - 1:
            time.sleep(0.05)

    print(
        f"Done: {parsed_count} parsed, {error_count} errors, "
        f"{len(recipes) - len(need_parsing)} skipped (already parsed).",
        file=sys.stderr,
    )
