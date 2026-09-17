"""Employee profile ("Profiel") semantic layer.

Reuses the same "op peildatum" as-of pattern salary.py already established
(mcp.fn_workforce_snapshot_asof) — no new SQL migration needed for this
page. The function's own parameters cover Afdeling/Functie/Manager (the
filter-rail fields Laura asked for first: "narrowing down the list of
employees... by choosing e.g. a department or role or manager"); it also
already RETURNS Performance_Bin/Tevredenheidsband_Naam as columns (Salaris
uses these too), just not as filterable parameters — so Performance/
Tevredenheid narrowing (Laura's follow-up: "find all employees with e.g. a
low satisfaction score, or performance score") is applied as an outer
WHERE around the function call instead of a new function parameter, same
"assemble parameterized SQL from catalog-approved pieces" boundary
ARCHITECTURE.md §7.3 already describes.

Unlike salary.py's filter rail (narrows a whole POPULATION to aggregate),
this page's filter rail narrows which employees appear in the search
picker — the single selected Employee_Key is what everything else on the
page is then keyed on.
"""

from dataclasses import dataclass, fields, replace
from datetime import date

from hr_dashboard.db.connection import get_connection
from hr_dashboard.semantic.common import rows_as_dicts

# mcp.fn_workforce_snapshot_asof(@as_of_date, @afdeling, @functie, @manager,
# @opleidingsniveau, @salaris_categorie) — this page only ever drives the
# first three; the last two are always NULL here (no Opleidingsniveau/
# Salarisgroep field on this page's rail, unlike Salaris's).
_ASOF_PARAM_PLACEHOLDERS = "?, " * 5 + "?"

# Every Profiel filter-rail field -> the column mcp.fn_workforce_snapshot_asof
# returns for it — used both for cross-filtering each field's own dropdown
# (same idea as salary.FILTER_FIELD_COLUMNS) and for narrowing the employee
# picker itself.
FILTER_FIELD_COLUMNS: dict[str, str] = {
    "afdeling": "Afdeling_Naam",
    "functie": "Functie_Naam",
    "manager": "Manager_Naam",
    "performance": "Performance_Bin",
    "tevredenheid": "Tevredenheidsband_Naam",
}

# Performance_Bin's own natural order (matches salary.py's rebuild of the
# old dim_employee[Performance Bin] DAX column: 0.5-wide bins) — an
# alphabetical sort would put "< 3.0" after "4.5 - 5.0".
PERFORMANCE_BIN_ORDER: list[str] = ["< 3.0", "3.0 - 3.5", "3.5 - 4.0", "4.0 - 4.5", "4.5 - 5.0"]
# dim_satisfaction_band's own SatisfactionBand_Key order (confirmed via a
# live query — not every one of these 5 necessarily appears in the data,
# but the sort should still be correct if they do).
TEVREDENHEID_BAND_ORDER: list[str] = ["Zeer laag", "Laag", "Neutraal", "Hoog", "Zeer hoog"]

# fact_employment's own event types (dim_event_type), oldest-events-first
# order isn't meaningful here (a career can revisit any of these), so no
# canonical order constant is needed the way the two bins above need one.

# "Status" isn't a plain column mcp.fn_workforce_snapshot_asof returns (it
# has no as-of-dependent notion of "in dienst") — it's computed the same
# way the identity card's own status label is (profiel.html: departed
# strictly before/on the selected peildatum), via dim_employee's
# Datum_uitdienst. Hardcoded rather than queried since there are only ever
# exactly these two possible values.
STATUS_OPTIONS: list[str] = ["In dienst", "Uit dienst"]
_STATUS_CASE_EXPR = (
    "CASE WHEN e.Datum_uitdienst IS NOT NULL AND e.Datum_uitdienst <= ? "
    "THEN 'Uit dienst' ELSE 'In dienst' END"
)


@dataclass
class ProfileFilters:
    """Narrows the employee picker on Profiel — not a population filter
    like SalaryFilters, a search filter. Every field defaults to "no
    filter" (None), matching the rest of the app's filter-rail convention."""

    afdeling: str | None = None
    functie: str | None = None
    manager: str | None = None
    performance: str | None = None
    tevredenheid: str | None = None
    status: str | None = None

    def is_empty(self) -> bool:
        return all(getattr(self, f.name) is None for f in fields(self))


def _snapshot_sql(select_clause: str) -> str:
    # Joins dim_employee (aliased e) alongside the as-of function (aliased
    # s) purely for the Status filter above — every other field this page
    # filters by already comes straight from the function's own output.
    return (
        f"SELECT {select_clause} "
        f"FROM mcp.fn_workforce_snapshot_asof({_ASOF_PARAM_PLACEHOLDERS}) AS s "
        "JOIN dbo.dim_employee AS e ON e.Employee_Key = s.Employee_Key "
        "WHERE (? IS NULL OR s.Performance_Bin = ?) "
        "AND (? IS NULL OR s.Tevredenheidsband_Naam = ?) "
        f"AND (? IS NULL OR {_STATUS_CASE_EXPR} = ?)"
    )


def _snapshot_params(as_of_date: date, filters: ProfileFilters) -> tuple:
    return (
        as_of_date, filters.afdeling, filters.functie, filters.manager, None, None,
        filters.performance, filters.performance,
        filters.tevredenheid, filters.tevredenheid,
        filters.status, as_of_date, filters.status,
    )


def get_profile_filter_options(as_of_date: date, filters: ProfileFilters) -> dict[str, list[str]]:
    """Cross-filtered dropdown options for the Profiel filter rail — same
    "clear this one field, keep the others" idea as salary.get_filter_options."""
    with get_connection() as conn:
        cur = conn.cursor()
        options = {}
        for field, column in FILTER_FIELD_COLUMNS.items():
            probe_filters = replace(filters, **{field: None})
            cur.execute(
                _snapshot_sql(f"DISTINCT s.{column}") + f" AND s.{column} IS NOT NULL",
                _snapshot_params(as_of_date, probe_filters),
            )
            values = [r[0] for r in cur.fetchall()]
            if field == "performance":
                values.sort(key=PERFORMANCE_BIN_ORDER.index)
            elif field == "tevredenheid":
                values.sort(key=TEVREDENHEID_BAND_ORDER.index)
            else:
                values.sort()
            options[field] = values
        options["status"] = STATUS_OPTIONS
        return options


def get_narrowed_employees(as_of_date: date, filters: ProfileFilters) -> list[dict]:
    """Employee_Key/Medewerker_Naam pairs matching the current filter rail —
    what the employee-search picker offers."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            _snapshot_sql("s.Employee_Key, s.Medewerker_Naam") + " ORDER BY s.Medewerker_Naam",
            _snapshot_params(as_of_date, filters),
        )
        return rows_as_dicts(cur)


def get_employee_snapshot(employee_key: int, as_of_date: date) -> dict | None:
    """One employee's as-of facts — salary, benchmark ratio, compa-ratio,
    department/role/manager, performance/tevredenheid bands — via the same
    mcp.fn_workforce_snapshot_asof every other page already uses, this time
    scoped to one Employee_Key instead of a rail-filtered population."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT *
            FROM mcp.fn_workforce_snapshot_asof({_ASOF_PARAM_PLACEHOLDERS})
            WHERE Employee_Key = ?
            """,
            (as_of_date, None, None, None, None, None, employee_key),
        )
        row = cur.fetchone()
        if row is None:
            return None
        columns = [c[0] for c in cur.description]
        return dict(zip(columns, row))


def get_employee_identity(employee_key: int) -> dict | None:
    """Static per-employee facts that don't need as-of resolution — a
    birthdate or avatar doesn't change between snapshots — so this reads
    dim_employee directly rather than going through the as-of function."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT Voornaam, Achternaam, Geboortedatum, Avatar_URL,
                   Eerste_Indienst_Datum, Aaneengesloten_Indienst_Datum,
                   Datum_uitdienst, In_Dienst
            FROM dbo.dim_employee
            WHERE Employee_Key = ?
            """,
            (employee_key,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        columns = [c[0] for c in cur.description]
        return dict(zip(columns, row))


def get_employee_history(employee_key: int) -> list[dict]:
    """Career events (hire, promotion, transfer, salary change, contract
    change, departure, ...), oldest first — computed directly from
    fact_employment here in Python, rather than porting the old PBIP's
    'Functiehistorie tot peildatum' DAX measure (a CONCATENATEX text-
    builder): reimplementing this straight from the raw event rows is
    simpler than reverse-engineering that DAX, and gives the timeline chart
    structured data instead of a pre-formatted string."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT fe.Startdatum, fe.Einddatum, det.Gebeurtenis, fe.Salaris,
                   r.Functie_Naam, fe.Contracttype, dr.Vertrekreden
            FROM dbo.fact_employment fe
            LEFT JOIN dbo.dim_event_type det ON det.EventType_Key = fe.EventType_Key
            LEFT JOIN dbo.dim_role r ON r.Role_Key = fe.Role_Key
            LEFT JOIN dbo.dim_departure_reason dr ON dr.DepartureReason_Key = fe.DepartureReason_Key
            WHERE fe.Employee_Key = ?
            ORDER BY fe.Startdatum
            """,
            (employee_key,),
        )
        return rows_as_dicts(cur)


def get_employee_score_trend(employee_key: int) -> list[dict]:
    """Performance/tevredenheid/betrokkenheid over time — periodic
    fact_workforce_snapshot data (roughly monthly), a different grain from
    get_employee_history's fact_employment career events. "Loopbaan" layers
    this on a second Y-axis alongside the (sparser) salary/event points,
    sharing only the time axis, not the row grain. Laura: Prestatie_Score
    is currently ~0-5 while Tevredenheid_Score/Betrokkenheid_Score are
    ~0-10 (confirmed live), and she's updating the data generator to put
    all three on the same 0-10 scale — nothing here assumes that's already
    done (no hardcoded scale/domain), so the chart will pick up the
    unified scale automatically once that lands, no code change needed."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT Snapshot_Date, Prestatie_Score, Tevredenheid_Score, Betrokkenheid_Score
            FROM dbo.fact_workforce_snapshot
            WHERE Employee_Key = ?
            ORDER BY Snapshot_Date
            """,
            (employee_key,),
        )
        return rows_as_dicts(cur)
