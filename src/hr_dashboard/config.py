"""Application configuration, read from the environment / .env.

Two DB auth modes (ARCHITECTURE.md §10.3):
  - "sql": SQL-authentication login (local dev — reuses the existing
    SQLSERVER_*/MSSQL_* variables already in .env).
  - "managed_identity": the Container App's system-assigned identity,
    token-based (production — no password anywhere). Not wired up yet;
    the connection layer already branches on this so switching later is a
    config change, not a rewrite.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    db_auth_mode: str = "sql"  # "sql" | "managed_identity"

    sqlserver_host: str
    sqlserver_database: str
    sqlserver_encrypt: bool = True
    sqlserver_trust_cert: bool = False

    # Only required when db_auth_mode == "sql"
    mssql_username: str | None = None
    mssql_pw: str | None = None

    # Azure OpenAI (the chat-with-your-data tile, ARCHITECTURE.md §8). Key-
    # based auth for local dev — same reasoning as db_auth_mode's "sql"
    # default: Managed Identity is the production story (§10.3), deferred
    # until this actually runs in the Container App.
    azure_openai_api_key: str | None = None
    azure_openai_endpoint: str | None = None
    azure_openai_deployment: str = "gpt-5.4-mini"
    azure_openai_api_version: str = "2025-04-01-preview"


settings = Settings()
