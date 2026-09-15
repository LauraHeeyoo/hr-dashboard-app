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


def test_salary_distribution_uses_canonical_categories():
    rows = salary.get_salary_distribution(AS_OF, NO_FILTERS)
    assert len(rows) > 0
    valid_categories = {
        "Onder EUR 35.000", "EUR 35.000 - 44.999", "EUR 45.000 - 59.999",
        "EUR 60.000 - 79.999", "EUR 80.000 - 99.999", "EUR 100.000 en hoger",
    }
    seen = {r["Salaris_Categorie"] for r in rows if r["Salaris_Categorie"] is not None}
    assert seen <= valid_categories, f"unexpected categories: {seen - valid_categories}"


def test_salary_by_dimension_rejects_unknown_dimension():
    try:
        salary.get_salary_by_dimension(AS_OF, "not_a_real_dimension", NO_FILTERS)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_salary_by_dimension_known_dimensions_return_rows():
    for dim in salary.DIMENSION_COLUMNS:
        rows = salary.get_salary_by_dimension(AS_OF, dim, NO_FILTERS)
        assert len(rows) > 0, f"no rows for dimension {dim!r}"


def test_lfl_growth_trend_is_a_small_percentage():
    rows = salary.get_lfl_growth_trend(date(2024, 1, 1), AS_OF)
    assert len(rows) > 0
    for r in rows:
        if r["LFL_Growth_Pct"] is not None:
            msg = "LFL growth should be a modest fraction, not a raw salary"
            assert -0.5 < r["LFL_Growth_Pct"] < 0.5, msg


def test_get_filter_options_returns_known_afdelingen():
    options = salary.get_filter_options()
    assert "Productie" in options["afdeling"]
    assert set(options["salaris_categorie"]) == {
        "Onder EUR 35.000", "EUR 35.000 - 44.999", "EUR 45.000 - 59.999",
        "EUR 60.000 - 79.999", "EUR 80.000 - 99.999", "EUR 100.000 en hoger",
    }
