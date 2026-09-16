"""The approved catalog of things the chat tile's planner LLM may ask for
(ARCHITECTURE.md §8) — the LLM never writes SQL and never invents a field
name; it only ever fills in a `VizRequest`, whose `measure`/`dimension`
values are real Python enums built from this catalog and salary.py's own
DIMENSION_COLUMNS. That's what lets the OpenAI SDK constrain the model's
structured output to exactly these keys at decode time — the same
allowlist idea as DIMENSION_COLUMNS itself, just enforced one layer
earlier. `get_viz_request` (client.py) still re-validates the parsed
result server-side before any query runs, never trusting the enum
constraint alone (ARCHITECTURE.md §7.4's "never trust the request" framing
applies to LLM output exactly as much as to a browser's).

Scoped to exactly what the Salaris page itself already shows (Laura's own
proposal): every measure here is a thin wrapper around an existing
salary.py function, not a new query.
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum, StrEnum

from pydantic import BaseModel, Field

from hr_dashboard.semantic import salary


@dataclass(frozen=True)
class MeasureSpec:
    label: str
    # "kpi": one number, respects filters, no dimension.
    # "breakdown": a per-category table, requires a dimension — reuses one
    #   of the dimension-grouped charts already on the page.
    # "trend": the like-for-like growth series, no dimension/filters.
    kind: str


MEASURE_CATALOG: dict[str, MeasureSpec] = {
    "mediaan_salaris": MeasureSpec("Mediaan salaris", "kpi"),
    "gemiddeld_benchmark_ratio": MeasureSpec("Gemiddeld salaris t.o.v. benchmark", "kpi"),
    "pct_onder_benchmark": MeasureSpec("Percentage medewerkers onder benchmark", "kpi"),
    "aantal_medewerkers": MeasureSpec("Aantal medewerkers", "kpi"),
    "totale_loonsom": MeasureSpec("Totale loonsom", "kpi"),
    "gecorrigeerde_loonkloof": MeasureSpec(
        "Gecorrigeerde loonkloof tussen mannen en vrouwen", "kpi"
    ),
    # These three labels stay short on purpose — compiler.py's own
    # _resolve_breakdown already appends ", per <dimensie>" when building
    # the answer sentence, and the "(kind=breakdown)" annotation already
    # shown next to each measure in the planner's own instructions
    # (client.py) is what tells the model a dimension is required, so
    # spelling that out again in the label here would just be repeated in
    # the final answer too.
    "aantal_medewerkers_per_dimensie": MeasureSpec("Aantal medewerkers", "breakdown"),
    "benchmark_verdeling_per_dimensie": MeasureSpec("Verdeling t.o.v. benchmark", "breakdown"),
    "nieuwe_vs_huidig_per_dimensie": MeasureSpec(
        "Startsalaris versus huidig salaris", "breakdown"
    ),
    "salarisgroei_trend": MeasureSpec(
        "Gemiddelde salarisgroei (like-for-like) over tijd", "trend"
    ),
}

# Functional Enum construction (not a hand-written class) so this can
# never drift from the dicts above/in salary.py — the enum members are
# always exactly the current catalog keys, nothing hardcoded twice.
MeasureKey = Enum("MeasureKey", {key: key for key in MEASURE_CATALOG})
DimensionKey = Enum("DimensionKey", {key: key for key in salary.DIMENSION_COLUMNS})


class ChartType(StrEnum):
    """An explicit override of a measure's own default mark type — e.g.
    Laura asked for the YoY trend (which defaults to a line) as a bar
    chart instead. Only meaningful for a 'breakdown' or 'trend' measure;
    a 'kpi' measure has no chart to begin with, so this is simply ignored
    there."""

    bar = "bar"
    line = "line"


class TrendSeries(StrEnum):
    """Which of the 'trend' measure's two series a peildatum-narrowed
    question is about — the same two lines already shown, with the same
    labels, in the trend chart's own legend. Only matters once a specific
    peildatum turns the answer into one figure instead of the whole chart
    (both series are always visible together on the chart itself, so there
    the ambiguity this fixes doesn't exist) — Laura caught that a single-
    figure answer defaulted to 'alle_behouden_medewerkers' regardless of
    which one the question actually asked about, with no way to even
    express the other choice."""

    alle_behouden_medewerkers = "alle_behouden_medewerkers"
    zelfde_functie_en_contract = "zelfde_functie_en_contract"


class VizRequest(BaseModel):
    """What the planner LLM must fill in — nothing else. `measure` and
    `dimension` are real enums (see above), so the OpenAI SDK constrains
    the model's structured output to exactly these keys at decode time.
    The five filter fields stay plain strings on purpose: which afdelingen/
    functies/managers/etc. actually exist is live data, not a fixed set —
    hardcoding them here would be exactly the "assumed instead of verified
    against the simulation" mistake this project has hit before. An
    incorrect filter value just yields zero rows downstream (parameterized
    SQL, ARCHITECTURE.md §7.4) — not a validation error, since the model
    can't be relied on to spell a name back perfectly even when it was
    given the real list in its own instructions.

    `peildatum`, when given, reuses the exact same "op peildatum" as-of
    pattern the rest of the app is already built on — every dashboard
    query already resolves "the situation on date X" this same way, this
    just lets a chat question pick its own X instead of always the latest
    snapshot. For the 'trend' measure specifically, giving a peildatum
    changes the answer from "here's the whole chart" to "here's the one
    point on the series closest to that date" — a single figure, not a
    chart, matching what a question phrased as "wat was ... op <datum>"
    is actually asking for."""

    measure: MeasureKey
    dimension: DimensionKey | None = Field(
        default=None,
        description="Only meaningful for a 'breakdown' measure — ignored otherwise.",
    )
    chart_type: ChartType | None = Field(
        default=None,
        description=(
            "Only set this if the question explicitly asks for a specific chart type."
        ),
    )
    peildatum: date | None = Field(
        default=None,
        description=(
            "Only set this if the question names a specific date/moment in the past. "
            "Leave empty to use the latest available data."
        ),
    )
    trend_series: TrendSeries | None = Field(
        default=None,
        description=(
            "Only meaningful for the 'trend' measure when peildatum is also set — which "
            "of its two series the question is about. Defaults to alle_behouden_medewerkers "
            "when left empty."
        ),
    )
    afdeling: str | None = None
    functie: str | None = None
    manager: str | None = None
    opleidingsniveau: str | None = None
    salaris_categorie: str | None = None
