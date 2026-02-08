# Scaled Recipes in Meal Plan Output

## Problem

The meal plan markdown shows recipe names with serving multipliers (e.g., "Chicken Fried Rice (2.0x)") but the user must click through wikilinks to see ingredients and directions. For meal prep, having everything in one document is more practical.

## Solution

Add a `--recipes` flag to `meal-planner plan` that inserts a "Recipes" section into the markdown output with each unique recipe's scaled ingredients and cooking directions.

## Output Structure

```
# Meal Plan: ...
## Monday / Tuesday / ... (daily tables)
## Weekly Summary

## Recipes

### Chicken Fried Rice (2.0x)
#### Ingredients
- 4 cloves garlic, minced
- 2 tsp grated fresh ginger
...
#### Directions
1. Prepare the vegetables ...

### Lemon Ricotta Pasta (2.5x)
...

---
# Shopping List
```

Each unique recipe appears once at its plan serving multiplier. Recipes are deduplicated — if the same recipe at the same scale appears on multiple days, it's listed once.

## Changes

### 1. `src/meal_planner/cli.py`

Add `--recipes` flag to the plan subcommand:

```python
p_plan.add_argument("--recipes", action="store_true", default=False,
                     help="Include scaled recipes in plan output")
```

Pass through to `run_plan()`.

### 2. `src/meal_planner/planner.py` — `run_plan()`

Add `recipes: bool = False` parameter. After printing `format_plan_markdown(plan)` but before the shopping list block:

```python
if recipes and output_format != "json":
    from meal_planner.recipe_renderer import render_plan_recipes
    recipes_md = render_plan_recipes(plan, cooking_path)
    if recipes_md:
        print(recipes_md)
```

For JSON format, add a `recipes` key to the JSON output with structured recipe data.

### 3. New module: `src/meal_planner/recipe_renderer.py`

Responsible for extracting and formatting scaled recipes from a MealPlan.

```python
def render_plan_recipes(plan: MealPlan, cooking_path: Path) -> str:
    """Render scaled recipes section for the meal plan markdown."""
```

Logic:
1. Collect unique `(recipe_name, servings)` pairs from `plan.slots` (skip duplicates)
2. For each, load the Recipe via `load_all_recipes()` or direct file read
3. Call `scale_recipe(recipe, target_servings)` from `scaler.py` to get scaled ingredients
4. Extract directions from the recipe's raw markdown file (regex for `### Directions` section)
5. Format as markdown: `### Recipe Name (Nx)\n#### Ingredients\n...\n#### Directions\n...`
6. Return the full `## Recipes\n\n...` section

#### Extracting directions from recipe files

Directions are not stored in the Recipe model — they live in the markdown body. Extract with:

```python
def extract_directions(file_path: Path) -> str | None:
    """Extract the Directions section from a recipe markdown file."""
```

Parse the markdown after frontmatter, find the `### Directions` heading, and capture everything until the next `###` heading or EOF.

### 4. `src/meal_planner/scaler.py`

No changes needed — `scale_recipe()` already returns scaled ingredient data. The new `recipe_renderer.py` module calls it directly.

### 5. Tests: `tests/test_recipe_renderer.py`

- `test_render_produces_recipes_section` — synthetic plan with 2 recipes, verify output contains `## Recipes` and both recipe names
- `test_deduplication` — same recipe on multiple days appears once
- `test_ingredients_are_scaled` — verify quantities are multiplied
- `test_directions_extracted` — verify directions section is present
- `test_missing_directions_handled` — recipe without directions section still renders ingredients

### 6. Skill workflow update

Update `workflows/generate-meal-plan.md` to always pass `--recipes` flag in the CLI command.

## Files

| File | Action |
|------|--------|
| `src/meal_planner/recipe_renderer.py` | CREATE |
| `src/meal_planner/cli.py` | MODIFY (add --recipes flag) |
| `src/meal_planner/planner.py` | MODIFY (pass recipes flag, call renderer) |
| `tests/test_recipe_renderer.py` | CREATE |
| `workflows/generate-meal-plan.md` (skill) | MODIFY (add --recipes to CLI command) |

## Verification

```bash
cd /Users/sean/Code/meal-planner
uv run pytest tests/ -v
uv run meal-planner plan --recipes --shopping-list --days 3 --cook-days "monday,tuesday,wednesday"
# Verify: Recipes section appears between Weekly Summary and Shopping List
# Verify: Ingredients are scaled, directions are present
```
