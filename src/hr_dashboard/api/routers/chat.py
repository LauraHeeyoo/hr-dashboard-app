"""JSON API for the "praten met de data" chat tile (ARCHITECTURE.md §8).
The one endpoint on the site that spends real LLM money per request, so
it's kept separate from pages.py's plain HTML page routes rather than
folded in there.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from hr_dashboard.llm import client, compiler
from hr_dashboard.semantic import salary
from hr_dashboard.semantic.salary import SalaryFilters

router = APIRouter()


class ChatQuestion(BaseModel):
    question: str


@router.post("/salaris/chat")
def salaris_chat(payload: ChatQuestion) -> dict:
    question = payload.question.strip()
    if not question:
        return {
            "answer": "Stel gerust een vraag over de salarisdata.",
            "chart_spec": None,
            "value": None,
            "value_label": None,
        }

    # Always the whole dataset's own latest peildatum/no rail filters as
    # the *default* — the chat tile answers about "now" unless the
    # question names something else, which becomes a VizRequest field
    # instead (a specific afdeling/functie/etc. as a filter, or a specific
    # date as peildatum — see client.py's instructions), never a
    # dependency on whatever the filter rail happens to be set to.
    #
    # Deliberately NOT switched to get_default_peildatum() the way the
    # page-level Peildatum fields were — this latest_date does double
    # duty here as both "the end of the real data range" (ask_planner's
    # own range-validity instructions) and "today" for relative language
    # ("dit jaar", "nu"). get_default_peildatum() now resolves to the end
    # of the *previous* calendar month (Laura's call, on top of the
    # data-generator finding that fact_workforce_snapshot's current-month
    # row is real data mislabeled with a future month-end date) — an
    # even earlier date than plain "today" was, so swapping it in here
    # would shrink the range the model believes is answerable even
    # further, without also touching ask_planner's own instructions
    # text. Risks the chat rejecting or misreading questions about dates
    # that are genuinely still in the simulated data. Flagged for Laura
    # rather than changed blind.
    latest_date = salary.get_latest_snapshot_date()
    earliest_date = salary.get_earliest_snapshot_date()
    filter_options = salary.get_filter_options(latest_date, SalaryFilters())

    try:
        viz_request = client.ask_planner(question, filter_options, earliest_date, latest_date)
        result = compiler.resolve_viz_request(viz_request, latest_date)
    except Exception as exc:
        return {
            "answer": f"Daar kon ik geen antwoord op vinden binnen de beschikbare data ({exc}).",
            "chart_spec": None,
            "value": None,
            "value_label": None,
        }

    return {
        "answer": result.answer,
        "chart_spec": result.chart_spec,
        "value": result.value,
        "value_label": result.value_label,
    }
