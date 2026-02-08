"""Unit tests for ingredient group normalization and table builder."""

from pathlib import Path

from meal_planner.ingredient_groups import (
    build_ingredient_group_table,
    normalize_ingredient_group,
)
from meal_planner.models import Recipe


class TestNormalizeIngredientGroup:
    def test_chicken_is_poultry(self):
        assert normalize_ingredient_group("chicken") == "poultry"

    def test_turkey_is_poultry(self):
        assert normalize_ingredient_group("turkey") == "poultry"

    def test_chicken_breast_is_poultry(self):
        assert normalize_ingredient_group("chicken breast") == "poultry"

    def test_case_insensitive(self):
        assert normalize_ingredient_group("Chicken") == "poultry"
        assert normalize_ingredient_group("BEEF") == "beef"
        assert normalize_ingredient_group("Salmon") == "seafood"

    def test_none_returns_none(self):
        assert normalize_ingredient_group(None) is None

    def test_unknown_returns_none(self):
        assert normalize_ingredient_group("pumpkin") is None
        assert normalize_ingredient_group("cauliflower") is None

    def test_beef_group(self):
        assert normalize_ingredient_group("ground beef") == "beef"
        assert normalize_ingredient_group("steak") == "beef"

    def test_pork_group(self):
        assert normalize_ingredient_group("pork chops") == "pork"
        assert normalize_ingredient_group("bacon") == "pork"
        assert normalize_ingredient_group("chorizo") == "pork"

    def test_seafood_group(self):
        assert normalize_ingredient_group("shrimp") == "seafood"
        assert normalize_ingredient_group("tilapia") == "seafood"

    def test_legumes_group(self):
        assert normalize_ingredient_group("chickpeas") == "legumes"
        assert normalize_ingredient_group("lentils") == "legumes"

    def test_whitespace_stripped(self):
        assert normalize_ingredient_group("  chicken  ") == "poultry"


def _recipe(name: str, ingredient: str | None) -> Recipe:
    return Recipe(name=name, file_path=Path(f"fake/{name}.md"), main_ingredient=ingredient)


class TestBuildIngredientGroupTable:
    def test_same_group_for_same_protein(self):
        candidates = [
            _recipe("Chicken Tikka", "chicken"),
            _recipe("Turkey Burger", "turkey"),
            _recipe("Beef Stew", "beef"),
        ]
        group_ids, num_groups, _ = build_ingredient_group_table(candidates)
        # chicken and turkey both map to poultry -> same group
        assert group_ids[0] == group_ids[1]
        # beef is different
        assert group_ids[2] != group_ids[0]

    def test_different_groups_for_different_proteins(self):
        candidates = [
            _recipe("Chicken Dish", "chicken"),
            _recipe("Beef Dish", "beef"),
            _recipe("Salmon Dish", "salmon"),
        ]
        group_ids, num_groups, _ = build_ingredient_group_table(candidates)
        assert len(set(group_ids)) == 3

    def test_none_values_get_unique_ids(self):
        candidates = [
            _recipe("Mystery A", None),
            _recipe("Mystery B", None),
        ]
        group_ids, num_groups, _ = build_ingredient_group_table(candidates)
        assert group_ids[0] != group_ids[1]

    def test_unmapped_named_values_share_ids(self):
        candidates = [
            _recipe("Pumpkin Soup", "pumpkin"),
            _recipe("Pumpkin Pie", "pumpkin"),
            _recipe("Cauliflower Steak", "cauliflower"),
        ]
        group_ids, num_groups, _ = build_ingredient_group_table(candidates)
        # Two pumpkin recipes share a group
        assert group_ids[0] == group_ids[1]
        # Cauliflower is different
        assert group_ids[2] != group_ids[0]

    def test_mixed_mapped_unmapped_none(self):
        candidates = [
            _recipe("Chicken Parm", "chicken"),
            _recipe("Pumpkin Soup", "pumpkin"),
            _recipe("Unknown", None),
        ]
        group_ids, num_groups, _ = build_ingredient_group_table(candidates)
        # All three should be different
        assert len(set(group_ids)) == 3
        assert num_groups == 3

    def test_empty_candidates(self):
        group_ids, num_groups, _ = build_ingredient_group_table([])
        assert group_ids == []
        assert num_groups == 0

    def test_group_key_to_id_contains_named_groups(self):
        candidates = [
            _recipe("Chicken Dish", "chicken"),
            _recipe("Beef Dish", "beef"),
            _recipe("Pasta Dish", "pasta"),
        ]
        _, _, group_key_to_id = build_ingredient_group_table(candidates)
        assert "group:poultry" in group_key_to_id
        assert "group:beef" in group_key_to_id
        assert "group:pasta" in group_key_to_id

    def test_group_key_to_id_consistent_with_group_ids(self):
        candidates = [
            _recipe("Chicken Dish", "chicken"),
            _recipe("Beef Dish", "beef"),
        ]
        group_ids, _, group_key_to_id = build_ingredient_group_table(candidates)
        assert group_ids[0] == group_key_to_id["group:poultry"]
        assert group_ids[1] == group_key_to_id["group:beef"]
