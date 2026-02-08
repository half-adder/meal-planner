---
name: meal-planner
description: Generate weekly meal plans and shopping lists from Obsidian recipe notes. Creates meal preferences, plans balanced weeks, and compiles ingredient lists.
---

<objective>
Plan weekly meals from the user's Obsidian recipe database (~1,700 recipes) using the `meal-planner` CLI tool. Guide the user through preferences, generate an optimized meal plan via CP-SAT solver, iterate on swaps, and write the final plan as an Obsidian note.
</objective>

<essential_principles>

## Paths

- **Vault:** `~/obsidian-sync/Personal`
- **Recipes:** `~/obsidian-sync/Personal/03. Resources/Cooking/*.md`
- **Preferences:** `~/obsidian-sync/Personal/03. Resources/Cooking/meal-preferences.yaml`
- **Output:** `~/obsidian-sync/Personal/03. Resources/Cooking/Meal Plans/`
- **CLI project:** `~/code/meal-planner/`

## CLI Commands

Always run from `~/code/meal-planner/` using `uv run`:

```bash
# Generate meal plan (JSON for processing, markdown for display)
uv run meal-planner plan --days 7 --format json
uv run meal-planner plan --days 7 --calories 2200 --protein 150 --format markdown

# Get recipe suggestions for swaps
uv run meal-planner suggest --meal-type dinner --max-time 30 --limit 5 --format json

# Generate shopping list from plan
uv run meal-planner plan --days 7 --format json | uv run meal-planner shopping-list

# Scale a recipe
uv run meal-planner scale "Chicken Biryani" --servings 3
```

## Formatting Rules

- One blank line between markdown headers and content
- Use `[[Recipe Name]]` wikilinks for recipe references
- Use `- [ ]` checkboxes for shopping list items
- Frontmatter uses YAML with `type: meal-plan`

</essential_principles>

<process>

## Step 1: Load Preferences

Read `~/obsidian-sync/Personal/03. Resources/Cooking/meal-preferences.yaml` to understand defaults. Tell the user their current settings briefly:
- Daily targets (calories, protein)
- Cook days and prep styles
- Any dietary restrictions

## Step 2: Collect Overrides

Ask the user (concisely) if they want to change anything for this week:
- "Any changes to your usual settings? (cook days, calories target, exclusions, etc.)"
- "What do you have in the pantry this week?"

If the user says "just go" or similar, use defaults as-is.

## Step 3: Generate Plan

Run the plan command with any overrides:

```bash
cd ~/code/meal-planner && uv run meal-planner plan --days 7 --format json
```

Parse the JSON output. Present the plan to the user as a readable markdown table showing each day's meals, calories, and protein. Include daily totals and weekly averages.

## Step 4: Iterate

Ask: "Want to swap any meals?"

If the user wants to swap a recipe:
1. Run `suggest` with appropriate filters to find alternatives
2. Present 3-5 options with scores
3. Let the user pick
4. Update the plan data accordingly and re-display

Repeat until the user is satisfied.

## Step 5: Generate Shopping List

Once the plan is approved, generate the shopping list:

```bash
echo '<plan-json>' | cd ~/code/meal-planner && uv run meal-planner shopping-list
```

Present the shopping list grouped by store section with checkboxes.

## Step 6: Write Obsidian Note

Write the final plan to `~/obsidian-sync/Personal/03. Resources/Cooking/Meal Plans/` as a markdown file named `YYYY-MM-DD Meal Plan.md` (using the plan's start date).

Use the output template below. The note should include:
1. Frontmatter with plan metadata
2. Daily meal tables with wikilinked recipes
3. Weekly summary with macro averages
4. Shopping list with checkboxes

</process>

<output_template>

```markdown
---
type: meal-plan
date_created: {{today}}
start_date: {{start_date}}
end_date: {{end_date}}
daily_calories_target: {{calories}}
daily_protein_target: {{protein}}
---

# Meal Plan: {{start_date}} to {{end_date}}

## Monday

| Meal | Recipe | Servings | Calories | Protein | Prep |
|------|--------|----------|----------|---------|------|
| Breakfast | [[Recipe Name]] | 1.5x | 450 | 30g | batch |
| Lunch | [[Recipe Name]] | 1.0x | 600 | 45g | leftover |
| Dinner | [[Recipe Name]] | 2.0x | 800 | 55g | fresh |
| **Total** | | | **1850** | **130g** | |

<!-- repeat for each day -->

## Weekly Summary

- Average daily calories: {{avg_cal}}/day (target: {{calories}})
- Average daily protein: {{avg_pro}}g/day (target: {{protein}}g)
- Cook sessions: {{cook_count}}
- Unique recipes: {{unique_count}}

## Shopping List

### Produce

- [ ] 2 lb chicken breast
- [ ] 3 cups broccoli

### Dairy

- [ ] 1 cup shredded cheese

<!-- grouped by section -->
```

</output_template>

<success_criteria>
- Plan written to Obsidian vault at the correct path
- Daily calories within 10% of target
- Daily protein within 15% of target
- All recipe names are valid wikilinks to existing files
- Shopping list is complete with quantities scaled to planned servings
- User approved the plan before writing
</success_criteria>
