"""Azure OpenAI wrapper for the chat tile's planner call (ARCHITECTURE.md
§6/§8). One structured-output call per question: the model's only job is
to map a free-text Dutch question onto a VizRequest — it never sees the
underlying data and never writes SQL, so a hallucinated or adversarial
question can, at worst, produce an invalid/nonsensical VizRequest, which
get_viz_request (compiler.py) rejects before any query runs.

There's deliberately no second LLM call to phrase the final answer: once
the (validated) request has been resolved against the real database, the
actual figure is known exactly, and templating a plain Dutch sentence
around a known number in Python is both cheaper and more trustworthy than
asking a model to restate a number it could still get wrong.
"""

from datetime import date

from openai import AzureOpenAI

from hr_dashboard.config import settings
from hr_dashboard.llm.catalog import MEASURE_CATALOG, VizRequest
from hr_dashboard.semantic import salary

_client: AzureOpenAI | None = None


def get_client() -> AzureOpenAI:
    """The only LLM-calling feature left in this app, as of Profiel's
    employee summary moving to a deterministic template
    (semantic/profile.py's build_employee_summary) — kept as a shared,
    lazily-constructed client rather than inlined into ask_planner in
    case a future feature needs it again."""
    global _client
    if _client is None:
        if not settings.azure_openai_api_key or not settings.azure_openai_endpoint:
            raise RuntimeError(
                "Azure OpenAI is niet geconfigureerd — zet AZURE_OPENAI_API_KEY en "
                "AZURE_OPENAI_ENDPOINT in .env."
            )
        _client = AzureOpenAI(
            api_key=settings.azure_openai_api_key,
            azure_endpoint=settings.azure_openai_endpoint,
            api_version=settings.azure_openai_api_version,
        )
    return _client


def _build_instructions(
    filter_options: dict[str, list[str]], earliest_date: date, latest_date: date
) -> str:
    # filter_options/earliest_date/latest_date all come from live queries
    # (salary.get_filter_options/get_earliest_snapshot_date/
    # get_latest_snapshot_date) — not hardcoded, so none of this drifts
    # from whatever the simulation currently contains (the same reasoning
    # that rules out hardcoding a simulation date range elsewhere in this
    # project).
    measures = "\n".join(
        f"- {key}: {spec.label} (kind={spec.kind})" for key, spec in MEASURE_CATALOG.items()
    )
    dimensions = "\n".join(f"- {key}: {label}" for key, label in salary.DIMENSION_LABELS.items())
    filters = "\n".join(
        f"- {field}: {', '.join(values)}" for field, values in filter_options.items()
    )
    return (
        "Je bent de planner voor een HR-salarisdashboard. Vertaal de vraag van de "
        "gebruiker naar een VizRequest — verzin geen velden, kies uitsluitend uit de "
        "onderstaande sleutels.\n\n"
        "Measures (kind='kpi' geeft één cijfer en negeert dimension; kind='breakdown' "
        "vereist een dimension; kind='trend' negeert dimension én alle filters):\n"
        f"{measures}\n\n"
        f"Dimensions (alleen zinvol bij een 'breakdown'-measure):\n{dimensions}\n\n"
        "Bekende waarden per filterveld — gebruik een filterveld alleen als de vraag "
        f"een specifieke groep noemt, en gebruik dan exact deze spelling:\n{filters}\n\n"
        "Noemt de vraag geen specifieke afdeling/functie/manager/opleidingsniveau/"
        "salarisgroep, laat dat filterveld dan leeg (null).\n\n"
        f"Beschikbare data loopt van {earliest_date} tot en met {latest_date} (dat laatste "
        "is ook 'vandaag' voor deze vraag). Noemt de vraag een specifieke datum of periode "
        "daarbinnen ('op 1 januari 2022', 'vorig jaar'), vul dan peildatum in (YYYY-MM-DD) — "
        "voor de 'trend'-measure verandert dat het antwoord van de hele grafiek naar het ene "
        "cijfer op dat punt. Zonder zo'n vraag laat je peildatum leeg.\n\n"
        "De 'trend'-measure (salarisgroei_trend) bestaat uit twee losse reeksen — vul, als "
        "peildatum ook is ingevuld, trend_series in om aan te geven welke van de twee "
        "bedoeld wordt:\n"
        "- alle_behouden_medewerkers: iedereen die het hele jaar in dienst is gebleven, "
        "ongeacht of hun functie of contract in die periode veranderde. Dit is de standaard "
        "als de vraag geen van beide expliciet noemt.\n"
        "- zelfde_functie_en_contract: dezelfde groep, maar dan alleen wie het hele jaar "
        "óók in exact dezelfde functie én hetzelfde contracttype bleef — dus niet 'dezelfde "
        "afdeling', dat bestaat hier niet als apart onderscheid.\n\n"
        "Vraagt de gebruiker expliciet om een bepaald grafiektype (bijv. 'als staafdiagram'), "
        "vul dan chart_type in; anders laat je die ook leeg."
    )


def ask_planner(
    question: str, filter_options: dict[str, list[str]], earliest_date: date, latest_date: date
) -> VizRequest:
    client = get_client()
    result = client.responses.parse(
        model=settings.azure_openai_deployment,
        instructions=_build_instructions(filter_options, earliest_date, latest_date),
        input=question,
        text_format=VizRequest,
    )
    return result.output_parsed
