"""Natural-language employee search for Profiel's filter rail (v1 —
Laura's own framing: cover what's already been discussed plus a few
more, then build the fuller catalog in a later session together with
expanding the Salaris chat).

Same boundary as catalog.py's VizRequest: the model only ever fills in
an EmployeeSearchRequest, a fixed set of fields backed by real data —
it never writes SQL and never invents a department/role/education
value. get_employees_matching_search (semantic/profile.py) resolves
the parsed request into actual Employee_Keys.

Deliberately NOT covered yet (Laura's call, deferred to the fuller-list
session): free-text criteria beyond afdeling/functie/opleidingsniveau,
and anything needing a measure this app doesn't already compute
somewhere.
"""

from pydantic import BaseModel

from hr_dashboard.config import settings
from hr_dashboard.llm.client import get_client


class EmployeeSearchRequest(BaseModel):
    """What the search planner LLM must fill in. Boolean fields default
    to False ("the question didn't ask about this"), not None — there's
    no meaningful third state for e.g. "salary below benchmark" the way
    VizRequest's optional peildatum genuinely has an "unspecified" case.

    afdeling/functie/opleidingsniveau stay plain strings, same reasoning
    as VizRequest's own filter fields: the real known values are live
    data (given to the model in its own instructions), not hardcoded
    here — an incorrect value just yields zero matches downstream."""

    afdeling: str | None = None
    functie: str | None = None
    opleidingsniveau: str | None = None
    jarig_binnen_30_dagen: bool = False
    jubileum_binnen_30_dagen: bool = False
    salaris_onder_benchmark: bool = False
    lage_compa_ratio: bool = False
    performance_gedaald: bool = False
    tevredenheid_gedaald: bool = False
    betrokkenheid_gedaald: bool = False
    verzuim_dagen_min: float | None = None

    def is_empty(self) -> bool:
        return self == EmployeeSearchRequest()


def _build_instructions(filter_values: dict[str, list[str]]) -> str:
    afdelingen = ", ".join(filter_values["afdeling"])
    functies = ", ".join(filter_values["functie"])
    opleidingsniveaus = ", ".join(filter_values["opleidingsniveau"])
    return (
        "Je vertaalt een vraag in gewone taal naar een zoekopdracht die de medewerker-"
        "lijst op de Profiel-pagina versmalt. Vul alleen in wat de vraag daadwerkelijk "
        "vraagt — laat een veld leeg (of op False) als de vraag er niets over zegt. "
        "Verzin geen criteria die niet worden genoemd.\n\n"
        f"Bekende afdelingen — gebruik exact deze spelling: {afdelingen}\n"
        f"Bekende functies — gebruik exact deze spelling: {functies}\n"
        f"Bekende opleidingsniveaus — gebruik exact deze spelling: {opleidingsniveaus}\n\n"
        "jarig_binnen_30_dagen: de medewerker is binnen 30 dagen jarig.\n"
        "jubileum_binnen_30_dagen: de medewerker heeft binnen 30 dagen een werkjubileum "
        "(een heel aantal jaren onafgebroken in dienst).\n"
        "salaris_onder_benchmark: het salaris zit onder de externe marktbenchmark.\n"
        "lage_compa_ratio: de medewerker staat laag in de eigen salarisschaal.\n"
        "performance_gedaald / tevredenheid_gedaald / betrokkenheid_gedaald: die score is "
        "het afgelopen jaar gedaald ten opzichte van ongeveer een jaar geleden.\n"
        "verzuim_dagen_min: alleen invullen als de vraag een concreet minimumaantal "
        "verzuimdagen over het afgelopen jaar noemt (bijv. 'meer dan 5 verzuimdagen' "
        "wordt 5) — anders leeg laten.\n\n"
        "Meerdere criteria mogen gecombineerd worden; ze gelden dan allemaal tegelijk (EN, "
        "geen OF)."
    )


def ask_employee_search(
    question: str, filter_values: dict[str, list[str]]
) -> EmployeeSearchRequest:
    client = get_client()
    result = client.responses.parse(
        model=settings.azure_openai_deployment,
        instructions=_build_instructions(filter_values),
        input=question,
        text_format=EmployeeSearchRequest,
    )
    return result.output_parsed
