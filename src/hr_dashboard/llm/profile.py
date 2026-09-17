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
    "'zorgwekkend'), in het Nederlands, in maximaal 7 zinnen doorlopende tekst (geen "
    "opsomming). Noem concreet, elk als het gegeven is: functie en tijd in dienst, hoe het "
    "salaris zich verhoudt tot de benchmark en de eigen salarisschaal, de meest recente "
    "performance/tevredenheidsindicatie en de belangrijkste factor(en) daarachter, hoe de "
    "medewerker is aangenomen (bron en kandidaatkwaliteit). Is de medewerker uit dienst, "
    "noem dan ook de reden van vertrek en hun tevredenheid/betrokkenheid/performance op het "
    "moment van vertrek."
)


def _format_facts(
    snapshot: dict, identity: dict, history: list[dict], hr_context: dict
) -> str:
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

    # Drivers apply the same way whether the employee is still active or
    # not — get_employee_hr_context always reads the LATEST available
    # snapshot's own driver keys, which for a departed employee is
    # naturally their last one before leaving. No separate "departed"
    # branch needed for these three.
    if hr_context.get("Performance_Driver"):
        lines.append(f"Belangrijkste performance-factor: {hr_context['Performance_Driver']}")
    if hr_context.get("Engagement_Driver"):
        lines.append(f"Belangrijkste betrokkenheid-factor: {hr_context['Engagement_Driver']}")
    if hr_context.get("Satisfaction_Driver"):
        lines.append(f"Belangrijkste tevredenheid-factor: {hr_context['Satisfaction_Driver']}")

    if hr_context.get("Bron_Naam"):
        lines.append(f"Aangenomen via: {hr_context['Bron_Naam']}")
    if hr_context.get("Kandidaat_Kwaliteit") is not None:
        lines.append(f"Kandidaatkwaliteit bij aanname: {hr_context['Kandidaat_Kwaliteit']:.1f}")

    # The "Uit dienst" row (if any) carries the departure reason and the
    # satisfaction/engagement scores captured AT the moment of leaving —
    # a more precise "as of departure" figure than the last periodic
    # snapshot, which could be a month or more stale by comparison.
    departure_row = next((e for e in history if e["Gebeurtenis"] == "Uit dienst"), None)
    if departure_row:
        if departure_row.get("Vertrekreden"):
            lines.append(f"Reden van vertrek: {departure_row['Vertrekreden']}")
        if departure_row.get("Tevredenheid_Score_Bij_Uitdienst") is not None:
            lines.append(
                "Tevredenheid bij uitdienst: "
                f"{departure_row['Tevredenheid_Score_Bij_Uitdienst']:.1f}"
            )
        if departure_row.get("Betrokkenheid_Score_Bij_Uitdienst") is not None:
            lines.append(
                "Betrokkenheid bij uitdienst: "
                f"{departure_row['Betrokkenheid_Score_Bij_Uitdienst']:.1f}"
            )

    if history:
        events = "; ".join(
            f"{e['Gebeurtenis_Datum']}: {e['Gebeurtenis']} ({e['Functie_Naam']})"
            for e in history
        )
        lines.append(f"Loopbaangeschiedenis: {events}")
    return "\n".join(lines)


def generate_employee_summary(
    snapshot: dict, identity: dict, history: list[dict], hr_context: dict
) -> str:
    client = get_client()
    result = client.responses.create(
        model=settings.azure_openai_deployment,
        instructions=_INSTRUCTIONS,
        input=_format_facts(snapshot, identity, history, hr_context),
    )
    return result.output_text
