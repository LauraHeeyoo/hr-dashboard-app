"""Cross-domain concepts shared by every page's semantic layer — currently
just the simulation engine's own run metadata, not really a "Salaris"
question, so it doesn't belong in salary.py.
"""

from datetime import datetime

from hr_dashboard.db.connection import get_connection


def get_last_refresh() -> datetime:
    """When the simulation engine last (re)generated this database's data —
    shown in the footer instead of a hardcoded build date, so it's always
    obvious how fresh the demo's underlying data actually is."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT last_run FROM dbo.simulation_state")
        return cur.fetchone()[0]
