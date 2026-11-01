# Methodology

How the agent turns public data into priorities. The reasoning rules come from [`CLAUDE.md`](../CLAUDE.md), applied at the levels public data supports: **state Medicaid program, provider group, county**. All code is in [`analytics.py`](../hedis_agent/analytics.py).

## 1. Measure performance (state Medicaid)

For each of 16 HEDIS-based Core Set measures, using the latest release with data:

| Field | Definition |
|---|---|
| Rate | The focus state's published `state_rate` |
| Denominator | Published `denominator` (2025 release only). Shown with every rate, e.g. `49.9% (533,181 / 1,068,498)` |
| Median, top / bottom quartile | National statistics across reporting states, as published by CMS |
| Rank | 1 + number of states doing better (direction-aware for lower-is-better measures) |
| Status | Top quartile · Above median · Below median · Bottom quartile · Not reported |
| **Target** | **Top-quartile state rate** (public), labeled with its source on every view |
| Gap to target | Points below the top quartile (0 if at or above) |
| Members to target | ⌈denominator × gap ÷ 100⌉, **only** for administrative/electronic rates. Hybrid-method denominators are chart-review samples, so no member count is estimated |

## 2. Measure priority (illustrative)

```
score = 35 × gap to top quartile ÷ largest gap
      + 30 × members to top quartile ÷ largest
      + 20 if below the national median
      + 15 if the trend is moving the wrong way
```

Not-reported measures score 0 and are listed as data gaps.

## 3. Trends and root cause

For each measure, the state's rate and the national median in every release from 2021 to 2025:

- **Change** = latest rate − first rate
- **vs. national trend** = state change − median change. This separates the state's own progress from a nationwide shift
- **Comparability notes** flag re-specification (e.g. HBD-AD → GSD-AD, PPC-AD → PPC2-AD) and reporting-method changes (e.g. hybrid → administrative). Following CLAUDE.md §13–14, a change that coincides with one of these is not read as real improvement or decline

## 4. State comparison

Latest rate for every state on every measure, drawn as a strip of dots with the focus state highlighted and the median marked.

## 5. Provider groups (CMS MIPS)

- Groups are kept only if **≥ 50%** of their clinicians practice in the focus state (see [data sources](data-sources.md#3-cms-doctors-and-clinicians-national-downloadable-file))
- **Patients not meeting** = patients × (100 − rate) ÷ 100, or patients × rate ÷ 100 for inverse measures (#001)
- **State rate** = patient-weighted rate across in-state groups
- **Flags:** *High volume + worse than national median* (patients ≥ median group size); *Small denominator (<20)*
- Signals describe opportunity size, not provider quality; results are not risk-adjusted

## 6. Communities (CDC PLACES)

- County indicators are colored by distance from the **state's county median** (direction-aware)
- **Estimated adults affected** = adult population × prevalence (diabetes, high blood pressure) or × (100 − rate) (no checkup)

## 7. Campaigns (illustrative)

Three kinds, each built only from public data:

| Kind | Built from | Size |
|---|---|---|
| Statewide Medicaid | Measures below the top quartile with a member denominator | Members needed to reach the top quartile |
| Community | The 5 largest counties worse than the county median on an indicator | Estimated adults affected |
| Provider partnership | The 3 largest in-state groups worse than the national median (≥ 20 patients) | Patients not meeting the measure |

Score = 60% × √(size ÷ largest size of the same kind) + 40% × kind weight (Statewide 1.0 · Community 0.9 · Provider 0.8). Sizes are compared only within a kind, and **no response rates are assumed**.

## 8. Data-quality checks (public sources)

Measures not reported by the state · measures with fewer than 40 reporting states · hybrid-method rates · re-specified or re-methoded measures · rates without denominators · multi-state groups excluded · groups with fewer than 20 patients · county estimates with a 95% CI wider than 10 points · sources not updated in 400+ days.

## 9. Not available in public data

Following CLAUDE.md §18, these are answered with *"This information is not available in the supplied public data"* plus what's needed: individual patients · payer-vs-EHR reconciliation · commercial and Medicare Advantage plan HEDIS rates · contract targets and incentive dollars · your own providers and clinics.

## 10. The agent

- **Model:** `claude-opus-5-5`, adaptive thinking, effort `medium`
- **System prompt:** `CLAUDE.md` plus a public-data deployment note (no patient/payer/EHR data; quote target sources; never convert hybrid samples to members)
- **12 tools:** `executive_summary`, `measures`, `trend`, `state_comparison`, `provider_groups`, `counties`, `campaigns`, `daily_plan`, `data_quality`, `data_sources`, `not_available`, `lookup_npi`
- **Loop:** call tools → return all results together → repeat (max 12 rounds). Numbers always come from tools
