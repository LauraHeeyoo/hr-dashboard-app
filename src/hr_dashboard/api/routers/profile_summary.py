"""JSON API for Profiel's "AI-samenvatting" button — kept separate from
pages.py's plain HTML page routes for the same reason as chat.py: this is
the other endpoint on the site that spends real LLM money per request.
"""

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from hr_dashboard.llm.profile import generate_employee_summary
from hr_dashboard.semantic import profile, salary

router = APIRouter()


@router.get("/profiel/samenvatting")
def profiel_samenvatting(
    employee_key: int,
    as_of: date | None = Query(default=None),
) -> dict:
    peildatum = as_of or salary.get_latest_snapshot_date()
    snapshot = profile.get_employee_snapshot(employee_key, peildatum)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Medewerker niet gevonden op deze peildatum.")
    identity = profile.get_employee_identity(employee_key)
    history = profile.get_employee_history(employee_key)
    hr_context = profile.get_employee_hr_context(employee_key)

    try:
        summary = generate_employee_summary(snapshot, identity, history, hr_context)
    except Exception as exc:
        return {"summary": None, "error": f"Kon geen samenvatting genereren ({exc})."}

    return {"summary": summary, "error": None}
