"""Real HTTP acceptance server with a deterministic planner and synthetic data.

This module is test-only: production configuration never enables a fake LLM.
Run from the repository root with the project's virtual environment.
"""

import tempfile
from pathlib import Path

import uvicorn

from road_safety.agents.planner import AnalysisPlan, PlannedView
from road_safety.api import create_app
from road_safety.config import Settings
from road_safety.contracts import Catalog, Filters, QuerySpec
from road_safety.data.demo import create_demo
from road_safety.storage import AnalysisContext


class AcceptancePlanner:
    """Make a stable ranking and a follow-up over its exact saved cohort."""

    async def plan(
        self,
        question: str,
        prior_context: AnalysisContext,
        filters: Filters,
        catalog: Catalog,
    ) -> AnalysisPlan:
        follow_up = "desses" in question.casefold()
        return AnalysisPlan(
            queries=[
                QuerySpec(
                    operation="ranking",
                    group_by="road_uf",
                    metric="accidents_with_severe" if follow_up else "accidents",
                    filters=filters,
                    limit=5,
                )
            ],
            use_previous_cohort=follow_up,
            views=[
                PlannedView(query_index=0, type="bar_chart"),
                PlannedView(query_index=0, type="table"),
            ],
        )


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[2]
    scratch = project_root / "tmp"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="e2e-", dir=scratch) as directory:
        data_dir = Path(directory)
        create_demo(data_dir)
        settings = Settings(
            data_dir=data_dir,
            openai_api_key="test-no-network",
            openai_model="acceptance-fake",
        )
        uvicorn.run(
            create_app(settings=settings, planner=AcceptancePlanner()),
            host="127.0.0.1",
            port=8011,
        )
