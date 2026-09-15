"""Salary ("Salaris") semantic layer — Phase 1 vertical slice.

Thin, typed wrappers around the SQL functions in migrations/views/
(mcp.fn_workforce_snapshot_asof, mcp.fn_salary_lfl_growth_trend). No LLM/
VizRequest machinery yet (that's Phase 3, ARCHITECTURE.md §8) — right now
this just gives the FastAPI routes typed, parameterized queries instead of
hand-rolled SQL scattered through route handlers.

Every query here binds values as real parameters (`?`), never string-
formats them into SQL (ARCHITECTURE.md §7.4). The one place an identifier
(a column name, not a value) is chosen dynamically — the dimension switcher
— goes through DIMENSION_COLUMNS, an allowlist dict: a caller selects a KEY,
the actual SQL identifier always comes from this dict, never from the
caller's string directly.
"""

from dataclasses import dataclass, fields, replace
from datetime import date

from hr_dashboard.db.connection import get_connection

# Allowlist: catalog key -> real SQL identifier. This is the mechanism, not
# string interpolation, that keeps "which column to group by" safe even
# once this is driven by user/LLM input in a later phase.
#
# Matches the old PBIP's own dimension-switcher parameter (`Parameter dim
# slicer salaris`) field-for-field, including its order — Afdeling, Manager,
# Functie, Performance, Tevredenheid. Opleidingsniveau is a filter-rail field
# only there, never a breakdown dimension, so it's deliberately absent here.
# One intentional deviation: the old parameter grouped Manager by first name
# only (`dim_manager[Voornaam]`), which collides whenever two managers share
# a first name; this groups by full name instead, like the filter rail does.
DIMENSION_COLUMNS: dict[str, str] = {
    "afdeling": "Afdeling_Naam",
    "manager": "Manager_Naam",
    "functie": "Functie_Naam",
    "performance": "Performance_Bin",
    "tevredenheid": "Tevredenheidsband_Naam",
}
DIMENSION_LABELS: dict[str, str] = {
    "afdeling": "Afdeling",
    "manager": "Manager",
    "functie": "Functie",
    "performance": "Performance",
    "tevredenheid": "Tevredenheid",
}

# Every filter-rail field -> the column mcp.fn_workforce_snapshot_asof
# returns for it. Used to cross-filter each field's own dropdown options
# by every OTHER currently selected filter (ARCHITECTURE.md — Laura: picking
# an afdeling shouldn't leave incompatible managers selectable afterwards).
FILTER_FIELD_COLUMNS: dict[str, str] = {
    "afdeling": "Afdeling_Naam",
    "functie": "Functie_Naam",
    "manager": "Manager_Naam",
    "opleidingsniveau": "Opleidingsniveau",
    "salaris_categorie": "Salaris_Categorie",
    "bron": "Bron_Naam",
}

# Must stay in sync with CATEGORY_ORDER in salaris.html — the canonical
# band order, since alphabetical sort would put "EUR 100.000 en hoger"
# before "EUR 35.000 - 44.999".
SALARY_CATEGORY_ORDER: list[str] = [
    "Onder EUR 35.000", "EUR 35.000 - 44.999", "EUR 45.000 - 59.999",
    "EUR 60.000 - 79.999", "EUR 80.000 - 99.999", "EUR 100.000 en hoger",
]

# Spreiding salaris and the "Aantal medewerkers" combi-chart both relabel
# these same salary bands with the old PBIP's own numbered, qualitative
# names (dim_salary_band's DAX calculated column 'Salaris categorie')
# instead of the currency-range names — the Salarisgroep filter dropdown
# and the raw Salaris_Categorie column keep the currency-range names.
SALARY_CATEGORY_DISPLAY: dict[str, str] = {
    "Onder EUR 35.000": "1. Laag",
    "EUR 35.000 - 44.999": "2. Ondergemiddeld",
    "EUR 45.000 - 59.999": "3. Gemiddeld",
    "EUR 60.000 - 79.999": "4. Bovengemiddeld",
    "EUR 80.000 - 99.999": "5. Hoog",
    "EUR 100.000 en hoger": "6. Extreem hoog",
}
SALARY_CATEGORY_DISPLAY_ORDER: list[str] = [
    SALARY_CATEGORY_DISPLAY[key] for key in SALARY_CATEGORY_ORDER
]

# Must stay in sync with BENCHMARK_ORDER in salaris.html — mirrors the old
# PBIP's `Benchmark groepen` calculated column (fact_workforce_snapshot),
# which prefixes Benchmark_Status with its rank for the same reason.
BENCHMARK_STATUS_ORDER: list[str] = [
    "Ver onder benchmark", "Onder benchmark", "Rond benchmark",
    "Boven benchmark", "Ver boven benchmark",
]


@dataclass
class SalaryFilters:
    """The Salaris page's filter rail — every field defaults to "no filter"
    (None), matching the old report's "All" slicer state."""

    afdeling: str | None = None
    functie: str | None = None
    manager: str | None = None
    opleidingsniveau: str | None = None
    salaris_categorie: str | None = None
    bron: str | None = None

    def as_sql_params(self) -> tuple:
        # Order must match mcp.fn_workforce_snapshot_asof's parameter order
        # (after @as_of_date).
        return (
            self.afdeling,
            self.functie,
            self.manager,
            self.opleidingsniveau,
            self.salaris_categorie,
            self.bron,
        )

    def is_empty(self) -> bool:
        return all(getattr(self, f.name) is None for f in fields(self))


# mcp.fn_workforce_snapshot_asof(@as_of_date, then 6 filter params) — used
# everywhere the function is called from Python, so the placeholder count
# only needs updating in one place if the function ever gains another param.
_ASOF_PARAM_PLACEHOLDERS = "?, " * 6 + "?"


def _rows_as_dicts(cursor) -> list[dict]:
    columns = [c[0] for c in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _snapshot_asof_sql(select_clause: str) -> str:
    return (
        f"SELECT {select_clause} "
        f"FROM mcp.fn_workforce_snapshot_asof({_ASOF_PARAM_PLACEHOLDERS})"
    )


@dataclass
class SalaryKpis:
    median_salaris: float | None
    gemiddeld_benchmark_ratio: float | None
    pct_onder_benchmark: float | None
    aantal_medewerkers: int


def get_latest_snapshot_date() -> date:
    """The default "Peildatum" when none is chosen — mirrors the old model's
    `Peildatum = MAX(dim_datum.Datum)` measure."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT MAX(Snapshot_Date) FROM dbo.fact_workforce_snapshot")
        return cur.fetchone()[0]


def get_filter_options(as_of_date: date, filters: SalaryFilters) -> dict[str, list[str]]:
    """Cross-filtered option lists for the filter-rail dropdowns.

    Each field's own list is computed with that field's filter cleared but
    every OTHER currently selected filter applied — so picking Afdeling=HR
    narrows the Manager dropdown to HR's own managers, without a selected
    value ever making itself vanish from its own list. Six small queries
    against the as-of function (tiny data volume, ARCHITECTURE.md §11).
    """
    with get_connection() as conn:
        cur = conn.cursor()
        options = {}
        for field, column in FILTER_FIELD_COLUMNS.items():
            probe_filters = replace(filters, **{field: None})
            params = (as_of_date, *probe_filters.as_sql_params())
            cur.execute(
                f"""
                SELECT DISTINCT {column}
                FROM mcp.fn_workforce_snapshot_asof({_ASOF_PARAM_PLACEHOLDERS})
                WHERE {column} IS NOT NULL
                """,
                params,
            )
            values = [r[0] for r in cur.fetchall()]
            if field == "salaris_categorie":
                values.sort(key=SALARY_CATEGORY_ORDER.index)
            else:
                values.sort()
            options[field] = values
        return options


def get_salary_kpis(as_of_date: date, filters: SalaryFilters) -> SalaryKpis:
    # Two straightforward round-trips rather than one query fighting to mix
    # PERCENTILE_CONT with plain aggregates cleanly — trivial either way at
    # this data volume (tens to low hundreds of rows).
    params = (as_of_date, *filters.as_sql_params())
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            _snapshot_asof_sql(
                "DISTINCT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY Salaris) OVER ()"
            ),
            params,
        )
        median_row = cur.fetchone()
        median_salaris = median_row[0] if median_row else None

        cur.execute(
            f"""
            SELECT
                AVG(Benchmark_Ratio) AS gemiddeld_benchmark_ratio,
                AVG(CASE WHEN Benchmark_Ratio < 1.0 THEN 1.0 ELSE 0.0 END) AS pct_onder_benchmark,
                COUNT(*) AS aantal_medewerkers
            FROM mcp.fn_workforce_snapshot_asof({_ASOF_PARAM_PLACEHOLDERS})
            """,
            params,
        )
        row = cur.fetchone()
        return SalaryKpis(
            median_salaris=median_salaris,
            gemiddeld_benchmark_ratio=row.gemiddeld_benchmark_ratio,
            pct_onder_benchmark=row.pct_onder_benchmark,
            aantal_medewerkers=row.aantal_medewerkers,
        )


def _relabel_salaris_categorie(rows: list[dict]) -> list[dict]:
    """Swaps each row's Salaris_Categorie for the old PBIP's own numbered,
    qualitative salary-band name (SALARY_CATEGORY_DISPLAY) in place."""
    for row in rows:
        row["Salaris_Categorie"] = SALARY_CATEGORY_DISPLAY.get(
            row["Salaris_Categorie"], row["Salaris_Categorie"]
        )
    return rows


_EMPLOYEE_ROW_COLUMNS = (
    "Employee_Key, Salaris, Salaris_Categorie, Benchmark_Ratio, Benchmark_Status, "
    "Afdeling_Naam, Manager_Naam, Functie_Naam, Performance_Bin, Tevredenheidsband_Naam"
)


def get_employee_rows(as_of_date: date, filters: SalaryFilters) -> list[dict]:
    """One row per employee, rail-filtered only — every field a chart or a
    click-to-highlight computation might need.

    Two jobs: (1) Spreiding salaris bins Salaris client-side (Vega-Lite's
    own `bin` transform, the same approach used in the Vega-Lite/Plotly
    comparison artifact, so the chart spec owns bin width, not this query);
    (2) salaris.html reuses this same array to recompute the KPI tiles for
    whatever's currently highlighted, entirely client-side (no server round
    trip per click — ARCHITECTURE.md, the connection-per-request cost is
    real and a click-triggered reload was the reason it felt slow).
    """
    params = (as_of_date, *filters.as_sql_params())
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(_snapshot_asof_sql(_EMPLOYEE_ROW_COLUMNS), params)
        return _relabel_salaris_categorie(_rows_as_dicts(cur))


def _validate_dimension(dimension: str) -> str:
    """Returns the real SQL column for `dimension`, or raises — never lets
    the caller's string reach SQL directly (DIMENSION_COLUMNS is the
    allowlist, ARCHITECTURE.md §7.4)."""
    if dimension not in DIMENSION_COLUMNS:
        raise ValueError(f"Unknown dimension: {dimension!r} (allowed: {list(DIMENSION_COLUMNS)})")
    return DIMENSION_COLUMNS[dimension]


def get_headcount_by_dimension(
    as_of_date: date, dimension: str, filters: SalaryFilters
) -> list[dict]:
    """Headcount by Salaris_Categorie, grouped by an approved dimension —
    the old PBIP's "Aantal medewerkers" chart. Colored by the qualitative,
    numbered salary-band labels (SALARY_CATEGORY_DISPLAY), matching that
    chart specifically — not the currency-range labels used elsewhere.

    Also carries Benchmark_Status per row, unused by this chart's own
    color encoding but needed so a click-to-highlight originating in the
    *other* combi-chart (colored by Benchmark_Status) can match precisely
    against both dimension_value and Salaris_Categorie here, instead of
    only being able to check one of the two (salaris.html — Laura: a click
    on Productie's "Laag" segment was highlighting all of Productie in the
    benchmark chart, not just its "Laag" slice, because that chart's data
    had no Salaris_Categorie to check against). Vega-Lite's own "sum"
    aggregate still collapses across Benchmark_Status for this chart's
    actual bars, so nothing about what's rendered changes.
    """
    column = _validate_dimension(dimension)
    params = (as_of_date, *filters.as_sql_params())

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT {column} AS dimension_value, Salaris_Categorie, Benchmark_Status,
                   COUNT(*) AS aantal
            FROM mcp.fn_workforce_snapshot_asof({_ASOF_PARAM_PLACEHOLDERS})
            WHERE {column} IS NOT NULL
            GROUP BY {column}, Salaris_Categorie, Benchmark_Status
            """,
            params,
        )
        return _relabel_salaris_categorie(_rows_as_dicts(cur))


def get_benchmark_distribution_by_dimension(
    as_of_date: date, dimension: str, filters: SalaryFilters
) -> list[dict]:
    """Headcount by Benchmark_Status, grouped by an approved dimension — the
    old PBIP's "Verdeling salaris t.o.v. benchmark" chart. Distinct from
    get_headcount_by_dimension, which colors by salary band instead.

    Also carries Salaris_Categorie per row, for the same click-to-highlight
    precision reason documented on get_headcount_by_dimension, in reverse."""
    column = _validate_dimension(dimension)
    params = (as_of_date, *filters.as_sql_params())

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT {column} AS dimension_value, Benchmark_Status, Salaris_Categorie,
                   COUNT(*) AS aantal
            FROM mcp.fn_workforce_snapshot_asof({_ASOF_PARAM_PLACEHOLDERS})
            WHERE {column} IS NOT NULL AND Benchmark_Status IS NOT NULL
            GROUP BY {column}, Benchmark_Status, Salaris_Categorie
            """,
            params,
        )
        return _relabel_salaris_categorie(_rows_as_dicts(cur))


def get_lfl_growth_trend(start_date: date, end_date: date) -> list[dict]:
    # Not filtered by the rail (yet) — the LFL cohort comparison already has
    # its own retained-employee logic; combining that with the filter rail
    # (e.g. "only Productie, both 12 months ago AND now") is a real design
    # question deferred until this chart is revisited, not an oversight.
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT Snapshot_Date, LFL_Growth_Pct, LFL_Growth_SameRoleContract_Pct
            FROM mcp.fn_salary_lfl_growth_trend(?, ?)
            ORDER BY Snapshot_Date
            """,
            start_date,
            end_date,
        )
        return _rows_as_dicts(cur)
