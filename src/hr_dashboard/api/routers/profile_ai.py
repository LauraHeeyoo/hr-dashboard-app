"""JSON API for Profiel's two AI features — the per-employee Q&A tile
and the filter rail's natural-language search box. Kept separate from
pages.py's plain HTML page routes for the same reason chat.py is: these
are the other endpoints on the site that spend real LLM money per
request.
"""

from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel

from hr_dashboard.llm.employee_qa import answer_employee_question
from hr_dashboard.llm.employee_search import ask_employee_search
from hr_dashboard.semantic import profile, salary

router = APIRouter()


class EmployeeQuestion(BaseModel):
    employee_key: int
    as_of: date | None = None
    question: str


@router.post("/profiel/vraag")
def profiel_vraag(payload: EmployeeQuestion) -> dict:
    question = payload.question.strip()
    if not question:
        return {"answer": None, "error": "Stel gerust een vraag over deze medewerker."}

    peildatum = payload.as_of or salary.get_latest_snapshot_date()
    snapshot = profile.get_employee_snapshot(payload.employee_key, peildatum)
    if snapshot is None:
        return {"answer": None, "error": "Medewerker niet gevonden op deze peildatum."}

    identity = profile.get_employee_identity(payload.employee_key)
    history = profile.get_employee_history(payload.employee_key)
    score_trend = profile.get_employee_score_trend(payload.employee_key)
    signals = profile.get_employee_signals(snapshot, score_trend)
    hr_context = profile.get_employee_hr_context(payload.employee_key)
    peer_averages = profile.get_peer_group_averages(
        payload.employee_key, snapshot["Afdeling_Naam"], peildatum
    )

    try:
        answer = answer_employee_question(
            question, snapshot, identity, history, hr_context, score_trend, signals,
            peer_averages,
        )
    except Exception as exc:
        return {"answer": None, "error": f"Kon geen antwoord genereren ({exc})."}

    return {"answer": answer, "error": None}


class EmployeeSearchQuestion(BaseModel):
    as_of: date | None = None
    question: str


@router.post("/profiel/zoek")
def profiel_zoek(payload: EmployeeSearchQuestion) -> dict:
    question = payload.question.strip()
    if not question:
        return {"employee_keys": None, "error": "Stel een zoekvraag in gewone taal."}

    peildatum = payload.as_of or salary.get_latest_snapshot_date()
    filter_values = profile.get_search_filter_values(peildatum)

    try:
        search_request = ask_employee_search(question, filter_values)
    except Exception as exc:
        return {"employee_keys": None, "error": f"Kon deze zoekvraag niet verwerken ({exc})."}

    if search_request.is_empty():
        return {
            "employee_keys": None,
            "error": "Ik kon geen zoekcriteria herkennen in deze vraag.",
        }

    employee_keys = profile.get_employees_matching_search(search_request, peildatum)
    return {"employee_keys": employee_keys, "error": None}
