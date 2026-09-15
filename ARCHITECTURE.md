# HR Dashboard Web App — Architecture Proposal

Status: **proposal / discussion document — nothing has been built yet.** This is the third and (pending your sign-off)
final revision of Phase 0. Scope unchanged: replace the Power BI HR report with a maintainable, **publicly hosted**
web application, owned primarily by data engineers/analysts/QA, reproducing its dashboard functionality and adding an
LLM-driven "ask a question, get a chart" interface.

---

## 1. How the inputs to this document are classified

🔒 = fixed requirement/decision · 🧪 = hypothesis, critically reassessed · ❓ = still genuinely open.

### 1.1 Fixed requirements & decisions (🔒) — all rounds combined

| # | Decision |
|---|---|
| D1 | Audience is the public internet, unauthenticated. No visitor login. |
| D2 | The public app only ever touches synthetic/demo HR data. A future real-data use case is a separate, architecturally isolated private deployment. |
| D3 | LLM-abuse prevention is required from the start (rate limiting, per-visitor limits, prompt-size limits, cost caps, automated-abuse protection). |
| D4 | Azure is the hosting platform. Container Apps is a strong candidate, not mandatory. |
| D5 | Terraform is the IaC tool (a deliberate learning goal) — small steps, no premature modules. |
| D6 | The existing Azure SQL Server/`db_hr_demo` are not Terraform-managed yet — existing dependency/data source. |
| D7 | The existing HR-generator Function App is a future Terraform-import candidate, not now. |
| D8 | Terraform provisions new application infrastructure only; existing vs. managed resources are clearly distinguished. |
| D9 | Infra provisioning, application deployment, DB migrations, and freshness monitoring are four distinct concerns/pipelines. |
| D10 | Terraform precedes the first application vertical slice but is not itself one. |
| D11 | The LLM provider sits behind a small abstraction, swappable without touching the semantic/query layer. |
| D12 | **Use the existing demo-dashboards Resource Group** as an unmanaged data source; Terraform owns only the new resources added for this app, clearly named/tagged within it. |
| D13 | **GitHub Actions is the CI/CD platform** (no longer open), authenticating to Azure via **OIDC/workload identity federation**, not a long-lived client secret. |
| D14 | **Azure OpenAI is the preferred LLM-provider direction**, contingent on a practical availability check (§6) — OpenAI-direct remains the documented fallback via the existing abstraction (D11) if that check fails. |
| D15 | **Salaris is the first application vertical slice** (final, not a comparison anymore — §13.1). |
| D16 | Semantic-model technical debt (§14) is resolved **per domain, at migration time** — never silently, never all up front. |
| D17 | **Vega-Lite is the preferred/default charting library**, adopted after reviewing the real side-by-side comparison (§4.1a) — a considered, **reversible** choice: if Phase 1 hits a concrete limitation Plotly demonstrably solves better, revisit it. Not architecturally excluded. Matplotlib/Seaborn remain fine for analysis/debugging/static output, never the primary interactive dashboard library. |
| D18 | The existing demo-dashboards Resource Group is confirmed as **`Demo_dashboards`** (region `westeurope`); it already contains `srv-demo-dashboards` (region `northeurope`, databases `db_hr_demo` + `db_marketing_demo`), the existing storage account `stdemodashboards`, and the HR-generator Function App **`fa-demo-hr-datagenerator`** (D7's future import candidate) — confirmed via `az resource list` this session. |
| D19 | A Microsoft Entra admin **is already configured** on `srv-demo-dashboards` (the signed-in account itself, confirmed via `az sql server ad-admin list`) — §10.3's Managed Identity design proceeds with no fallback needed. |
| D20 | **Revised during Phase 0.5.** The Terraform remote-state backend was designed to authenticate via Entra ID / Azure RBAC (`use_azuread_auth = true`, `Storage Blob Data Contributor` scoped to the state storage account) — the concrete exception anticipated in the original wording of this decision. Creating that role assignment needs `Microsoft.Authorization/roleAssignments/write`, which the Contributor role (the only role actually held) excludes; the person who could grant broader rights is unavailable for ~1 month. **Now:** the backend uses the storage account's own key instead, auto-fetched by Terraform via `listKeys` (a Contributor-level, control-plane action) — never typed into a file. This is deliberately scoped to *this state backend only*; it is not a reversal of the broader Managed-Identity design in §10.3, and the **same permission gap will recur** for any future role assignment this project's Terraform needs (e.g. Container App identity → Key Vault/Azure OpenAI) — revisit the RBAC path once someone with sufficient rights is available. |
| D21 | **Resolved: `northeurope`** for **compute/logging** resources (Container App Environment, Container App, Log Analytics) — not inherited from the Resource Group's `westeurope` metadata, and decided only after actually comparing both regions (evidence in §18), not assumed. Deciding factor: Azure Container Apps' Standard consumption meters are ~25-30% cheaper in `northeurope` (real Retail Prices API data), with SQL proximity as secondary confirmation. The bootstrap's state-storage account stays in `westeurope` regardless (unrelated, unaffected). **Narrowed by D23**: Azure OpenAI specifically is no longer covered by this decision — it has its own region (see D23), since it's an independent resource with independent regional characteristics. Full reasoning also recorded in `infra/variables.tf`'s `location` variable description. |
| D22 | **Working agreement for Phase 0.5 (Terraform-learning goal):** Laura runs every Terraform CLI command herself (`init`/`fmt`/`validate`/`plan`/`apply`/`destroy`/`import`/`state`); Claude writes/edits `.tf` files, explains each command before it's run, and analyzes the output after. Read-only Azure CLI checks remain fine on either side; mutating Azure CLI commands that substitute for a Terraform operation do not. **Refined once Laura's own plan/validate fluency was established:** for a straightforward `plan` showing only expected creates matching what was just discussed, she applies directly without waiting for a review round-trip. Still worth a pause and a shared look before applying: anything showing `destroy`/`replace` (not just `create`), an unexpected resource count, an unfamiliar warning, or the first instance of a resource type with real security impact (RBAC role assignments, Managed Identity bindings, network/access settings). |
| D23 | **Azure OpenAI gets its own region, `westeurope`, decoupled from `var.location` (D21).** Trigger: Laura wants a "mini"-class model as the starting chat model, chosen for reliability over the cheapest option (the cost difference between candidate models is fractions of a cent per question, not worth trading reliability for) but also wants `gpt-5.6-luna` kept available as a future option, and Luna is `westeurope`-only (not in `northeurope`). Resolution: Azure OpenAI token pricing is **identical** between `northeurope` and `westeurope` (confirmed) — no cost reason it needs to sit in `northeurope` alongside compute, and `westeurope` has the fuller model catalog. New variable `openai_location`, default `"westeurope"`, independent of `var.location`. **Model choice revised again at apply time**: the originally-planned `gpt-4o-mini` (2024-07-18) turned out to already be in "Deprecating" status — Azure rejected the deployment (a real 400 error, not something `plan`/`validate` could have caught, since model lifecycle state isn't part of the HCL). Replaced with **`gpt-5.4-mini`** (2026-03-17), verified `GenerallyAvailable` with the longest retirement runway (Sept 2027) of the current "mini"-tier options checked, ≈$0.0018/question at the same estimated prompt size — still trivial in absolute terms. |

### 1.2 Hypotheses reassessed this round (🧪)

| # | Hypothesis | Outcome |
|---|---|---|
| H9 | Production DB auth is a SQL login's password, stored in Key Vault | **Revised** — **Managed Identity is the preferred design**, contingent on one concrete prerequisite check (§10.3) |
| H10 | Every queryable object needs an `mcp`-schema wrapper view | **Revised** — pragmatic, per-object decision (§7.1); direct `dbo` reads are fine where there's no concrete architectural benefit to a view |
| H11 | Key Vault is part of Phase 0.5 by default | **Revised** — **deferred**; with Managed Identity (SQL + Azure OpenAI) and GitHub OIDC, v1 may need zero runtime secrets (§10.4) |
| H12 | Terraform manages the Container App's image/revision | **Revised** — explicit ownership split (Model A, §12.2) |
| H13 | CAPTCHA-style friction should wait for observed abuse, across the board | **Partially revised** — still true for general site access, but a lightweight, free, endpoint-scoped check (Cloudflare Turnstile) is now recommended **at Phase 3 launch**, specifically on the LLM endpoint, because that's a different cost/friction trade-off than a site-wide CAPTCHA (§10.6) |
| H14 | Azure Front Door belongs in the base design | **Revised** — **not in v1**; Container Apps' own public ingress is the default, Front Door Standard is a cheap, optional near-term upgrade, Premium is explicitly excluded absent a concrete future reason (§10.7) |

### 1.3 Still genuinely open (❓)

| # | Item | Where |
|---|---|---|
| O5 | The canonical salary-category definition (§14.2) — a **Phase 1 prerequisite**, not a Phase 0.5 blocker |

O3 (Entra admin) and O4 (naming/tagging) from earlier revisions are resolved — see D18/D19 and `infra/variables.tf`'s `project = "hrdash"` prefix / `common_tags` (confirm or adjust when you review the Phase 0.5 code).

---

## 2. What we found (recon — unchanged, summarized for context)

Azure SQL `db_hr_demo`: 35 tables, galaxy schema, measured data volume small (largest table 46,170 rows/8.2 MB, whole DB well under 50 MB). External simulator (likely the existing Function App, D7) writes new data on its own cadence, checkpointed in `simulation_state`. Power BI semantic model: 109 DAX measures, dominated by the "op peildatum" as-of pattern; known technical debt (conflicting tenure/salary-category definitions, `TODAY()`-volatile columns, dead model parts) — see §14. 13 report pages, stock chart types plus one reusable Deneb/Vega component; custom in-canvas navigation. Full detail unchanged from the recon phase — not repeated here to keep this revision focused on the ownership/security/deployment corrections requested.

**Terminology note carried forward:** the safety measure `Incidenten per 100 medewerkers` is headcount-normalized, not hours-worked-normalized — it is **not** TRIR. Name it "Incident Rate per 100 Employees" in code/docs, formula unchanged.

---

## 3. Inferred requirements — unchanged, now all finalized per §1.1

---

## 4. Architecture options — unchanged in shape, two pieces explicitly not locked in

FastAPI + server-rendered HTMX/Jinja2 remains the recommendation over Dash or a React/TS SPA, with the explicit complexity ceiling and gradual-migration path from the previous revision (streaming chat and a pin/reorder chart board are the concrete future triggers for isolating a component framework into one widget, not a rewrite). Unchanged — not repeated in full here.

**FastAPI itself is a preferred direction, not dogma.** It fits well today (async support, Pydantic-based request/response validation that maps naturally onto validating an LLM-produced `VizRequest`, typing throughout) — but if concrete requirements surfacing during implementation show Flask or Django fitting better (e.g. a specific team-familiarity reason, or Django's batteries-included admin/ORM turning out to earn its weight), that's a legitimate reason to reconsider. Not re-litigated speculatively now — only if implementation surfaces a real reason.

**The charting library: Vega-Lite, chosen after comparison** — see §4.1a.

### 4.1a Charting library: Vega-Lite (default), Plotly not excluded

A live side-by-side comparison was built using two representative Salaris-domain charts (the salary-distribution histogram and the department-vs-benchmark bar chart) rendered once with each library against the same real (synthetic) data: **[Vega-Lite vs Plotly](https://claude.ai/artifact/VnUZYuXiqG9RQbCwnLNKJd)**.

Summary of the comparison (full criteria-by-criteria table in that artifact):

| | Vega-Lite | Plotly |
|---|---|---|
| Code volume | More compact once color depends on a category (one encoding channel vs. one trace per category) | More compact for a single series; more verbose for multi-category color |
| Readability | A grammar-of-graphics JSON spec — new syntax, but small and consistent; maps directly onto "x/y/color" field thinking | Plain function calls over familiar trace objects — likely the most immediately familiar option for a pandas/Jupyter-native analyst |
| Interactivity | Opt-in, more setup, but that's what makes declarative cross-filtering possible | Pan/zoom/legend-toggle work with zero extra config — the more "free" interactivity for a single chart |
| Future cross-filtering | **Its strongest point** — shared selections between views are a first-class part of the grammar | Possible, but via hand-written `plotly_click` event glue per interaction |
| Fit with a deterministic `VizRequest → chart` compiler | Near-mechanical for simple charts, and stays in the *same* grammar as complexity grows | Equally mechanical for simple charts; richer compositions typically drop to a lower-level API — a second compiler target |
| Ecosystem | Smaller, research-backed (UW Interactive Data Lab); the existing PBI report's Profiel-page bullet bars already use Vega (via Deneb) | Larger, Python/ML-ecosystem-standard, backed by Plotly Inc. |
| This dataset's performance | Immaterial for either | Immaterial for either |

**Decision (D17): Vega-Lite is the preferred/default charting library**, made after reviewing the comparison artifact above (including the corrected second chart) — mainly because the architecture's LLM-safety design (§7–8) and the stated interest in future cross-filtering both favor a grammar that composes uniformly as complexity grows, and its JSON-native shape matches "the compiler's output is exactly what gets logged/tested/rendered." This is a **considered, reversible** choice, not an architectural exclusion of Plotly: if Phase 1 runs into a concrete limitation Plotly demonstrably handles better, revisiting it is explicitly in scope — it does not require another architecture round, just a swap of the chart-spec-compiler's target grammar (§15's `llm/chart_compiler.py` stays the seam this would go through). Matplotlib/Seaborn remain valid for analysis, debugging, and static output — never the primary interactive dashboard library.

---

## 5. Component diagram / data flow — revised for existing-RG ownership, no Key Vault, no Front Door by default

```
                                    ┌─────────────────────────┐
                                    │      Public internet       │
                                    │   (unauthenticated visitor) │
                                    └──────────────┬───────────────┘
                                                   │ HTTPS (Container Apps' own managed TLS ingress —
                                                   │  no Front Door in v1, §10.7)
┌══════════════════════════ Existing demo-dashboards Resource Group (D12) ═══════════════════════════┐
│                                                    │                                                  │
│  ┄┄┄┄┄┄┄┄ existing / unmanaged by Terraform ┄┄┄┄┄┄┄│┄┄┄┄┄┄┄┄┄┄┄┄  ══ Terraform-managed (D5/D8) ══════  │
│  ┊ Azure SQL Server: db_hr_demo                    │            ┌──────────────────────────────────┐ │
│  ┊  schema `mcp`: versioned views (where warranted)│            │ Azure Container App (FastAPI +    │ │
│  ┊  schema `dbo`: raw star schema, some read        │            │  Jinja2/HTMX, Vega-Lite, D17)      │ │
│  ┊  directly where that's a clean, stable contract  │            │  System-assigned Managed Identity─┼─┼─┐
│  ┊  (§7.1)                                          │◄───────────┤  ┌──────────┐ ┌────────────────┐ │ │ │
│  ┊                                                  │  AAD token │  │Rate limit/│ │Semantic/query   │ │ │ │
│  ┊ Existing HR-generator Function App (D7 — future  │  auth,     │  │abuse guard│ │layer (§7)       │ │ │ │
│  ┊  import candidate, untouched for now)             │  no stored │  └──────────┘ └────────────────┘ │ │ │
│  ┊                                                  │  password  └──────────────────────────────────┘ │ │
│  ┊ Other existing demo-dashboard resources           │                                                │ │
│  ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄│           ┌──────────────────────────────────┐ │ │
│                                                       │           │ Log Analytics / App Insights      │ │ │
│                                                       │           └──────────────────────────────────┘ │ │
│                                                       │           ┌──────────────────────────────────┐ │ │
│                                                       │           │ Container Apps Job (cron)          │ │ │
│                                                       │           │  — freshness detect + alert only,  │ │ │
│                                                       │           │  no DDL (added later, not Phase 0.5)│ │ │
│                                                       │           └──────────────────────────────────┘ │ │
│                                                       │           ┌──────────────────────────────────┐ │ │
│                                                       │           │ Azure OpenAI (D14) ◄───────────────┼─┘ │
│                                                       │           │  reached via the same Managed      │   │
│                                                       │           │  Identity, RBAC-granted, no key     │   │
│                                                       │           └──────────────────────────────────┘   │
│                                                       │           (Key Vault: **not present in v1** —     │
│                                                       │            add only when a real secret needs it,  │
│                                                       │            §10.4 — e.g. a Turnstile secret key    │
│                                                       │            if/when adopted in Phase 3)            │
└═══════════════════════════════════════════════════════════════════════════════════════════════════════┘

   ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄ Future / explicitly out of scope (D2) ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
   ┊  Private deployment with real employee data — separate subscription/resource   ┊
   ┊  group/DB/secrets, no network path from the public demo.                       ┊
   ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
```

The chat request pipeline (question → planner LLM call → server-side validation → deterministic query compilation →
execution → deterministic Vega-Lite compiling, D17) is unchanged in shape; §8 adds one guardrail step at the front
(Turnstile verification) ahead of the planner call.

---

## 6. LLM provider — Azure OpenAI, contingent on a practical check (D14)

The comparison from the previous revision stands (Managed Identity/secretless auth, unified Terraform/observability stack, two independent budget layers, Private Endpoint upgrade path for the future private deployment) and is accepted as the preferred direction. Per your instruction, this is **not re-litigated as a fresh vendor bake-off** — it now needs one thing: a practical go/no-go check during Phase 0.5's Azure OpenAI provisioning step (§12.1, step 9):

- The desired model is actually available as an Azure OpenAI deployment.
- A suitable region/deployment type is available (matching where the rest of the app is hosted, or close enough not to add meaningful latency).
- The subscription has, or can readily obtain, sufficient quota for demo-scale traffic.
- Provisioning this doesn't become disproportionately difficult for what is, after all, a small demo.

**If any of these fail in a way that isn't quickly resolvable**, fall back to OpenAI-direct via the already-designed `LLMClient` abstraction (D11) — no architecture change, just a different concrete implementation registered behind the same interface, and the secret-handling question reopens narrowly (an API key needs to live somewhere — see §10.4's trigger condition).

---

## 7. Semantic/query layer — pragmatic data-contract boundary, least-privilege grants

### 7.1 "Views only" reassessed — a per-object decision, not a blanket rule

Agreed: an `mcp` view that's just `SELECT * FROM dbo.dim_x` with no transformation is waste, not architecture. The decision per object is now:

**Use an `mcp` view when it:**
- centralizes business logic (the as-of/point-in-time pattern is the prime example);
- abstracts a join (e.g. the LFL self-join, the recruitment-funnel timing joins);
- exposes only approved columns (hides anything not meant for the app/LLM);
- carries as-of/time-intelligence logic of any kind;
- would otherwise need to insulate the app from a genuinely *planned* schema change — verified against the live database at implementation time, not assumed from `BACKLOG.md` (see the correction below).

**Read a `dbo` table directly when** it's stable reference data with no transformation need and no named benefit from the list above — a pure pass-through view is waste either way.

**Correction: the naming-convention reasoning in the previous revision was wrong.** `BACKLOG.md` was written primarily as a Power BI/data-generator backlog, not an automatically valid roadmap for this application — and the specific claim that most tables need a view "because of a planned English-language rename" doesn't hold up against the live database: the current, deliberate convention is **English table names and technical keys, Dutch business columns** (e.g. `dbo.fact_workforce_snapshot.Salaris`, `dbo.dim_department.Afdeling_Naam`) — largely already in place, not a pending migration. There is no requirement to rename business columns to English for this app. The semantic layer's catalog simply maps English code-identifiers (its internal keys, used in code and the `VizRequest` schema) to Dutch display labels, both pointing at the existing Dutch-named columns directly — no rename needed on either side. **General rule going forward:** treat `BACKLOG.md` and `Review en Plan - HR Dashboard.md` as historical context, not a source of truth — verify the live schema before treating any backlog item as still-pending work.

Either way, **the application-level boundary is unchanged**: the semantic layer's catalog is the only thing the UI or the LLM can address, whether a given catalog entry resolves to an `mcp` view or a direct `dbo` table — this per-object pragmatism is entirely internal to the catalog's implementation, invisible to anything above it.

### 7.2 Least-privilege permission model for the Managed Identity

- One dedicated database role, e.g. `app_runtime_reader`, created via versioned SQL (`migrations/grants/`, sibling to `migrations/views/` — both are "database contract" code, reviewed the same way).
- `GRANT SELECT` on exactly the `mcp` views and the specific `dbo` tables the catalog references — **never** `db_datareader`, **never** a schema-level blanket grant.
- The Container App's system-assigned Managed Identity is mapped to a contained database user (`CREATE USER [...] FROM EXTERNAL PROVIDER`, §10.3) and added to `app_runtime_reader` — one clear, auditable, code-reviewed grant list.
- A cheap but valuable test (§11): assert the granted object list exactly matches the catalog's registered objects — catches "someone added a catalog entry and forgot the grant" and its inverse.

### 7.3 Execution boundary (unchanged from the previous revision)

SQL Server does aggregation/filtering/joins/ranking/window functions (the as-of lookup, the LFL self-join, absence-day clipping, funnel timing, the incident-rate ratio, rank-based "top-1" tables — all SQL); Python's query-compiler layer describes/orchestrates and assembles parameterized SQL from catalog-approved pieces; genuinely-Python logic is limited to post-query formatting and the chart-spec compiler (library pending, §4.1a), plus the one flagged judgment call (the career-history narrative string, SQL `STRING_AGG` first, Python fallback only if the per-event templating outgrows T-SQL). Not repeated in full — see the previous revision's §7 for the complete per-measure table, which stands unchanged.

### 7.4 SQL injection — precise framing (unchanged, still accurate)

Values are parameterized by the driver; identifiers are never interpolated from user/LLM text — a request only ever *selects a key* into a fixed, developer-authored catalog, and the identifier that lands in the SQL text always comes from the registry, never the request. Combined with server-side re-validation and the least-privilege grant above (§7.2), this remains the complete picture.

---

## 8. LLM-to-visualization flow — one guardrail added at the front

Unchanged pipeline (§5's diagram), with one addition motivated by §10.6: **a Turnstile token is verified server-side before the planner LLM call is made at all.** A failed/missing token short-circuits before any LLM spend occurs — this is precisely why it's worth having specifically on this endpoint (it protects the one place real money is spent per request), rather than being blanket site-wide friction.

---

## 9. Data refresh strategy — unchanged from the previous revision

No cache in v1 (data volume doesn't justify it); views vs. direct tables per §7.1; migrations and freshness-monitoring remain two separate concerns (next section). Not repeated in full.

---

## 10. Security — Managed Identity design, Key Vault reassessed, public threat model with cost-aware bot protection

### 10.1–10.2 Visitor auth & public/private isolation — unchanged from the previous revision.

### 10.3 Database authentication — Managed Identity, designed

**Preferred design:**

```
Container App → system-assigned Managed Identity → Azure AD token → Azure SQL (db_hr_demo)
```

**Feasibility and prerequisites (this is a real design, not a restated preference):**
1. **Azure SQL requires a Microsoft Entra admin configured on the logical server** before any Azure-AD-based authentication works against it at all. **Confirmed present** (D19) — checked via `az sql server ad-admin list --resource-group Demo_dashboards --server srv-demo-dashboards`, which shows the signed-in account already set as the server's Entra admin. No fallback needed; proceed with the design below as planned.
2. Provisioning the Container App's identity as a database user requires running `CREATE USER [<identity-name>] FROM EXTERNAL PROVIDER;` **over an Azure-AD-authenticated connection** — the existing SQL-auth `mcp_readonly` login **cannot** do this (SQL auth and AAD auth are different authentication paths; a SQL login can't provision an AAD-mapped contained user). **Keep this simple for the bootstrap**: a one-time manual step is entirely acceptable — a privileged Entra admin connects via Azure AD auth (e.g. Azure Data Studio/SSMS or `sqlcmd`) and runs the `CREATE USER`/role-membership statements once. Automating this through the database-migration pipeline's own OIDC-federated identity (§12.3) is a legitimate later improvement, worth doing once there's real, recurring value in it (e.g. a second environment needing the same setup) — not a day-one requirement.
3. Once provisioned, the identity is added to the least-privilege `app_runtime_reader` role (§7.2) — never `db_datareader`.
4. The application's DB driver requests an Azure AD access token for the SQL resource and authenticates with it — the standard, documented mechanism for this (e.g. ODBC's `Authentication=ActiveDirectoryMsi` connection attribute, already available in the ODBC Driver 18 confirmed present on this machine, or acquiring a token via `azure-identity` and passing it through the driver's token-based connection method).

**Fallback:** if step 1 genuinely can't be arranged (organizational reasons, shared-server constraints), the design falls back to the previous revision's Key-Vault-backed SQL-auth login — not a redesign, just reverting one piece. This isn't expected to be needed, but it's an explicit, documented fallback rather than a silent assumption.

### 10.4 Secrets & Key Vault — reassessed, deferred

With Managed Identity for SQL (§10.3), Managed Identity/RBAC for Azure OpenAI (§6/D14), OIDC for GitHub Actions (§12.5), and (if Azure Container Registry is used) Managed-Identity-based `AcrPull` for image pulls, **v1 may need zero runtime secrets**. Concretely, what's left is:
- A fallback OpenAI-direct API key, needed only if D14's contingency triggers — kept as a GitHub Actions secret for build/deploy-time use and/or a local `.env` value for development, **not** a reason on its own to provision Key Vault.
- A Cloudflare Turnstile secret key, **if** adopted at Phase 3 (§10.6) — this is the most likely concrete trigger for introducing Key Vault, at that point, not before.

**Decision: Key Vault is not part of Phase 0.5.** Add it exactly when a concrete runtime secret exists that needs it — a small, well-motivated Terraform addition later, not a redesign. This is a deliberate YAGNI call, not an oversight.

### 10.5 Public-demo threat model — essential v1 / recommended / later, cost-aware

| Measure | Tier | Notes |
|---|---|---|
| Per-visitor (IP + session) rate limiting on chat and query endpoints | Essential v1 | App layer |
| Maximum prompt length; input size limits on all endpoints | Essential v1 | App layer |
| Maximum result rows / date range per query | Essential v1 | Semantic layer, already designed |
| Request timeouts | Essential v1 | App + DB client |
| Global LLM cost cap + budget alert | Essential v1 | Azure Cost Management on the OpenAI resource + an app-side running counter |
| Kill switch / feature flag for the chat feature | Essential v1 | App config, flippable without redeploy |
| Graceful degradation when the LLM is unavailable | Essential v1 | App |
| No raw prompts/PII in long-lived logs | Essential v1 | Logging config |
| HTTPS/TLS; least-privilege DB account | Essential v1 | Container Apps' own ingress (§10.7) + §7.2 |
| **Cloudflare Turnstile (or equivalent) on the chat/LLM endpoint specifically** | **Recommended from Phase 3 launch** — revised from "wait for abuse," see §10.6's reasoning | App (client widget + one server-side verify call) |
| Front Door Standard (edge rate limiting, managed WAF, custom domain) | Optional near-term upgrade, once a real public domain/launch is imminent | Infra, §10.7 |
| CAPTCHA-style friction on general site access (not the LLM endpoint) | Later — only if abuse is actually observed | App |
| IP allow/block-listing from observed patterns | Later, reactive | Infra/App |
| Distributed (Redis-backed) rate limiting | Later — triggered by scaling past one Container App replica, not by data volume | App/infra |
| Front Door Premium | **Excluded from the base design** unless a concrete future business/security reason emerges | Infra |

### 10.6 Turnstile — reassessed as a Phase-3 recommendation, not a "wait and see"

The earlier "no CAPTCHA at launch" reasoning was about a **traditional, site-wide CAPTCHA** — real friction, applied broadly, for a benefit that's hard to justify before observed abuse. Turnstile is different in kind, which changes the trade-off:

| Criterion | Assessment |
|---|---|
| Security value | Meaningfully raises the bar against scripted abuse of the one endpoint that actually costs money per request — a well-targeted, not blanket, control |
| User friction | Low — Turnstile is designed to be a largely invisible/non-interactive challenge, not an image-grid puzzle |
| Implementation complexity | Low — a small client-side widget + one server-side token-verification HTTP call, gating the planner LLM call (§8) |
| Privacy | Reasonable — no image puzzles, minimal tracking relative to classic CAPTCHA; worth a one-line mention in a privacy notice if adopted |
| Cost | Free at this traffic scale |
| Needed from day one, or only after observed abuse? | **From day one of the LLM feature (Phase 3)** — because the cost exposure (real LLM spend) exists from the moment the endpoint is public, while the mitigating control here is nearly free and low-friction, the asymmetry favors having it before, not after, abuse occurs. This is the opposite trade-off from the site-wide-CAPTCHA case, which is exactly why it gets a different answer. |

This is a considered, revised recommendation, not a default technology choice — Turnstile is named as the concrete example because it's free and well-known, but any comparably low-friction/low-cost bot-check is an equally valid implementation.

### 10.7 Front Door — reassessed with cost explicitly in view

Three tiers, compared honestly on cost vs. benefit for a small NL sales demo (exact current pricing should be re-verified at implementation time; the relative ordering below is the durable part):

| Tier | What it adds | Cost order of magnitude | Verdict |
|---|---|---|---|
| **No Front Door** (Container Apps' own public HTTPS ingress) | Managed TLS, a public endpoint — included, nothing extra | Effectively free | **Default for v1.** Combined with §10.5's app-level guardrails and §10.6's Turnstile, this is "cheap and simple, but with real protection against an unexpected LLM bill" — exactly the stated priority. |
| **Front Door Standard** | Custom domain with managed TLS in front of Container Apps, a baseline managed WAF ruleset, edge-level IP rate limiting | Tens of euros/month range | Worth adding once there's a real public custom domain / an actual go-live moment for prospects — not blocking Phase 1–3. |
| **Front Door Premium** | Advanced bot-management rules, Private Link to origin, richer WAF | Hundreds of euros/month range | **Explicitly excluded from the base design.** Add only if a concrete future reason appears (sustained abuse Standard's ruleset can't handle, or a compliance requirement) — not by default. |

Performance/CDN benefits alone are correctly not a reason to add any of this for a small Dutch-market sales demo, as you noted — the only justification considered here is security/abuse-cost control, and Tier 0 plus app-level guardrails plus Turnstile covers that proportionately.

---

## 11. Testing strategy — one addition

Everything from the previous revision stands (reconciliation tests against SQL views/templates, query-compiler unit tests, guardrail/adversarial fixtures, LLM record/replay, Playwright smoke tests). **Added:** a permission-drift test asserting the `app_runtime_reader` role's granted objects exactly match the semantic catalog's registered objects (§7.2) — cheap, and it catches both over-permissioning and under-permissioning as the catalog evolves.

---

## 12. Deployment & CI/CD

### 12.1 Terraform learning path — revised order

Reordered to reflect: existing RG as a data source (D12), no Key Vault yet (§10.4), Managed Identity throughout, and an explicit note on the OIDC bootstrapping nuance.

1. **Provider/backend configuration** and minimal project structure (`azurerm` provider pinned).
2. **Remote state backend bootstrap** — a Storage Account + container for Terraform state, created once via a small separate step (the classic chicken-and-egg exception: this can't sensibly be managed by the state it will hold). Access restricted to the few principals that need it.
3. **The existing demo-dashboards Resource Group, referenced as a `data "azurerm_resource_group"` source** — not managed, not imported; every new resource's `resource_group_name` points at it.
4. **GitHub Actions OIDC federation** — an Azure AD App Registration (Service Principal) with a federated credential trusting this repository's workflows, scoped RBAC roles on the subscription/resource group it actually needs. **Note the ordering nuance**: the very first applies of steps 1–3 are reasonably run locally by a human (`az login` + `terraform apply`) before CI can apply anything — this step is what lets steps 5 onward run from GitHub Actions instead of a laptop, so it belongs early, but not before there's a resource group to scope its RBAC role assignments against.
5. **Log Analytics workspace + Application Insights** — must exist before step 6 (a real dependency, not just a logical nicety: Container App Environments require a Log Analytics workspace).
6. **Container App Environment** (depends on 5).
7. **Minimal Container App** — placeholder image, **Single revision mode**, with the `lifecycle.ignore_changes` ownership split (§12.2) wired in from this very first apply, not retrofitted later.
8. **System-assigned Managed Identity** on the Container App (conceptually its own step for the learning path, even though it's one attribute on the same resource).
9. **Azure RBAC role assignments Terraform is responsible for**: (once step 10 exists) `Cognitive Services OpenAI User` on the Azure OpenAI resource for the Container App's identity. **Container registry choice is deliberately not decided yet** — Azure Container Registry is a logical future candidate, but the registry gets chosen/provisioned when the first real application image is actually built and pushed (start of Phase 1), not speculatively now; if ACR is chosen then, an `AcrPull` role assignment for the identity is a small, obvious addition to this step at that time. **The SQL-side grant (the contained database user + role membership, §10.3/§7.2) is explicitly *not* a Terraform/Azure-RBAC concern** — it's versioned SQL, reinforcing the same separation of concerns as D9.
10. **Azure OpenAI resource + model deployment**, with the practical availability check from §6 happening live here; RBAC grant to the same Managed Identity.
11. *(Later, triggered by need, not by schedule)* **Key Vault** — only once a concrete secret exists (§10.4).
12. *(Later)* **Container Apps Job** for the freshness/alerting job (§9), once its code exists.
13. *(Later)* **Front Door Standard**, once a real public launch is imminent (§10.7) — Premium excluded absent a concrete reason.
14. *(Much later, D7)* **Import the existing Function App** into Terraform state — a deliberately deferred, separate exercise.

Kept flat, no module hierarchy, matching D5 — a local module gets extracted only once a second environment genuinely duplicates these resources, not in anticipation.

### 12.2 Container App image/revision ownership — Model A, precisely scoped

**Model A adopted** (your preference, and the technically better fit): Terraform owns the Container App's infrastructural configuration; the application pipeline owns which image is running.

| Property | Owned by |
|---|---|
| Container App Environment, scaling rules, ingress config, CPU/memory, revision mode (Single), managed identity assignment, non-secret environment variable *names* | **Terraform** |
| Container image reference, revision suffix | **Application pipeline** (via `az containerapp update --image ...` or the Container Apps GitHub Action), explicitly excluded from Terraform's management via `lifecycle { ignore_changes = [...] }` scoped to *only* those two attributes |

**The risk you flagged is real and worth stating precisely:** `ignore_changes` must target the specific `image`/`revision_suffix` attributes on the container/template block — **not** the whole `template` block. Ignoring the entire block would also silently hide drift in scaling rules, environment variables, or resource limits that Terraform is supposed to own, which is exactly the over-broad outcome to avoid. The precise HCL attribute path depends on the current `azurerm_container_app` schema and should be confirmed against the provider docs at implementation time (step 7 above) rather than assumed here.

**Why not Model B** (Terraform deploys every image): it conflates two different cadences and risk profiles (infra changes are rare and reviewed; app deploys are frequent and should be fast), forces every code push through a Terraform plan/apply cycle and its state-locking overhead, and fights the "small, understandable Terraform steps" learning goal by putting a fast-moving image tag inside infra HCL. Model A is both your stated preference and the better fit here.

### 12.3 Application pipeline

Lint/typecheck/tests → build image → push (registry pulled via the Managed Identity's `AcrPull`, no registry secret) → `az containerapp update` to roll a new revision, per the ownership split in §12.2. Authenticates to Azure via the same OIDC federation as the infra pipeline (§12.5), scoped to only the roles it needs (image push, container app update) — a distinct, narrower federated credential from the infra pipeline's, not the same all-purpose principal wearing every hat.

### 12.4 Database migration pipeline

Applies versioned SQL under `migrations/views/` and `migrations/grants/` (§7.2) against `db_hr_demo`. Authenticates via Azure AD (the same OIDC-federated identity pattern, scoped to its own narrower SQL permissions — capable of the DDL/grant statements this pipeline needs, distinct from the app's read-only runtime identity). **Note:** the one-time `CREATE USER ... FROM EXTERNAL PROVIDER` bootstrap for the Container App's identity (§10.3) is done manually by a privileged Entra admin for now, deliberately kept simple — folding it into this pipeline's own automation is a later improvement, not a Phase-0.5 requirement.

### 12.5 Runtime freshness job — unchanged

A Container Apps Job (cron), detection + alerting only, no DDL, added later per §12.1 step 12.

### 12.6 GitHub Actions + OIDC (D13, no longer open)

```
GitHub Actions workflow (permissions: id-token: write)
   → OIDC token
Microsoft Entra ID (federated credential on an App Registration, subject scoped to this repo/branch/environment)
   → short-lived Azure access token
Azure (azure/login action), scoped RBAC roles per pipeline (§12.1 step 4, §12.3, §12.4)
```

No client secret in GitHub Secrets, ever. Two (or more) distinct federated-credential-backed identities are used — one for infra/app-deploy Azure RBAC, one narrower for database migrations — rather than one principal holding every permission, consistent with least privilege.

---

## 13. Phased implementation plan

**Phase 0 — architecture/reconnaissance.** See §13.2 for the explicit exit check.

**Phase 0.5 — Infrastructure as Code foundation.** The 14-step Terraform path in §12.1, now under way — see `infra/` (structure, provider config, and the `bootstrap/` state-backend configuration are written; `bootstrap/` is reviewed but not yet applied, so no real Azure resource exists from this project yet). D19 confirmed the Entra-admin prerequisite before any HCL was written.

**Phase 1 — First application vertical slice: Salaris (final, D15).** Existing tables/versioned views → semantic/query layer → FastAPI backend → browser visualization → deployed Azure environment → tests/logging/config. No LLM yet. **Prerequisite specific to this phase, not to Phase 0.5:** the salary-category canonical-definition decision (§14.2, O5) must be made *before* building the category-dependent visuals — document the variants, recommend, get your explicit choice, log the PBI-comparability impact, then build.

**Phase 2 — Verzuim + shared components**, reusing what Phase 1 proves, tackling the harder patterns (measure-switcher scatter, gradient KPI coloring, rank-based tables) once the deployment chain is de-risked.

**Phase 3 — LLM chat vertical slice.** Small approved catalog scoped to Salaris + Verzuim fields. **Turnstile (§10.6) ships alongside this, not after it** — the guardrail and the feature go live together, given the cost-exposure reasoning in §10.6.

**Phase 4 — Remaining pages/domains**, each resolving its own slice of §14's technical-debt register as it's migrated (D16) — never in bulk, never silently.

**Phase 5 — Hardening.** Front Door Standard if a real public launch is imminent (§10.7); Key Vault if a concrete secret has appeared by then (§10.4); Redis-backed rate limiting if scaled past one replica (§9); the Function App Terraform import (D7); fuller reconciliation-test coverage; broader observability — including a small, currently-missing piece: the `gpt-4o-mini` deployment's `version_upgrade_option = "OnceCurrentVersionExpired"` (§12.1/main.tf) avoids a hard break when the pinned model version is retired, but nothing actively notifies us when that swap happens — Microsoft's own advance model-retirement announcements are the only warning today, and Terraform would only surface it passively as drift on a later `plan`. Not worth dedicated tooling at this scale yet, but worth a real alert once observability gets built out.

### 13.1 First vertical slice — final

Salaris, per D15. The comparison and reasoning from the previous revision (§13.1 there) stand as the record of *why*: it proves the deployment chain's most important reusable concepts (the as-of pattern, the dimension-switcher UI pattern) without stacking that first-time infrastructure risk on top of Verzuim's heavier business logic (dual field-parameters, gradient KPI coloring, rank-window tables), which becomes Phase 2's well-scoped content instead.

### 13.2 Phase 0 exit check

Reviewed explicitly, as requested: LLM provider (resolved, contingent fallback designed, D14), first vertical slice (resolved, D15), CI/CD platform (resolved, D13), resource group strategy (resolved, D12/D18), database auth approach (resolved, prerequisite confirmed present, D19), charting library (resolved, D17), Key Vault (resolved: deferred, §10.4), Container App ownership model (resolved, Model A, §12.2), Front Door (resolved: not in v1, §10.7), technical-debt resolution process (resolved: per-domain, D16). **No open item blocks Phase 0.5** — only O5 (a Phase 1, not Phase 0.5, prerequisite) remains.

**Phase 0 is complete.**

**Phase 0.5 is under way** (see `infra/README.md` for current status): project structure, provider configuration, and the state-backend bootstrap configuration are written and reviewed; `bootstrap/` has **not** been applied yet, so this project has not created a single real Azure resource so far — that's the next checkpoint.

---

## 14. Semantic-model technical debt register — resolved per domain (D16)

Unchanged in content from the previous revision (tenure's three definitions, salary-category's two conflicting schemes, `TODAY()`-volatility, dead model parts, the confirmed non-duplicate benchmark measures) — what changes is process, now made explicit: **each conflict is resolved only when the domain/page that actually uses it is migrated**, following the same four-step method every time — document the existing variants → recommend a canonical definition with reasoning → get your explicit choice → record any impact on historical Power BI comparability. §14.2 (salary category) is the first of these to actually fire, as a named Phase 1 prerequisite (§13, O5). §14.1 (tenure) doesn't block Phase 1 — it's relevant to Profiel/Verzuim, migrated later — and stays exactly as documented until then.

---

## 15. Repository / project structure — revised

```
HR Dashboard app/
├── ARCHITECTURE.md
├── infra/                            # Terraform — flat, no modules (D5)
│   ├── bootstrap/                    # one-time remote-state-backend bootstrap (§12.1 step 2)
│   ├── providers.tf
│   ├── main.tf                       # existing RG as a data source (D12) + all new resources
│   ├── variables.tf / outputs.tf
│   └── README.md                     # what's Terraform-managed vs. existing/unmanaged — the single
│                                      #   source of truth for this; not duplicated elsewhere (see below)
├── pyproject.toml
├── .env.example                      # local-dev only (e.g. an OpenAI-direct fallback key, §10.4)
├── docker/Dockerfile
├── src/hr_dashboard/
│   ├── api/                          # FastAPI: routers, dependencies, rate-limit/abuse-guard middleware,
│   │                                 #   Turnstile verification (§8/§10.6)
│   ├── semantic/                     # catalog.py, queries.py (§7) — no measures/ Python-logic folder;
│   │                                 #   business logic lives in SQL (§7.3)
│   ├── llm/                          # client.py (provider abstraction, D11), planner.py, guardrails.py,
│   │                                 #   chart_compiler.py (library pending, §4.1a)
│   ├── db/connection.py              # Managed-Identity token-based connection (§10.3)
│   ├── config.py
│   └── templates/ + static/
├── jobs/refresh_freshness.py         # detection + alerting only (§9/§12.5)
├── tests/{unit,integration,reconciliation,e2e}/
│   └── ... + a permission-drift test (§11) comparing app_runtime_reader's grants to the catalog
├── migrations/
│   ├── views/                        # versioned `mcp` view SQL (§7.1)
│   └── grants/                       # versioned role/grant SQL, incl. the CREATE USER ... FROM EXTERNAL
│                                      #   PROVIDER step (§7.2/§10.3/§12.4)
└── .github/workflows/
    ├── infra.yml                     # fmt/validate/plan/apply, OIDC (§12.1/§12.6)
    ├── app.yml                       # lint/typecheck/tests/build/push/deploy (§12.2/§12.3)
    └── db-migrate.yml                # applies migrations/, separate OIDC identity (§12.4)
```

Documentation of existing/unmanaged Azure dependencies lives in **one place** (`infra/README.md`, cross-referenced from this document) rather than duplicated across files, per your instruction to avoid multiple sources of truth.

---

## 16. Open questions for you

1. **O5** — the salary-category canonical definition (§14.2) — needed before Phase 1's category-dependent visuals are built, not before Phase 0.5.
2. Confirm or adjust the `hrdash` naming prefix / tag scheme proposed in `infra/variables.tf` (was O4).
3. Review `infra/bootstrap/` before it's applied — the first real Azure resource this project creates.

---

## Summary of this round

**Changed:** DB auth design (Managed Identity, with its real prerequisite named), the views-vs-direct-tables boundary (pragmatic, not blanket), Key Vault (deferred out of v1), Container App image ownership (Model A, precisely scoped), the public bot-protection stack (Container Apps ingress only by default, Turnstile brought forward to Phase 3, Front Door tiered and Premium excluded), the Resource Group strategy (existing, unmanaged, tagged subset), and the Terraform learning path (reordered around all of the above, with the OIDC-bootstrap nuance and the SQL-grant/Azure-RBAC split made explicit).

**Unchanged:** the overall architecture recommendation (FastAPI + HTMX/Jinja2 + Vega-Lite), the LLM guardrail pipeline's shape, the SQL-first execution boundary, the refresh strategy (no cache in v1), and the four-pipeline CI/CD split.

**No longer open:** LLM provider direction, first vertical slice, CI/CD platform, resource-group strategy, technical-debt resolution process, charting library, Entra-admin prerequisite — all now fixed (§1.1).

**Genuinely still open:** the items in §16 — none of which block Phase 0.5's next step.

**Phase 0 is marked complete** (§13.2).

---

## 17. Post-Phase-0 implementation notes (do not reopen Phase 0)

Logged after Phase 0's close, for implementation time — none of these change a Phase 0 decision or block Phase 0.5.

1. **`BACKLOG.md` is not an automatic roadmap.** It's primarily a Power BI/data-generator backlog. Its planned English-column-rename item was checked against the live database and does **not** hold — the current, deliberate convention is English table names/technical keys with Dutch business columns, largely already in place (§7.1). Always verify the live schema before treating a backlog item as pending work; the semantic layer maps English catalog keys to Dutch display labels over the existing Dutch columns, with no rename required.
2. **Container registry choice is deferred**, not ACR-by-default — decide when the first application image is actually built (start of Phase 1), see §12.1 step 9.
3. **The Managed Identity → Azure SQL bootstrap stays manual for now**: a one-time `CREATE USER ... FROM EXTERNAL PROVIDER` by a privileged Entra admin is acceptable; automating it through the database-migration pipeline's identity is a later improvement, only once there's real recurring value (§10.3/§12.4).
4. **FastAPI is preferred, not fixed** — Flask/Django remain legitimate reconsiderations if concrete implementation requirements favor them (§4).
5. **Vega-Lite is now the default charting library (D17)** — chosen after reviewing the comparison artifact (§4.1a), a considered and explicitly reversible decision, not an exclusion of Plotly.
6. **Automated tests are part of every phase's Definition of Done**, not a hardening-phase afterthought — every phase in §13 ships with its own tests, and migrated Power BI business logic gets a reconciliation test wherever relevant (§11), starting with Phase 1.

---

## 18. Phase 0.5 progress

- ✅ Confirmed via `az`: the demo-dashboards Resource Group is **`Demo_dashboards`** (D18); a Microsoft Entra admin is already set on `srv-demo-dashboards` (D19) — the Managed Identity design in §10.3 needs no fallback.
- ✅ `infra/` written: `README.md`, `providers.tf`, `variables.tf` (proposed `hrdash` naming prefix + tags; `location` deliberately unset, D21), `main.tf` (existing-RG data source only), `outputs.tf`.
- ✅ `infra/bootstrap/` applied via `terraform init` → `fmt` → `validate` → `plan` → `apply`, all run by Laura per D22. **Two of three originally-planned resources are live**: the storage account `sthrdashtfstate` and its `tfstate` blob container, both in `Demo_dashboards`. The third (the RBAC role assignment for Entra ID auth) failed with `AuthorizationFailed` — confirmed via `az role assignment list` that the signed-in account holds only `Contributor`, which excludes `Microsoft.Authorization/roleAssignments/write`; the person who could grant more is unavailable for ~1 month.
- ✅ **D20 revised in response**: the state backend now uses the storage account's own key (auto-fetched by Terraform via `listKeys`, never hand-typed) instead of Entra ID/RBAC, for this backend specifically. The now-unneeded role assignment resource (and its supporting `azurerm_client_config` data source) were removed from `infra/bootstrap/main.tf`; `infra/providers.tf`'s backend block no longer sets `use_azuread_auth`. Flagged as a recurring risk: the same `roleAssignments/write` gap will resurface for any future role assignment this project's Terraform needs (e.g. Container App identity → Key Vault/Azure OpenAI).
- ✅ `.gitignore` added at the project root (Terraform artifacts + `.env`; `.terraform.lock.hcl` deliberately kept).
- ✅ **`infra/bootstrap/` is done.** The revised `apply` succeeded (0 added, 1 changed, 0 destroyed — `shared_access_key_enabled` and `default_to_oauth_authentication` flipped to match the key-based model). The state backend (`sthrdashtfstate` / `tfstate` container) fully exists and is usable.
- ✅ **The main configuration (`infra/`) is now initialized against remote state** — `terraform init -backend-config=...` succeeded ("Successfully configured the backend 'azurerm'!"), state lives at `sthrdashtfstate/tfstate/hr-dashboard-app.tfstate`. Its own `.terraform.lock.hcl` was created (separate from `bootstrap/`'s).
- ✅ `terraform plan` in `infra/` hit an interactive prompt for `var.location` (it has no default and isn't referenced yet, but Terraform still prompts for every declared root variable) — the trigger to actually resolve **D21** rather than type something ad hoc.
- ✅ **D21 resolved: `northeurope`.** Checked with real data, not assumption — Container Apps availability is identical in both regions; Azure OpenAI token pricing is identical in both (301 and 168 compared meters, zero differences); but Azure Container Apps' Standard consumption meters (the ones this project will actually be billed on) are **~25-30% cheaper in `northeurope`** than `westeurope` (Retail Prices API), and Log Analytics ~7.7% cheaper — a real cost difference that had been initially (wrongly) assumed away, corrected after Laura's own prior experience prompted a proper check. `northeurope` also has entirely sufficient Azure OpenAI model availability (gpt-4o, gpt-4o-mini, gpt-4.1 family) and matches `srv-demo-dashboards`'s own region. `infra/variables.tf`'s `location` now defaults to `"northeurope"`, with the full comparison recorded in its description.
- ✅ `terraform plan` in `infra/` showed the expected "Changes to Outputs" only (0 resources) on this freshly-initialized backend — applied, clean `0/0/0` baseline state confirmed.
- ✅ **First real resource added to `main.tf`: a dedicated `azurerm_log_analytics_workspace`** (`log-hrdash`, `northeurope`, `PerGB2018`, 30-day retention, 1 GB/day quota as a cost guardrail) — a hard prerequisite for the Container App Environment (next step), not optional. Deliberately a **new** workspace, not a reuse of the existing `workspace-fademohrdata` (HR-generator's own, in the separate `fademohrdata` resource group) — no cost benefit to sharing (Log Analytics bills per GB, not per workspace) and it would couple this project's observability to infrastructure it doesn't own.
- ✅ **Log Analytics workspace `log-hrdash` is live** in `Demo_dashboards`/`northeurope` (`Apply complete! Resources: 1 added, 0 changed, 0 destroyed`). D22 refined here too: once Laura's own `plan`-reading fluency was established, she applies straightforward creates directly, without waiting for a review round-trip each time — still pausing for anything showing destroy/replace, an unexpected resource count, or the first instance of a security-sensitive resource type (RBAC, Managed Identity, network settings).
- ✅ **Container App Environment (`cae-hrdash`) and a placeholder Container App (`ca-hrdash`), both live** in `Demo_dashboards`/`northeurope` — applied together in one batch per the revised D22 pace (Apply complete! Resources: 2 added, 0 changed, 0 destroyed). System-assigned Managed Identity is enabled on the Container App (no access granted to anything yet — that's still its own future step). Confirmed reachable: `https://ca-hrdash.mangofield-ec0ac9e0.northeurope.azurecontainerapps.io` serves the placeholder image's "Hello World" page, verifying the `target_port = 80` guess was correct.
- Two schema surprises hit and fixed along the way, both real provider details rather than reasoning errors: `azurerm_container_app`'s `revision_suffix` lives inside `template`, not top-level; `azurerm_container_app_environment` requires an explicit `logs_destination = "log-analytics"` alongside `log_analytics_workspace_id`. One subscription-level gate also hit: `Microsoft.App` needed `az provider register` (one-time, subscription-wide, not a Terraform-owned resource) before the Environment could be created.
- Cost review requested and done before this apply: Consumption-only environment (no `workload_profile` blocks → no Dedicated/GPU costs), no zone redundancy, minimal container size (0.25 vCPU/0.5Gi), and — the one gap found — `min_replicas`/`max_replicas` are now explicit (`0`/`1`) rather than left to an assumed default, so the placeholder scales to zero when idle. Worth a follow-up check in Cost Management once billing data exists, to confirm the Consumption-only environment isn't incurring an "Environment Management Hour" charge (that meter is believed to apply only to Dedicated workload profiles, not verified with billing data yet).
- ✅ **D23 resolved**: Azure OpenAI gets its own region (`westeurope`, `var.openai_location`), decoupled from compute (`var.location` stays `northeurope`) — triggered by wanting `gpt-4o-mini` (chosen for reliability over the cheaper `gpt-4.1-nano`) while keeping `gpt-5.6-luna` (checked: `westeurope`-only, "GenerallyAvailable" since July 2026) available as a future option. No cost trade-off — Azure OpenAI token pricing is identical in both regions.
- ✅ **`azurerm_cognitive_account.openai` + a `gpt-4o-mini` deployment written to `main.tf`** — the practical availability check from §6 done via `az cognitiveservices model list`/pricing lookups rather than assumed. Model version pinned (`2024-07-18`, checked, not guessed). **RBAC grant to the Container App's identity deliberately deferred to Phase 3** — no need to hit the same `roleAssignments/write` wall (D20) for a grant nothing uses yet.
- ✅ **`azurerm_cognitive_account.openai` (`oai-hrdash`) is live.** Its deployment failed on the first `apply` attempt (`ServiceModelDeprecating` — `gpt-4o-mini`/2024-07-18 closed to new deployments) — verified via `az cognitiveservices model list` before guessing a replacement, and confirmed cost-cheap via the Retail Prices API's unit-of-measure breakdown (GlobalStandard is pure per-token `Consumption` billing — no base/reserved-capacity fee; `capacity` is a throughput rate-limit ceiling, not a paid-for reservation). Also confirmed `version_upgrade_option = "OnceCurrentVersionExpired"` has no built-in notification when it eventually triggers (§13, Phase 5 follow-up).
- ✅ **`gpt-5.4-mini` deployment live** on `oai-hrdash`. Apply complete: 1 added, 0 changed, 0 destroyed.

**Phase 0.5's core resource list (§12.1) is now built**: existing-RG data source, Log Analytics workspace, Container App Environment, a placeholder Container App with system-assigned Managed Identity (image/revision ownership split wired in per §12.2), and Azure OpenAI with a `gpt-5.4-mini` deployment. Everything remaining in §12.1 (Key Vault, the Container Apps Job, Front Door, the Function App Terraform import) is explicitly deferred until a concrete trigger arises (§10.4/§10.7/D7) — nothing left to build speculatively right now.
