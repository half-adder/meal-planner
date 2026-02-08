"""Tests for the recipe renderer (scaled recipes in plan output)."""

from pathlib import Path

import pytest
from meal_planner.models import (
    IngredientSection,
    MealPlan,
    MealSlot,
    MealType,
    ParsedIngredient,
    PrepStyle,
    Recipe,
)
from meal_planner.recipe_renderer import extract_directions, render_plan_recipes


@pytest.fixture
def recipe_dir(tmp_path):
    """Create a temp directory with recipe markdown files that have parsed ingredients."""
    # Chicken Fried Rice
    cfr = tmp_path / "Chicken Fried Rice.md"
    cfr.write_text(
        "---\n"
        "type: recipe\n"
        "calories: 500\n"
        "protein_g: 23\n"
        "servings: 4\n"
        "meal_type: dinner\n"
        "parsed_ingredients:\n"
        "- items:\n"
        "  - item: garlic\n"
        "    notes: minced\n"
        "    qty: 2\n"
        "    unit: cloves\n"
        "  - item: chicken breast\n"
        "    qty: 1\n"
        "    unit: whole\n"
        "  - item: cooking oil\n"
        "    qty: 3\n"
        "    unit: Tbsp\n"
        "  section: null\n"
        "---\n"
        "\n"
        "## Chicken Fried Rice\n"
        "\n"
        "### Ingredients\n"
        "\n"
        "- 2 cloves garlic, minced\n"
        "- 1 chicken breast\n"
        "- 3 Tbsp cooking oil\n"
        "\n"
        "### Directions\n"
        "\n"
        "1. Dice the chicken into small pieces.\n"
        "2. Heat oil in a pan over medium-high heat.\n"
        "3. Add garlic and cook until fragrant.\n"
        "\n"
        "### Nutrition\n"
        "\n"
        "- Calories: 500\n"
    )

    # Lemon Ricotta Pasta
    lrp = tmp_path / "Lemon Ricotta Pasta.md"
    lrp.write_text(
        "---\n"
        "type: recipe\n"
        "calories: 400\n"
        "protein_g: 18\n"
        "servings: 4\n"
        "meal_type: dinner\n"
        "parsed_ingredients:\n"
        "- items:\n"
        "  - item: pasta\n"
        "    qty: 8\n"
        "    unit: oz\n"
        "  - item: ricotta\n"
        "    qty: 1\n"
        "    unit: cup\n"
        "  - item: lemon\n"
        "    qty: 1\n"
        "    unit: whole\n"
        "  section: null\n"
        "---\n"
        "\n"
        "## Lemon Ricotta Pasta\n"
        "\n"
        "### Ingredients\n"
        "\n"
        "- 8 oz pasta\n"
        "- 1 cup ricotta\n"
        "- 1 lemon\n"
        "\n"
        "### Directions\n"
        "\n"
        "1. Cook pasta according to package directions.\n"
        "2. Mix ricotta with lemon zest and juice.\n"
        "3. Toss pasta with ricotta mixture.\n"
    )

    # No-ingredients recipe (for fallback test)
    nir = tmp_path / "Mystery Dish.md"
    nir.write_text(
        "---\n"
        "type: recipe\n"
        "calories: 300\n"
        "protein_g: 15\n"
        "meal_type: dinner\n"
        "---\n"
        "\n"
        "## Mystery Dish\n"
        "\n"
        "Just wing it.\n"
    )

    return tmp_path


def _make_plan(slots: list[MealSlot]) -> MealPlan:
    return MealPlan(
        start_date="2026-02-09",
        end_date="2026-02-11",
        days=3,
        calories_target=3500,
        protein_target=160,
        slots=slots,
    )


class TestExtractDirections:
    def test_extracts_directions_section(self, recipe_dir):
        path = recipe_dir / "Chicken Fried Rice.md"
        directions = extract_directions(path)
        assert directions is not None
        assert "Dice the chicken" in directions
        assert "Heat oil" in directions

    def test_stops_at_next_heading(self, recipe_dir):
        path = recipe_dir / "Chicken Fried Rice.md"
        directions = extract_directions(path)
        assert "Calories" not in directions

    def test_returns_none_for_missing_directions(self, recipe_dir):
        path = recipe_dir / "Mystery Dish.md"
        directions = extract_directions(path)
        assert directions is None

    def test_returns_none_for_missing_file(self, tmp_path):
        path = tmp_path / "nonexistent.md"
        directions = extract_directions(path)
        assert directions is None


class TestRenderPlanRecipes:
    def test_renders_recipes_section(self, recipe_dir):
        cfr = Recipe(
            name="Chicken Fried Rice", file_path=recipe_dir / "Chicken Fried Rice.md",
            calories=500, protein_g=23, meal_type="dinner",
        )
        plan = _make_plan([
            MealSlot(day=0, day_name="Monday", meal_type=MealType.DINNER,
                     prep_style=PrepStyle.FRESH, recipe=cfr, servings=2.0),
        ])
        output = render_plan_recipes(plan, recipe_dir)
        assert "## Recipes" in output
        assert "### Chicken Fried Rice (2.0x)" in output
        assert "#### Ingredients" in output
        assert "#### Directions" in output

    def test_deduplication(self, recipe_dir):
        cfr = Recipe(
            name="Chicken Fried Rice", file_path=recipe_dir / "Chicken Fried Rice.md",
            calories=500, protein_g=23, meal_type="dinner",
        )
        plan = _make_plan([
            MealSlot(day=0, day_name="Monday", meal_type=MealType.DINNER,
                     prep_style=PrepStyle.FRESH, recipe=cfr, servings=2.0),
            MealSlot(day=1, day_name="Tuesday", meal_type=MealType.DINNER,
                     prep_style=PrepStyle.LEFTOVER, recipe=cfr, servings=2.0),
        ])
        output = render_plan_recipes(plan, recipe_dir)
        # Recipe should appear only once
        assert output.count("### Chicken Fried Rice (2.0x)") == 1

    def test_ingredients_are_scaled(self, recipe_dir):
        cfr = Recipe(
            name="Chicken Fried Rice", file_path=recipe_dir / "Chicken Fried Rice.md",
            calories=500, protein_g=23, meal_type="dinner",
        )
        # 2.0x servings on a 4-serving recipe = 8 servings = 2x scale
        plan = _make_plan([
            MealSlot(day=0, day_name="Monday", meal_type=MealType.DINNER,
                     prep_style=PrepStyle.FRESH, recipe=cfr, servings=2.0),
        ])
        output = render_plan_recipes(plan, recipe_dir)
        # Original: 2 cloves garlic -> 2.0x = 4 cloves
        assert "4 cloves garlic" in output

    def test_multiple_recipes(self, recipe_dir):
        cfr = Recipe(
            name="Chicken Fried Rice", file_path=recipe_dir / "Chicken Fried Rice.md",
            calories=500, protein_g=23, meal_type="dinner",
        )
        lrp = Recipe(
            name="Lemon Ricotta Pasta", file_path=recipe_dir / "Lemon Ricotta Pasta.md",
            calories=400, protein_g=18, meal_type="dinner",
        )
        plan = _make_plan([
            MealSlot(day=0, day_name="Monday", meal_type=MealType.DINNER,
                     prep_style=PrepStyle.FRESH, recipe=cfr, servings=2.0),
            MealSlot(day=1, day_name="Tuesday", meal_type=MealType.DINNER,
                     prep_style=PrepStyle.FRESH, recipe=lrp, servings=1.5),
        ])
        output = render_plan_recipes(plan, recipe_dir)
        assert "### Chicken Fried Rice (2.0x)" in output
        assert "### Lemon Ricotta Pasta (1.5x)" in output

    def test_missing_ingredients_handled(self, recipe_dir):
        mystery = Recipe(
            name="Mystery Dish", file_path=recipe_dir / "Mystery Dish.md",
            calories=300, protein_g=15, meal_type="dinner",
        )
        plan = _make_plan([
            MealSlot(day=0, day_name="Monday", meal_type=MealType.DINNER,
                     prep_style=PrepStyle.FRESH, recipe=mystery, servings=1.0),
        ])
        output = render_plan_recipes(plan, recipe_dir)
        assert "### Mystery Dish (1.0x)" in output
        assert "not available" in output

    def test_empty_plan(self, recipe_dir):
        plan = _make_plan([])
        output = render_plan_recipes(plan, recipe_dir)
        assert output == ""


class TestCLIRecipesFlag:
    def test_plan_parser_accepts_recipes(self):
        from meal_planner.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["plan", "--recipes"])
        assert args.recipes is True

    def test_plan_parser_recipes_default_false(self):
        from meal_planner.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["plan"])
        assert args.recipes is False


class TestCLIRequireGroupFlag:
    def test_plan_parser_accepts_require_group(self):
        from meal_planner.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["plan", "--require-group", "beef"])
        assert args.require_group == ["beef"]

    def test_plan_parser_require_group_repeatable(self):
        from meal_planner.cli import build_parser

        parser = build_parser()
        args = parser.parse_args([
            "plan", "--require-group", "beef", "--require-group", "poultry",
        ])
        assert args.require_group == ["beef", "poultry"]

    def test_plan_parser_require_group_default_empty(self):
        from meal_planner.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["plan"])
        assert args.require_group == []
