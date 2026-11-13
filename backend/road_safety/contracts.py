"""Versioned public contracts shared with the TypeScript renderer.

SQL identifiers and widget capabilities are closed sets. Runtime validation is
mandatory even when a model provider promises structured output.
"""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

type Scalar = str | int | float | bool | None
type Metric = Literal["accidents", "accidents_with_severe", "severe_injuries", "deaths", "injuries"]
type Dimension = Literal[
    "road",
    "road_uf",
    "segment_10km",
    "uf",
    "concession",
    "accident_type",
    "direction",
    "track_type",
    "month",
    "year",
    "weekday",
    "hour",
    "vehicle_type",
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Filters(Contract):
    start_date: date | None = None
    end_date: date | None = None
    roads: list[str] = Field(default_factory=list, max_length=50)
    ufs: list[str] = Field(default_factory=list, max_length=27)
    concessions: list[str] = Field(default_factory=list, max_length=50)
    accident_types: list[str] = Field(default_factory=list, max_length=50)
    directions: list[str] = Field(default_factory=list, max_length=20)
    track_types: list[str] = Field(default_factory=list, max_length=20)
    vehicle_types: list[str] = Field(default_factory=list, max_length=10)
    severity: Literal["all", "with_severe", "with_deaths", "with_injuries"] = "all"
    km_min: float | None = Field(default=None, ge=0)
    km_max: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def check_ranges(self) -> "Filters":
        if self.start_date and self.end_date and self.start_date >= self.end_date:
            raise ValueError("end_date must be after start_date (exclusive end)")
        if self.km_min is not None and self.km_max is not None and self.km_min >= self.km_max:
            raise ValueError("km_max must be greater than km_min")
        return self


class Cohort(Contract):
    dimension: Dimension
    keys: list[str] = Field(min_length=1, max_length=100)


class QuerySpec(Contract):
    operation: Literal["ranking", "timeseries", "distribution", "comparison", "detail", "overview"]
    metric: Metric = "accidents"
    group_by: Dimension = "road_uf"
    filters: Filters = Field(default_factory=Filters)
    comparison_filters: Filters | None = None
    cohort: Cohort | None = None
    limit: int = Field(default=5, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000000)
    sort: Literal["ascending", "descending"] = "descending"


class Evidence(Contract):
    snapshot_id: str
    source: str = "ANTT — Acidentes em rodovias federais concedidas"
    source_url: str = "https://dados.antt.gov.br/dataset/acidentes-rodovias"
    start_date: str
    end_date: str
    metric: Metric
    definition: str
    matched_rows: int
    resources_with_records: int
    resources_total: int
    coverage: Literal["observed", "partial", "none"]
    warnings: list[str] = Field(default_factory=list)


class Column(Contract):
    key: str
    label: str
    data_type: Literal["string", "number", "date"] = "string"
    format: Literal["text", "number", "percent"] = "text"


class Dataset(Contract):
    id: str
    snapshot_id: str
    title: str
    columns: list[Column]
    rows: list[dict[str, Scalar]]
    row_count: int
    query: QuerySpec
    evidence: Evidence


class WidgetBase(Contract):
    id: str
    title: str
    dataset_id: str
    description: str = ""


class MetricWidget(WidgetBase):
    type: Literal["metric"]
    field: str = "value"
    aggregation: Literal["sum", "count", "avg"] = "sum"


class ChartWidget(WidgetBase):
    type: Literal["bar_chart", "line_chart", "area_chart", "donut_chart"]
    x_field: str = "label"
    y_field: str = "value"
    sort: Literal["ascending", "descending"] | None = None


class TableWidget(WidgetBase):
    type: Literal["table"]
    columns: list[str] = Field(default_factory=list)


class MapWidget(WidgetBase):
    type: Literal["map_choropleth"]
    x_field: str = "key"
    y_field: str = "value"


type Widget = Annotated[
    MetricWidget | ChartWidget | TableWidget | MapWidget, Field(discriminator="type")
]


class UpsertAction(Contract):
    action: Literal["add", "update"]
    widget: Widget


class RemoveAction(Contract):
    action: Literal["remove"]
    widget_id: str


type DashboardAction = Annotated[UpsertAction | RemoveAction, Field(discriminator="action")]


class LayoutItem(Contract):
    i: str
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(ge=1, le=12)
    h: int = Field(ge=1, le=30)


class Dashboard(Contract):
    widgets: list[Widget] = Field(default_factory=list)
    layouts: dict[str, list[LayoutItem]] = Field(default_factory=dict)
    pinned_widget_ids: list[str] = Field(default_factory=list)


class ChatRequest(Contract):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    request_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    filters: Filters | None = None


class AnalysisResponse(Contract):
    schema_version: Literal["1"] = "1"
    session_id: str
    request_id: str
    run_id: str
    analysis_id: str
    snapshot_id: str | None
    status: Literal["complete", "clarification", "insufficient_data"]
    answer: str
    datasets: list[Dataset] = Field(default_factory=list)
    dashboard_actions: list[DashboardAction] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class ChatMessage(Contract):
    id: str
    role: Literal["user", "assistant"]
    content: str
    analysis_id: str | None = None


class Session(Contract):
    id: str
    title: str
    active_filters: Filters | None = None
    messages: list[ChatMessage] = Field(default_factory=list)
    dashboard: Dashboard = Field(default_factory=Dashboard)
    datasets: list[Dataset] = Field(default_factory=list)
    latest_analysis: AnalysisResponse | None = None


class SessionSummary(Contract):
    id: str
    title: str


class Catalog(Contract):
    available: bool
    snapshot_id: str | None = None
    min_date: str | None = None
    max_date: str | None = None
    total_accidents: int = 0
    resources: int = 0
    filters: dict[str, list[str]] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    coverage: list[dict[str, Scalar]] = Field(default_factory=list)


class Health(Contract):
    status: Literal["ok"] = "ok"
    data_available: bool
    llm_configured: bool
    model: str | None = None


class StageEvent(Contract):
    run_id: str
    stage: str
    label: str


class ErrorEvent(Contract):
    run_id: str
    code: str
    message: str


class ContractBundle(Contract):
    """Export root; each property becomes one generated Zod schema."""

    chat_request: ChatRequest
    response: AnalysisResponse
    dataset: Dataset
    session: Session
    session_summary: SessionSummary
    catalog: Catalog
    dashboard: Dashboard
    health: Health
    stage: StageEvent
    error: ErrorEvent
