# Build guide: recreate the HEDIS Public Intelligence Agent

Everything you need to rebuild this project from an empty folder: the public data it's fed, how each piece is built, and a **checkpoint** after each step.

- **Just run it:** [Path A](#path-a-run-this-repo) (4 commands)
- **Rebuild it yourself:** [Path B](#path-b-rebuild-it-step-by-step) (9 steps)
- **Another state:** set `HEDIS_STATE=TX` (any two-letter code) before `refresh`

Related: [Methodology](methodology.md) (formulas) · [Data sources](data-sources.md) (citations)

---

## Prerequisites

| Need | Why |
|---|---|
| Python 3.10+ | Everything is Python; the core uses only the standard library |
| Internet | Only to refresh public data (cached copies are committed in `data/public/`) |
| Anthropic API key *(optional)* | Only for the agent chat |

## Path A: Run this repo

```bash
git clone https://github.com/vivilicious-os/hedis-care-gap-agent.git
cd hedis-care-gap-agent
python3 -m venv .venv && source .venv/bin/activate
python -m hedis_agent serve            # http://localhost:8000 (uses cached public data)
```

Agent chat:

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python -m hedis_agent ask "How is Ohio doing?"
```

**Checkpoint:** the dashboard header reads *Ohio · Core Set 2025*, and the brief says *15 of 16 tracked HEDIS-based measures*.

---

## Path B: Rebuild it step by step

### Step 1: Write the rules (`CLAUDE.md`)

[`CLAUDE.md`](../CLAUDE.md) describes how a value-based-care HEDIS analyst should reason: show denominators, rank on more than lowest rate, separate data quality from performance, distinguish real improvement from denominator or specification changes, **never invent targets or benchmarks**, and answer as *Observation → Why it matters → Action*. It becomes the agent's system prompt in Step 7. Its §2 column names label the fact table in Step 3.

### Step 2: Pull the public data

```bash
python -m hedis_agent refresh          # ~10 minutes; most of it is the CMS clinician directory
```

| Source | Call | Saved to |
|---|---|---|
| Medicaid Core Set, last 5 releases, all states | `data.medicaid.gov/api/1/datastore/query/{id}/0?conditions[0][property]=measure_abbreviation&conditions[0][value]=CBP-AD` | `data/public/medicaid_core_set.json` |
| CMS MIPS group results (5 measures) | `data.cms.gov/provider-data/api/1/datastore/query/0ba7-2cb0/0?conditions[0][property]=measure_cd&conditions[0][value]=MIPS_GRP_236_overall` | `data/public/cms_mips_national.json` |
| CMS clinician directory (focus state) | `data.cms.gov/provider-data/api/1/datastore/query/{distribution_id}?conditions[0][property]=state&conditions[0][value]=OH` | joined into `data/public/cms_mips_groups_OH.json` |
| CDC PLACES counties | `data.cdc.gov/resource/i46a-9kgh.json?stateabbr=OH` | `data/public/cdc_places_counties_OH.json` |
| NPPES (optional) | `npiregistry.cms.hhs.gov/api/?version=2.1&...` | `data/public/nppes_provider_supply.json` |

Clients: [`medicaid.py`](../hedis_agent/medicaid.py), [`cms.py`](../hedis_agent/cms.py), [`places.py`](../hedis_agent/places.py), [`nppes.py`](../hedis_agent/nppes.py). The measure list and the text used to pick one rate per measure are in [`config.py`](../hedis_agent/config.py).

**Checkpoint:** five `Core Set <year>: N rows` lines (2021–2025), clinician-directory progress lines, then a fact-table summary.

> **Gotchas:** CMS returns 403 for some bare user-agents (include a URL in yours) and for the clinician file's dataset-ID endpoint (query its distribution ID instead). python.org builds of Python on macOS may lack CA certificates; the HTTP helper falls back to the system bundle with verification on. Hybrid-method Core Set denominators are samples. Only the 2025 Core Set publishes denominators.

### Step 3: Build the fact table

```bash
python -m hedis_agent build
```

[`facts.py`](../hedis_agent/facts.py) merges the caches into `data/public/hedis_public_facts_OH.csv`, one row per state × measure × year, provider group × measure, and county × indicator. Columns use the CLAUDE.md names (`MeasureCode`, `PayerName`, `LineOfBusiness`, `ProviderId`, `ProviderName`, `DepartmentName`, `MeasurementYear`, `AsOfDate`, `SourceRunDate`, `RuleVersion`, `BaseKey`, …) plus public-data fields (`Rate`, `Denominator`, `PeerMedian`, `PeerTopQuartile`, `CILow`, …). Full column map: [data sources §5](data-sources.md#5-fact-table-and-claudemd-column-names).

**Checkpoint:** about 3,900 rows from three sources (`Medicaid Core Set`, `CMS MIPS`, `CDC PLACES`) and no patient columns.

### Step 4: Analytics

[`analytics.py`](../hedis_agent/analytics.py), class `PublicAnalyzer`, built in this order:

| Method | Does |
|---|---|
| `measures` | State rate vs. median and quartiles, rank, status, target (top quartile), members to target, trend, priority |
| `trend` / `trends` | 2021–2025 series vs. national median, with re-specification and method-change notes |
| `state_grid` | Every state's latest rate per measure |
| `providers` | In-state CMS groups: rate, patients, patients not meeting, flags |
| `counties_table` | PLACES indicators, county medians, estimated adults affected |
| `campaigns` | Statewide, community and provider-partnership campaigns, ranked |
| `data_quality` | Checks on the public sources |
| `executive_summary` / `headline` / `daily_plan` | The morning brief |

```bash
python -m hedis_agent summary
python -m hedis_agent measures
python -m hedis_agent campaigns
python -m hedis_agent quality
```

**Checkpoint:** `summary` lists CCS and IET in the top quartile and WCV and DEV below the median; `quality` flags COL as not reported by Ohio.

### Step 5: Dashboard

[`server.py`](../hedis_agent/server.py) (standard-library server, localhost only) serves [`web/dashboard.html`](../hedis_agent/web/dashboard.html): brief, measures, 5-year trends, state comparison, counties, provider groups, campaigns, data quality, not-available, sources.

```bash
python -m hedis_agent serve
python -m hedis_agent site            # static copy (chat off) → docs/index.html
```

### Step 6: Daily run

```bash
python -m hedis_agent morning          # refresh → build → report → static dashboard → dated brief
0 6 * * 1-5 cd /path/to/repo && .venv/bin/python -m hedis_agent morning   # crontab line
```

### Step 7: The Claude agent

[`agent.py`](../hedis_agent/agent.py):

- **System prompt:** `CLAUDE.md` + a deployment note: public data only, focus state, quote target sources, never convert hybrid samples to members, and say "not available in the supplied public data" for patient, payer-vs-EHR, plan or contract questions
- **12 tools**, each wrapping one analytics method
- **Loop:**

```python
resp = client.beta.messages.create(
    model="claude-opus-5-5", max_tokens=16000, system=system, tools=TOOLS, messages=messages,
    thinking={"type": "adaptive"}, output_config={"effort": "medium"},
    betas=["server-side-fallback-2026-07-01"], fallbacks="default")
# stop_reason == "tool_use": run every requested tool, send all results in one message, repeat (max 12)
```

**What the model sees:** the system prompt, the question, and JSON tool results. Nothing else.

### Step 8: Test

```bash
python -m unittest discover -s tests -v
```

**Checkpoint:** 8 tests pass. They check that the fact table uses the CLAUDE.md names with no patient fields, that ranks and targets are consistent, that hybrid samples are never turned into member counts, the trend math, that provider groups are in-state only, campaign ranking, that every agent tool runs offline, and that the static page embeds data safely.

### Step 9: Publish (optional)

```bash
gh repo create <you>/hedis-public-intelligence --public --source . --push
```

GitHub Pages: Settings → Pages → `main` / `/docs` serves the static dashboard.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `CERTIFICATE_VERIFY_FAILED` | `pip install certifi`, or run Python's `Install Certificates.command` |
| CMS `HTTP 403` | User-agent must include a URL; use the distribution ID for the clinician file |
| `refresh` fails offline | Cached copies in `data/public/` keep everything working |
| A measure shows "Not reported" | The state didn't report it to CMS that year; it's listed under data quality |
| Chat says "Set ANTHROPIC_API_KEY" | Install requirements, export the key, restart `serve` |
