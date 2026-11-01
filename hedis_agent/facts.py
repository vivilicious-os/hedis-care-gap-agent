"""Build one fact table from the public API caches.

Column names follow CLAUDE.md §2 wherever one fits (MeasureCode, PayerName,
LineOfBusiness, ProviderId, ProviderName, DepartmentName, MeasurementYear,
AsOfDate, SourceRunDate, RuleVersion, BaseKey, ...). Columns CLAUDE.md does
not define (Rate, Denominator, PeerMedian, ...) describe the public data.
Every row comes from a public API; there are no patient-level rows.
"""
from __future__ import annotations

import csv
from datetime import date

from . import cms, medicaid, places
from .config import (CORE_SET_MEASURES, FACTS_FILE, FOCUS_STATE, FOCUS_STATE_NAME, MIPS_MEASURES,
                     PLACES_INDICATORS)

COLUMNS = [
    # CLAUDE.md column names
    "RunId", "BuildId", "AsOfDate", "SourceRunDate", "ReportDate", "RuleVersion", "MeasurementYear",
    "MeasureCode", "MeasureName", "HEDISCode", "MeasureCategory", "MeasureGroup",
    "PayerName", "LineOfBusiness", "ProviderId", "ProviderName", "DepartmentName", "BaseKey",
    # public-data columns
    "Source", "Level", "Geography", "Rate", "Denominator", "HigherIsBetter",
    "PeerMedian", "PeerTopQuartile", "PeerBottomQuartile", "PeerCount",
    "Methodology", "RateDefinition", "CILow", "CIHigh", "AdultPopulation", "Notes",
]


def build() -> dict:
    today = date.today().isoformat()
    run = f"PUBLIC-{today}"
    rows = []
    med = medicaid.load()
    if med:
        mod = {r["year"]: (r.get("modified") or "")[:10] for r in med["releases"]}
        for r in med["rows"]:
            m = CORE_SET_MEASURES[r["code"]]
            rows.append({
                "RunId": run, "BuildId": "medicaid-core-set", "AsOfDate": med["fetched"],
                "SourceRunDate": mod.get(r["year"], ""), "ReportDate": today, "RuleVersion": r["abbr"],
                "MeasurementYear": r["year"], "MeasureCode": r["code"], "MeasureName": m["name"],
                "HEDISCode": r["abbr"].split("-")[0], "MeasureCategory": m["category"], "MeasureGroup": m["group"],
                "PayerName": f"{r['state']} Medicaid & CHIP", "LineOfBusiness": "Medicaid",
                "ProviderId": "", "ProviderName": "", "DepartmentName": "",
                "BaseKey": f"{r['state']}|{r['code']}|{r['year']}",
                "Source": "Medicaid Core Set", "Level": "State", "Geography": r["state"],
                "Rate": r["rate"], "Denominator": r["denominator"], "HigherIsBetter": r["higher_is_better"],
                "PeerMedian": r["median"], "PeerTopQuartile": r["top_quartile"],
                "PeerBottomQuartile": r["bottom_quartile"], "PeerCount": r["states_reporting"],
                "Methodology": r["methodology"], "RateDefinition": r["definition"], "CILow": "", "CIHigh": "",
                "AdultPopulation": "", "Notes": r["notes"] if r["rate"] is not None else f"Not reported ({r['rate_raw']})",
            })
    nat, grp = cms.load_national(), cms.load_groups()
    if nat and grp:
        for code, groups in grp["measures"].items():
            m, n = MIPS_MEASURES[code], nat["measures"].get(code, {})
            for g in groups:
                rows.append({
                    "RunId": run, "BuildId": "cms-mips-groups", "AsOfDate": grp["fetched"],
                    "SourceRunDate": (nat.get("modified") or "")[:10], "ReportDate": today,
                    "RuleVersion": m["measure_cd"], "MeasurementYear": 2024, "MeasureCode": code,
                    "MeasureName": m["name"], "HEDISCode": code, "MeasureCategory": "Clinician group quality",
                    "MeasureGroup": "MIPS", "PayerName": "Medicare (MIPS)", "LineOfBusiness": "Medicare",
                    "ProviderId": g["org_pac_id"], "ProviderName": g["name"],
                    "DepartmentName": ", ".join(g.get("cities", [])), "BaseKey": f"{g['org_pac_id']}|{code}|2024",
                    "Source": "CMS MIPS", "Level": "ProviderGroup", "Geography": FOCUS_STATE_NAME,
                    "Rate": g["rate"], "Denominator": g["patients"], "HigherIsBetter": m["higher_is_better"],
                    "PeerMedian": n.get("median"), "PeerTopQuartile": n.get("p75") if m["higher_is_better"] else n.get("p25"),
                    "PeerBottomQuartile": n.get("p25") if m["higher_is_better"] else n.get("p75"),
                    "PeerCount": n.get("groups"), "Methodology": g.get("collection_type"),
                    "RateDefinition": m["name"], "CILow": "", "CIHigh": "", "AdultPopulation": "",
                    "Notes": f"{g.get('clinicians', 0)} clinicians",
                })
    pl = places.load()
    if pl:
        for c in pl["counties"]:
            for key, ind in c["indicators"].items():
                meta = PLACES_INDICATORS[key]
                rows.append({
                    "RunId": run, "BuildId": "cdc-places", "AsOfDate": pl["fetched"],
                    "SourceRunDate": pl.get("modified", ""), "ReportDate": today,
                    "RuleVersion": f"PLACES {pl['release_year']}", "MeasurementYear": pl["release_year"],
                    "MeasureCode": key.upper(), "MeasureName": meta["name"], "HEDISCode": "",
                    "MeasureCategory": f"Community {meta['kind']}", "MeasureGroup": "CDC PLACES",
                    "PayerName": "All payers (community)", "LineOfBusiness": "Community (all adults)",
                    "ProviderId": "", "ProviderName": "", "DepartmentName": c["county"],
                    "BaseKey": f"{c['fips']}|{key.upper()}|{pl['release_year']}",
                    "Source": "CDC PLACES", "Level": "County", "Geography": f"{c['county']} County",
                    "Rate": ind["crude"], "Denominator": "", "HigherIsBetter": meta["higher_is_better"],
                    "PeerMedian": "", "PeerTopQuartile": "", "PeerBottomQuartile": "", "PeerCount": "",
                    "Methodology": "Model-based estimate (BRFSS)", "RateDefinition": meta["name"],
                    "CILow": ind["ci_low"], "CIHigh": ind["ci_high"], "AdultPopulation": c["adults"], "Notes": "",
                })
    FACTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(FACTS_FILE, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return {"path": str(FACTS_FILE), "rows": len(rows), "state": FOCUS_STATE}


def load(path=FACTS_FILE) -> list[dict]:
    def num(x):
        try:
            return float(x) if x not in ("", None) else None
        except ValueError:
            return None
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in ("Rate", "Denominator", "PeerMedian", "PeerTopQuartile", "PeerBottomQuartile", "PeerCount",
                  "CILow", "CIHigh", "AdultPopulation"):
            r[k] = num(r[k])
        r["MeasurementYear"] = int(r["MeasurementYear"]) if r["MeasurementYear"] else None
        r["HigherIsBetter"] = r["HigherIsBetter"] == "True"
    return rows
