"""A pyodbc connection, built from Settings.

Two auth paths (see config.py): SQL-authentication for local dev, or the
Container App's Managed Identity token for production. Callers never see
the difference — they just call get_connection().
"""

import pyodbc

from hr_dashboard.config import settings


def _base_conn_str() -> str:
    encrypt = "yes" if settings.sqlserver_encrypt else "no"
    trust_cert = "yes" if settings.sqlserver_trust_cert else "no"
    return (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={settings.sqlserver_host},1433;"
        f"DATABASE={settings.sqlserver_database};"
        f"Encrypt={encrypt};TrustServerCertificate={trust_cert};"
    )


def get_connection() -> pyodbc.Connection:
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
