"""Weekly meal plan optimization using OR-Tools CP-SAT solver."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

from ortools.sat.python import cp_model

from meal_planner.config import apply_cli_overrides, load_config
from meal_planner.ingredient_groups import build_ingredient_group_table
from meal_planner.models import MealPlan, MealSlot, MealType, PrepStyle, Recipe
from meal_planner.pins import PinSpec, ResolvedPin, resolve_pins
from meal_planner.suggest import filter_recipes, load_all_recipes

logger = logging.getLogger(__name__)

DAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


def get_day_index(day_name: str) -> int:
    """Convert day name to 0-indexed (Monday=0)."""
    mapping = {d.lower(): i for i, d in enumerate(DAY_NAMES)}
    return mapping.get(day_name.lower(), -1)


def build_meal_plan(
    cooking_path: Path,
    config: dict,
    pantry_items: list[str] | None = None,
    exclude: list[str] | None = None,
    pins: list[PinSpec] | None = None,
    recipes: list[Recipe] | None = None,
) -> MealPlan | None:
    """Build an optimized weekly meal plan using CP-SAT."""
    num_days = config["schedule"]["plan_days"]
    daily_cal = config["nutrition"]["daily_calories"]
    daily_pro = config["nutrition"]["daily_protein_g"]
    meal_alloc = config["nutrition"]["meal_allocation"]
    cook_day_names = config["schedule"]["cook_days"]
    prep_styles = config["prep_styles"]
    max_fresh_time = config["preferences"]["max_prep_time_minutes"]
    max_batch_time = config["preferences"]["max_batch_time_minutes"]
    dietary = config["preferences"].get("dietary_tags") or None

    cook_day_indices = set()
    for d in cook_day_names:
        idx = get_day_index(d)
        if idx >= 0 and idx < num_days:
            cook_day_indices.add(idx)

    # Load all recipes
    all_recipes = recipes if recipes is not None else load_all_recipes(cooking_path)

    # Pre-filter candidates per meal type
    breakfast_candidates = filter_recipes(
        all_recipes,
        meal_type="breakfast",
        max_time=max_batch_time
        if prep_styles["breakfast"] == "batch"
        else max_fresh_time,
        dietary_tags=dietary,
        exclude=exclude,
    )
    # For lunch/dinner, include broader categories
    lunch_candidates = filter_recipes(
        all_recipes,
        meal_type="lunch",
        max_time=max_fresh_time,
        dietary_tags=dietary,
        exclude=exclude,
    )
    dinner_candidates = filter_recipes(
        all_recipes,
        meal_type="dinner",
        max_time=max_fresh_time,
        dietary_tags=dietary,
        exclude=exclude,
    )

    # Filter to recipes with calorie data (needed for optimization)
    breakfast_candidates = [r for r in breakfast_candidates if r.calories is not None]
    lunch_candidates = [r for r in lunch_candidates if r.calories is not None]
    dinner_candidates = [r for r in dinner_candidates if r.calories is not None]

    if not breakfast_candidates:
        logger.warning("No breakfast candidates found, using all recipes with calories")
        breakfast_candidates = [r for r in all_recipes if r.calories is not None]
    if not dinner_candidates:
        logger.warning("No dinner candidates found, using all recipes with calories")
        dinner_candidates = [r for r in all_recipes if r.calories is not None]
    if not lunch_candidates:
        # Lunch can draw from dinner candidates too
        lunch_candidates = list(dinner_candidates)

    # Snack candidates (broader pool: snack, appetizer, dessert, side)
    snacks_enabled = "snack" in config["schedule"]["meals_per_day"]
    snack_candidates: list[Recipe] = []
    if snacks_enabled:
        snack_candidates = filter_recipes(
            all_recipes,
            meal_type="snack",
            max_time=max_fresh_time,
            dietary_tags=dietary,
            exclude=exclude,
        )
        snack_candidates = [r for r in snack_candidates if r.calories is not None]
        if not snack_candidates:
            logger.warning("No snack candidates found, using all recipes with calories")
            snack_candidates = [r for r in all_recipes if r.calories is not None]

    # For batch breakfast: one recipe for all days
    batch_breakfast = prep_styles["breakfast"] == "batch"

    # Resolve pins (may inject recipes into candidate lists)
    resolved_pins: list[ResolvedPin] = []
    if pins:
        candidates_by_meal = {
            "breakfast": breakfast_candidates,
            "lunch": lunch_candidates,
            "dinner": dinner_candidates,
            "snack": snack_candidates,
        }
        resolved_pins = resolve_pins(
            pins, candidates_by_meal, all_recipes, num_days, batch_breakfast
        )

    # Per-meal calorie/protein targets
    targets = {}
    for meal in ["breakfast", "lunch", "dinner"] + (["snack"] if snacks_enabled else []):
        targets[meal] = {
            "cal": daily_cal * meal_alloc[meal],
            "pro": daily_pro * meal_alloc[meal],
        }

    # Serving options (fixed-point: multiply by 10 internally)
    SERVING_OPTIONS = [5, 10, 15, 20, 25, 30, 35, 40]  # 0.5, 1.0 .. 4.0

    # Build CP-SAT model
    model = cp_model.CpModel()

    # Decision variables

    # Breakfast variables
    if batch_breakfast:
        bf_recipe = model.new_int_var(0, len(breakfast_candidates) - 1, "bf_recipe")
        bf_servings = model.new_int_var_from_domain(
            cp_model.Domain.from_values(SERVING_OPTIONS), "bf_servings"
        )
    else:
        bf_recipe_vars = []
        bf_serving_vars = []
        for d in range(num_days):
            bf_recipe_vars.append(
                model.new_int_var(0, len(breakfast_candidates) - 1, f"bf_recipe_d{d}")
            )
            bf_serving_vars.append(
                model.new_int_var_from_domain(
                    cp_model.Domain.from_values(SERVING_OPTIONS), f"bf_servings_d{d}"
                )
            )

    # Dinner variables (only on cook days for fresh style)
    dinner_recipe_vars = {}
    dinner_serving_vars = {}
    for d in range(num_days):
        if prep_styles["dinner"] == "fresh" and d not in cook_day_indices:
            continue  # Non-cook days get leftovers
        dinner_recipe_vars[d] = model.new_int_var(
            0, len(dinner_candidates) - 1, f"dn_recipe_d{d}"
        )
        dinner_serving_vars[d] = model.new_int_var_from_domain(
            cp_model.Domain.from_values(SERVING_OPTIONS), f"dn_servings_d{d}"
        )

    # Leftover serving variables (for variable leftover portions)
    dinner_lo_serving_vars: dict[int, object] = {}
    lunch_lo_serving_vars: dict[int, object] = {}

    # Lunch variables
    lunch_recipe_vars = {}
    lunch_serving_vars = {}
    lunch_is_leftover = prep_styles["lunch"] == "leftover"
    for d in range(num_days):
        if lunch_is_leftover:
            # Lunch comes from previous day's dinner or same day if cook day
            continue
        lunch_recipe_vars[d] = model.new_int_var(
            0, len(lunch_candidates) - 1, f"ln_recipe_d{d}"
        )
        lunch_serving_vars[d] = model.new_int_var_from_domain(
            cp_model.Domain.from_values(SERVING_OPTIONS), f"ln_servings_d{d}"
        )

    # Snack variables (one per day, always fresh — no batch/leftover logic)
    snack_recipe_vars: dict[int, object] = {}
    snack_serving_vars: dict[int, object] = {}
    if snacks_enabled:
        for d in range(num_days):
            snack_recipe_vars[d] = model.new_int_var(
                0, len(snack_candidates) - 1, f"sn_recipe_d{d}"
            )
            snack_serving_vars[d] = model.new_int_var_from_domain(
                cp_model.Domain.from_values(SERVING_OPTIONS), f"sn_servings_d{d}"
            )

    # Apply pin constraints
    pinned_days: dict[str, set[int]] = {}  # meal_type -> set of pinned day indices
    for rpin in resolved_pins:
        meal_key = rpin.meal_type.value
        pinned_days.setdefault(meal_key, set()).update(rpin.days)

        for d in rpin.days:
            if rpin.meal_type == MealType.BREAKFAST:
                if batch_breakfast:
                    model.add(bf_recipe == rpin.candidate_index)
                else:
                    model.add(bf_recipe_vars[d] == rpin.candidate_index)
            elif rpin.meal_type == MealType.DINNER:
                if d in dinner_recipe_vars:
                    model.add(dinner_recipe_vars[d] == rpin.candidate_index)
                else:
                    logger.warning("Day %d is a leftover day for dinner, pin skipped", d)
            elif rpin.meal_type == MealType.LUNCH:
                if d in lunch_recipe_vars:
                    model.add(lunch_recipe_vars[d] == rpin.candidate_index)
                else:
                    logger.warning("Lunch on day %d is leftover mode, pin skipped", d)
            elif rpin.meal_type == MealType.SNACK:
                if d in snack_recipe_vars:
                    model.add(snack_recipe_vars[d] == rpin.candidate_index)
                else:
                    logger.warning("Snacks not enabled, pin for day %d skipped", d)

    # Objective: minimize calorie and protein deviation
    # We use element constraints to look up recipe calories/protein
    cal_penalty_terms = []
    pro_penalty_terms = []

    # Scale factor for fixed-point arithmetic (calories * 10 to match serving encoding)
    SCALE = 10

    # Pre-compute calorie/protein tables (scaled by SCALE)
    bf_cal_table = [int((r.calories or 0) * SCALE) for r in breakfast_candidates]
    bf_pro_table = [int((r.protein_g or 0) * SCALE) for r in breakfast_candidates]
    dn_cal_table = [int((r.calories or 0) * SCALE) for r in dinner_candidates]
    dn_pro_table = [int((r.protein_g or 0) * SCALE) for r in dinner_candidates]
    ln_cal_table = [int((r.calories or 0) * SCALE) for r in lunch_candidates]
    ln_pro_table = [int((r.protein_g or 0) * SCALE) for r in lunch_candidates]

    if snacks_enabled:
        sn_cal_table = [int((r.calories or 0) * SCALE) for r in snack_candidates]
        sn_pro_table = [int((r.protein_g or 0) * SCALE) for r in snack_candidates]

    for d in range(num_days):
        day_cal_terms = []
        day_pro_terms = []

        # Breakfast contribution
        if batch_breakfast:
            bf_base_cal = model.new_int_var(
                0, max(bf_cal_table) + 1, f"bf_base_cal_d{d}"
            )
            model.add_element(bf_recipe, bf_cal_table, bf_base_cal)
            bf_meal_cal = model.new_int_var(0, 100000, f"bf_meal_cal_d{d}")
            model.add_multiplication_equality(bf_meal_cal, [bf_base_cal, bf_servings])
            day_cal_terms.append(bf_meal_cal)

            bf_base_pro = model.new_int_var(
                0, max(bf_pro_table) + 1, f"bf_base_pro_d{d}"
            )
            model.add_element(bf_recipe, bf_pro_table, bf_base_pro)
            bf_meal_pro = model.new_int_var(0, 100000, f"bf_meal_pro_d{d}")
            model.add_multiplication_equality(bf_meal_pro, [bf_base_pro, bf_servings])
            day_pro_terms.append(bf_meal_pro)
        else:
            bf_base_cal = model.new_int_var(
                0, max(bf_cal_table) + 1, f"bf_base_cal_d{d}"
            )
            model.add_element(bf_recipe_vars[d], bf_cal_table, bf_base_cal)
            bf_meal_cal = model.new_int_var(0, 100000, f"bf_meal_cal_d{d}")
            model.add_multiplication_equality(
                bf_meal_cal, [bf_base_cal, bf_serving_vars[d]]
            )
            day_cal_terms.append(bf_meal_cal)

            bf_base_pro = model.new_int_var(
                0, max(bf_pro_table) + 1, f"bf_base_pro_d{d}"
            )
            model.add_element(bf_recipe_vars[d], bf_pro_table, bf_base_pro)
            bf_meal_pro = model.new_int_var(0, 100000, f"bf_meal_pro_d{d}")
            model.add_multiplication_equality(
                bf_meal_pro, [bf_base_pro, bf_serving_vars[d]]
            )
            day_pro_terms.append(bf_meal_pro)

        # Dinner contribution
        if d in dinner_recipe_vars:
            dn_base_cal = model.new_int_var(
                0, max(dn_cal_table) + 1, f"dn_base_cal_d{d}"
            )
            model.add_element(dinner_recipe_vars[d], dn_cal_table, dn_base_cal)
            dn_meal_cal = model.new_int_var(0, 100000, f"dn_meal_cal_d{d}")
            model.add_multiplication_equality(
                dn_meal_cal, [dn_base_cal, dinner_serving_vars[d]]
            )
            day_cal_terms.append(dn_meal_cal)

            dn_base_pro = model.new_int_var(
                0, max(dn_pro_table) + 1, f"dn_base_pro_d{d}"
            )
            model.add_element(dinner_recipe_vars[d], dn_pro_table, dn_base_pro)
            dn_meal_pro = model.new_int_var(0, 100000, f"dn_meal_pro_d{d}")
            model.add_multiplication_equality(
                dn_meal_pro, [dn_base_pro, dinner_serving_vars[d]]
            )
            day_pro_terms.append(dn_meal_pro)
        else:
            # Leftover dinner from nearest previous cook day
            prev_cook = None
            for cd in sorted(dinner_recipe_vars.keys(), reverse=True):
                if cd < d:
                    prev_cook = cd
                    break
            if prev_cook is None:
                # Wrap around to last cook day
                prev_cook = (
                    max(dinner_recipe_vars.keys()) if dinner_recipe_vars else None
                )

            if prev_cook is not None:
                lo_serving = model.new_int_var_from_domain(
                    cp_model.Domain.from_values(SERVING_OPTIONS),
                    f"dn_lo_servings_d{d}",
                )
                dinner_lo_serving_vars[d] = lo_serving
                dn_base_cal = model.new_int_var(
                    0, max(dn_cal_table) + 1, f"dn_lo_base_cal_d{d}"
                )
                model.add_element(
                    dinner_recipe_vars[prev_cook], dn_cal_table, dn_base_cal
                )
                dn_meal_cal = model.new_int_var(0, 100000, f"dn_lo_meal_cal_d{d}")
                model.add_multiplication_equality(
                    dn_meal_cal, [dn_base_cal, lo_serving]
                )
                day_cal_terms.append(dn_meal_cal)

                dn_base_pro = model.new_int_var(
                    0, max(dn_pro_table) + 1, f"dn_lo_base_pro_d{d}"
                )
                model.add_element(
                    dinner_recipe_vars[prev_cook], dn_pro_table, dn_base_pro
                )
                dn_meal_pro = model.new_int_var(0, 100000, f"dn_lo_meal_pro_d{d}")
                model.add_multiplication_equality(
                    dn_meal_pro, [dn_base_pro, lo_serving]
                )
                day_pro_terms.append(dn_meal_pro)

        # Lunch contribution
        if d in lunch_recipe_vars:
            ln_base_cal = model.new_int_var(
                0, max(ln_cal_table) + 1, f"ln_base_cal_d{d}"
            )
            model.add_element(lunch_recipe_vars[d], ln_cal_table, ln_base_cal)
            ln_meal_cal = model.new_int_var(0, 100000, f"ln_meal_cal_d{d}")
            model.add_multiplication_equality(
                ln_meal_cal, [ln_base_cal, lunch_serving_vars[d]]
            )
            day_cal_terms.append(ln_meal_cal)

            ln_base_pro = model.new_int_var(
                0, max(ln_pro_table) + 1, f"ln_base_pro_d{d}"
            )
            model.add_element(lunch_recipe_vars[d], ln_pro_table, ln_base_pro)
            ln_meal_pro = model.new_int_var(0, 100000, f"ln_meal_pro_d{d}")
            model.add_multiplication_equality(
                ln_meal_pro, [ln_base_pro, lunch_serving_vars[d]]
            )
            day_pro_terms.append(ln_meal_pro)
        elif lunch_is_leftover:
            # Lunch from previous dinner leftovers
            source_day = d - 1 if d > 0 else num_days - 1
            source_cook = None
            for cd in sorted(dinner_recipe_vars.keys(), reverse=True):
                if cd <= source_day:
                    source_cook = cd
                    break
            if source_cook is None:
                source_cook = (
                    max(dinner_recipe_vars.keys()) if dinner_recipe_vars else None
                )

            if source_cook is not None:
                lo_serving = model.new_int_var_from_domain(
                    cp_model.Domain.from_values(SERVING_OPTIONS),
                    f"ln_lo_servings_d{d}",
                )
                lunch_lo_serving_vars[d] = lo_serving
                ln_base_cal = model.new_int_var(
                    0, max(dn_cal_table) + 1, f"ln_lo_base_cal_d{d}"
                )
                model.add_element(
                    dinner_recipe_vars[source_cook], dn_cal_table, ln_base_cal
                )
                ln_meal_cal = model.new_int_var(0, 100000, f"ln_lo_meal_cal_d{d}")
                model.add_multiplication_equality(
                    ln_meal_cal, [ln_base_cal, lo_serving]
                )
                day_cal_terms.append(ln_meal_cal)

                ln_base_pro = model.new_int_var(
                    0, max(dn_pro_table) + 1, f"ln_lo_base_pro_d{d}"
                )
                model.add_element(
                    dinner_recipe_vars[source_cook], dn_pro_table, ln_base_pro
                )
                ln_meal_pro = model.new_int_var(0, 100000, f"ln_lo_meal_pro_d{d}")
                model.add_multiplication_equality(
                    ln_meal_pro, [ln_base_pro, lo_serving]
                )
                day_pro_terms.append(ln_meal_pro)

        # Snack contribution
        if snacks_enabled and d in snack_recipe_vars:
            sn_base_cal = model.new_int_var(0, max(sn_cal_table) + 1, f"sn_base_cal_d{d}")
            model.add_element(snack_recipe_vars[d], sn_cal_table, sn_base_cal)
            sn_meal_cal = model.new_int_var(0, 100000, f"sn_meal_cal_d{d}")
            model.add_multiplication_equality(sn_meal_cal, [sn_base_cal, snack_serving_vars[d]])
            day_cal_terms.append(sn_meal_cal)

            sn_base_pro = model.new_int_var(0, max(sn_pro_table) + 1, f"sn_base_pro_d{d}")
            model.add_element(snack_recipe_vars[d], sn_pro_table, sn_base_pro)
            sn_meal_pro = model.new_int_var(0, 100000, f"sn_meal_pro_d{d}")
            model.add_multiplication_equality(sn_meal_pro, [sn_base_pro, snack_serving_vars[d]])
            day_pro_terms.append(sn_meal_pro)

        # Day total cal/pro (in SCALE^2 units: cal*10 * servings*10 = cal*100)
        day_total_cal = model.new_int_var(0, 1000000, f"day_total_cal_d{d}")
        model.add(day_total_cal == sum(day_cal_terms))
        day_total_pro = model.new_int_var(0, 1000000, f"day_total_pro_d{d}")
        model.add(day_total_pro == sum(day_pro_terms))

        # Target in same units (cal * SCALE^2)
        cal_target_scaled = int(daily_cal * SCALE * SCALE)
        pro_target_scaled = int(daily_pro * SCALE * SCALE)

        # Absolute deviation
        cal_dev = model.new_int_var(0, cal_target_scaled * 2, f"cal_dev_d{d}")
        model.add_abs_equality(cal_dev, day_total_cal - cal_target_scaled)
        cal_penalty_terms.append(cal_dev)

        pro_dev = model.new_int_var(0, pro_target_scaled * 2, f"pro_dev_d{d}")
        model.add_abs_equality(pro_dev, day_total_pro - pro_target_scaled)
        pro_penalty_terms.append(pro_dev)

    # Variety constraints: all unpinned recipes must be different
    pinned_dn = pinned_days.get("dinner", set())
    unpinned_dn = [v for d, v in dinner_recipe_vars.items() if d not in pinned_dn]
    if len(unpinned_dn) > 1:
        model.add_all_different(unpinned_dn)

    pinned_ln = pinned_days.get("lunch", set())
    unpinned_ln = [v for d, v in lunch_recipe_vars.items() if d not in pinned_ln]
    if len(unpinned_ln) > 1:
        model.add_all_different(unpinned_ln)

    pinned_sn = pinned_days.get("snack", set())
    unpinned_sn = [v for d, v in snack_recipe_vars.items() if d not in pinned_sn]
    if len(unpinned_sn) > 1:
        model.add_all_different(unpinned_sn)

    # Ingredient-group diversity: unpinned dinners should have different protein sources
    dn_group_ids, num_groups, group_key_to_id = build_ingredient_group_table(
        dinner_candidates
    )
    unpinned_dn_days = [d for d in dinner_recipe_vars if d not in pinned_dn]
    dn_group_vars: list = []
    if len(unpinned_dn_days) > 1 and num_groups > 1:
        for d in unpinned_dn_days:
            gvar = model.new_int_var(0, num_groups - 1, f"dn_group_d{d}")
            model.add_element(dinner_recipe_vars[d], dn_group_ids, gvar)
            dn_group_vars.append(gvar)
        model.add_all_different(dn_group_vars)

    # Required ingredient groups: at least one dinner must use each required group
    required_groups = config["preferences"].get("required_ingredient_groups") or []
    if required_groups and dn_group_vars:
        for group_name in required_groups:
            group_key = f"group:{group_name}"
            if group_key not in group_key_to_id:
                continue  # no candidates with this group — skip silently
            target_id = group_key_to_id[group_key]
            bools = []
            for i, gvar in enumerate(dn_group_vars):
                b = model.new_bool_var(f"req_{group_name}_d{unpinned_dn_days[i]}")
                model.add(gvar == target_id).only_enforce_if(b)
                model.add(gvar != target_id).only_enforce_if(~b)
                bools.append(b)
            model.add_bool_or(bools)

    # Objective: minimize weighted deviations
    total_penalty = model.new_int_var(0, 100000000, "total_penalty")
    model.add(
        total_penalty == 10 * sum(cal_penalty_terms) + 15 * sum(pro_penalty_terms)
    )
    model.minimize(total_penalty)

    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30.0
    status = solver.solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        logger.error("Solver could not find a feasible plan")
        return None

    # Extract solution
    start_date = datetime.now()
    # Adjust to next Monday
    days_until_monday = (7 - start_date.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 7
    start_date = start_date + timedelta(days=days_until_monday)

    plan = MealPlan(
        start_date=start_date.strftime("%Y-%m-%d"),
        end_date=(start_date + timedelta(days=num_days - 1)).strftime("%Y-%m-%d"),
        days=num_days,
        calories_target=daily_cal,
        protein_target=daily_pro,
    )

    for d in range(num_days):
        day_date = start_date + timedelta(days=d)
        day_name = DAY_NAMES[d % 7]

        # Breakfast
        if batch_breakfast:
            bf_idx = solver.value(bf_recipe)
            bf_svgs = solver.value(bf_servings) / SCALE
            bf_r = breakfast_candidates[bf_idx]
        else:
            bf_idx = solver.value(bf_recipe_vars[d])
            bf_svgs = solver.value(bf_serving_vars[d]) / SCALE
            bf_r = breakfast_candidates[bf_idx]

        plan.slots.append(
            MealSlot(
                day=d,
                day_name=day_name,
                meal_type=MealType.BREAKFAST,
                prep_style=PrepStyle.BATCH if batch_breakfast else PrepStyle.FRESH,
                recipe=bf_r,
                servings=bf_svgs,
                calories=(bf_r.calories or 0) * bf_svgs,
                protein_g=(bf_r.protein_g or 0) * bf_svgs,
                pinned=(d in pinned_days.get("breakfast", set())),
            )
        )

        # Dinner
        if d in dinner_recipe_vars:
            dn_idx = solver.value(dinner_recipe_vars[d])
            dn_svgs = solver.value(dinner_serving_vars[d]) / SCALE
            dn_r = dinner_candidates[dn_idx]
            dn_prep = PrepStyle.FRESH
        else:
            # Leftover from previous cook day
            prev_cook = None
            for cd in sorted(dinner_recipe_vars.keys(), reverse=True):
                if cd < d:
                    prev_cook = cd
                    break
            if prev_cook is None:
                prev_cook = max(dinner_recipe_vars.keys())
            dn_idx = solver.value(dinner_recipe_vars[prev_cook])
            dn_r = dinner_candidates[dn_idx]
            dn_svgs = solver.value(dinner_lo_serving_vars[d]) / SCALE
            dn_prep = PrepStyle.LEFTOVER

        plan.slots.append(
            MealSlot(
                day=d,
                day_name=day_name,
                meal_type=MealType.DINNER,
                prep_style=dn_prep,
                recipe=dn_r,
                servings=dn_svgs,
                calories=(dn_r.calories or 0) * dn_svgs,
                protein_g=(dn_r.protein_g or 0) * dn_svgs,
                pinned=(d in pinned_days.get("dinner", set())),
            )
        )

        # Lunch
        if d in lunch_recipe_vars:
            ln_idx = solver.value(lunch_recipe_vars[d])
            ln_svgs = solver.value(lunch_serving_vars[d]) / SCALE
            ln_r = lunch_candidates[ln_idx]
            ln_prep = PrepStyle.FRESH
        elif lunch_is_leftover:
            source_day = d - 1 if d > 0 else num_days - 1
            source_cook = None
            for cd in sorted(dinner_recipe_vars.keys(), reverse=True):
                if cd <= source_day:
                    source_cook = cd
                    break
            if source_cook is None:
                source_cook = max(dinner_recipe_vars.keys())
            ln_idx = solver.value(dinner_recipe_vars[source_cook])
            ln_r = dinner_candidates[ln_idx]
            ln_svgs = solver.value(lunch_lo_serving_vars[d]) / SCALE
            ln_prep = PrepStyle.LEFTOVER
        else:
            continue

        plan.slots.append(
            MealSlot(
                day=d,
                day_name=day_name,
                meal_type=MealType.LUNCH,
                prep_style=ln_prep,
                recipe=ln_r,
                servings=ln_svgs,
                calories=(ln_r.calories or 0) * ln_svgs,
                protein_g=(ln_r.protein_g or 0) * ln_svgs,
                pinned=(d in pinned_days.get("lunch", set())),
            )
        )

        # Snack
        if snacks_enabled and d in snack_recipe_vars:
            sn_idx = solver.value(snack_recipe_vars[d])
            sn_svgs = solver.value(snack_serving_vars[d]) / SCALE
            sn_r = snack_candidates[sn_idx]
            plan.slots.append(
                MealSlot(
                    day=d,
                    day_name=day_name,
                    meal_type=MealType.SNACK,
                    prep_style=PrepStyle.FRESH,
                    recipe=sn_r,
                    servings=sn_svgs,
                    calories=(sn_r.calories or 0) * sn_svgs,
                    protein_g=(sn_r.protein_g or 0) * sn_svgs,
                    pinned=(d in pinned_days.get("snack", set())),
                )
            )

    return plan


def format_plan_markdown(plan: MealPlan) -> str:
    """Format a meal plan as Obsidian markdown."""
    lines = [
        "---",
        "type: meal-plan",
        f"date_created: {datetime.now().strftime('%Y-%m-%d')}",
        f"start_date: {plan.start_date}",
        f"end_date: {plan.end_date}",
        f"daily_calories_target: {plan.calories_target}",
        f"daily_protein_target: {plan.protein_target}",
        "---",
        "",
        f"# Meal Plan: {plan.start_date} to {plan.end_date}",
        "",
    ]

    for d in range(plan.days):
        day_slots = plan.slots_for_day(d)
        if not day_slots:
            continue

        day_name = day_slots[0].day_name
        lines.append(f"## {day_name}")
        lines.append("")
        lines.append("| Meal | Recipe | Calories | Protein | Prep |")
        lines.append("|------|--------|----------|---------|------|")

        day_cal = 0.0
        day_pro = 0.0

        for slot in sorted(day_slots, key=lambda s: list(MealType).index(s.meal_type)):
            recipe_name = slot.recipe.name if slot.recipe else "TBD"
            svgs_note = f" ({slot.servings:.1f}x)" if slot.servings != 1.0 else ""
            prep_note = slot.prep_style.value
            if slot.pinned:
                prep_note += " (pinned)"
            lines.append(
                f"| {slot.meal_type.value.title()} "
                f"| [[{recipe_name}]]{svgs_note} "
                f"| {slot.calories:.0f} "
                f"| {slot.protein_g:.0f}g "
                f"| {prep_note} |"
            )
            day_cal += slot.calories
            day_pro += slot.protein_g

        lines.append(f"| **Total** | | **{day_cal:.0f}** | **{day_pro:.0f}g** | |")
        lines.append("")

    # Weekly summary
    total_cal = sum(s.calories for s in plan.slots)
    total_pro = sum(s.protein_g for s in plan.slots)
    unique_recipes = len({s.recipe.name for s in plan.slots if s.recipe})
    cook_days = len(
        {
            s.day
            for s in plan.slots
            if s.prep_style == PrepStyle.FRESH and s.meal_type == MealType.DINNER
        }
    )

    lines.append("## Weekly Summary")
    lines.append("")
    lines.append(
        f"- Total calories: ~{total_cal:.0f} (avg {total_cal / plan.days:.0f}/day)"
    )
    lines.append(
        f"- Total protein: ~{total_pro:.0f}g (avg {total_pro / plan.days:.0f}g/day)"
    )
    lines.append(f"- Cook sessions: {cook_days}")
    lines.append(f"- Unique recipes: {unique_recipes}")
    lines.append("")

    return "\n".join(lines)


def format_plan_json(plan: MealPlan) -> str:
    """Format a meal plan as JSON."""
    data = {
        "start_date": plan.start_date,
        "end_date": plan.end_date,
        "days": plan.days,
        "calories_target": plan.calories_target,
        "protein_target": plan.protein_target,
        "slots": [
            {
                "day": s.day,
                "day_name": s.day_name,
                "meal_type": s.meal_type.value,
                "prep_style": s.prep_style.value,
                "recipe": s.recipe.name if s.recipe else None,
                "recipe_file": str(s.recipe.file_path) if s.recipe else None,
                "servings": s.servings,
                "calories": round(s.calories, 1),
                "protein_g": round(s.protein_g, 1),
                "pinned": s.pinned,
            }
            for s in plan.slots
        ],
    }
    return json.dumps(data, indent=2)


def run_plan(
    cooking_path: Path,
    vault_path: Path,
    start_date: str | None = None,
    days: int | None = None,
    calories: int | None = None,
    protein: int | None = None,
    cook_days: str | None = None,
    pantry: str | None = None,
    exclude: str | None = None,
    output_format: str = "markdown",
    snacks: bool = False,
    pins: list[str] | None = None,
    shopping_list: bool = False,
    save_plan: str | None = None,
    recipes: bool = False,
    require_groups: list[str] | None = None,
) -> None:
    """CLI entry point for plan command."""
    config = load_config(vault_path)
    config = apply_cli_overrides(
        config,
        calories=calories,
        protein=protein,
        cook_days=cook_days,
        days=days,
    )

    if require_groups:
        config["preferences"]["required_ingredient_groups"] = [
            g.lower().strip() for g in require_groups
        ]

    if snacks:
        if "snack" not in config["schedule"]["meals_per_day"]:
            config["schedule"]["meals_per_day"].append("snack")
        if "snack" not in config["nutrition"]["meal_allocation"]:
            # Redistribute: take 15% proportionally from existing meals
            alloc = config["nutrition"]["meal_allocation"]
            total_existing = sum(alloc.values())
            for k in alloc:
                alloc[k] = alloc[k] / total_existing * 0.85
            alloc["snack"] = 0.15

    pantry_items = [p.strip() for p in pantry.split(",")] if pantry else None
    exclude_list = [e.strip() for e in exclude.split(",")] if exclude else None

    from meal_planner.pins import parse_pin
    parsed_pins = [parse_pin(p) for p in (pins or [])]

    plan = build_meal_plan(cooking_path, config, pantry_items, exclude_list, parsed_pins)

    if plan is None:
        sys.exit(1)

    plan_json_str = format_plan_json(plan)

    # --save-plan: persist plan JSON to file
    if save_plan is not None:
        if save_plan == "auto":
            save_path = f"meal-plan-{plan.start_date}.json"
        else:
            save_path = save_plan
        with open(save_path, "w") as f:
            f.write(plan_json_str)
        print(f"Plan saved to {save_path}", file=sys.stderr)

    # Print plan output
    if output_format == "json":
        print(plan_json_str)
    else:
        print(format_plan_markdown(plan))

    # --recipes: append scaled recipes section
    if recipes and output_format != "json":
        from meal_planner.recipe_renderer import render_plan_recipes

        recipes_md = render_plan_recipes(plan, cooking_path)
        if recipes_md:
            print(recipes_md)

    # --shopping-list: append shopping list after separator
    if shopping_list:
        from meal_planner.shopping import (
            build_shopping_sections,
            format_shopping_markdown,
        )

        pantry_staples = config.get("pantry_staples", [])
        if pantry:
            pantry_staples = pantry_staples + [p.strip() for p in pantry.split(",")]

        plan_data = json.loads(plan_json_str)
        sections = build_shopping_sections(plan_data, cooking_path, pantry_staples)

        if sections:
            if output_format == "json":
                from meal_planner.shopping import format_shopping_json

                print(format_shopping_json(sections))
            else:
                print("---")
                print()
                print(format_shopping_markdown(sections))
