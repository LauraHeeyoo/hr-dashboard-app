"""Reconciliation-style sanity tests for the Salaris semantic layer.

These run against the real (synthetic) db_hr_demo — reasonable at this data
volume (ARCHITECTURE.md §11) — and check the migrated business logic lands
in plausible ranges, catching gross translation errors rather than proving
exact DAX parity (no PBI report is running to diff against directly).
"""

from datetime import date

from hr_dashboard.semantic import salary
from hr_dashboard.semantic.salary import SalaryFilters

AS_OF = date(2026, 8, 31)
NO_FILTERS = SalaryFilters()


def test_get_latest_snapshot_date_is_a_real_date():
    d = salary.get_latest_snapshot_date()
    assert d.year >= 2020


def test_get_earliest_snapshot_date_is_before_the_latest():
    assert salary.get_earliest_snapshot_date() < salary.get_latest_snapshot_date()


def test_salary_kpis_are_plausible():
    kpis = salary.get_salary_kpis(AS_OF, NO_FILTERS)
    assert kpis.aantal_medewerkers > 0
    assert 0.5 < kpis.gemiddeld_benchmark_ratio < 1.5
    assert 0.0 <= kpis.pct_onder_benchmark <= 1.0
    assert 10_000 < kpis.median_salaris < 300_000


def test_salary_kpis_afdeling_filter_narrows_results():
    unfiltered = salary.get_salary_kpis(AS_OF, NO_FILTERS)
    filtered = salary.get_salary_kpis(AS_OF, SalaryFilters(afdeling="Productie"))
    assert 0 < filtered.aantal_medewerkers < unfiltered.aantal_medewerkers


def test_employee_rows_uses_qualitative_salary_labels():
    """Spreiding salaris (and the client-side highlight/KPI recompute) color
    by the old PBIP's own numbered salary-band names ("1. Laag" ...), like
    the "Aantal medewerkers" combi-chart — not the currency-range names
    used by the Salarisgroep filter."""
    rows = salary.get_employee_rows(AS_OF, NO_FILTERS)
    assert len(rows) > 0
    seen = {r["Salaris_Categorie"] for r in rows if r["Salaris_Categorie"] is not None}
    assert seen <= set(salary.SALARY_CATEGORY_DISPLAY.values()), f"unexpected categories: {seen}"


def test_employee_rows_carry_every_field_a_highlight_computation_needs():
    """salaris.html recomputes the KPI tiles client-side for whatever's
    highlighted — it needs these fields on every row, not just the ones
    Spreiding salaris itself renders."""
    rows = salary.get_employee_rows(AS_OF, NO_FILTERS)
    row = rows[0]
    for field in (
        "Benchmark_Ratio", "Benchmark_Status", "Afdeling_Naam",
        "Manager_Naam", "Functie_Naam", "Performance_Bin", "Tevredenheidsband_Naam",
    ):
        assert field in row, f"missing {field!r} on employee row"


def test_headcount_by_dimension_rejects_unknown_dimension():
    try:
        salary.get_headcount_by_dimension(AS_OF, "not_a_real_dimension", NO_FILTERS)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_headcount_by_dimension_known_dimensions_return_rows():
    for dim in salary.DIMENSION_COLUMNS:
        rows = salary.get_headcount_by_dimension(AS_OF, dim, NO_FILTERS)
        assert len(rows) > 0, f"no rows for dimension {dim!r}"


def test_headcount_by_dimension_uses_qualitative_salary_labels():
    """The old PBIP's 'Aantal medewerkers' chart colors by its own numbered
    salary-band names ("1. Laag" ...), not the currency-range names used
    elsewhere (Spreiding salaris, the Salarisgroep filter)."""
    rows = salary.get_headcount_by_dimension(AS_OF, "afdeling", NO_FILTERS)
    seen = {r["Salaris_Categorie"] for r in rows}
    assert seen <= set(salary.SALARY_CATEGORY_DISPLAY.values())


def test_benchmark_distribution_by_dimension_rejects_unknown_dimension():
    try:
        salary.get_benchmark_distribution_by_dimension(AS_OF, "not_a_real_dimension", NO_FILTERS)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_benchmark_distribution_by_dimension_uses_canonical_groups():
    rows = salary.get_benchmark_distribution_by_dimension(AS_OF, "afdeling", NO_FILTERS)
    assert len(rows) > 0
    seen = {r["Benchmark_Status"] for r in rows}
    assert seen <= set(salary.BENCHMARK_STATUS_ORDER), f"unexpected groups: {seen}"


def test_lfl_growth_trend_is_a_small_percentage():
    rows = salary.get_lfl_growth_trend(date(2024, 1, 1), AS_OF)
    assert len(rows) > 0
    for r in rows:
        if r["LFL_Growth_Pct"] is not None:
            msg = "LFL growth should be a modest fraction, not a raw salary"
            assert -0.5 < r["LFL_Growth_Pct"] < 0.5, msg


def test_lfl_growth_trend_rejects_unknown_granularity():
    try:
        salary.get_lfl_growth_trend(date(2024, 1, 1), AS_OF, granularity="week")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_lfl_growth_trend_year_granularity_is_a_real_recomputation():
    """'year' isn't a subsample of the monthly series — it's one row per
    calendar year, each a genuine 12-month retained-cohort comparison
    anchored on that year's latest available snapshot."""
    monthly = salary.get_lfl_growth_trend(date(2020, 1, 1), AS_OF, granularity="month")
    yearly = salary.get_lfl_growth_trend(date(2020, 1, 1), AS_OF, granularity="year")
    assert 0 < len(yearly) < len(monthly)
    years_seen = {r["Snapshot_Date"].year for r in yearly}
    assert len(years_seen) == len(yearly), "expected at most one row per calendar year"


def test_get_filter_options_returns_known_afdelingen():
    options = salary.get_filter_options(AS_OF, NO_FILTERS)
    assert "Productie" in options["afdeling"]
    assert set(options["salaris_categorie"]) == {
        "Onder EUR 35.000", "EUR 35.000 - 44.999", "EUR 45.000 - 59.999",
        "EUR 60.000 - 79.999", "EUR 80.000 - 99.999", "EUR 100.000 en hoger",
    }


def test_get_filter_options_cross_filters_by_other_selections():
    """Selecting Afdeling=Productie should narrow the manager list to
    managers who actually have Productie employees, not every manager."""
    all_managers = salary.get_filter_options(AS_OF, NO_FILTERS)["manager"]
    narrowed = salary.get_filter_options(AS_OF, SalaryFilters(afdeling="Productie"))["manager"]
    assert 0 < len(narrowed) < len(all_managers)


def test_get_filter_options_never_excludes_the_selected_value_itself():
    """A field's own selection must stay in its own dropdown list, even
    though it's cleared when computing that field's cross-filtered options."""
    options = salary.get_filter_options(AS_OF, SalaryFilters(afdeling="Productie"))
    assert "Productie" in options["afdeling"]


def test_salary_filters_has_no_bron_field():
    """Recruitment source was removed from this page entirely (Laura,
    reviewing as an HR manager: it answers a recruitment question, not a
    compensation one) — not just hidden in the UI."""
    assert not hasattr(SalaryFilters(), "bron")


def test_employee_rows_carry_the_new_hr_manager_review_fields():
    rows = salary.get_employee_rows(AS_OF, NO_FILTERS)
    row = rows[0]
    for field in ("Salaris_Werkelijk", "Geslacht", "Opleidingsniveau", "Dienstjaren",
                  "Compa_Ratio_Interne_Schaal"):
        assert field in row, f"missing {field!r} on employee row"


def test_compute_total_payroll_uses_actual_not_fte_equivalent_pay():
    """Salaris_Werkelijk (actual pro-rata pay), not Salaris (the FTE-
    equivalent figure everything else on the page correctly uses) — summing
    the FTE-equivalent would overstate real payroll cost."""
    rows = salary.get_employee_rows(AS_OF, NO_FILTERS)
    total = salary.compute_total_payroll(rows)
    assert total == sum(r["Salaris_Werkelijk"] for r in rows)
    assert total < sum(r["Salaris"] for r in rows), (
        "actual pay should be <= FTE-equivalent pay whenever anyone works part-time"
    )


def test_corrected_gender_pay_gap_is_plausible():
    gap = salary.get_corrected_gender_pay_gap(AS_OF, NO_FILTERS)
    assert gap.aantal_man > 0
    assert gap.aantal_vrouw > 0
    assert gap.aantal_vergelijkbare_functies > 0
    assert -0.5 < gap.ongecorrigeerd_pct < 0.5
    assert -0.5 < gap.gecorrigeerd_pct < 0.5


def test_new_hire_vs_current_known_dimensions_return_rows():
    rows = salary.get_new_hire_vs_current(AS_OF, "functie", NO_FILTERS)
    assert len(rows) > 0
    row = rows[0]
    assert row["gem_start_salaris"] > 0
    assert row["gem_huidig_salaris"] > 0
    assert row["aantal"] > 0


def test_new_hire_vs_current_rejects_unknown_dimension():
    try:
        salary.get_new_hire_vs_current(AS_OF, "not_a_real_dimension", NO_FILTERS)
        assert False, "expected ValueError"
    except ValueError:
        pass
