# Data sources

**This project uses public data only.** Every number comes from a U.S. federal public API. There is no patient-level, payer-file, EHR or synthetic data. The only thing taken from the project's [`CLAUDE.md`](../CLAUDE.md) is its **column names**, which label the public fact table (see [§5](#5-fact-table-and-claudemd-column-names)).

| # | Source | Publisher | Level | Used for |
|---|---|---|---|---|
| [1] | Medicaid & CHIP Child and Adult Core Set, 2021–2025 | CMS (data.medicaid.gov) | State | State Medicaid rates, national median and quartiles, **targets**, trends, state comparison |
| [2] | MIPS Group Public Reporting, PY 2024 | CMS (data.cms.gov) | Provider group | Provider-group rates and patient counts, national medians |
| [3] | Doctors and Clinicians National Downloadable File | CMS (data.cms.gov) | Clinician → group | Which groups practice in the focus state |
| [4] | PLACES: County Data, 2025 release | CDC (data.cdc.gov) | County | Screening, chronic-disease and access estimates for community campaigns |
| [5] | NPPES NPI Registry API | CMS | Provider | Optional NPI lookup and provider-supply counts |

---

## [1] Medicaid & CHIP Child and Adult Core Set

> Centers for Medicare & Medicaid Services. (2021–2026). *Child and Adult Health Care Quality Measures* [Data sets, 2021–2025 releases]. Data.Medicaid.gov. Retrieved 2026-11-01.

| Release | Dataset ID | Last modified |
|---|---|---|
| 2025 | [`14bc26c3-5584-4032-9175-f3a0399cb206`](https://data.medicaid.gov/dataset/14bc26c3-5584-4032-9175-f3a0399cb206) | 2026-09-22 |
| 2024 | [`a5023394-ab10-465b-bb4a-7de5ac98d90c`](https://data.medicaid.gov/dataset/a5023394-ab10-465b-bb4a-7de5ac98d90c) | 2025-09-22 |
| 2023 | [`e85033c7-367e-467e-9e81-8e85048102b8`](https://data.medicaid.gov/dataset/e85033c7-367e-467e-9e81-8e85048102b8) | 2025-10-09 |
| 2022 | [`dfd13757-d763-4f7a-9641-3f06ce21b4c6`](https://data.medicaid.gov/dataset/dfd13757-d763-4f7a-9641-3f06ce21b4c6) | 2023-09-11 |
| 2021 | [`a058ef78-e18b-4435-94aa-b70ab6ce5904`](https://data.medicaid.gov/dataset/a058ef78-e18b-4435-94aa-b70ab6ce5904) | 2023-09-11 |

- **Underlying analysis:** Mathematica analysis of Quality Measure Reporting (QMR) system reports (dataset `source` field)
- **License:** U.S. Public Domain
- **API:** `https://data.medicaid.gov/api/1/datastore/query/{dataset_id}/0` (no key)
- **Fields used:** `state`, `measure_abbreviation`, `rate_definition`, `state_rate`, `denominator` (2025 only), `median`, `mean`, `top_quartile`, `bottom_quartile`, `number_of_states_reporting`, `measure_type`, `methodology`, `population`, `rate_used_in_calculating_state_mean_and_median`, `notes`
- **Measures (16):** BCS-AD, CCS-AD, COL-AD, CHL-AD, CBP-AD, GSD-AD/HBD-AD, PPC2-AD/PPC-AD, AMM-AD, FUH-AD, IET-AD, W30-CH, WCV-CH, CIS-CH, IMA-CH, LSC-CH, DEV-CH. One rate per measure is selected by text match on `rate_definition` ([`config.py`](../hedis_agent/config.py)), preferring the row CMS used in the national median
- **Caveats:** state Medicaid/CHIP programs only. HEDIS-based but not NCQA HEDIS results. Specifications, age bands and reporting method (administrative / hybrid / electronic) can change by year and state. Hybrid-method denominators are chart-review samples, not member counts

## [2] CMS MIPS Group Public Reporting

> Centers for Medicare & Medicaid Services. (2026). *PY 2024 Group Public Reporting: MIPS Measures and Attestations* [Data set]. Provider Data Catalog, dataset `0ba7-2cb0`. Last modified 2026-08-24. Retrieved 2026-11-01, from https://data.cms.gov/provider-data/dataset/0ba7-2cb0

- **API:** `https://data.cms.gov/provider-data/api/1/datastore/query/0ba7-2cb0/0` (no key, 1,500 rows per page)
- **Measures:** #236 Controlling High Blood Pressure (4,589 groups nationally) · #309 Cervical Cancer Screening (2,124) · #001 HbA1c Poor Control >9% (3,721, lower is better) · #117 Diabetes Eye Exam (3,301) · #134 Depression Screening & Follow-Up (2,513)
- **Fields used:** `org_pac_id`, `facility_name`, `measure_cd`, `prf_rate`, `patient_count`, `collection_type`, `five_star_benchmark`, `star_value`
- **Caveats:** clinician-group results, mostly Medicare Part B. Related to HEDIS but not HEDIS rates. Not risk-adjusted

## [3] CMS Doctors and Clinicians National Downloadable File

> Centers for Medicare & Medicaid Services. (2026). *National Downloadable File* [Data set]. Provider Data Catalog, dataset `mj5m-pzi6`. Retrieved 2026-11-01, from https://data.cms.gov/provider-data/dataset/mj5m-pzi6

- **API:** query by distribution ID (`/datastore/query/{distribution_id}`); the dataset-ID endpoint returns HTTP 403
- **Fields used:** `npi`, `org_pac_id`, `facility_name`, `citytown`, `state`, `num_org_mem`
- **Rule:** a group from [2] is kept as in-state only if **at least 50% of its clinicians** have a practice address in the focus state. Multi-state systems report national patient counts, which would overstate in-state need. The number excluded is reported as a data-quality check

## [4] CDC PLACES county data

> Centers for Disease Control and Prevention. (2026). *PLACES: County Data (GIS Friendly Format), 2025 release* [Data set]. Data.CDC.gov, dataset `i46a-9kgh`. Last modified 2026-09-22. Retrieved 2026-11-01, from https://data.cdc.gov/d/i46a-9kgh

- **API:** `https://data.cdc.gov/resource/i46a-9kgh.json?stateabbr=OH` (Socrata, no key)
- **Fields used:** `countyname`, `countyfips`, `totalpop18plus`, and crude prevalence + 95% CI for `colon_screen`, `mammouse`, `checkup`, `bpmed`, `access2`, `diabetes`, `bphigh`, `depression`
- **Caveats:** model-based small-area estimates from BRFSS survey data, for all adults regardless of insurance. Not HEDIS rates; used for *where to focus*, not performance. Wide confidence intervals are flagged

## [5] NPPES NPI Registry

> Centers for Medicare & Medicaid Services. (2026). *NPPES NPI Registry API* (v2.1). Retrieved 2026-11-01, from https://npiregistry.cms.hhs.gov/registry/help-api

- **Used for:** `python -m hedis_agent npi <NPI>` lookups and primary-care provider counts. Returns at most 1,200 results per query

---

## 5. Fact table and CLAUDE.md column names

`python -m hedis_agent build` writes `data/public/hedis_public_facts_<STATE>.csv`: one row per state × measure × year (Core Set), provider group × measure (CMS) and county × indicator (PLACES). The analytics engine reads only this table.

| Column | From CLAUDE.md? | Meaning in the public data |
|---|:-:|---|
| `MeasureCode`, `MeasureName`, `HEDISCode`, `MeasureCategory`, `MeasureGroup` | ✓ | Measure identity (`HEDISCode` = Core Set or MIPS code) |
| `PayerName`, `LineOfBusiness` | ✓ | e.g. "Ohio Medicaid & CHIP" / Medicaid; "Medicare (MIPS)" / Medicare; "All payers (community)" |
| `ProviderId`, `ProviderName`, `DepartmentName` | ✓ | CMS group PAC ID, group name, cities (county name for PLACES) |
| `MeasurementYear`, `AsOfDate`, `SourceRunDate`, `ReportDate`, `RuleVersion`, `RunId`, `BuildId`, `BaseKey` | ✓ | Release year, fetch date, source last-modified date, build date, measure version, run IDs, unique key |
| `Source`, `Level`, `Geography`, `Rate`, `Denominator`, `HigherIsBetter`, `PeerMedian`, `PeerTopQuartile`, `PeerBottomQuartile`, `PeerCount`, `Methodology`, `RateDefinition`, `CILow`, `CIHigh`, `AdultPopulation`, `Notes` | — | Public-data fields with no CLAUDE.md equivalent |

The CLAUDE.md patient columns (`PatientIdentityKey`, `PAT_MRN_ID`, `Member_ID`, names, `DOB`, `PayerStatus`, `EpicStatus`, …) are **not** used: public data has no patients. The agent says so when asked patient-level questions.

## 6. Not data: model settings

Priority and campaign weights in [`analytics.py`](../hedis_agent/analytics.py) are logic, not facts, and are labeled *"Illustrative prioritization model — weights require business approval."*

## 7. Trademarks

HEDIS® is a registered trademark of the National Committee for Quality Assurance (NCQA). This project is independent and does not use or redistribute NCQA specifications or results.
