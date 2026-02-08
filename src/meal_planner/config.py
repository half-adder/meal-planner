"""Preferences loading with defaults and CLI override merging."""

from __future__ import annotations

from pathlib import Path

import yaml

DEFAULT_COOKING_DIR = "03. Resources/Cooking"

DEFAULTS = {
    "nutrition": {
        "daily_calories": 2200,
        "daily_protein_g": 150,
        "meal_allocation": {
            "breakfast": 0.20,
            "lunch": 0.30,
            "dinner": 0.35,
            "snack": 0.15,
        },
    },
    "prep_styles": {
        "breakfast": "batch",
        "lunch": "leftover",
        "dinner": "fresh",
        "snack": "fresh",
    },
    "schedule": {
        "cook_days": ["sunday", "wednesday"],
        "meals_per_day": ["breakfast", "lunch", "dinner", "snack"],
        "plan_days": 7,
    },
    "preferences": {
        "max_prep_time_minutes": 60,
        "max_batch_time_minutes": 120,
        "dietary_tags": [],
        "cuisines_excluded": [],
        "ingredients_excluded": [],
    },
    "pantry_staples": [
        "salt",
        "black pepper",
        "olive oil",
        "butter",
        "garlic",
        "onion",
        "rice",
        "eggs",
        "soy sauce",
    ],
}


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(vault_path: Path) -> dict:
    """Load meal preferences from YAML file, falling back to defaults."""
    config_path = vault_path / DEFAULT_COOKING_DIR / "meal-preferences.yaml"

    if config_path.exists():
        with open(config_path) as f:
            user_config = yaml.safe_load(f) or {}
        return deep_merge(DEFAULTS, user_config)

    return DEFAULTS.copy()


def apply_cli_overrides(config: dict, **overrides: object) -> dict:
    """Apply CLI argument overrides to config.

    Supports flat keys that map into nested config:
      calories -> nutrition.daily_calories
      protein -> nutrition.daily_protein_g
      cook_days -> schedule.cook_days
      days -> schedule.plan_days
    """
    if overrides.get("calories") is not None:
        config["nutrition"]["daily_calories"] = overrides["calories"]
    if overrides.get("protein") is not None:
        config["nutrition"]["daily_protein_g"] = overrides["protein"]
    if overrides.get("cook_days") is not None:
        days_str = str(overrides["cook_days"])
        config["schedule"]["cook_days"] = [d.strip().lower() for d in days_str.split(",")]
    if overrides.get("days") is not None:
        config["schedule"]["plan_days"] = overrides["days"]

    return config
