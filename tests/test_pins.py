import pytest
from meal_planner.models import MealType
from meal_planner.pins import (
    PinPattern, PinSpec, parse_pin, expand_pin_days,
    find_recipe, resolve_pins,
)


class TestParsePins:
    def test_single_day(self):
        pin = parse_pin("monday:breakfast:Breakfast Slop")
        assert pin.day == 0
        assert pin.meal_type == MealType.BREAKFAST
        assert pin.recipe_query == "Breakfast Slop"
        assert pin.pattern == PinPattern.SINGLE

    def test_all_pattern(self):
        pin = parse_pin("all:dinner:Chicken Tikka")
        assert pin.day is None
        assert pin.pattern == PinPattern.ALL

    def test_even_odd(self):
        even = parse_pin("even:breakfast:Slop")
        odd = parse_pin("odd:snack:Granola Bar")
        assert even.pattern == PinPattern.EVEN
        assert odd.pattern == PinPattern.ODD

    def test_case_insensitive(self):
        pin = parse_pin("Monday:BREAKFAST:Breakfast Slop")
        assert pin.day == 0
        assert pin.meal_type == MealType.BREAKFAST

    def test_recipe_with_colons(self):
        pin = parse_pin("all:dinner:Recipe: A Subtitle")
        assert pin.recipe_query == "Recipe: A Subtitle"

    def test_invalid_day(self):
        with pytest.raises(ValueError, match="Unknown day"):
            parse_pin("badday:breakfast:Foo")

    def test_invalid_meal(self):
        with pytest.raises(ValueError, match="Unknown meal type"):
            parse_pin("monday:brunch:Foo")

    def test_empty_recipe(self):
        with pytest.raises(ValueError, match="Empty recipe"):
            parse_pin("monday:breakfast:")

    def test_bad_format(self):
        with pytest.raises(ValueError, match="Invalid pin format"):
            parse_pin("just-a-string")


class TestExpandDays:
    def test_single(self):
        pin = PinSpec(day=2, meal_type=MealType.DINNER, recipe_query="X", pattern=PinPattern.SINGLE)
        assert expand_pin_days(pin, 7) == [2]

    def test_all(self):
        pin = PinSpec(day=None, meal_type=MealType.DINNER, recipe_query="X", pattern=PinPattern.ALL)
        assert expand_pin_days(pin, 7) == [0, 1, 2, 3, 4, 5, 6]

    def test_even(self):
        pin = PinSpec(day=None, meal_type=MealType.DINNER, recipe_query="X", pattern=PinPattern.EVEN)
        assert expand_pin_days(pin, 7) == [0, 2, 4, 6]

    def test_odd(self):
        pin = PinSpec(day=None, meal_type=MealType.DINNER, recipe_query="X", pattern=PinPattern.ODD)
        assert expand_pin_days(pin, 7) == [1, 3, 5]

    def test_day_out_of_range(self):
        pin = PinSpec(day=10, meal_type=MealType.DINNER, recipe_query="X", pattern=PinPattern.SINGLE)
        assert expand_pin_days(pin, 7) == []


class TestFindRecipe:
    def test_exact_match(self, sample_recipes):
        candidates = sample_recipes[:4]
        r, idx, injected = find_recipe("Breakfast Slop", candidates, sample_recipes)
        assert r.name == "Breakfast Slop"
        assert not injected

    def test_substring_match(self, sample_recipes):
        candidates = sample_recipes[:4]
        r, idx, injected = find_recipe("Tikka", candidates, sample_recipes)
        assert r.name == "Chicken Tikka Masala"
        assert not injected

    def test_injection_from_all(self, sample_recipes):
        candidates = sample_recipes[:2]  # only breakfast recipes
        r, idx, injected = find_recipe("Caesar Salad", candidates, sample_recipes)
        assert r.name == "Caesar Salad"
        assert injected
        assert idx == 2  # appended to end
        assert len(candidates) == 3  # mutated

    def test_not_found(self, sample_recipes):
        with pytest.raises(ValueError, match="No recipe found"):
            find_recipe("Nonexistent Recipe", sample_recipes[:2], sample_recipes)


class TestResolvePins:
    def test_conflict_detection(self, sample_recipes):
        pins = [
            parse_pin("monday:dinner:Chicken Tikka Masala"),
            parse_pin("monday:dinner:Beef Stew Recipe"),
        ]
        candidates = {"dinner": sample_recipes[2:4]}
        with pytest.raises(ValueError, match="Conflicting pins"):
            resolve_pins(pins, candidates, sample_recipes, 7)

    def test_batch_breakfast_rejects_single_day(self, sample_recipes):
        pins = [parse_pin("monday:breakfast:Breakfast Slop")]
        candidates = {"breakfast": sample_recipes[:2]}
        with pytest.raises(ValueError, match="batch mode"):
            resolve_pins(pins, candidates, sample_recipes, 7, batch_breakfast=True)

    def test_batch_breakfast_allows_all(self, sample_recipes):
        pins = [parse_pin("all:breakfast:Breakfast Slop")]
        candidates = {"breakfast": sample_recipes[:2]}
        resolved = resolve_pins(pins, candidates, sample_recipes, 7, batch_breakfast=True)
        assert len(resolved) == 1
        assert resolved[0].days == list(range(7))
