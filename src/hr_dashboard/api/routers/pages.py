import json
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Query, Request
from fastapi.templating import Jinja2Templates

from hr_dashboard.semantic import common, profile, salary
from hr_dashboard.semantic.profile import ProfileFilters
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


def _last_refresh_label() -> str:
    """A plain d-m-Y H:M string, not `%B`-based, so this never depends on
    the server process's locale being set to Dutch."""
    return common.get_last_refresh().strftime("%d-%m-%Y %H:%M")


@router.get("/")
def index():
    return {"pages": ["/salaris"]}


def _clean_dimension(value: str) -> str:
    return value if value in salary.DIMENSION_COLUMNS else "afdeling"


@router.get("/salaris")
def salaris_page(
    request: Request,
    as_of: date | None = Query(default=None),
    dim_headcount: str = Query(default="afdeling"),
    dim_benchmark: str = Query(default="afdeling"),
    dim_new_hire: str = Query(default="afdeling"),
    afdeling: str | None = Query(default=None),
    functie: str | None = Query(default=None),
    manager: str | None = Query(default=None),
    opleidingsniveau: str | None = Query(default=None),
    salaris_categorie: str | None = Query(default=None),
):
    # Each dimension-dependent chart used to share one page-wide switcher;
    # now that every chart is its own freely movable/resizable tile (Laura,
    # reviewing the drag-and-resize idea: a shared control becomes a
    # fragile cross-tile dependency once tiles can be rearranged or hidden
    # independently), each gets its own switcher and its own query param.
    dim_headcount = _clean_dimension(dim_headcount)
    dim_benchmark = _clean_dimension(dim_benchmark)
    dim_new_hire = _clean_dimension(dim_new_hire)

    peildatum = as_of or salary.get_latest_snapshot_date()
    filters = SalaryFilters(
        afdeling=_none_if_blank(afdeling),
        functie=_none_if_blank(functie),
        manager=_none_if_blank(manager),
        opleidingsniveau=_none_if_blank(opleidingsniveau),
        salaris_categorie=_none_if_blank(salaris_categorie),
    )

    kpis = salary.get_salary_kpis(peildatum, filters)
    employee_rows = salary.get_employee_rows(peildatum, filters)
    headcount_by_dimension = salary.get_headcount_by_dimension(
        peildatum, dim_headcount, filters
    )
    benchmark_by_dimension = salary.get_benchmark_distribution_by_dimension(
        peildatum, dim_benchmark, filters
    )
    filter_options = salary.get_filter_options(peildatum, filters)
    total_payroll = salary.compute_total_payroll(employee_rows)
    gender_pay_gap = salary.get_corrected_gender_pay_gap(peildatum, filters)
    new_hire_vs_current = salary.get_new_hire_vs_current(peildatum, dim_new_hire, filters)

    # The LFL trend chart isn't point-in-time like the rest of the page —
    # it's a whole history, so it always spans the database's true earliest
    # to latest snapshot (independent of Peildatum), not a fixed lookback.
    # salaris.html fetches both granularities once and then a client-side
    # range slider + Maand/Jaar toggle works entirely from what's already
    # loaded — no server round trip per interaction (ARCHITECTURE.md —
    # Laura: this was the same "every click reloads the page" complaint
    # that motivated fixing connection pooling).
    lfl_earliest = salary.get_earliest_snapshot_date()
    lfl_latest = salary.get_latest_snapshot_date()
    lfl_trend_monthly = salary.get_lfl_growth_trend(lfl_earliest, lfl_latest, "month")
    lfl_trend_yearly = salary.get_lfl_growth_trend(lfl_earliest, lfl_latest, "year")

    # Dimension-switcher links: same page, same filters, only that one
    # chart's own dimension param changes — built server-side so the
    # template just renders plain <a> hrefs, no client-side state needed
    # for this first slice.
    current_params = dict(request.query_params)
    _DIM_PARAM_NAMES = ("dim_headcount", "dim_benchmark", "dim_new_hire")

    def _dimension_urls(param_name: str) -> dict[str, str]:
        return {
            key: "/salaris?" + "&".join(
                f"{k}={v}" for k, v in {**current_params, param_name: key}.items() if v
            )
            for key in salary.DIMENSION_LABELS
        }

    headcount_dimension_urls = _dimension_urls("dim_headcount")
    benchmark_dimension_urls = _dimension_urls("dim_benchmark")
    new_hire_dimension_urls = _dimension_urls("dim_new_hire")

    # Drill-through links for the two "a specific set of people" KPI tiles —
    # same rail filters carried over (Laura: click the tile, land on a
    # detail table already filtered the way the tile was), only the three
    # per-chart dimension params dropped (the detail page has no dimension
    # switcher) and `subset` added.
    rail_params = {k: v for k, v in current_params.items() if k not in _DIM_PARAM_NAMES}
    medewerkers_urls = {
        subset: "/salaris/medewerkers?" + "&".join(
            f"{k}={v}" for k, v in {**rail_params, "subset": subset}.items() if v
        )
        for subset in ("alle", "onder_benchmark")
    }

    return templates.TemplateResponse(
        request,
        "salaris.html",
        {
            "peildatum": peildatum,
            "last_refresh": _last_refresh_label(),
            "kpis": kpis,
            "total_payroll": total_payroll,
            "gender_pay_gap": gender_pay_gap,
            "filters": filters,
            "filter_options": filter_options,
            "dimension_options": salary.DIMENSION_LABELS,
            "medewerkers_urls": medewerkers_urls,
            "dim_headcount": dim_headcount,
            "dim_benchmark": dim_benchmark,
            "dim_new_hire": dim_new_hire,
            "headcount_dimension_urls": headcount_dimension_urls,
            "benchmark_dimension_urls": benchmark_dimension_urls,
            "new_hire_dimension_urls": new_hire_dimension_urls,
            "headcount_title": salary.DIMENSION_LABELS[dim_headcount],
            "benchmark_title": salary.DIMENSION_LABELS[dim_benchmark],
            "new_hire_title": salary.DIMENSION_LABELS[dim_new_hire],
            "employee_rows_json": json.dumps(employee_rows, default=_json_default),
            "headcount_by_dimension_json": json.dumps(
                headcount_by_dimension, default=_json_default
            ),
            "benchmark_by_dimension_json": json.dumps(
                benchmark_by_dimension, default=_json_default
            ),
            "lfl_trend_monthly_json": json.dumps(lfl_trend_monthly, default=_json_default),
            "lfl_trend_yearly_json": json.dumps(lfl_trend_yearly, default=_json_default),
            "new_hire_vs_current_json": json.dumps(new_hire_vs_current, default=_json_default),
            # So each chart's own click-emit code can translate its own
            # selected dimension key (e.g. "manager") into the real raw
            # employee-row field name (e.g. "Manager_Naam") without
            # duplicating DIMENSION_COLUMNS by hand in JS.
            "dimension_columns_json": json.dumps(salary.DIMENSION_COLUMNS),
        },
    )


# subset key -> (label, predicate on an employee_rows dict). Only the two
# KPI tiles that represent "a specific set of people" drill through (Laura:
# not "gemiddelde"/"mediaan" tiles, which have no single underlying set to
# list) — chart segments still use the existing client-side highlight
# instead, to keep this one mechanism from overlapping with that one.
_MEDEWERKERS_SUBSETS = {
    "alle": ("Alle medewerkers", lambda row: True),
    "onder_benchmark": (
        "Medewerkers onder benchmark",
        lambda row: row["Benchmark_Ratio"] is not None and row["Benchmark_Ratio"] < 1.0,
    ),
}


@router.get("/salaris/medewerkers")
def salaris_medewerkers_page(
    request: Request,
    as_of: date | None = Query(default=None),
    subset: str = Query(default="alle"),
    afdeling: str | None = Query(default=None),
    functie: str | None = Query(default=None),
    manager: str | None = Query(default=None),
    opleidingsniveau: str | None = Query(default=None),
    salaris_categorie: str | None = Query(default=None),
):
    """Drill-through detail page for the "Aantal medewerkers" and "% onder
    benchmark" KPI tiles on /salaris — arrives here with the same filter
    rail already applied (Laura's own framing: "op die KPI klikken en dan op
    een detailpagina uitkomen met een overzicht van medewerkers"), plus its
    own copy of that rail so it can be narrowed further, and a "wis alle
    filters" control she specifically asked for."""
    if subset not in _MEDEWERKERS_SUBSETS:
        subset = "alle"

    peildatum = as_of or salary.get_latest_snapshot_date()
    filters = SalaryFilters(
        afdeling=_none_if_blank(afdeling),
        functie=_none_if_blank(functie),
        manager=_none_if_blank(manager),
        opleidingsniveau=_none_if_blank(opleidingsniveau),
        salaris_categorie=_none_if_blank(salaris_categorie),
    )

    subset_label, subset_predicate = _MEDEWERKERS_SUBSETS[subset]
    employee_rows = [
        row for row in salary.get_employee_rows(peildatum, filters) if subset_predicate(row)
    ]
    filter_options = salary.get_filter_options(peildatum, filters)

    clear_filters_params = {"subset": subset}
    if as_of:
        clear_filters_params["as_of"] = as_of.isoformat()

    return templates.TemplateResponse(
        request,
        "salaris_medewerkers.html",
        {
            "peildatum": peildatum,
            "last_refresh": _last_refresh_label(),
            "subset": subset,
            "subset_label": subset_label,
            "employee_rows": employee_rows,
            "aantal": len(employee_rows),
            "filters": filters,
            "filter_options": filter_options,
            "clear_filters_url": "/salaris/medewerkers?" + "&".join(
                f"{k}={v}" for k, v in clear_filters_params.items()
            ),
        },
    )


@router.get("/profiel")
def profiel_page(
    request: Request,
    as_of: date | None = Query(default=None),
    afdeling: str | None = Query(default=None),
    functie: str | None = Query(default=None),
    manager: str | None = Query(default=None),
    performance: str | None = Query(default=None),
    tevredenheid: str | None = Query(default=None),
    status: str | None = Query(default=None),
    # A plain `int | None` param here 422s on the empty string the
    # "— Kies een medewerker —" placeholder option submits (FastAPI won't
    # coerce "" to None for an int type the way it does for the str|None
    # filter fields above) — every OTHER rail field change auto-submits
    # the whole form (dashboard_base.html), including this one at
    # whatever it's currently set to, so leaving no employee selected and
    # then changing e.g. Afdeling would 422 the whole page.
    employee_key: str | None = Query(default=None),
):
    peildatum = as_of or salary.get_latest_snapshot_date()
    employee_key_int = int(employee_key) if employee_key else None
    filters = ProfileFilters(
        afdeling=_none_if_blank(afdeling),
        functie=_none_if_blank(functie),
        manager=_none_if_blank(manager),
        performance=_none_if_blank(performance),
        tevredenheid=_none_if_blank(tevredenheid),
        status=_none_if_blank(status),
    )

    filter_options = profile.get_profile_filter_options(peildatum, filters)
    narrowed_employees = profile.get_narrowed_employees(peildatum, filters)

    # A selected employee is looked up regardless of whether they still
    # match the CURRENT rail filters — the rail is a search aid for
    # finding someone, not a hard gate on who stays visible once picked
    # (changing a filter after picking someone shouldn't blank the page).
    snapshot = identity = None
    history: list[dict] = []
    if employee_key_int is not None:
        snapshot = profile.get_employee_snapshot(employee_key_int, peildatum)
        if snapshot is not None:
            identity = profile.get_employee_identity(employee_key_int)
            history = profile.get_employee_history(employee_key_int)

    clear_filters_params = {}
    if as_of:
        clear_filters_params["as_of"] = as_of.isoformat()

    return templates.TemplateResponse(
        request,
        "profiel.html",
        {
            "peildatum": peildatum,
            "last_refresh": _last_refresh_label(),
            "filters": filters,
            "filter_options": filter_options,
            "narrowed_employees": narrowed_employees,
            "employee_key": employee_key_int,
            "snapshot": snapshot,
            "identity": identity,
            "history_json": json.dumps(history, default=_json_default),
            "clear_filters_url": "/profiel?" + "&".join(
                f"{k}={v}" for k, v in clear_filters_params.items()
            ),
        },
    )
