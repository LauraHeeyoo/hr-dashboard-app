"""Employee-summary generation for Profiel's "AI-samenvatting" button.

Not a planner/VizRequest question (client.py/catalog.py) — there's no
free-text question to interpret here, just one employee's own already-
fetched, already-correct data (semantic/profile.py's snapshot + identity +
history + score trend + hr context), which this asks the model to phrase
into a short, topic-grouped bullet list. Reuses client.py's AzureOpenAI
client rather than constructing a second one; still no second LLM call to
double-check a number the way client.py's own docstring warns against —
every fact given to the model below is already resolved from the database,
the model only phrases it. Uses structured output (like client.py's
ask_planner) rather than asking the model to format its own bullet
markers in free text, so the frontend can render a real <ul> without
parsing model-authored formatting.
"""

from pydantic import BaseModel

from hr_dashboard.config import settings
from hr_dashboard.llm.client import get_client

_INSTRUCTIONS = (
    "Je bent een HR-adviseur die een kort, feitelijk profiel schrijft voor de manager van "
    "deze medewerker, als een lijst losse bullets (elk een of twee zinnen, geen "
    "opsomming van losse woorden). Gebruik uitsluitend de gegevens hieronder — verzin "
    "niets en voeg geen eigen aannames toe. Schrijf neutraal en feitelijk (geen "
    "waardeoordelen als 'goed' of 'zorgwekkend'), in het Nederlands. Varieer de "
    "zinsopbouw tussen bullets over vergelijkbare onderwerpen (bijvoorbeeld tevredenheid "
    "en betrokkenheid) — gebruik niet voor allebei exact dezelfde sjabloonzin.\n\n"
    "Groepeer per onderwerp, in deze volgorde, en laat een bullet helemaal weg als de "
    "bijbehorende gegevens hieronder ontbreken:\n"
    "1. Naam, functie, afdeling, periode in dienst, contracttype en uren per week. Is de "
    "medewerker uit dienst, gebruik dan 'was in dienst van [datum] tot [datum]'; is de "
    "medewerker nog in dienst, gebruik dan 'is sinds [datum] in dienst' of 'werkt sinds "
    "[datum] bij ons' — nooit een combinatie van beide zoals 'werkt sinds [datum] in "
    "dienst'.\n"
    "2. Salarisinformatie: hoe het salaris zich verhoudt tot de externe benchmark en tot "
    "de eigen salarisschaal (compa-ratio).\n"
    "3. Performance: de band, de score, en de belangrijkste factor daarachter.\n"
    "4. Tevredenheid: de band, de score, en de belangrijkste factor daarachter.\n"
    "5. Betrokkenheid: de score en de belangrijkste factor daarachter (er is geen band "
    "beschikbaar voor betrokkenheid, noem dus alleen de score).\n"
    "6. Aanname: via welke bron de medewerker is aangenomen, en de kandidaatkwaliteit bij "
    "aanname.\n"
    "7. Alleen als de medewerker uit dienst is: de reden van vertrek, en hun tevredenheid/"
    "betrokkenheid op het moment van vertrek als die beschikbaar zijn."
)


class EmployeeSummary(BaseModel):
    bullets: list[str]


def _format_facts(
    snapshot: dict,
    identity: dict,
    history: list[dict],
    hr_context: dict,
    score_trend: list[dict],
) -> str:
    lines = [
        f"Naam: {snapshot['Medewerker_Naam']}",
        f"Functie: {snapshot['Functie_Naam']} ({snapshot['Afdeling_Naam']})",
        f"In dienst sinds: {identity['Aaneengesloten_Indienst_Datum']}",
        f"Contracttype: {snapshot['Contracttype']}, {snapshot['Contracturen']} uur/week",
    ]

    # The "Uit dienst" row (if any) carries the departure date/reason and the
    # satisfaction/engagement scores captured AT the moment of leaving — a
    # more precise "as of departure" figure than the last periodic snapshot,
    # which could be a month or more stale by comparison.
    departure_row = next((e for e in history if e["Gebeurtenis"] == "Uit dienst"), None)
    if departure_row:
        lines.append(f"Uit dienst per: {departure_row['Gebeurtenis_Datum']}")

    if snapshot.get("Benchmark_Ratio") is not None:
        lines.append(f"Salaris t.o.v. externe benchmark: {snapshot['Benchmark_Ratio']:.0%}")
    if snapshot.get("Compa_Ratio_Interne_Schaal") is not None:
        lines.append(
            f"Positie in eigen salarisschaal (compa-ratio): "
            f"{snapshot['Compa_Ratio_Interne_Schaal']:.0%}"
        )

    # Prestatie_Score/Tevredenheid_Score/Betrokkenheid_Score (score_trend)
    # are already doubled onto the same 0-10 scale as the bins by
    # get_employee_score_trend — see that function's docstring for why this
    # app-side scaling is a deliberate, permanent choice rather than a
    # stopgap.
    latest_scores = score_trend[-1] if score_trend else {}
    if snapshot.get("Performance_Bin"):
        lines.append(f"Performance-band: {snapshot['Performance_Bin']}")
    if latest_scores.get("Prestatie_Score") is not None:
        lines.append(f"Performance-score: {latest_scores['Prestatie_Score']:.1f}")
    if hr_context.get("Performance_Driver"):
        lines.append(f"Belangrijkste performance-factor: {hr_context['Performance_Driver']}")

    if snapshot.get("Tevredenheidsband_Naam"):
        lines.append(f"Tevredenheidsband: {snapshot['Tevredenheidsband_Naam']}")
    if latest_scores.get("Tevredenheid_Score") is not None:
        lines.append(f"Tevredenheid-score: {latest_scores['Tevredenheid_Score']:.1f}")
    if hr_context.get("Satisfaction_Driver"):
        lines.append(f"Belangrijkste tevredenheid-factor: {hr_context['Satisfaction_Driver']}")

    if latest_scores.get("Betrokkenheid_Score") is not None:
        lines.append(f"Betrokkenheid-score: {latest_scores['Betrokkenheid_Score']:.1f}")
    if hr_context.get("Engagement_Driver"):
        lines.append(f"Belangrijkste betrokkenheid-factor: {hr_context['Engagement_Driver']}")

    if hr_context.get("Bron_Naam"):
        lines.append(f"Aangenomen via: {hr_context['Bron_Naam']}")
    if hr_context.get("Kandidaat_Kwaliteit") is not None:
        lines.append(f"Kandidaatkwaliteit bij aanname: {hr_context['Kandidaat_Kwaliteit']:.1f}")

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

    return "\n".join(lines)


def generate_employee_summary(
    snapshot: dict,
    identity: dict,
    history: list[dict],
    hr_context: dict,
    score_trend: list[dict],
) -> list[str]:
    client = get_client()
    result = client.responses.parse(
        model=settings.azure_openai_deployment,
        instructions=_INSTRUCTIONS,
        input=_format_facts(snapshot, identity, history, hr_context, score_trend),
        text_format=EmployeeSummary,
    )
    return result.output_parsed.bullets
