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
from datetime import date, timedelta

from hr_dashboard.db.connection import get_connection
from hr_dashboard.semantic import salary
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

# mcp.fn_workforce_snapshot_asof computes Performance_Bin from the raw,
# un-doubled Prestatie_Score column — everywhere on this page the SCORE
# itself is shown doubled onto a 0-10 scale (see get_employee_score_trend's
# docstring), the BAND needs the same doubling applied for display, or a
# doubled score of e.g. 7.5 would appear next to an un-doubled band like
# "3.5 - 4.0" instead of the matching "7.0 - 8.0". Only a display-layer
# relabeling — filtering (_snapshot_sql) still matches on the raw string.
PERFORMANCE_BIN_DOUBLED: dict[str, str] = {
    "< 3.0": "< 6.0",
    "3.0 - 3.5": "6.0 - 7.0",
    "3.5 - 4.0": "7.0 - 8.0",
    "4.0 - 4.5": "8.0 - 9.0",
    "4.5 - 5.0": "9.0 - 10.0",
}


def double_performance_bin(bin_value: str | None) -> str | None:
    """Maps a raw Performance_Bin (as mcp.fn_workforce_snapshot_asof
    computes it) onto its doubled-scale display label. Falls back to the
    raw value unchanged for any bin not in the map, rather than raising —
    display code should never hard-fail over a labeling gap."""
    if bin_value is None:
        return None
    return PERFORMANCE_BIN_DOUBLED.get(bin_value, bin_value)
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
        result = dict(zip(columns, row))
        # Doubled here at the source (not per-caller) so every consumer of
        # this snapshot — the identity card and the AI summary alike —
        # automatically sees a band that matches the doubled score shown
        # alongside it. See PERFORMANCE_BIN_DOUBLED above for why.
        result["Performance_Bin"] = double_performance_bin(result["Performance_Bin"])
        return result


def get_employee_identity(employee_key: int) -> dict | None:
    """Static per-employee facts that don't need as-of resolution — a
    birthdate or avatar doesn't change between snapshots — so this reads
    dim_employee directly rather than going through the as-of function.

    Bijzondere_Aanstelling is almost always NULL (confirmed live — values
    like "Expat" are the rare exception) — the summary template only
    mentions it when set, the same way it only mentions a departure
    reason when there is one."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT Voornaam, Achternaam, Geboortedatum, Avatar_URL,
                   Eerste_Indienst_Datum, Aaneengesloten_Indienst_Datum,
                   Datum_uitdienst, In_Dienst, Bijzondere_Aanstelling
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
    structured data instead of a pre-formatted string.

    Each fact_employment row is one continuous "stint" (Startdatum ->
    Einddatum) with a Gebeurtenis label — for every row except the very
    last one, that label describes what happened AT Startdatum (a hire,
    promotion, transfer, raise starts a new stint). "Uit dienst" breaks
    that pattern: it's inherently a stint-ENDING event, so its real date
    is that row's Einddatum, not its Startdatum — confirmed directly
    against dim_employee.Datum_uitdienst, which matches the "Uit dienst"
    row's Einddatum, not its Startdatum (Laura caught this: a departure
    date shown on "Loopbaan" didn't match the database). Gebeurtenis_Datum
    below is the one column the timeline chart should actually plot
    events at; Startdatum/Einddatum stay in the result too since the
    tooltip/text still want to show a real stint's boundaries.

    Also carries Tevredenheid_Score_Bij_Uitdienst/
    Betrokkenheid_Score_Bij_Uitdienst — only populated on the "Uit
    dienst" row, a departing employee's satisfaction/engagement AT THE
    MOMENT they left, for the summary to use instead of (or in addition
    to) their last periodic snapshot, which could be a month or more
    stale by comparison.

    Afdeling_Naam (via dim_role, same join build_employee_summary's own
    "Promotie"/"Transfer" verification query used) lets the summary
    describe a Transfer's actual before/after — confirmed live that a
    Transfer does NOT always mean the department changed (some are a
    same-department role change), so the summary needs both fields to
    describe it correctly rather than assuming department always
    changed."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT fe.Startdatum, fe.Einddatum, det.Gebeurtenis, fe.Salaris,
                   r.Functie_Naam, d.Afdeling_Naam, fe.Contracttype, dr.Vertrekreden,
                   fe.Tevredenheid_Score_Bij_Uitdienst, fe.Betrokkenheid_Score_Bij_Uitdienst,
                   CASE WHEN det.Gebeurtenis = 'Uit dienst' THEN fe.Einddatum
                        ELSE fe.Startdatum END AS Gebeurtenis_Datum
            FROM dbo.fact_employment fe
            LEFT JOIN dbo.dim_event_type det ON det.EventType_Key = fe.EventType_Key
            LEFT JOIN dbo.dim_role r ON r.Role_Key = fe.Role_Key
            LEFT JOIN dbo.dim_department d ON d.Department_Key = r.Department_Key
            LEFT JOIN dbo.dim_departure_reason dr ON dr.DepartureReason_Key = fe.DepartureReason_Key
            WHERE fe.Employee_Key = ?
            ORDER BY Gebeurtenis_Datum
            """,
            (employee_key,),
        )
        return rows_as_dicts(cur)


def get_employee_score_trend(employee_key: int) -> list[dict]:
    """Performance/tevredenheid/betrokkenheid/verzuim over time — periodic
    fact_workforce_snapshot data (roughly monthly), a different grain from
    get_employee_history's fact_employment career events. "Loopbaan" layers
    the three scores on their own panel and Verzuim_Werkdagen on another,
    both sharing only the time axis with the (sparser) salary/event panel,
    not the row grain.

    Verzuim_Werkdagen (not Afwezige_Dagen) matches what the old Power BI
    model's own absence measures used — sick-leave workdays specifically,
    not every kind of absence (planned leave, public holidays, etc.). The
    Verzuim page itself isn't built yet in this app; this is the first
    place that column is read from here.

    Also joins each row's own driver name (same three dim_*_driver joins
    get_employee_hr_context uses, just for every snapshot here instead of
    only the latest) — the score chart marks the points where a driver
    changed and shows the driver in the tooltip at every point, not just
    the single "most recent" one hr_context needs for the AI summary."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT s.Snapshot_Date, s.Prestatie_Score, s.Tevredenheid_Score,
                   s.Betrokkenheid_Score, s.Verzuim_Werkdagen,
                   pd.Factor_Naam AS Performance_Driver,
                   sd.Factor_Naam AS Satisfaction_Driver,
                   ed.Factor_Naam AS Engagement_Driver
            FROM dbo.fact_workforce_snapshot AS s
            LEFT JOIN dbo.dim_performance_driver AS pd
                ON pd.PerformanceDriver_Key = s.PerformanceDriver_Key
            LEFT JOIN dbo.dim_satisfaction_driver AS sd
                ON sd.SatisfactionDriver_Key = s.SatisfactionDriver_Key
            LEFT JOIN dbo.dim_engagement_driver AS ed
                ON ed.EngagementDriver_Key = s.EngagementDriver_Key
            WHERE s.Employee_Key = ?
            ORDER BY s.Snapshot_Date
            """,
            (employee_key,),
        )
        rows = rows_as_dicts(cur)
        # DELIBERATE, PERMANENT (Laura, 2026-09-17/18): Prestatie_Score is
        # still ~0-5 in the live data while Tevredenheid_Score/
        # Betrokkenheid_Score are already ~0-10 (confirmed live).
        # Prestatie_Score and Kandidaat_Kwaliteit (get_employee_hr_context)
        # both feed many other parts of the data-simulation engine, so
        # unifying the scale in the generator itself would ripple through
        # the whole project — Laura decided it's simpler to keep this
        # scaling here in app-logic instead, permanently, rather than a
        # stopgap pending a generator change. get_peer_group_averages below
        # has the exact same doubling, for the exact same reason — keep
        # both in sync if this ever changes.
        for row in rows:
            if row["Prestatie_Score"] is not None:
                row["Prestatie_Score"] = row["Prestatie_Score"] * 2
        return rows


def _value_about_a_year_before(score_trend: list[dict], field: str, latest_date: date):
    """The score_trend row closest to exactly one year before latest_date
    — None if nothing lands within ~2 months of that target (avoids
    comparing against a snapshot that's actually 3+ years old just
    because it happened to be the earliest one)."""
    if not score_trend:
        return None
    target = latest_date - timedelta(days=365)
    candidate = min(score_trend, key=lambda r: abs((r["Snapshot_Date"] - target).days))
    if abs((candidate["Snapshot_Date"] - target).days) > 60:
        return None
    return candidate.get(field)


def get_employee_signals(snapshot: dict, score_trend: list[dict]) -> list[str]:
    """Plain-language, independently-checked observations for the
    "Aandachtspunten" tile — deliberately NOT a composite/numeric "flight
    risk" score (Laura's own proposal explicitly ruled that out: a manager
    should see exactly which real number triggered each line, not just a
    verdict). Every signal below states its own actual figures rather than
    just firing a generic warning, and this returns an empty list rather
    than "nothing to see here" text — the template decides how to word
    the empty state."""
    signals = []

    benchmark_status = snapshot.get("Benchmark_Status")
    benchmark_ratio = snapshot.get("Benchmark_Ratio")
    if benchmark_status in salary.BENCHMARK_STATUS_ORDER[:2] and benchmark_ratio is not None:
        signals.append(
            f"Salaris zit ‘{benchmark_status}’ ({benchmark_ratio:.0%} van de "
            "externe marktbenchmark)."
        )

    compa_ratio = snapshot.get("Compa_Ratio_Interne_Schaal")
    if compa_ratio is not None and compa_ratio < 0.30:
        signals.append(f"Positie in de eigen salarisschaal is laag ({compa_ratio:.0%}).")

    if score_trend:
        latest = score_trend[-1]
        latest_date = latest["Snapshot_Date"]
        score_fields = (("Prestatie_Score", "Performance"), ("Tevredenheid_Score", "Tevredenheid"))
        for field, label in score_fields:
            past_value = _value_about_a_year_before(score_trend, field, latest_date)
            current_value = latest.get(field)
            if past_value is not None and current_value is not None and current_value < past_value:
                signals.append(
                    f"{label} is het afgelopen jaar gedaald (van {past_value:.1f} "
                    f"naar {current_value:.1f})."
                )

        def _verzuim_values(rows: list[dict]) -> list[float]:
            # Verzuim_Werkdagen is a SQL DECIMAL column — pyodbc returns
            # those as decimal.Decimal, which can't be mixed with a plain
            # float in arithmetic (the `* 1.5` below), so cast here at the
            # source rather than at every use site.
            return [
                float(r["Verzuim_Werkdagen"])
                for r in rows
                if r.get("Verzuim_Werkdagen") is not None
            ]

        recent_verzuim = _verzuim_values(score_trend[-3:])
        earlier_verzuim = _verzuim_values(score_trend[:-3])
        if recent_verzuim and earlier_verzuim:
            recent_avg = sum(recent_verzuim) / len(recent_verzuim)
            earlier_avg = sum(earlier_verzuim) / len(earlier_verzuim)
            if earlier_avg > 0 and recent_avg > earlier_avg * 1.5:
                signals.append(
                    "Verzuim ligt de laatste maanden hoger dan gebruikelijk voor deze "
                    f"medewerker ({recent_avg:.1f} dagen/maand recent vs. "
                    f"{earlier_avg:.1f} gemiddeld)."
                )

    return signals


def get_peer_group_averages(employee_key: int, afdeling: str, as_of_date: date) -> dict:
    """Department-peer averages for the "Vergelijking met peers" tile —
    Salaris, Prestatie_Score, Tevredenheid_Score, Betrokkenheid_Score,
    Verzuim_Werkdagen and Compa_Ratio_Interne_Schaal, averaged across
    every OTHER employee in the same department, as of the same
    peildatum (Laura's proposal: "vs. their own department... is a
    fairer comparison than one company-wide blend").

    A direct fact_workforce_snapshot query rather than
    mcp.fn_workforce_snapshot_asof — that function doesn't return
    Tevredenheid_Score/Betrokkenheid_Score/Verzuim_Werkdagen at all (only
    their derived bands/status), so this repeats just its "latest
    snapshot <= peildatum, per employee" join, not the whole function.
    Compa_Ratio_Interne_Schaal isn't a raw column either there or here —
    it's computed the exact same way the function computes it (position
    between dim_salary_scale's own Minimum_Salaris/Maximum_Salaris), just
    averaged across the peer group instead of returned per employee.

    Salaris is explicitly cast to DECIMAL before AVG() — SQL Server's
    AVG() of a plain INT column does integer division (truncates instead
    of averaging), which would silently give a wrong, rounded-down figure
    here."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                AVG(CAST(s.Salaris AS DECIMAL(18, 4))) AS Salaris,
                AVG(s.Prestatie_Score) AS Prestatie_Score,
                AVG(s.Tevredenheid_Score) AS Tevredenheid_Score,
                AVG(s.Betrokkenheid_Score) AS Betrokkenheid_Score,
                AVG(s.Verzuim_Werkdagen) AS Verzuim_Werkdagen,
                AVG(CASE WHEN sca.Maximum_Salaris > sca.Minimum_Salaris
                         THEN CAST(s.Salaris - sca.Minimum_Salaris AS DECIMAL(18, 4))
                              / (sca.Maximum_Salaris - sca.Minimum_Salaris)
                         ELSE NULL
                    END) AS Compa_Ratio_Interne_Schaal,
                COUNT(*) AS Peer_Count
            FROM dbo.fact_workforce_snapshot AS s
            LEFT JOIN dbo.dim_salary_scale AS sca ON sca.SalaryScale_Key = s.SalaryScale_Key
            INNER JOIN (
                SELECT Employee_Key, MAX(Snapshot_Date) AS Snapshot_Date
                FROM dbo.fact_workforce_snapshot
                WHERE Snapshot_Date <= ?
                GROUP BY Employee_Key
            ) AS latest
                ON latest.Employee_Key = s.Employee_Key
               AND latest.Snapshot_Date = s.Snapshot_Date
            JOIN dbo.dim_department AS d ON d.Department_Key = s.Department_Key
            WHERE d.Afdeling_Naam = ?
              AND s.Employee_Key != ?
            """,
            (as_of_date, afdeling, employee_key),
        )
        row = cur.fetchone()
        columns = [c[0] for c in cur.description]
        result = dict(zip(columns, row))
        # Same deliberate, permanent doubling as get_employee_score_trend's
        # own Prestatie_Score, and for the same reason — comparing this
        # employee's (already doubled) score against a peer average that
        # wasn't would make the comparison meaningless, not just
        # inconsistent styling. Keep both in sync if this ever changes.
        if result["Prestatie_Score"] is not None:
            result["Prestatie_Score"] = result["Prestatie_Score"] * 2
        return result


def get_employee_hr_context(employee_key: int) -> dict:
    """The "why" behind the numbers, for build_employee_summary below to
    weave in — not shown anywhere else on the page:

    - The most recent performance/engagement/satisfaction DRIVER (which
      single factor most influenced that score), from the latest
      fact_workforce_snapshot row's own driver foreign keys.
    - How they were hired: fact_recruitment carries Employee_Key
      directly, so this is a plain lookup, not the old PBIP measure's
      "match by Role_Key + closest Decision_Date" reconstruction — an
      employee's own recruitment record is already known exactly.

    Two small queries rather than one join: drivers come from
    fact_workforce_snapshot (one row per employee per month),
    recruitment context from fact_recruitment (one row per employee,
    ever) — joining them would multiply one side by the other for no
    reason."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT TOP 1
                pd.Factor_Naam AS Performance_Driver,
                ed.Factor_Naam AS Engagement_Driver,
                sd.Factor_Naam AS Satisfaction_Driver
            FROM dbo.fact_workforce_snapshot AS s
            LEFT JOIN dbo.dim_performance_driver AS pd
                ON pd.PerformanceDriver_Key = s.PerformanceDriver_Key
            LEFT JOIN dbo.dim_engagement_driver AS ed
                ON ed.EngagementDriver_Key = s.EngagementDriver_Key
            LEFT JOIN dbo.dim_satisfaction_driver AS sd
                ON sd.SatisfactionDriver_Key = s.SatisfactionDriver_Key
            WHERE s.Employee_Key = ?
            ORDER BY s.Snapshot_Date DESC
            """,
            (employee_key,),
        )
        row = cur.fetchone()
        columns = [c[0] for c in cur.description]
        context = dict(zip(columns, row)) if row else {}

        cur.execute(
            """
            SELECT TOP 1 fr.Kandidaat_Kwaliteit, hs.Bron_Naam
            FROM dbo.fact_recruitment AS fr
            LEFT JOIN dbo.dim_hire_source AS hs ON hs.HireSource_Key = fr.HireSource_Key
            WHERE fr.Employee_Key = ?
            ORDER BY fr.Decision_Date DESC
            """,
            (employee_key,),
        )
        row = cur.fetchone()
        if row:
            columns = [c[0] for c in cur.description]
            context.update(dict(zip(columns, row)))
        else:
            context["Kandidaat_Kwaliteit"] = None
            context["Bron_Naam"] = None

        # Same deliberate, permanent 0-5 -> 0-10 doubling as
        # Prestatie_Score (see get_employee_score_trend) — Kandidaat_
        # Kwaliteit is still ~0-5 in the live data, and feeds the same
        # data-simulation engine elsewhere, so it gets the same app-side
        # scaling rather than a generator change.
        if context["Kandidaat_Kwaliteit"] is not None:
            context["Kandidaat_Kwaliteit"] = context["Kandidaat_Kwaliteit"] * 2
        return context


# Dutch month names, "voluit geschreven" (written out in full) as the
# summary's own template text requires — date.strftime("%B") would depend
# on the server's locale being set to Dutch, which isn't guaranteed.
_MAAND_NAMEN: list[str] = [
    "januari", "februari", "maart", "april", "mei", "juni",
    "juli", "augustus", "september", "oktober", "november", "december",
]

# Career-trajectory events worth calling out in the summary — deliberately
# NOT every dim_event_type value. Salarisaanpassing is routine enough
# (most employees have several) to not tell much of a story, and would
# quietly reintroduce salary content the summary deliberately dropped.
# Contract verlengd is similarly routine. Locatietransfer is a different
# topic (where someone works, not career progression) and pairs better
# with a static "Location" fact than a trajectory sentence.
_PROMOTIE = "Promotie"
_TRANSFER = "Transfer"
_CONTRACT_VAST = "Contract omgezet naar vast"


def _maand_jaar(d: date) -> str:
    return f"{_MAAND_NAMEN[d.month - 1]} {d.year}"


def _join_and(items: list[str]) -> str:
    """Dutch list join — comma-separated, "en" (not ", en") before the
    last item, no Oxford comma."""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " en " + items[-1]


def _next_occurrence(month: int, day: int, on_or_after: date) -> date:
    """The next date with this month/day that isn't before on_or_after —
    used for both "next birthday" and "next work anniversary." Falls back
    to the 28th for a Feb 29 birthdate in a non-leap year rather than
    raising, since a slightly-off fallback date beats a crash over a rare
    edge case."""
    for year in (on_or_after.year, on_or_after.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            candidate = date(year, month, 28)
        if candidate >= on_or_after:
            return candidate
    raise AssertionError("unreachable — the second year always qualifies")


def _latest_transfer_description(history: list[dict]) -> str | None:
    """Describes the most recent Transfer's actual before/after — a
    Transfer does NOT always mean the department changed (confirmed
    live: some are a same-department role change, e.g. Supply Chain
    Planner -> Inkoper within Logistiek), so this only names the
    department when it's actually different, rather than assuming it
    always is."""
    transfer_indices = [
        i for i, e in enumerate(history) if e["Gebeurtenis"] == _TRANSFER and i > 0
    ]
    if not transfer_indices:
        return None
    i = transfer_indices[-1]
    old, new = history[i - 1], history[i]
    if old["Afdeling_Naam"] == new["Afdeling_Naam"]:
        return (
            f"De laatste transfer was van {old['Functie_Naam']} naar {new['Functie_Naam']} "
            f"(beide binnen {new['Afdeling_Naam']})."
        )
    return (
        f"De laatste transfer was van {old['Functie_Naam']} ({old['Afdeling_Naam']}) naar "
        f"{new['Functie_Naam']} ({new['Afdeling_Naam']})."
    )


def _career_trajectory_bullet(naam: str, history: list[dict]) -> str | None:
    promotie_count = sum(1 for e in history if e["Gebeurtenis"] == _PROMOTIE)
    transfer_count = sum(1 for e in history if e["Gebeurtenis"] == _TRANSFER)
    contract_vast = any(e["Gebeurtenis"] == _CONTRACT_VAST for e in history)

    counted = []
    if promotie_count:
        counted.append(f"{promotie_count} keer een promotie")
    if transfer_count:
        counted.append(f"{transfer_count} keer een transfer")

    if not counted and not contract_vast:
        return None

    if counted:
        sentence = f"Sinds indiensttreding heeft {naam} {_join_and(counted)} gehad"
        sentence += ", en is overgegaan naar een vast contract." if contract_vast else "."
    else:
        sentence = f"Sinds indiensttreding is {naam} overgegaan naar een vast contract."

    if transfer_count:
        transfer_detail = _latest_transfer_description(history)
        if transfer_detail:
            sentence += f" {transfer_detail}"
    return sentence


def build_employee_summary(
    snapshot: dict, identity: dict, history: list[dict], hr_context: dict, peildatum: date
) -> list[str]:
    """A short, template-based profile summary — deterministic, not an
    LLM call. Replaces an earlier LLM-generated version: Laura's call,
    since a fixed sentence around a known value is cheaper and more
    trustworthy than asking a model to restate it (the same reasoning
    llm/client.py's own docstring already gives for why the Salaris
    chat never uses a second LLM call to phrase its final answer either),
    and a template can't introduce a grammar mistake a model occasionally
    did (e.g. blending "werkt sinds X" and "is sinds X in dienst" into
    the ungrammatical "werkt sinds X in dienst").

    Each bullet is its own list entry (rendered as one <li> each) and
    omitted entirely when its data doesn't apply — matching
    get_employee_signals' own "omit rather than force a result"
    convention, e.g. an employee with zero promotions/transfers gets no
    career-trajectory bullet rather than one saying "0 promoties.\""""
    naam = snapshot["Medewerker_Naam"]
    role = snapshot["Functie_Naam"]
    is_departed = (
        identity["Datum_uitdienst"] is not None and identity["Datum_uitdienst"] <= peildatum
    )
    departure_row = next((e for e in history if e["Gebeurtenis"] == "Uit dienst"), None)

    bullets = []

    if is_departed and departure_row:
        opening = (
            f"{naam} was {role} en was in dienst van "
            f"{_maand_jaar(identity['Aaneengesloten_Indienst_Datum'])} tot "
            f"{_maand_jaar(departure_row['Gebeurtenis_Datum'])}."
        )
        if departure_row.get("Vertrekreden"):
            opening += f" De reden van vertrek: {departure_row['Vertrekreden']}."
        bullets.append(opening)
    else:
        bullets.append(
            f"{naam} is {role} en is in dienst sinds "
            f"{_maand_jaar(identity['Aaneengesloten_Indienst_Datum'])}."
        )

    if identity.get("Bijzondere_Aanstelling"):
        werkwoord = "had" if is_departed else "heeft"
        bullets.append(
            f"{naam} {werkwoord} een bijzondere aanstelling: {identity['Bijzondere_Aanstelling']}."
        )

    trajectory = _career_trajectory_bullet(naam, history)
    if trajectory:
        bullets.append(trajectory)

    driver_parts = []
    if hr_context.get("Performance_Driver"):
        driver_parts.append(
            f"was {hr_context['Performance_Driver']} de belangrijkste driver voor performance"
        )
    if hr_context.get("Satisfaction_Driver"):
        driver_parts.append(
            f"werd tevredenheid vooral beïnvloed door {hr_context['Satisfaction_Driver']}"
        )
    if hr_context.get("Engagement_Driver"):
        driver_parts.append(
            f"was {hr_context['Engagement_Driver']} de belangrijkste factor voor betrokkenheid"
        )
    if driver_parts:
        bullets.append(f"Op basis van het laatste meetmoment {_join_and(driver_parts)}.")

    hiring_source = hr_context.get("Bron_Naam")
    candidate_quality = hr_context.get("Kandidaat_Kwaliteit")
    if hiring_source:
        hiring = f"{naam} is aangenomen via {hiring_source}."
        if candidate_quality is not None:
            hiring += f" De kandidaatkwaliteit was {candidate_quality:.1f}."
        bullets.append(hiring)
    elif candidate_quality is not None:
        bullets.append(f"De kandidaatkwaliteit bij aanname was {candidate_quality:.1f}.")

    if not is_departed:
        geboortedatum = identity.get("Geboortedatum")
        aanneem_datum = identity.get("Aaneengesloten_Indienst_Datum")
        parts = []
        if geboortedatum:
            parts.append(
                f"{naam} is jarig op {geboortedatum.day} {_MAAND_NAMEN[geboortedatum.month - 1]}."
            )
        if aanneem_datum:
            volgend_jubileum = _next_occurrence(
                aanneem_datum.month, aanneem_datum.day, peildatum
            )
            jaren_in_dienst = volgend_jubileum.year - aanneem_datum.year
            parts.append(
                f"Het volgende jubileum is op {volgend_jubileum.day} "
                f"{_MAAND_NAMEN[volgend_jubileum.month - 1]} en {naam} is dan "
                f"{jaren_in_dienst} jaar in dienst."
            )
        if parts:
            bullets.append(" ".join(parts))

    return bullets
