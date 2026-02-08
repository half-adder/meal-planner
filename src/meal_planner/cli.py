"""CLI entry point for the meal planner."""

from __future__ import annotations

import argparse
from pathlib import Path

DEFAULT_VAULT_PATH = Path.home() / "obsidian-sync" / "Personal"
DEFAULT_COOKING_DIR = "03. Resources/Cooking"


def get_cooking_path(args: argparse.Namespace) -> Path:
    vault = Path(args.vault_path) if args.vault_path else DEFAULT_VAULT_PATH
    return vault / DEFAULT_COOKING_DIR


def cmd_index(args: argparse.Namespace) -> None:
    from meal_planner.indexer import run_index

    run_index(
        cooking_path=get_cooking_path(args),
        dry_run=args.dry_run,
        limit=args.limit,
        force=getattr(args, "force", False),
        skip_api=getattr(args, "skip_api", False),
        max_workers=getattr(args, "workers", 4),
    )


def cmd_suggest(args: argparse.Namespace) -> None:
    from meal_planner.suggest import run_suggest

    run_suggest(
        cooking_path=get_cooking_path(args),
        meal_type=args.meal_type,
        max_time=args.max_time,
        cuisine=args.cuisine,
        dietary_tags=args.dietary_tags,
        exclude=args.exclude,
        available_ingredients=args.available_ingredients,
        target_calories=args.target_calories,
        target_protein=args.target_protein,
        min_protein=args.min_protein,
        max_calories=args.max_calories,
        limit=args.limit,
        output_format=args.format,
    )


def cmd_plan(args: argparse.Namespace) -> None:
    from meal_planner.planner import run_plan

    vault = Path(args.vault_path) if args.vault_path else DEFAULT_VAULT_PATH
    run_plan(
        cooking_path=get_cooking_path(args),
        vault_path=vault,
        start_date=args.start_date,
        days=args.days,
        calories=args.calories,
        protein=args.protein,
        cook_days=args.cook_days,
        pantry=args.pantry,
        exclude=args.exclude,
        output_format=args.format,
        snacks=args.snacks,
        pins=args.pin,
        shopping_list=args.shopping_list,
        save_plan=args.save_plan,
        recipes=args.recipes,
        require_groups=args.require_group,
    )


def cmd_shopping_list(args: argparse.Namespace) -> None:
    from meal_planner.shopping import run_shopping_list

    vault = Path(args.vault_path) if args.vault_path else DEFAULT_VAULT_PATH
    run_shopping_list(
        cooking_path=get_cooking_path(args),
        vault_path=vault,
        plan_file=args.plan_file,
        pantry=args.pantry,
        output_format=args.format,
    )


def cmd_scale(args: argparse.Namespace) -> None:
    from meal_planner.scaler import run_scale

    run_scale(
        cooking_path=get_cooking_path(args),
        recipe_name=args.recipe,
        servings=args.servings,
        output_format=args.format,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="meal-planner",
        description="Weekly meal planning from Obsidian recipe notes",
    )
    parser.add_argument(
        "--vault-path",
        type=str,
        default=None,
        help=f"Path to Obsidian vault (default: {DEFAULT_VAULT_PATH})",
    )
    parser.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error"],
        default="info",
        help="Logging verbosity (default: info)",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Also write logs to this file",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # index
    p_index = sub.add_parser("index", help="Parse recipe files and build index")
    p_index.add_argument(
        "--dry-run", action="store_true", help="Print stats without writing"
    )
    p_index.add_argument("--limit", type=int, default=None, help="Process only N files")
    p_index.add_argument(
        "--force", action="store_true", help="Re-parse even if hash matches"
    )
    p_index.add_argument(
        "--skip-api", action="store_true", help="Use regex parser instead of Haiku"
    )
    p_index.add_argument(
        "--workers", type=int, default=4, help="Parallel Haiku workers (default: 4)"
    )
    p_index.set_defaults(func=cmd_index)

    # suggest
    p_suggest = sub.add_parser("suggest", help="Find and rank recipe candidates")
    p_suggest.add_argument("--meal-type", type=str)
    p_suggest.add_argument("--max-time", type=int)
    p_suggest.add_argument("--cuisine", type=str)
    p_suggest.add_argument("--dietary-tags", type=str, help="Comma-separated tags")
    p_suggest.add_argument(
        "--exclude", type=str, help="Comma-separated recipe names to exclude"
    )
    p_suggest.add_argument(
        "--available-ingredients", type=str, help="Comma-separated pantry items"
    )
    p_suggest.add_argument("--target-calories", type=int)
    p_suggest.add_argument("--target-protein", type=int)
    p_suggest.add_argument("--min-protein", type=int)
    p_suggest.add_argument("--max-calories", type=int)
    p_suggest.add_argument("--limit", type=int, default=10)
    p_suggest.add_argument(
        "--format", type=str, choices=["json", "table"], default="table"
    )
    p_suggest.set_defaults(func=cmd_suggest)

    # plan
    p_plan = sub.add_parser("plan", help="Generate optimized weekly meal plan")
    p_plan.add_argument("--start-date", type=str, help="YYYY-MM-DD")
    p_plan.add_argument("--days", type=int, default=7)
    p_plan.add_argument("--calories", type=int)
    p_plan.add_argument("--protein", type=int)
    p_plan.add_argument("--cook-days", type=str, help="Comma-separated day names")
    p_plan.add_argument(
        "--pantry", type=str, help="Comma-separated available ingredients"
    )
    p_plan.add_argument(
        "--exclude", type=str, help="Comma-separated recipe names to exclude"
    )
    p_plan.add_argument(
        "--snacks", action="store_true", help="Include daily snack slot"
    )
    p_plan.add_argument(
        "--pin",
        action="append",
        default=[],
        help='Pin a recipe to a meal slot. Format: "day:meal:Recipe Name". '
             'day: a day name, "all", "even", or "odd". '
             'meal: breakfast/lunch/dinner/snack. Repeatable.',
    )
    p_plan.add_argument(
        "--require-group",
        action="append",
        default=[],
        help="Require at least one dinner from this ingredient group "
             "(e.g., beef, poultry, seafood). Repeatable.",
    )
    p_plan.add_argument(
        "--recipes",
        action="store_true",
        help="Include scaled recipes with ingredients and directions in plan output",
    )
    p_plan.add_argument(
        "--shopping-list",
        action="store_true",
        help="Append a shopping list to the plan output",
    )
    p_plan.add_argument(
        "--save-plan",
        nargs="?",
        const="auto",
        default=None,
        help="Save plan JSON to file. Optional path; defaults to meal-plan-YYYY-MM-DD.json",
    )
    p_plan.add_argument(
        "--format", type=str, choices=["json", "markdown"], default="markdown"
    )
    p_plan.set_defaults(func=cmd_plan)

    # shopping-list
    p_shop = sub.add_parser("shopping-list", help="Generate shopping list from plan")
    p_shop.add_argument("--plan-file", type=str, help="Path to plan JSON (or stdin)")
    p_shop.add_argument(
        "--pantry", type=str, help="Comma-separated pantry items to subtract"
    )
    p_shop.add_argument(
        "--format", type=str, choices=["json", "markdown"], default="markdown"
    )
    p_shop.set_defaults(func=cmd_shopping_list)

    # scale
    p_scale = sub.add_parser("scale", help="Scale a recipe to N servings")
    p_scale.add_argument("recipe", type=str, help="Recipe name (fuzzy matched)")
    p_scale.add_argument("--servings", type=float, required=True)
    p_scale.add_argument(
        "--format", type=str, choices=["json", "markdown"], default="markdown"
    )
    p_scale.set_defaults(func=cmd_scale)

    return parser


def main() -> None:
    from meal_planner.log import setup_logging

    parser = build_parser()
    args = parser.parse_args()

    log_file = Path(args.log_file) if args.log_file else None
    setup_logging(level=args.log_level, log_file=log_file)

    args.func(args)


if __name__ == "__main__":
    main()
