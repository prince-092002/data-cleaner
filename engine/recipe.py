"""Save, load and run YAML recipes. See docs/CONTRACT.md section 6.

A recipe is the approved plan written down, so the same cleaning can be repeated on a
similar file without going through the suggestions again.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

from engine import ENGINE_VERSION
from engine.changelog import utc_now
from engine.errors import PlanError
from engine.models import ApprovedPlan, CleanResult, PlanStep, SourceInfo

RECIPE_VERSION = "1.0"


class RecipeStep(BaseModel):
    rule_id: str
    rule_version: str
    column: str | None = None
    action: Literal["auto", "approved"]
    params: dict[str, Any] = Field(default_factory=dict)


class Recipe(BaseModel):
    recipe_version: str = RECIPE_VERSION
    name: str
    created_at: str
    engine_version: str = ENGINE_VERSION
    source: SourceInfo
    steps: list[RecipeStep]


def from_plan(plan: ApprovedPlan, source: SourceInfo | None = None, name: str | None = None) -> Recipe:
    source = source or plan.source
    return Recipe(
        name=name or f"{source.filename} cleaning recipe",
        created_at=utc_now(),
        source=source,
        steps=[RecipeStep(**s.model_dump(exclude={"proposal_id"})) for s in plan.steps],
    )


def to_plan(recipe: Recipe) -> ApprovedPlan:
    return ApprovedPlan(source=recipe.source, steps=[PlanStep(**s.model_dump()) for s in recipe.steps])


def dumps(recipe: Recipe) -> str:
    return yaml.safe_dump(recipe.model_dump(mode="json"), sort_keys=False, allow_unicode=True)


def save(recipe: Recipe, path: Path) -> None:
    Path(path).write_text(dumps(recipe), encoding="utf-8")


def load(path: Path) -> Recipe:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        recipe = Recipe.model_validate(data)
    except (yaml.YAMLError, ValidationError, OSError) as exc:
        raise PlanError("This recipe file is not valid.") from exc
    if recipe.recipe_version.split(".")[0] != RECIPE_VERSION.split(".")[0]:
        raise PlanError(f"Recipe version {recipe.recipe_version} is not supported.")
    return recipe


def run(
    recipe: Recipe,
    path: Path,
    out_dir: Path,
    run_id: str,
    progress: Callable[[int, str], None] | None = None,
) -> CleanResult:
    """Apply a saved recipe to a file. Steps for columns the file does not have are skipped
    and reported in result.warnings."""
    from engine import pipeline

    path = Path(path)
    plan = to_plan(recipe)
    file_type = "xlsx" if path.suffix.lower() == ".xlsx" else "csv"
    # Sheet and header row come from the recipe; encoding and delimiter are re-detected.
    plan.source = SourceInfo(
        filename=path.name,
        file_type=file_type,
        sheet=recipe.source.sheet if file_type == "xlsx" else None,
        header_row=recipe.source.header_row,
    )
    return pipeline.clean(path, plan, out_dir, run_id, progress=progress, recipe_name=recipe.name)
