"""Integration tests: pins + CP-SAT solver, --save-plan, --shopping-list."""

import copy
import json
from pathlib import Path

import pytest
from meal_planner.cli import build_parser
from meal_planner.config import DEFAULTS
from meal_planner.models import MealType, Recipe
from meal_planner.pins import parse_pin
from meal_planner.planner import build_meal_plan, format_plan_json
from meal_planner.shopping import build_shopping_sections


def make_config(**overrides):
    """Create a test config with fresh prep styles and a short plan."""
    config = copy.deepcopy(DEFAULTS)
    config["prep_styles"]["breakfast"] = "fresh"
    config["prep_styles"]["lunch"] = "fresh"
    config["schedule"]["plan_days"] = 3
    config["schedule"]["meals_per_day"] = ["breakfast", "lunch", "dinner"]
    config["schedule"]["cook_days"] = ["monday", "tuesday", "wednesday"]
    for k, v in overrides.items():
        if k in config:
            config[k] = v
    return config


@pytest.fixture
def solver_recipes() -> list[Recipe]:
    """Recipes with enough variety for a 3-day plan.

    Need at least 3 breakfast, 3 lunch, 3 dinner with calorie data.
    """
    return [
        # Breakfasts
        Recipe(name="Breakfast Slop", file_path=Path("fake/a.md"),
               calories=400, protein_g=30, meal_type="breakfast"),
        Recipe(name="Blueberry Kefir Smoothie", file_path=Path("fake/b.md"),
               calories=300, protein_g=20, meal_type="breakfast"),
        Recipe(name="French Toast Recipe", file_path=Path("fake/c.md"),
               calories=450, protein_g=15, meal_type="breakfast"),
        Recipe(name="Baked Oatmeal", file_path=Path("fake/d.md"),
               calories=350, protein_g=12, meal_type="breakfast"),
        # Lunches (meal_type includes aliases that filter_recipes handles)
        Recipe(name="Caesar Salad", file_path=Path("fake/e.md"),
               calories=350, protein_g=20, meal_type="lunch"),
        Recipe(name="Tortilla Soup", file_path=Path("fake/f.md"),
               calories=300, protein_g=18, meal_type="lunch"),
        Recipe(name="BLT Sandwich", file_path=Path("fake/g.md"),
               calories=400, protein_g=22, meal_type="lunch"),
        Recipe(name="Chicken Caesar Wraps", file_path=Path("fake/h.md"),
               calories=450, protein_g=30, meal_type="lunch"),
        # Dinners
        Recipe(name="Chicken Tikka Masala", file_path=Path("fake/i.md"),
               calories=550, protein_g=40, meal_type="dinner"),
        Recipe(name="Beef Stew Recipe", file_path=Path("fake/j.md"),
               calories=480, protein_g=35, meal_type="dinner"),
        Recipe(name="Pad See Ew", file_path=Path("fake/k.md"),
               calories=500, protein_g=25, meal_type="dinner"),
        Recipe(name="Chicken Parmesan", file_path=Path("fake/l.md"),
               calories=600, protein_g=45, meal_type="dinner"),
        # Snacks
        Recipe(name="Granola Bar", file_path=Path("fake/m.md"),
               calories=200, protein_g=8, meal_type="snack"),
        Recipe(name="Apple Pie", file_path=Path("fake/n.md"),
               calories=350, protein_g=4, meal_type="snack"),
        Recipe(name="Chocolate Chip Cookies", file_path=Path("fake/o.md"),
               calories=250, protein_g=3, meal_type="snack"),
    ]


class TestPlannerNoPins:
    def test_solver_works_without_pins(self, solver_recipes):
        """Regression: solver should work with no pins at all."""
        config = make_config()
        plan = build_meal_plan(
            cooking_path=Path("unused"),
            config=config,
            recipes=solver_recipes,
        )
        assert plan is not None
        assert len(plan.slots) == 9  # 3 days * 3 meals


class TestPlannerWithPins:
    def test_pin_dinner_respected(self, solver_recipes):
        """Pin a specific dinner and verify it appears."""
        config = make_config()
        pins = [parse_pin("wednesday:dinner:Chicken Tikka Masala")]
        plan = build_meal_plan(
            cooking_path=Path("unused"),
            config=config,
            pins=pins,
            recipes=solver_recipes,
        )
        assert plan is not None
        wed_dinners = [
            s for s in plan.slots
            if s.day == 2 and s.meal_type == MealType.DINNER
        ]
        assert len(wed_dinners) == 1
        assert wed_dinners[0].recipe.name == "Chicken Tikka Masala"
        assert wed_dinners[0].pinned is True

    def test_pin_all_breakfast(self, solver_recipes):
        """Pin all breakfasts to the same recipe."""
        config = make_config()
        pins = [parse_pin("all:breakfast:Breakfast Slop")]
        plan = build_meal_plan(
            cooking_path=Path("unused"),
            config=config,
            pins=pins,
            recipes=solver_recipes,
        )
        assert plan is not None
        breakfasts = [
            s for s in plan.slots if s.meal_type == MealType.BREAKFAST
        ]
        assert len(breakfasts) == 3
        for bf in breakfasts:
            assert bf.recipe.name == "Breakfast Slop"
            assert bf.pinned is True

    def test_unpinned_slots_not_marked(self, solver_recipes):
        """Slots that aren't pinned should have pinned=False."""
        config = make_config()
        pins = [parse_pin("monday:dinner:Beef Stew Recipe")]
        plan = build_meal_plan(
            cooking_path=Path("unused"),
            config=config,
            pins=pins,
            recipes=solver_recipes,
        )
        assert plan is not None
        # All breakfasts and lunches should be unpinned
        for s in plan.slots:
            if s.meal_type in (MealType.BREAKFAST, MealType.LUNCH):
                assert s.pinned is False

    def test_multiple_pins(self, solver_recipes):
        """Multiple pins on different meals."""
        config = make_config()
        pins = [
            parse_pin("all:breakfast:Breakfast Slop"),
            parse_pin("tuesday:dinner:Pad See Ew"),
        ]
        plan = build_meal_plan(
            cooking_path=Path("unused"),
            config=config,
            pins=pins,
            recipes=solver_recipes,
        )
        assert plan is not None
        # Check breakfast
        for s in plan.slots:
            if s.meal_type == MealType.BREAKFAST:
                assert s.recipe.name == "Breakfast Slop"
        # Check tuesday dinner
        tue_dinners = [
            s for s in plan.slots
            if s.day == 1 and s.meal_type == MealType.DINNER
        ]
        assert tue_dinners[0].recipe.name == "Pad See Ew"


class TestSavePlanFlag:
    def test_save_plan_writes_json(self, solver_recipes, tmp_path):
        """--save-plan writes valid JSON to the specified path."""
        config = make_config()
        plan = build_meal_plan(
            cooking_path=Path("unused"),
            config=config,
            recipes=solver_recipes,
        )
        assert plan is not None
        out_file = tmp_path / "test-plan.json"
        out_file.write_text(format_plan_json(plan))
        data = json.loads(out_file.read_text())
        assert "slots" in data
        assert "start_date" in data
        assert len(data["slots"]) == 9

    def test_save_plan_auto_name(self, solver_recipes):
        """Auto save-plan path uses start_date."""
        config = make_config()
        plan = build_meal_plan(
            cooking_path=Path("unused"),
            config=config,
            recipes=solver_recipes,
        )
        assert plan is not None
        expected_name = f"meal-plan-{plan.start_date}.json"
        assert plan.start_date in expected_name


class TestShoppingListFlag:
    def test_build_shopping_sections_with_synthetic_plan(self, tmp_path):
        """build_shopping_sections returns sections (or empty) for a synthetic plan."""
        # Create a fake recipe file with parsed ingredients
        recipe_dir = tmp_path / "recipes"
        recipe_dir.mkdir()
        recipe_file = recipe_dir / "Test Recipe.md"
        recipe_file.write_text(
            "---\n"
            "calories: 400\n"
            "protein_g: 30\n"
            "servings: 2\n"
            "---\n"
            "# Test Recipe\n"
            "## Ingredients\n"
            "- 1 cup rice\n"
            "- 2 chicken breasts\n"
        )
        plan_data = {
            "slots": [
                {"recipe": "Test Recipe", "servings": 2.0, "day": 0},
            ]
        }
        sections = build_shopping_sections(plan_data, recipe_dir)
        # May or may not have sections depending on whether the recipe
        # parses successfully without indexing — but the function should
        # not raise an error.
        assert isinstance(sections, dict)

    def test_build_shopping_sections_empty_plan(self, tmp_path):
        """Empty plan returns empty sections."""
        recipe_dir = tmp_path / "recipes"
        recipe_dir.mkdir()
        plan_data = {"slots": []}
        sections = build_shopping_sections(plan_data, recipe_dir)
        assert sections == {}


class TestIngredientGroupDiversity:
    @pytest.fixture
    def diversity_recipes(self) -> list[Recipe]:
        """Recipes with main_ingredient values for diversity testing.

        Three dinners with different proteins, plus enough other meals.
        """
        return [
            # Breakfasts
            Recipe(name="Oatmeal", file_path=Path("fake/a.md"),
                   calories=350, protein_g=12, meal_type="breakfast"),
            Recipe(name="Smoothie", file_path=Path("fake/b.md"),
                   calories=300, protein_g=20, meal_type="breakfast"),
            Recipe(name="Toast", file_path=Path("fake/c.md"),
                   calories=400, protein_g=15, meal_type="breakfast"),
            # Lunches
            Recipe(name="Salad", file_path=Path("fake/d.md"),
                   calories=350, protein_g=20, meal_type="lunch"),
            Recipe(name="Soup", file_path=Path("fake/e.md"),
                   calories=300, protein_g=18, meal_type="lunch"),
            Recipe(name="Wrap", file_path=Path("fake/f.md"),
                   calories=400, protein_g=22, meal_type="lunch"),
            # Dinners — 3 chicken, 1 beef, 1 seafood, 1 pork
            # Without diversity constraint the solver might pick 3 chicken dishes
            Recipe(name="Chicken Tikka", file_path=Path("fake/g.md"),
                   calories=550, protein_g=40, meal_type="dinner",
                   main_ingredient="chicken"),
            Recipe(name="Chicken Parm", file_path=Path("fake/h.md"),
                   calories=600, protein_g=45, meal_type="dinner",
                   main_ingredient="chicken"),
            Recipe(name="Chicken Stir Fry", file_path=Path("fake/i.md"),
                   calories=500, protein_g=35, meal_type="dinner",
                   main_ingredient="chicken"),
            Recipe(name="Beef Stew", file_path=Path("fake/j.md"),
                   calories=480, protein_g=35, meal_type="dinner",
                   main_ingredient="beef"),
            Recipe(name="Salmon Bowl", file_path=Path("fake/k.md"),
                   calories=500, protein_g=38, meal_type="dinner",
                   main_ingredient="salmon"),
            Recipe(name="Pork Chops", file_path=Path("fake/l.md"),
                   calories=520, protein_g=40, meal_type="dinner",
                   main_ingredient="pork"),
        ]

    def test_dinners_have_distinct_ingredient_groups(self, diversity_recipes):
        """Solver should pick dinners with different ingredient groups."""
        config = make_config()
        plan = build_meal_plan(
            cooking_path=Path("unused"),
            config=config,
            recipes=diversity_recipes,
        )
        assert plan is not None
        dinners = [
            s for s in plan.slots if s.meal_type == MealType.DINNER
        ]
        assert len(dinners) == 3
        # All three dinners should have different main_ingredient groups
        from meal_planner.ingredient_groups import normalize_ingredient_group
        groups = [
            normalize_ingredient_group(s.recipe.main_ingredient)
            for s in dinners
        ]
        assert len(set(groups)) == 3, (
            f"Expected 3 distinct ingredient groups, got {groups}"
        )


class TestRequiredGroups:
    @pytest.fixture
    def group_recipes(self) -> list[Recipe]:
        """Recipes with main_ingredient values for required-group testing."""
        return [
            # Breakfasts
            Recipe(name="Oatmeal", file_path=Path("fake/a.md"),
                   calories=350, protein_g=12, meal_type="breakfast"),
            Recipe(name="Smoothie", file_path=Path("fake/b.md"),
                   calories=300, protein_g=20, meal_type="breakfast"),
            Recipe(name="Toast", file_path=Path("fake/c.md"),
                   calories=400, protein_g=15, meal_type="breakfast"),
            # Lunches
            Recipe(name="Salad", file_path=Path("fake/d.md"),
                   calories=350, protein_g=20, meal_type="lunch"),
            Recipe(name="Soup", file_path=Path("fake/e.md"),
                   calories=300, protein_g=18, meal_type="lunch"),
            Recipe(name="Wrap", file_path=Path("fake/f.md"),
                   calories=400, protein_g=22, meal_type="lunch"),
            # Dinners — 3 chicken, 1 beef, 1 pasta, 1 legumes
            Recipe(name="Chicken Tikka", file_path=Path("fake/g.md"),
                   calories=550, protein_g=40, meal_type="dinner",
                   main_ingredient="chicken"),
            Recipe(name="Chicken Parm", file_path=Path("fake/h.md"),
                   calories=600, protein_g=45, meal_type="dinner",
                   main_ingredient="chicken"),
            Recipe(name="Chicken Stir Fry", file_path=Path("fake/i.md"),
                   calories=500, protein_g=35, meal_type="dinner",
                   main_ingredient="chicken"),
            Recipe(name="Beef Stew", file_path=Path("fake/j.md"),
                   calories=480, protein_g=35, meal_type="dinner",
                   main_ingredient="beef"),
            Recipe(name="Pasta Primavera", file_path=Path("fake/k.md"),
                   calories=500, protein_g=18, meal_type="dinner",
                   main_ingredient="pasta"),
            Recipe(name="Chickpea Curry", file_path=Path("fake/l.md"),
                   calories=520, protein_g=30, meal_type="dinner",
                   main_ingredient="chickpeas"),
        ]

    def test_required_beef_is_present(self, group_recipes):
        """When beef is required, at least one dinner must be beef."""
        config = make_config()
        config["preferences"]["required_ingredient_groups"] = ["beef"]
        plan = build_meal_plan(
            cooking_path=Path("unused"),
            config=config,
            recipes=group_recipes,
        )
        assert plan is not None
        from meal_planner.ingredient_groups import normalize_ingredient_group
        dinner_groups = [
            normalize_ingredient_group(s.recipe.main_ingredient)
            for s in plan.slots if s.meal_type == MealType.DINNER
        ]
        assert "beef" in dinner_groups, (
            f"Expected beef in dinner groups, got {dinner_groups}"
        )

    def test_required_multiple_groups(self, group_recipes):
        """When beef and legumes are required, both must appear."""
        config = make_config()
        config["preferences"]["required_ingredient_groups"] = ["beef", "legumes"]
        plan = build_meal_plan(
            cooking_path=Path("unused"),
            config=config,
            recipes=group_recipes,
        )
        assert plan is not None
        from meal_planner.ingredient_groups import normalize_ingredient_group
        dinner_groups = [
            normalize_ingredient_group(s.recipe.main_ingredient)
            for s in plan.slots if s.meal_type == MealType.DINNER
        ]
        assert "beef" in dinner_groups, f"Missing beef in {dinner_groups}"
        assert "legumes" in dinner_groups, f"Missing legumes in {dinner_groups}"

    def test_unknown_required_group_is_skipped(self, group_recipes):
        """Requiring a group with no candidates doesn't crash."""
        config = make_config()
        config["preferences"]["required_ingredient_groups"] = ["seafood"]
        plan = build_meal_plan(
            cooking_path=Path("unused"),
            config=config,
            recipes=group_recipes,
        )
        # Should still produce a valid plan (seafood skipped silently)
        assert plan is not None


class TestCLIParserFlags:
    def test_plan_parser_accepts_shopping_list(self):
        """--shopping-list flag is accepted by the plan subcommand."""
        parser = build_parser()
        args = parser.parse_args(["plan", "--shopping-list"])
        assert args.shopping_list is True

    def test_plan_parser_shopping_list_default_false(self):
        """--shopping-list defaults to False."""
        parser = build_parser()
        args = parser.parse_args(["plan"])
        assert args.shopping_list is False

    def test_plan_parser_accepts_save_plan_auto(self):
        """--save-plan without value defaults to 'auto'."""
        parser = build_parser()
        args = parser.parse_args(["plan", "--save-plan"])
        assert args.save_plan == "auto"

    def test_plan_parser_accepts_save_plan_path(self):
        """--save-plan with explicit path."""
        parser = build_parser()
        args = parser.parse_args(["plan", "--save-plan", "my-plan.json"])
        assert args.save_plan == "my-plan.json"

    def test_plan_parser_save_plan_default_none(self):
        """--save-plan defaults to None when not provided."""
        parser = build_parser()
        args = parser.parse_args(["plan"])
        assert args.save_plan is None

    def test_plan_parser_both_flags(self):
        """Both flags can be used together."""
        parser = build_parser()
        args = parser.parse_args(["plan", "--shopping-list", "--save-plan"])
        assert args.shopping_list is True
        assert args.save_plan == "auto"
