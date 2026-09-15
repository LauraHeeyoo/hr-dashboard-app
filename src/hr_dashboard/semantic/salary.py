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

from dataclasses import dataclass, fields
from datetime import date

from hr_dashboard.db.connection import get_connection

# Allowlist: catalog key -> real SQL identifier. This is the mechanism, not
# string interpolation, that keeps "which column to group by" safe even
# once this is driven by user/LLM input in a later phase.
DIMENSION_COLUMNS: dict[str, str] = {
    "afdeling": "Afdeling_Naam",
    "functie": "Functie_Naam",
    "manager": "Manager_Naam",
    "opleidingsniveau": "Opleidingsniveau",
}
DIMENSION_LABELS: dict[str, str] = {
    "afdeling": "Afdeling",
    "functie": "Functie",
    "manager": "Manager",
    "opleidingsniveau": "Opleidingsniveau",
}


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


def _rows_as_dicts(cursor) -> list[dict]:
    columns = [c[0] for c in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _snapshot_asof_sql(select_clause: str) -> str:
    return (
        f"SELECT {select_clause} "
        "FROM mcp.fn_workforce_snapshot_asof(?, ?, ?, ?, ?, ?, ?)"
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


def get_filter_options() -> dict[str, list[str]]:
    """Option lists for the filter-rail dropdowns. Small, stable reference
    tables — read directly (ARCHITECTURE.md §7.1's "no view needed" case),
    not through the as-of function."""
    with get_connection() as conn:
        cur = conn.cursor()
        queries = {
            "afdeling": (
                "SELECT DISTINCT Afdeling_Naam FROM dbo.dim_department "
                "WHERE Afdeling_Naam IS NOT NULL ORDER BY 1"
            ),
            "functie": (
                "SELECT DISTINCT Functie_Naam FROM dbo.dim_role "
                "WHERE Functie_Naam IS NOT NULL ORDER BY 1"
            ),
            "manager": (
                "SELECT DISTINCT Voornaam + ' ' + Achternaam FROM dbo.dim_manager ORDER BY 1"
            ),
            "opleidingsniveau": (
                "SELECT DISTINCT Opleidingsniveau FROM dbo.dim_education "
                "WHERE Opleidingsniveau IS NOT NULL ORDER BY 1"
            ),
            "salaris_categorie": (
                "SELECT Salarisband_Naam FROM dbo.dim_salary_band ORDER BY Minimum_Salaris"
            ),
            "bron": (
                "SELECT DISTINCT Bron_Naam FROM dbo.dim_hire_source "
                "WHERE Bron_Naam IS NOT NULL ORDER BY 1"
            ),
        }
        options = {}
        for key, query in queries.items():
            cur.execute(query)
            options[key] = [r[0] for r in cur.fetchall()]
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
            """
            SELECT
                AVG(Benchmark_Ratio) AS gemiddeld_benchmark_ratio,
                AVG(CASE WHEN Benchmark_Ratio < 1.0 THEN 1.0 ELSE 0.0 END) AS pct_onder_benchmark,
                COUNT(*) AS aantal_medewerkers
            FROM mcp.fn_workforce_snapshot_asof(?, ?, ?, ?, ?, ?, ?)
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


def get_salary_distribution(as_of_date: date, filters: SalaryFilters) -> list[dict]:
    """One row per employee: Salaris + Salaris_Categorie.

    Binning happens client-side (Vega-Lite's own `bin` transform) — the same
    approach used in the Vega-Lite/Plotly comparison artifact, so the chart
    spec, not this query, owns bin width.
    """
    params = (as_of_date, *filters.as_sql_params())
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(_snapshot_asof_sql("Employee_Key, Salaris, Salaris_Categorie"), params)
        return _rows_as_dicts(cur)


def get_salary_by_dimension(as_of_date: date, dimension: str, filters: SalaryFilters) -> list[dict]:
    """Headcount by Salaris_Categorie, grouped by an approved dimension.

    `dimension` must be a key in DIMENSION_COLUMNS — anything else raises
    before touching SQL. The actual column name substituted into the query
    always comes from the dict, never from `dimension` itself.
    """
    if dimension not in DIMENSION_COLUMNS:
        raise ValueError(f"Unknown dimension: {dimension!r} (allowed: {list(DIMENSION_COLUMNS)})")
    column = DIMENSION_COLUMNS[dimension]
    params = (as_of_date, *filters.as_sql_params())

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT {column} AS dimension_value, Salaris_Categorie, COUNT(*) AS aantal
            FROM mcp.fn_workforce_snapshot_asof(?, ?, ?, ?, ?, ?, ?)
            WHERE {column} IS NOT NULL
            GROUP BY {column}, Salaris_Categorie
            """,
            params,
        )
        return _rows_as_dicts(cur)


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
