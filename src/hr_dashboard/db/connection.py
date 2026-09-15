"""A pooled pyodbc connection, built from Settings.

Two auth paths (see config.py): SQL-authentication for local dev, or the
Container App's Managed Identity token for production. Callers never see
the difference, or the pool — they just use `with get_connection() as conn:`,
exactly as before.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from queue import Empty, Queue
from threading import Lock

import pyodbc

from hr_dashboard.config import settings

# A fresh connection per call was the actual cause of "every filter click
# feels slow" (Laura, reported after the click-to-cross-filter experiment):
# each pyodbc.connect() is its own TCP+TLS+login round trip to Azure SQL,
# and a single /salaris page load opens seven of them (one per query
# group), none ever reused, all sequential. This pool keeps a handful of
# already-authenticated connections warm across requests so most calls
# skip that handshake entirely — the only change is behind get_connection();
# every call site stays exactly as it was.
_MAX_POOL_SIZE = 5
_pool: Queue[pyodbc.Connection] = Queue()
_open_count = 0
_open_count_lock = Lock()


def _base_conn_str() -> str:
    encrypt = "yes" if settings.sqlserver_encrypt else "no"
    trust_cert = "yes" if settings.sqlserver_trust_cert else "no"
    return (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={settings.sqlserver_host},1433;"
        f"DATABASE={settings.sqlserver_database};"
        f"Encrypt={encrypt};TrustServerCertificate={trust_cert};"
    )


def _open_new_connection() -> pyodbc.Connection:
    if settings.db_auth_mode == "sql":
        if not settings.mssql_username or not settings.mssql_pw:
            raise RuntimeError(
                "db_auth_mode='sql' requires mssql_username/mssql_pw (set in .env)"
            )
        conn_str = _base_conn_str() + (
            f"UID={settings.mssql_username};PWD={settings.mssql_pw};"
        )
        return pyodbc.connect(conn_str, timeout=10)

    if settings.db_auth_mode == "managed_identity":
        # Token-based auth via the Container App's system-assigned identity.
        # Deferred until this actually runs in Azure (ARCHITECTURE.md §10.3)
        # — azure-identity isn't a dependency yet because nothing exercises
        # this path locally. Add it (DefaultAzureCredential + the
        # SQL_COPT_SS_ACCESS_TOKEN pyodbc attribute) when this is first
        # deployed, not before.
        raise NotImplementedError(
            "managed_identity auth is designed (§10.3) but not implemented yet — "
            "add azure-identity token acquisition here when first deploying to Azure"
        )

    raise ValueError(f"Unknown db_auth_mode: {settings.db_auth_mode!r}")


def _is_alive(conn: pyodbc.Connection) -> bool:
    # A pooled connection can go stale between requests (Azure SQL idle
    # timeout, a sleeping dev machine, a network blip) — this costs a few
    # ms on an already-open session, versus the ~150-500ms of a doomed
    # query on a dead one followed by a fresh handshake anyway.
    try:
        conn.cursor().execute("SELECT 1")
        return True
    except pyodbc.Error:
        return False


def _discard(conn: pyodbc.Connection) -> None:
    global _open_count
    try:
        conn.close()
    except pyodbc.Error:
        pass
    with _open_count_lock:
        _open_count -= 1


def _checkout() -> pyodbc.Connection:
    global _open_count
    while True:
        try:
            conn = _pool.get_nowait()
        except Empty:
            with _open_count_lock:
                _open_count += 1
            return _open_new_connection()
        if _is_alive(conn):
            return conn
        _discard(conn)  # try the next pooled connection, or open a fresh one


def _checkin(conn: pyodbc.Connection) -> None:
    if _pool.qsize() < _MAX_POOL_SIZE:
        _pool.put(conn)
    else:
        _discard(conn)


@contextmanager
def get_connection() -> Iterator[pyodbc.Connection]:
    conn = _checkout()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _checkin(conn)
