"""Haiku-powered ingredient parsing via Claude CLI with frontmatter caching."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

import frontmatter

from meal_planner.indexer import compute_ingredients_hash
from meal_planner.log import stderr_console
from meal_planner.models import Recipe

logger = logging.getLogger(__name__)

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

BATCH_PARSE_PROMPT = """\
Parse the ingredients for each recipe below into structured JSON. Each recipe is delimited by a header line.

Return a single JSON object where each key is the recipe number (as a string like "0", "1", etc.) and each value is a JSON array of section objects for that recipe.

Rules for each recipe's ingredient list:
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

"""


def _call_haiku_raw(prompt: str, timeout: int = 120) -> str | None:
    """Call Claude Haiku via CLI and return raw text output, or None on failure."""
    try:
        result = subprocess.run(
            ["claude", "--model", "haiku", "-p"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            logger.error("claude CLI error: %s", result.stderr.strip())
            return None

        text = result.stdout.strip()

        # Strip markdown fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[: text.rfind("```")]
            text = text.strip()

        return text
    except subprocess.TimeoutExpired:
        logger.error("claude CLI timed out after %ds", timeout)
        return None
    except FileNotFoundError:
        logger.error("'claude' CLI not found. Install it first.")
        return None


def call_haiku(raw_ingredients: str) -> list[dict] | None:
    """Call Claude Haiku via the claude CLI to parse ingredients."""
    text = _call_haiku_raw(PARSE_PROMPT + raw_ingredients, timeout=60)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.error("JSON parse error: %s", e)
        return None


def call_haiku_batch(
    recipes: list[tuple[str, str]],
    batch_size: int = 10,
) -> dict[int, list[dict] | None]:
    """Parse ingredients for multiple recipes in batched CLI calls.

    Args:
        recipes: list of (recipe_name, raw_ingredients) tuples
        batch_size: number of recipes per CLI call

    Returns:
        dict mapping original index -> parsed sections or None
    """
    results: dict[int, list[dict] | None] = {}

    for batch_start in range(0, len(recipes), batch_size):
        batch = recipes[batch_start : batch_start + batch_size]
        batch_indices = list(range(batch_start, batch_start + len(batch)))

        # Build batched prompt
        parts = []
        for i, (name, raw) in enumerate(batch):
            parts.append(f"===== RECIPE {i}: {name} =====")
            parts.append(raw)
            parts.append("")

        prompt = BATCH_PARSE_PROMPT + "\n".join(parts)
        text = _call_haiku_raw(prompt, timeout=120)

        if text is not None:
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    all_ok = True
                    for i, orig_idx in enumerate(batch_indices):
                        key = str(i)
                        if key in parsed and isinstance(parsed[key], list):
                            results[orig_idx] = parsed[key]
                        else:
                            all_ok = False
                    if all_ok:
                        continue  # batch succeeded, move to next
            except json.JSONDecodeError as e:
                logger.error("Batch JSON parse error: %s", e)

        # Fallback: parse individually for this batch
        logger.debug(
            "Falling back to individual parsing for batch at index %d", batch_start
        )
        for i, (name, raw) in enumerate(batch):
            orig_idx = batch_indices[i]
            if orig_idx not in results:
                results[orig_idx] = call_haiku(raw)

    return results


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


def _fetch_batch(batch: list[Recipe]) -> dict[int, list[dict]]:
    """Call Haiku for a batch of recipes and return parsed results.

    Returns a dict mapping batch-local index -> parsed sections.
    Missing keys indicate failures that need individual fallback.
    """
    parts = []
    for i, recipe in enumerate(batch):
        parts.append(f"===== RECIPE {i}: {recipe.name} =====")
        parts.append(recipe.raw_ingredients)
        parts.append("")

    prompt = BATCH_PARSE_PROMPT + "\n".join(parts)
    text = _call_haiku_raw(prompt, timeout=120)

    results: dict[int, list[dict]] = {}
    if text is not None:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                for i in range(len(batch)):
                    key = str(i)
                    if key in parsed and isinstance(parsed[key], list):
                        results[i] = parsed[key]
        except json.JSONDecodeError as e:
            logger.error("Batch JSON parse error: %s", e)

    return results


def parse_all_ingredients(
    recipes: list[Recipe],
    cooking_path: Path,
    force: bool = False,
    batch_size: int = 10,
    max_workers: int = 4,
) -> None:
    """Parse ingredients for all recipes using Claude Haiku via CLI."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeRemainingColumn,
    )

    need_parsing: list[Recipe] = []

    for recipe in recipes:
        if not recipe.raw_ingredients:
            continue

        current_hash = compute_ingredients_hash(recipe.raw_ingredients)

        if (
            not force
            and recipe.ingredients_hash == current_hash
            and recipe.parsed_ingredients
        ):
            logger.debug("SKIP (hash match): %s", recipe.name)
            continue

        recipe._pending_hash = current_hash  # type: ignore[attr-defined]
        need_parsing.append(recipe)

    if not need_parsing:
        logger.info("All recipes already parsed. Use --force to re-parse.")
        return

    logger.info("Parsing %d recipes with Haiku...", len(need_parsing))

    # Split into batches
    batches: list[list[Recipe]] = []
    for start in range(0, len(need_parsing), batch_size):
        batches.append(need_parsing[start : start + batch_size])

    parsed_count = 0
    error_count = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("[green]{task.fields[ok]}[/green] ok"),
        TextColumn("[red]{task.fields[fail]}[/red] fail"),
        TimeRemainingColumn(),
        console=stderr_console,
    ) as progress:
        task = progress.add_task(
            "Parsing ingredients",
            total=len(need_parsing),
            ok=0,
            fail=0,
        )

        # Submit all batches to thread pool
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_batch = {
                executor.submit(_fetch_batch, batch): batch for batch in batches
            }

            for future in as_completed(future_to_batch):
                batch = future_to_batch[future]
                batch_results = future.result()

                # Process each recipe in this batch
                for i, recipe in enumerate(batch):
                    sections = batch_results.get(i)

                    # Fallback: parse individually if batch missed this recipe
                    if sections is None:
                        logger.debug(
                            "Falling back to individual parse: %s", recipe.name
                        )
                        sections = call_haiku(recipe.raw_ingredients)

                    if sections is None:
                        error_count += 1
                        logger.debug("FAILED: %s", recipe.name)
                        progress.update(task, advance=1, fail=error_count)
                        continue

                    fm_data = parsed_to_frontmatter_format(sections)
                    current_hash = recipe._pending_hash  # type: ignore[attr-defined]
                    write_parsed_to_file(recipe.file_path, fm_data, current_hash)

                    parsed_count += 1
                    total_items = sum(len(s.get("items", [])) for s in sections)
                    logger.debug("OK: %s (%d ingredients)", recipe.name, total_items)
                    progress.update(task, advance=1, ok=parsed_count)

    logger.info(
        "Done: %d parsed, %d errors, %d skipped (already parsed)",
        parsed_count,
        error_count,
        len(recipes) - len(need_parsing),
    )
