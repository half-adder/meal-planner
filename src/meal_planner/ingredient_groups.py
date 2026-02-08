"""Ingredient group normalization and lookup table for diversity constraints."""

from __future__ import annotations

from meal_planner.models import Recipe

# Map raw main_ingredient values (lowercased) to canonical group names.
INGREDIENT_GROUP_MAP: dict[str, str] = {
    # Poultry
    "chicken": "poultry",
    "turkey": "poultry",
    "chicken breast": "poultry",
    "chicken thigh": "poultry",
    "chicken thighs": "poultry",
    "chicken drumsticks": "poultry",
    "chicken wings": "poultry",
    "ground turkey": "poultry",
    "ground chicken": "poultry",
    # Beef
    "beef": "beef",
    "ground beef": "beef",
    "steak": "beef",
    "beef stew meat": "beef",
    "corned beef": "beef",
    # Pork
    "pork": "pork",
    "pork chops": "pork",
    "pork loin": "pork",
    "ground pork": "pork",
    "ham": "pork",
    "bacon": "pork",
    "sausage": "pork",
    "chorizo": "pork",
    "bratwurst": "pork",
    # Seafood
    "salmon": "seafood",
    "shrimp": "seafood",
    "fish": "seafood",
    "tilapia": "seafood",
    "tuna": "seafood",
    "crab": "seafood",
    "cod": "seafood",
    # Legumes
    "beans": "legumes",
    "black beans": "legumes",
    "chickpeas": "legumes",
    "lentils": "legumes",
    "kidney beans": "legumes",
    "pinto beans": "legumes",
    "white beans": "legumes",
    "black-eyed peas": "legumes",
    # Tofu / plant protein
    "tofu": "tofu",
    "tempeh": "tofu",
    # Pasta
    "pasta": "pasta",
    "spaghetti": "pasta",
    "rigatoni": "pasta",
    "penne": "pasta",
    "ravioli": "pasta",
    "tortellini": "pasta",
    "gnocchi": "pasta",
    "noodles": "pasta",
    # Grains
    "rice": "grains",
    "quinoa": "grains",
    "barley": "grains",
    "farro": "grains",
    "oats": "grains",
    # Eggs
    "eggs": "eggs",
    "egg": "eggs",
}


def normalize_ingredient_group(main_ingredient: str | None) -> str | None:
    """Return the canonical group name for a main_ingredient, or None."""
    if main_ingredient is None:
        return None
    return INGREDIENT_GROUP_MAP.get(main_ingredient.lower().strip())


def build_ingredient_group_table(
    candidates: list[Recipe],
) -> tuple[list[int], int, dict[str, int]]:
    """Build a candidate-index -> group-id lookup table.

    Returns (group_ids, num_groups, group_key_to_id) where group_ids[i] is the
    group id for candidate i, and group_key_to_id maps "group:<name>" keys to
    their integer IDs.

    Grouping rules:
    - Named groups (in INGREDIENT_GROUP_MAP): consistent ID by group name.
    - Unmapped but non-None ingredients: consistent ID by raw lowered value
      (e.g., two "pumpkin" recipes share a group).
    - None ingredients: unique ID per recipe (never collide with each other).
    """
    # Assign IDs: first pass collects all distinct group keys
    group_key_to_id: dict[str, int] = {}
    next_id = 0

    group_ids: list[int] = []
    for recipe in candidates:
        group = normalize_ingredient_group(recipe.main_ingredient)
        if group is not None:
            # Named group
            key = f"group:{group}"
        elif recipe.main_ingredient is not None:
            # Unmapped but present — group by raw value
            key = f"raw:{recipe.main_ingredient.lower().strip()}"
        else:
            # None — unique per recipe
            key = f"none:{next_id}"

        if key not in group_key_to_id:
            group_key_to_id[key] = next_id
            next_id += 1

        group_ids.append(group_key_to_id[key])

    return group_ids, next_id, group_key_to_id
