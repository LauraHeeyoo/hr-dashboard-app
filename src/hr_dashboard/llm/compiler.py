"""Deterministic compiler: turns a validated VizRequest into a real query
against the existing salary.py functions, then a plain Dutch sentence and
(for breakdown/trend measures) a Vega-Lite chart spec — the
"deterministic query compilation" and "deterministic Vega-Lite compiling"
steps of ARCHITECTURE.md §8's pipeline. Every measure here is a thin
wrapper around a function that already exists for the Salaris page itself;
nothing here invents a new query.

`measure`/`dimension` on a VizRequest are real Python enums (catalog.py),
so by construction they can never hold anything outside the approved
catalog — there is no code path here that builds a SQL identifier from
free text. The five filter fields stay plain strings and flow into the
same parameterized SalaryFilters every other page uses; an unrecognized
value just yields zero rows, not a query error.
"""

from dataclasses import dataclass
from datetime import date

from hr_dashboard.llm.catalog import MEASURE_CATALOG, TrendSeries, VizRequest
from hr_dashboard.semantic import salary
from hr_dashboard.semantic.salary import SalaryFilters


@dataclass
class ChatResult:
    answer: str
    chart_spec: dict | None = None
    # Set only when the answer is a single figure (every "kpi" measure,
    # plus the "trend" measure when a specific peildatum narrows it down
    # to one point) — the frontend renders these as a KPI-style card
    # instead of a plain sentence, matching the rest of the dashboard's
    # own tiles, rather than a chart caption.
    value: str | None = None
    value_label: str | None = None


_FILTER_LABELS = {
    "afdeling": "afdeling",
    "functie": "functie",
    "manager": "manager",
    "opleidingsniveau": "opleidingsniveau",
    "salaris_categorie": "salarisgroep",
}


def _filters_from_request(req: VizRequest) -> SalaryFilters:
    return SalaryFilters(
        afdeling=req.afdeling,
        functie=req.functie,
        manager=req.manager,
        opleidingsniveau=req.opleidingsniveau,
        salaris_categorie=req.salaris_categorie,
    )


def _filters_description(filters: SalaryFilters) -> str:
    parts = [
        f"{label} {getattr(filters, field)}"
        for field, label in _FILTER_LABELS.items()
        if getattr(filters, field)
    ]
    return f" voor {' en '.join(parts)}" if parts else ""


def _format_euro(value: float) -> str:
    return "€" + f"{value:,.0f}".replace(",", ".")


def _kpi_result(value_label: str, value_str: str) -> ChatResult:
    return ChatResult(f"{value_label} is {value_str}.", value=value_str, value_label=value_label)


def _resolve_kpi(measure_key: str, req: VizRequest, as_of_date: date) -> ChatResult:
    label = MEASURE_CATALOG[measure_key].label
    filters = _filters_from_request(req)
    suffix = _filters_description(filters)
    value_label = f"{label}{suffix}"

    if measure_key == "totale_loonsom":
        rows = salary.get_employee_rows(as_of_date, filters)
        if not rows:
            return ChatResult(f"Geen medewerkers gevonden{suffix}.")
        total = salary.compute_total_payroll(rows)
        return _kpi_result(value_label, _format_euro(total))

    if measure_key == "gecorrigeerde_loonkloof":
        gap = salary.get_corrected_gender_pay_gap(as_of_date, filters)
        if gap.gecorrigeerd_pct is None:
            return ChatResult(f"Er is niet genoeg data om {label.lower()}{suffix} te berekenen.")
        return _kpi_result(value_label, f"{gap.gecorrigeerd_pct * 100:.1f}%")

    # catalog key -> SalaryKpis field name; only "mediaan_salaris" differs
    # (SalaryKpis calls it median_salaris) from its catalog key.
    kpis = salary.get_salary_kpis(as_of_date, filters)
    kpis_field = "median_salaris" if measure_key == "mediaan_salaris" else measure_key
    value = getattr(kpis, kpis_field)
    if value is None:
        return ChatResult(f"Geen data gevonden voor {label.lower()}{suffix}.")
    if measure_key == "aantal_medewerkers":
        return _kpi_result(value_label, str(value))
    if measure_key == "mediaan_salaris":
        return _kpi_result(value_label, _format_euro(value))
    # gemiddeld_benchmark_ratio, pct_onder_benchmark — both fractions.
    return _kpi_result(value_label, f"{value * 100:.1f}%")


_BREAKDOWN_CHART_BASE = {
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "width": "container",
    # contains:"padding" — see salaris.html's own chart specs for why this
    # matters once a legend/long axis labels are involved.
    "autosize": {"type": "fit", "contains": "padding"},
}


def _headcount_spec(rows: list[dict], mark: str) -> dict:
    return {
        **_BREAKDOWN_CHART_BASE,
        "height": {"step": 22},
        "data": {"values": rows},
        "mark": mark,
        "encoding": {
            "y": {"field": "dimension_value", "type": "nominal", "sort": "-x", "title": None},
            "x": {
                "field": "aantal", "aggregate": "sum", "type": "quantitative",
                "title": "Aantal medewerkers",
            },
            "color": {
                "field": "Salaris_Categorie", "type": "nominal", "title": "Salaris categorie",
            },
            "tooltip": [
                {"field": "dimension_value", "title": "Waarde"},
                {"field": "Salaris_Categorie", "title": "Categorie"},
                {"field": "aantal", "aggregate": "sum", "title": "Aantal"},
            ],
        },
    }


def _benchmark_spec(rows: list[dict], mark: str) -> dict:
    return {
        **_BREAKDOWN_CHART_BASE,
        "height": {"step": 22},
        "data": {"values": rows},
        "mark": mark,
        "encoding": {
            "y": {"field": "dimension_value", "type": "nominal", "sort": "-x", "title": None},
            "x": {
                "field": "aantal", "aggregate": "sum", "type": "quantitative", "stack": "normalize",
                "title": "Aandeel medewerkers", "axis": {"format": "%"},
            },
            "color": {"field": "Benchmark_Status", "type": "nominal", "title": "Benchmark"},
            "tooltip": [
                {"field": "dimension_value", "title": "Waarde"},
                {"field": "Benchmark_Status", "title": "Benchmark"},
                {"field": "aantal", "aggregate": "sum", "title": "Aantal"},
            ],
        },
    }


def _new_hire_spec(rows: list[dict], mark: str) -> dict:
    return {
        **_BREAKDOWN_CHART_BASE,
        "height": {"step": 26},
        "data": {"values": rows},
        "transform": [
            {"fold": ["gem_start_salaris", "gem_huidig_salaris"], "as": ["Salaris_Type", "Bedrag"]}
        ],
        "mark": mark,
        "encoding": {
            "y": {"field": "dimension_value", "type": "nominal", "sort": "-x", "title": None},
            "x": {"field": "Bedrag", "type": "quantitative", "title": "Gemiddeld salaris (€)"},
            "yOffset": {
                "field": "Salaris_Type", "sort": ["gem_start_salaris", "gem_huidig_salaris"],
            },
            "color": {
                "field": "Salaris_Type", "type": "nominal",
                "scale": {
                    "domain": ["gem_start_salaris", "gem_huidig_salaris"],
                    "range": ["#9aa0a6", "#2a78d6"],
                },
                "legend": {
                    "title": None,
                    "labelExpr": (
                        "datum.label == 'gem_start_salaris' ? 'Startsalaris' : 'Huidig salaris'"
                    ),
                },
            },
            "tooltip": [
                {"field": "dimension_value", "title": "Waarde"},
                {"field": "Salaris_Type", "title": "Type"},
                {"field": "Bedrag", "title": "Gem. salaris", "format": ",.0f"},
            ],
        },
    }


_BREAKDOWN_QUERIES = {
    "aantal_medewerkers_per_dimensie": (salary.get_headcount_by_dimension, _headcount_spec),
    "benchmark_verdeling_per_dimensie": (
        salary.get_benchmark_distribution_by_dimension,
        _benchmark_spec,
    ),
    "nieuwe_vs_huidig_per_dimensie": (salary.get_new_hire_vs_current, _new_hire_spec),
}


def _resolve_breakdown(measure_key: str, req: VizRequest, as_of_date: date) -> ChatResult:
    measure_label = MEASURE_CATALOG[measure_key].label
    # The model sometimes leaves `dimension` empty even for a measure that
    # needs one — default to "afdeling" (the same default the dashboard's
    # own dimension-switchers use) rather than erroring out on a question
    # that's otherwise perfectly answerable.
    dimension_key = req.dimension.value if req.dimension else "afdeling"
    dim_label = salary.DIMENSION_LABELS[dimension_key]
    filters = _filters_from_request(req)
    mark = req.chart_type.value if req.chart_type else "bar"

    query_fn, spec_fn = _BREAKDOWN_QUERIES[measure_key]
    rows = query_fn(as_of_date, dimension_key, filters)
    if not rows:
        suffix = _filters_description(filters)
        return ChatResult(f"Geen data gevonden voor {measure_label.lower()}{suffix}.")
    return ChatResult(f"{measure_label}, per {dim_label.lower()}.", spec_fn(rows, mark))


def _closest_row(rows: list[dict], target: date) -> dict:
    return min(rows, key=lambda row: abs((row["Snapshot_Date"] - target).days))


def _resolve_trend(req: VizRequest) -> ChatResult:
    earliest = salary.get_earliest_snapshot_date()
    latest = salary.get_latest_snapshot_date()
    rows = salary.get_lfl_growth_trend(earliest, latest, "month")
    if not rows:
        return ChatResult("Er is geen data beschikbaar voor de salarisgroei.")

    if req.peildatum is not None:
        # A specific moment was asked for ("wat was ... op <datum>") — one
        # figure at the closest available monthly point, not the whole
        # series. But there are genuinely two series at that point (same
        # as the chart's own legend: "Alle behouden medewerkers" vs.
        # "Zelfde functie en contract") — Laura caught first that the
        # label didn't say which one a figure actually was, and then that
        # there was no way to even ASK for the other one — "bij dezelfde
        # functie/contract" kept coming back as "alle behouden
        # medewerkers" regardless, since req.trend_series didn't exist
        # yet. It does now, with "alle behouden medewerkers" as the
        # explicit default when the question doesn't say either way.
        closest = _closest_row(rows, req.peildatum)
        wants_same_role = req.trend_series == TrendSeries.zelfde_functie_en_contract
        field = "LFL_Growth_SameRoleContract_Pct" if wants_same_role else "LFL_Growth_Pct"
        series_label = (
            "zelfde functie en contract" if wants_same_role else "alle behouden medewerkers"
        )
        value = closest[field]
        if value is None:
            return ChatResult(f"Geen data gevonden rond {req.peildatum}.")
        return _kpi_result(
            f"Gemiddelde salarisgroei (like-for-like) op {closest['Snapshot_Date']} "
            f"— {series_label}",
            f"{value * 100:.1f}%",
        )

    mark = "bar" if req.chart_type and req.chart_type.value == "bar" else {
        "type": "line", "point": True,
    }
    spec = {
        **_BREAKDOWN_CHART_BASE,
        "height": "container",
        "data": {"values": rows},
        "transform": [
            {
                "fold": ["LFL_Growth_Pct", "LFL_Growth_SameRoleContract_Pct"],
                "as": ["Series", "Growth"],
            }
        ],
        "mark": mark,
        "encoding": {
            "x": {"field": "Snapshot_Date", "type": "temporal", "title": None},
            "y": {
                "field": "Growth", "type": "quantitative", "title": "YoY groei",
                "axis": {"format": "%"},
            },
            "color": {
                "field": "Series", "type": "nominal",
                "legend": {
                    "title": None,
                    "labelExpr": (
                        "datum.label == 'LFL_Growth_Pct' ? 'Alle behouden medewerkers' : "
                        "'Zelfde functie en contract'"
                    ),
                },
            },
            "tooltip": [
                {"field": "Snapshot_Date", "type": "temporal", "title": "Datum"},
                {"field": "Growth", "type": "quantitative", "format": ".1%", "title": "Groei"},
            ],
        },
    }
    return ChatResult(
        "Hier is de gemiddelde salarisgroei (like-for-like) over tijd.", spec
    )


def resolve_viz_request(req: VizRequest, fallback_as_of_date: date) -> ChatResult:
    measure_key = req.measure.value
    kind = MEASURE_CATALOG[measure_key].kind
    # A "trend" measure resolves its own as-of-ness (either the whole
    # series, or the single closest point to req.peildatum) — it doesn't
    # take a plain as_of_date the way kpi/breakdown do.
    as_of_date = req.peildatum or fallback_as_of_date
    if kind == "kpi":
        return _resolve_kpi(measure_key, req, as_of_date)
    if kind == "breakdown":
        return _resolve_breakdown(measure_key, req, as_of_date)
    return _resolve_trend(req)
