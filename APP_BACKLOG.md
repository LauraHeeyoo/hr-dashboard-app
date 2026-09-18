# App backlog — HR Dashboard app

Deliberately separate from two other things with a similar-sounding name, so
neither gets confused for this one:

- **`../HR Dashboard new/BACKLOG.md`** — the *old* Power BI/data-generator
  project's own backlog. `ARCHITECTURE.md` §7.1 already flags that file as
  historical context for this app, not a source of truth for it.
- **`ARCHITECTURE.md`** — this app's own infra/architecture decision log
  (Terraform, security, the semantic layer's design, the phased build plan).
  This file is the opposite kind of list: small, concrete product/UX
  follow-ups on pages that are otherwise done, not architecture decisions.

Each item below has enough context to pick up cold, without needing the
session that produced it.

## Salaris page

### 1. Scores in the medewerkers detail table — bucketing decision pending

`Performance` and `Tevredenheid` currently show inconsistent styles despite
both being the same *kind* of thing (a bucket, not a raw score): Performance
shows a numeric-range bucket label (`4.0 - 4.5`, computed in
`mcp.fn_workforce_snapshot_asof` to match the old model's
`dim_employee[Performance Bin]` DAX column), while Tevredenheid shows a
word-labeled bucket (`Laag`/`Neutraal`/`Hoog`, from the existing
`dim_satisfaction_band` dimension table). Neither is wrong, they just came
from two different pre-existing shapes.

The underlying `dbo.fact_workforce_snapshot` table has genuine raw,
per-employee scores for both (`Prestatie_Score`, `Tevredenheid_Score`),
currently exposed nowhere in the app (the SQL function selects
`Prestatie_Score` but `salary.py` doesn't pull it into `employee_rows`;
`Tevredenheid_Score` isn't even selected by the function yet). There's also
a third, related raw score in the same fact table not discussed yet:
`Betrokkenheid_Score` (engagement) — worth folding into the same decision
rather than a separate pass.

Laura wants to decide later whether to show the raw scores, keep both
bucketed (and align their label styles), or something else. Not urgent.

### 2. Salaris chart interactivity — one known precision gap

After generalizing cross-chart highlighting so any of the 6 Salaris charts
can highlight any other (via `computeGroupKeys`/`hlKeys` in `salaris.html`),
one case is still coarser than the rest: clicking a `Salaris_Categorie`
segment in "Spreiding salaris" can only resolve to whole-department
precision in "Startsalaris versus huidig salaris", because that chart's own
server-side aggregation (`get_new_hire_vs_current`) has no per-category
breakdown to narrow within — so it can end up highlighting most/all of that
chart's bars instead of a narrow subset.

Laura: "it's not perfect... but interactive enough... let's keep it like
this for now." Revisit if this becomes actively confusing in a demo.
Options if it does: give that chart its own category breakdown server-side
(a bigger change — see the reasoning in `salary.py`'s
`get_new_hire_vs_current` docstring/comments about why that's not a small
tweak), or accept whole-department precision as simply correct given that
chart's data shape.

Not the same thing as `ARCHITECTURE.md` §14.4 ("extract click-to-highlight
into a shared module") — that's about code reuse across future pages; this
is a precision limit in the current Salaris-page implementation itself.

### 3. Expand the AI chat's semantic-layer coverage

"Vraag het aan de data" (the chat box on Salaris) can only answer questions
the current semantic layer/catalog supports. Not tracked anywhere else yet
(checked `ARCHITECTURE.md` §16 "Open questions for you" — empty). As new
measures/breakdowns get added to the catalog for other reasons, revisit
what the chat can be taught to answer.

### 4. Expand/collapse button styling — fix before demo

The "Volledig weergeven"/"Inklappen" toggle buttons (oversized
mobile/collapsible charts) work correctly but haven't had a visual pass.
Laura: "Not too sure about how... they look, but that's purely aesthetics
so not a big deal for now" — not urgent, but she wants it fixed before she
demos the app, so this one has a real deadline unlike the rest of this
list.

### 5. ~~"% medewerkers onder benchmark" KPI disagrees with the benchmark chart at the margins~~ (RESOLVED)

Spotted by Laura: selecting "Directie" showed the KPI at 100% ("onder
benchmark"), while "Verdeling salaris t.o.v. benchmark" showed all 4
Directie employees in the "Rond benchmark" bin, none in "Onder"/"Ver
onder". Root cause: the KPI (`get_salary_kpis` in `salary.py`) computed
`AVG(CASE WHEN Benchmark_Ratio < 1.0 THEN 1.0 ELSE 0.0 END)` — any amount
below benchmark, no tolerance — while `Benchmark_Status` (what the chart
bins by) uses a ±10% tolerance band around parity ("Rond benchmark" covers
ratio 0.90–1.10, confirmed live). All 4 Directie employees sat at 90–98%:
below 100% (so the strict KPI counted them), but inside the ±10% band (so
the chart correctly called them "roughly at benchmark"). This matched the
original PBIP's own DAX measure exactly, so it wasn't a rebuild bug — but
Laura's call: "it needs to be binned. That makes more sense" — from an HR
perspective a continuous ratio essentially never lands on exactly 100%, so
"any amount below" was never a meaningful threshold anyway.

**Decision:** the KPI now counts "onder benchmark" as `Benchmark_Status`
being "Onder benchmark" or "Ver onder benchmark", matching the chart
exactly — a deliberate, confirmed departure from the original PBIP measure.
Fixed in both `get_salary_kpis` (server-rendered baseline) and
`salaris.html`'s client-side KPI recompute (click-to-highlight). Also
surfaced and fixed a latent bug this exposed: the three top KPIs used
Jinja's implicit truthiness (`{% if kpis.x %}`) instead of `is not none`,
so a genuine `0.0` result — now common for "onder benchmark" — rendered as
"—" instead of "0.0%".

## Profiel page

### 6. Expand beyond the identity card, timeline, and AI summary (mostly done)

The first slice shipped a filter rail, identity/snapshot card, career
timeline, and AI-generated summary. Since then, also shipped:

- **Trend charts** — performance/tevredenheid/betrokkenheid as their own
  panel on "Loopbaan" (not a second Y-axis on the salary chart — that
  version was built first, but Laura found dual-axis hard to read, so it
  became a separate stacked panel sharing only the time axis), plus a
  fourth panel for Verzuim_Werkdagen (its own honest day-count axis, a bar
  mark since it's a discrete count, not a continuous score).
- **A transparent "worth a conversation" panel** ("Aandachtspunten") —
  shipped as designed: rule-based, each signal stating its own real
  numbers, explicitly not a composite/numeric score. Current rules:
  below-benchmark salary, low position in the own salary scale, a
  year-over-year drop in performance or tevredenheid, and a recent
  verzuim average notably above the employee's own prior average. Empty
  list renders as "Geen bijzonderheden gevonden," not a forced result.
- **Peer-group comparison** ("Vergelijking met peers") — five small,
  independent 2-bar charts (Salaris, Performance, Tevredenheid,
  Betrokkenheid, Verzuim) comparing this employee against the average of
  every other employee in the same department, at the same peildatum.
  Department only for now, not role — role-based peer comparison ("vs.
  people in the same role") would be a straightforward variant of the
  same `get_peer_group_averages` query (swap the department filter for a
  role filter) if wanted later.

Still open:

- Possibly gating the newer tiles behind a collapsible "Meer analyses"
  section (`dashboard_base.html`'s expand/collapse convention) if the page
  starts to feel overwhelming by default — not needed yet.

Explicitly out of scope for now (from the original proposal): a numeric
flight-risk score, drilling into other employees from this page, and the
qualification/diploma or safety-incident items the *old* Power BI
project's own backlog had flagged (would need a data-availability check
first — not confirmed to exist in this app's database yet).

### 7. ~~Uit-dienst salary jump with no explaining event~~ (RESOLVED)

Spotted on Faas Giselmeyer's own "Loopbaan" chart, then confirmed systemic
by querying the live database directly: a departing employee's final
`fact_employment` row (`Gebeurtenis = 'Uit dienst'`) very often had a
different `Salaris` than the row before it, with no `Salarisaanpassing`
(or other) event recording why — checked across the whole table, 131 of
227 departures (58%) showed this unexplained jump, while every OTHER
event type's salary changes were consistently explained by that same
row's own event (Promotie/Salarisaanpassing always changed it,
Locatietransfer never did). Root cause: the terminal row's one
`Gebeurtenis` field was already "spent" recording the departure itself
(which — per the Datum_uitdienst fix elsewhere in this backlog —
actually describes that row's `Einddatum`, not its `Startdatum`), leaving
no room to also record that something (usually a raise) happened at that
same row's `Startdatum`.

**Fixed in the data-generation engine** (a data-engine change, not an
app-code change — this app only reads the database): departing employees
now get an extra row where `Startdatum = Einddatum` at the moment they
leave, so the departure no longer overwrites/absorbs whatever event
actually happened right before it — confirmed on Faas directly (his
salary increase now has its own `Salarisaanpassing` row, 2025-08-18 to
2026-06-22, followed by a zero-duration `Uit dienst` row at 2026-06-22
with the same salary) and re-ran the systemic check after the full
re-run: 0 of 227 departures now show a salary mismatch.

Checked whether the app itself needed any change for the new row shape —
it doesn't. `Gebeurtenis_Datum`'s CASE expression keys off the
`Gebeurtenis` string rather than row position, the summary's career-
trajectory bullets only match `Promotie`/`Transfer` so the new
`Salarisaanpassing` row is invisible to them, the zero-duration row still
carries `Vertrekreden` correctly, and `MIN(Einddatum)` (the Loopbaan
timeline cutoff) can't be lowered by a new row with a recent date. The
extra Salarisaanpassing point actually renders better than before, since
it's covered by the existing "no on-chart label for Salarisaanpassing"
rule — a marker with a working tooltip, no added label clutter.

### 8. Profiel's charts don't auto-size within their tile

Laura: "Grafieken auto-sizen nu niet binnen een tile" — the "Loopbaan"
chart (and presumably any future Profiel chart) isn't resizing to fill its
`.grid-stack-item` the way every chart on Salaris already does. Salaris's
charts get this via `width/height: "container"` +
`autosize: {type: "fit", contains: "padding"}` in the Vega-Lite spec, which
"Loopbaan" already has too — so the cause isn't obviously the same fix,
worth actually debugging (e.g. a missing/short container height at embed
time, gridstack's resize event not reaching this page's own chart the way
`dashboard_base.html`'s shared resize observer reaches Salaris's charts)
rather than assumed. Explicitly deferred to "the next iteration," not
urgent.
