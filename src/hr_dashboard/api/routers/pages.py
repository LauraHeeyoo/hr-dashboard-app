import json
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Query, Request
from fastapi.templating import Jinja2Templates

from hr_dashboard.semantic import salary
from hr_dashboard.semantic.salary import SalaryFilters

router = APIRouter()
templates = Jinja2Templates(directory="src/hr_dashboard/templates")


def _json_default(value):
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        # pyodbc returns SQL DECIMAL columns (e.g. Benchmark_Ratio) as
        # Decimal, which json.dumps can't serialize natively. Falling
        # through to str(value) here would silently turn it into a JSON
        # string ("0.82...") instead of a number — fine for server-rendered
        # Jinja text, but breaks any client-side arithmetic on it (the
        # click-to-highlight KPI recompute in salaris.html does exactly
        # that on Benchmark_Ratio).
        return float(value)
    return str(value)


def _none_if_blank(value: str | None) -> str | None:
    """A <select> left on its "Alle" option submits `name=` (empty string),
    not an omitted param — FastAPI binds that to "", not None. Without this,
    every filter round-tripped through the HTML form (not just the ones a
    user actually picked) turns into a `column = ''` condition, which
    matches nothing — exactly the "everything goes empty after Toepassen"
    bug this fixes."""
    return value if value else None


@router.get("/")
def index():
    return {"pages": ["/salaris"]}


@router.get("/salaris")
def salaris_page(
    request: Request,
    as_of: date | None = Query(default=None),
    dimension: str = Query(default="afdeling"),
    afdeling: str | None = Query(default=None),
    functie: str | None = Query(default=None),
    manager: str | None = Query(default=None),
    opleidingsniveau: str | None = Query(default=None),
    salaris_categorie: str | None = Query(default=None),
    bron: str | None = Query(default=None),
):
    if dimension not in salary.DIMENSION_COLUMNS:
        dimension = "afdeling"

    peildatum = as_of or salary.get_latest_snapshot_date()
    filters = SalaryFilters(
        afdeling=_none_if_blank(afdeling),
        functie=_none_if_blank(functie),
        manager=_none_if_blank(manager),
        opleidingsniveau=_none_if_blank(opleidingsniveau),
        salaris_categorie=_none_if_blank(salaris_categorie),
        bron=_none_if_blank(bron),
    )

    kpis = salary.get_salary_kpis(peildatum, filters)
    employee_rows = salary.get_employee_rows(peildatum, filters)
    headcount_by_dimension = salary.get_headcount_by_dimension(peildatum, dimension, filters)
    benchmark_by_dimension = salary.get_benchmark_distribution_by_dimension(
        peildatum, dimension, filters
    )
    filter_options = salary.get_filter_options(peildatum, filters)

    trend_start = date(peildatum.year - 4, peildatum.month, 1)
    lfl_trend = salary.get_lfl_growth_trend(trend_start, peildatum)

    # Dimension-switcher links: same page, same filters, only `dimension`
    # changes — built server-side so the template just renders plain <a>
    # hrefs, no client-side state needed for this first slice.
    current_params = dict(request.query_params)
    dimension_urls = {}
    for key in salary.DIMENSION_LABELS:
        params = {**current_params, "dimension": key}
        dimension_urls[key] = "/salaris?" + "&".join(f"{k}={v}" for k, v in params.items() if v)

    return templates.TemplateResponse(
        request,
        "salaris.html",
        {
            "peildatum": peildatum,
            "kpis": kpis,
            "filters": filters,
            "filter_options": filter_options,
            "dimension": dimension,
            "dimension_options": salary.DIMENSION_LABELS,
            "dimension_urls": dimension_urls,
            "by_dimension_title": salary.DIMENSION_LABELS[dimension],
            "employee_rows_json": json.dumps(employee_rows, default=_json_default),
            "headcount_by_dimension_json": json.dumps(
                headcount_by_dimension, default=_json_default
            ),
            "benchmark_by_dimension_json": json.dumps(
                benchmark_by_dimension, default=_json_default
            ),
            "lfl_trend_json": json.dumps(lfl_trend, default=_json_default),
            # So the client-side highlight/KPI recompute knows which raw
            # employee-row field the current dimension switcher corresponds
            # to (e.g. "manager" -> "Manager_Naam") without duplicating
            # DIMENSION_COLUMNS by hand in JS.
            "dimension_columns_json": json.dumps(salary.DIMENSION_COLUMNS),
        },
    )
