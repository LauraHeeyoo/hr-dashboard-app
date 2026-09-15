"""Regression test for the "empty <select> submits '' not omitted" bug:
a real HTML form always sends every field, so a filter left on "Alle" comes
in as `name=` (empty string), which FastAPI binds to "" — not None. Without
normalizing that to None, every filter round-tripped through the form turned
into a `column = ''` condition matching nothing, emptying every chart the
moment the form was submitted at all (ARCHITECTURE.md — reported by Laura).
"""

from hr_dashboard.api.routers.pages import _none_if_blank


def test_none_if_blank_treats_empty_string_as_no_filter():
    assert _none_if_blank("") is None


def test_none_if_blank_leaves_none_as_none():
    assert _none_if_blank(None) is None


def test_none_if_blank_keeps_a_real_value():
    assert _none_if_blank("Productie") == "Productie"
