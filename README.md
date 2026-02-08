# meal-planner

Weekly meal planning from Obsidian recipe notes with CP-SAT optimization.

Reads a database of recipe markdown files (with YAML frontmatter for nutrition, servings, cook time, etc.), runs constraint-based optimization to generate balanced weekly meal plans, and outputs shopping lists.

## Features

- **Constraint-optimized planning** — Google OR-Tools CP-SAT solver minimizes calorie/protein deviation while enforcing variety, prep style, and cook day constraints
- **Multi-serving scoring** — Tests 1x through 3x servings per recipe to find the best macro fit
- **Smart ingredient parsing** — Uses Claude Haiku (via CLI) to parse free-text ingredient lists into structured `{qty, unit, item, notes}` data, cached in recipe frontmatter
- **Shopping list generation** — Aggregates and scales ingredients across the plan, groups by store section, subtracts pantry staples
- **Recipe scaling** — Fuzzy-match recipes by name and scale to any serving count with practical fraction rounding
- **Claude Code skill** — Conversational `/meal-plan` command for interactive planning with recipe swaps

## Installation

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/yourusername/meal-planner.git
cd meal-planner
uv sync
```

Or install as a tool:

```bash
uv tool install git+https://github.com/yourusername/meal-planner.git
```

## Configuration

Create `meal-preferences.yaml` in your recipe directory:

```yaml
nutrition:
  daily_calories: 2200
  daily_protein_g: 150
  meal_allocation:
    breakfast: 0.25
    lunch: 0.35
    dinner: 0.40

prep_styles:
  breakfast: batch     # batch | fresh | leftover
  lunch: leftover      # typically dinner leftovers
  dinner: fresh        # cook fresh each time

schedule:
  cook_days: [sunday, wednesday]
  meals_per_day: [breakfast, lunch, dinner]
  plan_days: 7

preferences:
  max_prep_time_minutes: 60
  max_batch_time_minutes: 120
  dietary_tags: []
  cuisines_excluded: []
  ingredients_excluded: []

pantry_staples:
  - salt
  - black pepper
  - olive oil
  - butter
  - garlic
  - onion
  - rice
  - eggs
  - soy sauce
```

All settings have built-in defaults and can be overridden via CLI flags.

## Recipe Format

Recipes are markdown files with YAML frontmatter:

```markdown
---
type: recipe
calories: 450
protein_g: 35
servings: 4
total_time: 30 minutes
meal_type: dinner
cuisine: Mexican
dietary_tags: [gluten-free]
---

## Ingredients

- 1 lb chicken breast
- 2 cups rice
- 1 can black beans
```

The `type: recipe` field is required. Nutrition fields (`calories`, `protein_g`) are per serving.

## CLI Usage

### Index recipes

Parse all recipe files and optionally run Haiku ingredient extraction:

```bash
# Dry run — show stats without modifying files
uv run meal-planner index --dry-run

# Parse all and extract ingredients via Claude Haiku
uv run meal-planner index

# Skip API calls, just parse frontmatter
uv run meal-planner index --skip-api

# Force re-parse even if ingredients haven't changed
uv run meal-planner index --force --limit 50
```

### Suggest recipes

Filter and rank recipes with multi-dimensional scoring:

```bash
# Quick dinners
uv run meal-planner suggest --meal-type dinner --max-time 30 --limit 5

# High-protein options
uv run meal-planner suggest --min-protein 40 --format json

# With pantry ingredients for overlap scoring
uv run meal-planner suggest --meal-type lunch --available-ingredients "chicken,rice,beans"
```

### Generate meal plan

Run the CP-SAT optimizer to build a balanced weekly plan:

```bash
# Use defaults from preferences file
uv run meal-planner plan

# Override targets
uv run meal-planner plan --calories 1800 --protein 120 --days 5

# Different cook schedule
uv run meal-planner plan --cook-days "monday,thursday,saturday"

# JSON output for piping
uv run meal-planner plan --format json
```

### Shopping list

Generate an aggregated shopping list from a plan:

```bash
# Pipe from plan
uv run meal-planner plan --format json | uv run meal-planner shopping-list

# From file
uv run meal-planner shopping-list --plan-file plan.json

# Add extra pantry items to subtract
uv run meal-planner shopping-list --plan-file plan.json --pantry "flour,sugar"
```

### Scale a recipe

Scale ingredient quantities to a target serving count:

```bash
uv run meal-planner scale "Chicken Biryani" --servings 2
uv run meal-planner scale "vegetable curry" --servings 8 --format json
```

## Architecture

```
src/meal_planner/
├── cli.py          # argparse entry point with subcommands
├── models.py       # Recipe, MealSlot, MealPlan dataclasses
├── indexer.py      # Frontmatter parsing, ingredient extraction
├── haiku_parser.py # Claude Haiku ingredient parsing via CLI
├── config.py       # Preferences loading with defaults + overrides
├── suggest.py      # Filtering + multi-dimension scoring
├── planner.py      # CP-SAT constraint optimization
├── shopping.py     # Ingredient aggregation + store section grouping
└── scaler.py       # Recipe scaling with fraction rounding
```

### How the planner works

1. **Pre-filter** — Reduces ~1,700 recipes to ~50-200 candidates per meal type based on hard filters (meal type, dietary tags, time constraints)
2. **Model** — CP-SAT solver assigns recipes to meal slots with serving multipliers (1x-3x), respecting batch/leftover/fresh prep styles and cook day schedules
3. **Optimize** — Minimizes weighted calorie and protein deviation from targets, with variety enforced via AllDifferent constraints on cook-day recipes
4. **Extract** — Solution maps back to recipe objects with serving counts and macro totals

### Ingredient parsing

The `index` command optionally calls Claude Haiku (via the `claude` CLI) to parse free-text ingredient lines into structured data:

```yaml
parsed_ingredients:
  - section: null
    items:
      - qty: 1
        unit: lb
        item: chicken breast
      - qty: 2
        unit: cups
        item: rice
```

Results are cached in recipe frontmatter with a SHA-256 hash of the raw text. Re-running `index` skips recipes whose ingredients haven't changed.

## Claude Code Skill

For interactive planning, symlink the skill into Claude Code:

```bash
ln -s ~/code/meal-planner/skill ~/.claude/skills/global/meal-planner
```

Then use `/meal-plan` in Claude Code for a conversational workflow: review preferences, generate plan, swap recipes, and write the final note to your vault.

## Vault Path

By default, looks for recipes at `~/obsidian-sync/Personal/03. Resources/Cooking/`. Override with:

```bash
uv run meal-planner --vault-path /path/to/vault plan
```
