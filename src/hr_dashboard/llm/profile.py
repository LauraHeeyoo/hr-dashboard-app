"""Employee-summary generation for Profiel's "AI-samenvatting" button.

Not a planner/VizRequest question (client.py/catalog.py) — there's no
free-text question to interpret here, just one employee's own already-
fetched, already-correct data (semantic/profile.py's snapshot + identity +
history), which this asks the model to phrase into a short, neutral
paragraph. Reuses client.py's AzureOpenAI client rather than constructing
a second one; still no second LLM call to double-check a number the way
client.py's own docstring warns against — every fact given to the model
below is already resolved from the database, the model only phrases it.
"""

from hr_dashboard.config import settings
from hr_dashboard.llm.client import get_client

_INSTRUCTIONS = (
    "Je bent een HR-adviseur die een kort profiel schrijft voor de manager van deze "
    "medewerker. Gebruik uitsluitend de gegevens hieronder — verzin niets en voeg geen "
    "eigen aannames toe. Schrijf neutraal en feitelijk (geen waardeoordelen als 'goed' of "
    "'zorgwekkend'), in het Nederlands, in maximaal 4 zinnen doorlopende tekst (geen "
    "opsomming). Noem concreet: functie en tijd in dienst, hoe het salaris zich verhoudt "
    "tot de benchmark en de eigen salarisschaal, en de meest recente performance/"
    "tevredenheidsindicatie als die gegeven is."
)


def _format_facts(snapshot: dict, identity: dict, history: list[dict]) -> str:
    lines = [
        f"Naam: {snapshot['Medewerker_Naam']}",
        f"Functie: {snapshot['Functie_Naam']} ({snapshot['Afdeling_Naam']})",
        f"Manager: {snapshot['Manager_Naam']}",
        f"In dienst sinds: {identity['Aaneengesloten_Indienst_Datum']}",
        f"Contracttype: {snapshot['Contracttype']}, {snapshot['Contracturen']} uur/week",
    ]
    if snapshot.get("Benchmark_Ratio") is not None:
        lines.append(f"Salaris t.o.v. externe benchmark: {snapshot['Benchmark_Ratio']:.0%}")
    if snapshot.get("Compa_Ratio_Interne_Schaal") is not None:
        lines.append(
            f"Positie in eigen salarisschaal (compa-ratio): "
            f"{snapshot['Compa_Ratio_Interne_Schaal']:.0%}"
        )
    if snapshot.get("Performance_Bin"):
        lines.append(f"Meest recente performance-band: {snapshot['Performance_Bin']}")
    if snapshot.get("Tevredenheidsband_Naam"):
        lines.append(f"Meest recente tevredenheidsband: {snapshot['Tevredenheidsband_Naam']}")
    if history:
        events = "; ".join(
            f"{e['Startdatum']}: {e['Gebeurtenis']} ({e['Functie_Naam']})" for e in history
        )
        lines.append(f"Loopbaangeschiedenis: {events}")
    return "\n".join(lines)


def generate_employee_summary(snapshot: dict, identity: dict, history: list[dict]) -> str:
    client = get_client()
    result = client.responses.create(
        model=settings.azure_openai_deployment,
        instructions=_INSTRUCTIONS,
        input=_format_facts(snapshot, identity, history),
    )
    return result.output_text
