"""Regression test for the "empty <select> submits '' not omitted" bug:
a real HTML form always sends every field, so a filter left on "Alle" comes
in as `name=` (empty string), which FastAPI binds to "" — not None. Without
normalizing that to None, every filter round-tripped through the form turned
into a `column = ''` condition matching nothing, emptying every chart the
moment the form was submitted at all (ARCHITECTURE.md — reported by Laura).
"""

import json
from decimal import Decimal

from hr_dashboard.api.routers.pages import _json_default, _none_if_blank


def test_none_if_blank_treats_empty_string_as_no_filter():
    assert _none_if_blank("") is None


def test_none_if_blank_leaves_none_as_none():
    assert _none_if_blank(None) is None


def test_none_if_blank_keeps_a_real_value():
    assert _none_if_blank("Productie") == "Productie"


def test_json_default_serializes_decimal_as_a_number_not_a_string():
    """pyodbc returns SQL DECIMAL columns (e.g. Benchmark_Ratio) as Decimal.
    json.dumps can't serialize that natively, and falling through to
    str(value) would silently turn "0.82" into a JSON *string* — which
    quietly breaks client-side arithmetic on it (the click-to-highlight KPI
    recompute in salaris.html does exactly that on Benchmark_Ratio)."""
    encoded = json.dumps({"ratio": Decimal("0.823612607758620")}, default=_json_default)
    assert json.loads(encoded)["ratio"] == 0.823612607758620
