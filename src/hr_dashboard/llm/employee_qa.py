"""Free-text Q&A about a single employee, for Profiel's own small "Vraag
over deze medewerker" tile.

Unlike the Salaris chat's planner (client.py) — which maps a question
onto a VizRequest because answering it means aggregating over a
population too large to hand to the model directly — a single
employee's own facts are small enough to just dump into the prompt
wholesale, the same way the old (now-removed) LLM-generated summary
did. That removes the need for a pre-defined question catalog entirely:
the model can answer anything covered by the facts below, not just a
fixed set of anticipated questions. The trade-off that pattern accepts
(never let the model touch a population directly) doesn't apply here
either, since there IS no population — just one employee's own
already-resolved data.

Still no second LLM call to double-check a number, same reasoning
client.py's own docstring gives: every fact handed to the model below
is already resolved from the database, the model only answers from it.
"""

from hr_dashboard.config import settings
from hr_dashboard.llm.client import get_client

_INSTRUCTIONS = (
    "Je bent een HR-assistent die een vraag beantwoordt over ÉÉN medewerker, op basis "
    "van de feiten hieronder. Gebruik uitsluitend deze feiten — verzin niets, gok niet, "
    "en gebruik geen kennis van buiten deze feiten. Staat het antwoord er niet in, zeg dat "
    "dan expliciet (bijvoorbeeld: 'Dat staat niet in de beschikbare gegevens.') in plaats "
    "van een gok te geven. Antwoord kort (1-3 zinnen), feitelijk en in het Nederlands."
)


def _format_facts(
    snapshot: dict,
    identity: dict,
    history: list[dict],
    hr_context: dict,
    score_trend: list[dict],
    signals: list[str],
    peer_averages: dict | None,
) -> str:
    lines = [
        f"Naam: {snapshot['Medewerker_Naam']}",
        f"Functie: {snapshot['Functie_Naam']} ({snapshot['Afdeling_Naam']})",
        f"Manager: {snapshot.get('Manager_Naam') or '—'}",
        f"Contract: {snapshot['Contracttype']}, {snapshot['Contracturen']} uur/week",
        f"In dienst sinds: {identity['Aaneengesloten_Indienst_Datum']}",
    ]
    if identity.get("Datum_uitdienst"):
        lines.append(f"Uit dienst per: {identity['Datum_uitdienst']}")
    if identity.get("Geboortedatum"):
        lines.append(f"Geboortedatum: {identity['Geboortedatum']}")
    if identity.get("Vestiging_Naam"):
        lines.append(f"Locatie: {identity['Vestiging_Naam']}")
    if identity.get("Bijzondere_Aanstelling"):
        lines.append(f"Bijzondere aanstelling: {identity['Bijzondere_Aanstelling']}")
    if snapshot.get("Opleidingsniveau"):
        lines.append(f"Opleidingsniveau: {snapshot['Opleidingsniveau']}")

    if snapshot.get("Salaris") is not None:
        lines.append(f"Salaris: €{snapshot['Salaris']:,.0f}")
    if snapshot.get("Benchmark_Ratio") is not None:
        lines.append(f"Salaris t.o.v. externe benchmark: {snapshot['Benchmark_Ratio']:.0%}")
    if snapshot.get("Compa_Ratio_Interne_Schaal") is not None:
        lines.append(f"Compa-ratio (eigen schaal): {snapshot['Compa_Ratio_Interne_Schaal']:.0%}")
    if snapshot.get("Performance_Bin"):
        lines.append(f"Performance-band: {snapshot['Performance_Bin']}")
    if snapshot.get("Tevredenheidsband_Naam"):
        lines.append(f"Tevredenheidsband: {snapshot['Tevredenheidsband_Naam']}")

    if score_trend:
        latest = score_trend[-1]
        lines.append(f"Laatste meetmoment: {latest['Snapshot_Date']}")
        if latest.get("Prestatie_Score") is not None:
            lines.append(f"Laatste performance-score: {latest['Prestatie_Score']:.1f}")
        if latest.get("Tevredenheid_Score") is not None:
            lines.append(f"Laatste tevredenheidsscore: {latest['Tevredenheid_Score']:.1f}")
        if latest.get("Betrokkenheid_Score") is not None:
            lines.append(f"Laatste betrokkenheidsscore: {latest['Betrokkenheid_Score']:.1f}")
        if latest.get("Verzuim_Werkdagen") is not None:
            lines.append(f"Laatste verzuim (werkdagen): {latest['Verzuim_Werkdagen']}")

    if hr_context.get("Performance_Driver"):
        lines.append(f"Belangrijkste performance-factor: {hr_context['Performance_Driver']}")
    if hr_context.get("Satisfaction_Driver"):
        lines.append(f"Belangrijkste tevredenheid-factor: {hr_context['Satisfaction_Driver']}")
    if hr_context.get("Engagement_Driver"):
        lines.append(f"Belangrijkste betrokkenheid-factor: {hr_context['Engagement_Driver']}")
    if hr_context.get("Bron_Naam"):
        lines.append(f"Aangenomen via: {hr_context['Bron_Naam']}")
    if hr_context.get("Kandidaat_Kwaliteit") is not None:
        lines.append(f"Kandidaatkwaliteit bij aanname: {hr_context['Kandidaat_Kwaliteit']:.1f}")

    if history:
        events = "; ".join(
            f"{e['Gebeurtenis_Datum']}: {e['Gebeurtenis']} ({e['Functie_Naam']})"
            for e in history
        )
        lines.append(f"Loopbaangeschiedenis: {events}")

    if signals:
        lines.append("Aandachtspunten: " + " ".join(signals))

    if peer_averages and peer_averages.get("Peer_Count"):
        lines.append(
            "Afdelingsgemiddelden ter vergelijking: "
            f"salaris €{peer_averages.get('Salaris', 0):,.0f}, "
            f"performance {peer_averages.get('Prestatie_Score', 0):.1f}, "
            f"tevredenheid {peer_averages.get('Tevredenheid_Score', 0):.1f}, "
            f"betrokkenheid {peer_averages.get('Betrokkenheid_Score', 0):.1f}, "
            f"verzuim {peer_averages.get('Verzuim_Werkdagen', 0):.1f} dagen "
            f"(gebaseerd op {peer_averages['Peer_Count']} collega's)."
        )

    return "\n".join(lines)


def answer_employee_question(
    question: str,
    snapshot: dict,
    identity: dict,
    history: list[dict],
    hr_context: dict,
    score_trend: list[dict],
    signals: list[str],
    peer_averages: dict | None,
) -> str:
    client = get_client()
    result = client.responses.create(
        model=settings.azure_openai_deployment,
        instructions=_INSTRUCTIONS,
        input=(
            _format_facts(
                snapshot, identity, history, hr_context, score_trend, signals, peer_averages
            )
            + f"\n\nVraag: {question}"
        ),
    )
    return result.output_text
