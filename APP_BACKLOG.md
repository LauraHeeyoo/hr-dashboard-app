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

### 6. Expand beyond the identity card, timeline, and AI summary

The first slice shipped three things: a filter rail that narrows an
employee-search picker, an identity/snapshot card, a career timeline, and
an AI-generated summary paragraph. Laura's own proposal (before building)
listed several more pieces, deliberately deferred rather than built all at
once — "we can expand on the page later (with the 'Meer analyses' button
possibly)":

- **Trend charts**, not just snapshots — performance/engagement/
  satisfaction/absence over the employee's last N reviews or months,
  instead of only "the latest value." This was the single change Laura
  singled out as the most valuable one over the old Power BI page.
  Under discussion (not yet decided): rather than a separate chart, add
  performance/tevredenheid(/betrokkenheid) as a second Y-axis directly on
  "Loopbaan", so a career event and a wellbeing dip/rise are visible
  together on one chart. Two real wrinkles to resolve before building:
  (a) these scores currently live on different scales — confirmed live,
  `Prestatie_Score` is ~2.4–5.0, `Tevredenheid_Score`/`Betrokkenheid_Score`
  are both ~4.4–8.5 (already close to each other, Performance is the odd
  one out) — Laura is touching the data generator anyway and may put all
  three on one shared 0–5 or 0–10 scale, which would make a single
  secondary axis much cleaner than three); (b) these scores are periodic
  snapshot data (`fact_workforce_snapshot`, roughly monthly), not
  `fact_employment` career events — a data-grain mismatch with what
  "Loopbaan" currently draws from, not a blocker, just a second query to
  add and layer on the same time axis at a different density.
- **Peer-group comparison** instead of (or alongside) the org-wide average
  the old page's KPI mini-charts used — "vs. their own department" or "vs.
  people in the same role" is a fairer comparison than one company-wide
  blend.
- **A transparent "worth a conversation" panel** — a short, rule-based (not
  a black-box score) list of things worth a manager's attention (e.g.
  "compa-ratio below 90% for 8+ months"), explicitly *not* a numeric
  "flight risk" score.
- Possibly gated behind a collapsible "Meer analyses" section, the same
  pattern salaris.html already uses for its own secondary charts
  (`dashboard_base.html`'s expand/collapse convention), so the page doesn't
  get overwhelming by default.

Explicitly out of scope for now (also from that same proposal): a
numeric flight-risk score, drilling into other employees from this page,
and the qualification/diploma or safety-incident items the *old* Power BI
project's own backlog had flagged (would need a data-availability check
first — not confirmed to exist in this app's database yet).

### 7. Profiel's charts don't auto-size within their tile

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
