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

### 4. Expand/collapse button styling

The "Volledig weergeven"/"Inklappen" toggle buttons (oversized
mobile/collapsible charts) work correctly but haven't had a visual pass.
Laura: "Not too sure about how... they look, but that's purely aesthetics
so not a big deal for now."

### 5. "% medewerkers onder benchmark" KPI disagrees with the benchmark chart at the margins

Spotted by Laura: selecting "Directie" shows the KPI at 100% ("onder
benchmark"), while "Verdeling salaris t.o.v. benchmark" shows all 4 Directie
employees in the "Rond benchmark" bin, none in "Onder"/"Ver onder". Checked
against both the live data and the original Power BI DAX — not a bug
introduced during the rebuild:

- The KPI (`get_salary_kpis` in `salary.py`) computes
  `AVG(CASE WHEN Benchmark_Ratio < 1.0 THEN 1.0 ELSE 0.0 END)` — literally
  "is raw Salaris below Benchmark_Salaris at all, by any amount". This
  matches the original model's `Percentage medewerkers onder benchmark op
  peildatum` DAX measure exactly (`Salaris < Benchmark_Salaris`, no
  tolerance).
- `Benchmark_Status` (what the chart bins by) uses a ±10% tolerance band
  around parity: "Rond benchmark" covers ratio 0.90–1.10, confirmed via a
  live query. All 4 Directie employees sit at 90–98% — below 100% (so the
  strict KPI counts them), but inside the ±10% band (so the chart correctly
  calls them "roughly at benchmark").

So both numbers are individually correct for what they each define — but
they're different questions ("any amount below" vs. "outside a normal
tolerance band") shown side by side on the same page, which reads as a
contradiction. Options: leave both as-is (they were already two different
measures in the original Power BI model), add a tooltip/subtitle to the KPI
clarifying its stricter definition, or redefine the KPI to align with
`Benchmark_Status`'s tolerance band (a deliberate departure from the
original PBI measure — would need the same "confirmed choice + PBI-
comparability impact" treatment `ARCHITECTURE.md` §14.2 gives the salary-
category bucketing decision). Not yet decided.
