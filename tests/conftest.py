import pytest
from pathlib import Path
from meal_planner.models import Recipe


@pytest.fixture
def sample_recipes() -> list[Recipe]:
    """Small set of fake recipes for unit tests."""
    return [
        Recipe(name="Breakfast Slop", file_path=Path("fake/a.md"),
               calories=400, protein_g=30, meal_type="breakfast"),
        Recipe(name="Blueberry Kefir Smoothie", file_path=Path("fake/b.md"),
               calories=300, protein_g=20, meal_type="breakfast"),
        Recipe(name="Chicken Tikka Masala", file_path=Path("fake/c.md"),
               calories=550, protein_g=40, meal_type="dinner"),
        Recipe(name="Beef Stew Recipe", file_path=Path("fake/d.md"),
               calories=480, protein_g=35, meal_type="dinner"),
        Recipe(name="Caesar Salad", file_path=Path("fake/e.md"),
               calories=350, protein_g=20, meal_type="lunch"),
        Recipe(name="Tortilla Soup", file_path=Path("fake/f.md"),
               calories=300, protein_g=18, meal_type="soup"),
        Recipe(name="Granola Bar", file_path=Path("fake/g.md"),
               calories=200, protein_g=8, meal_type="snack"),
        Recipe(name="Apple Pie", file_path=Path("fake/h.md"),
               calories=350, protein_g=4, meal_type="dessert"),
    ]
