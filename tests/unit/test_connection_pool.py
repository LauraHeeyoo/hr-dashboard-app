"""Regression tests for the connection pool: a fresh pyodbc.connect() per
call was the real cause of "every filter click feels slow" (Laura) — each
one is its own TCP+TLS+login round trip to Azure SQL. These confirm
get_connection() actually reuses a connection instead of opening a new one
every time, without changing anything at the call sites.
"""

from hr_dashboard.db import connection


def test_get_connection_reuses_a_connection_after_it_is_returned():
    with connection.get_connection() as conn:
        first = conn

    with connection.get_connection() as conn:
        second = conn

    assert first is second, "expected the pool to hand back the same connection"


def test_get_connection_still_supports_normal_queries():
    with connection.get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        assert cur.fetchone()[0] == 1


def test_get_connection_rolls_back_and_still_returns_to_pool_on_error():
    try:
        with connection.get_connection() as conn:
            reused_after_error = conn
            cur = conn.cursor()
            cur.execute("SELECT * FROM this_table_does_not_exist")
    except Exception:
        pass

    with connection.get_connection() as conn:
        assert conn is reused_after_error, "a query error shouldn't discard a healthy connection"
