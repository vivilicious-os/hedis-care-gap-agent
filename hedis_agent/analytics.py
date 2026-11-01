"""HEDIS intelligence on public data only.

Reads the public fact table (facts.py) and answers the CLAUDE.md questions at
the levels public data supports: state Medicaid program, provider group and
county. Patient-level questions are answered with "not available in public
data" and the data that would be needed.
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import date

from . import cms, medicaid, places
from .config import (CORE_SET_MEASURES, FOCUS_STATE, FOCUS_STATE_NAME, MIPS_MEASURES, PLACES_INDICATORS,
                     PRIORITY_DISCLAIMER, STALE_DAYS)
from .facts import load as load_facts


def fmt_n(x) -> str:
    return "n/a" if x is None else f"{int(round(x)):,}"


NOT_AVAILABLE = [
    {"question": "Which individual patients should we contact?",
     "why": "Public data has no patient-level records.",
     "needs": "Patient-level gap extract (PatientIdentityKey, MeasureCode, PayerStatus, EpicStatus, LastVisitDate, ...)"},
    {"question": "Which gaps are closed in Epic but still open with the payer?",
     "why": "Payer and EHR gap statuses are not published.", "needs": "PayerStatus and EpicStatus per patient-measure"},
    {"question": "How are commercial and Medicare Advantage HEDIS rates performing?",
     "why": "Plan-level HEDIS results (NCQA Quality Compass) are licensed, not a public API.",
     "needs": "Plan HEDIS results or your own payer reports"},
    {"question": "What are our contract targets and incentive dollars?",
     "why": "Contract terms are private.", "needs": "Payer contract targets and incentive schedules"},
    {"question": "Which of our own providers and clinics are behind?",
     "why": "Public data covers provider groups that report to CMS MIPS, not your attribution.",
     "needs": "Your attribution (ProviderId, DepartmentName) joined to your gap data"},
]


class PublicAnalyzer:
    def __init__(self, rows: list[dict] | None = None):
        self.rows = rows if rows is not None else load_facts()
        self.state = FOCUS_STATE_NAME
        self.medicaid = [r for r in self.rows if r["Level"] == "State"]
        self.groups = [r for r in self.rows if r["Level"] == "ProviderGroup"]
        self.counties = [r for r in self.rows if r["Level"] == "County"]
        self.years = sorted({r["MeasurementYear"] for r in self.medicaid})
        self.latest = self.years[-1] if self.years else None
        self.as_of = max((r["AsOfDate"] for r in self.rows), default="")
        self._measures = None

    # ------------------------------------------------------------ Medicaid measures
    def _year_rows(self, year: int, code: str) -> list[dict]:
        return [r for r in self.medicaid if r["MeasurementYear"] == year and r["MeasureCode"] == code]

    def _focus(self, year: int, code: str) -> dict | None:
        return next((r for r in self._year_rows(year, code) if r["Geography"] == self.state), None)

    def measures(self) -> list[dict]:
        """The focus state's latest Medicaid rate per measure, compared with all states."""
        if self._measures is not None:
            return self._measures
        out = []
        for code, meta in CORE_SET_MEASURES.items():
            year = max((r["MeasurementYear"] for r in self.medicaid if r["MeasureCode"] == code), default=None)
            if year is None:
                continue
            f = self._focus(year, code)
            peers = [r for r in self._year_rows(year, code) if r["Rate"] is not None]
            ref = peers[0] if peers else None
            hib = ref["HigherIsBetter"] if ref else True
            row = {"measure": code, "name": meta["name"], "category": meta["category"], "group": meta["group"],
                   "program": meta["program"], "year": year, "higher_is_better": hib,
                   "median": ref["PeerMedian"] if ref else None,
                   "top_quartile": ref["PeerTopQuartile"] if ref else None,
                   "bottom_quartile": ref["PeerBottomQuartile"] if ref else None,
                   "states_reporting": int(ref["PeerCount"] or 0) if ref else 0,
                   "definition": (f or ref or {}).get("RateDefinition", ""),
                   "methodology": (f or {}).get("Methodology", ""), "abbr": (f or ref or {}).get("RuleVersion", "")}
            if not f or f["Rate"] is None:
                row.update(rate=None, reported=False, status=f"Not reported by {self.state}",
                           target=row["top_quartile"], target_source="Public: top-quartile state rate")
                out.append(row)
                continue
            rate, den = f["Rate"], f["Denominator"]
            sample = "hybrid" in (f["Methodology"] or "").lower()
            better = lambda a, b: a > b if hib else a < b  # noqa: E731
            rank = sum(1 for p in peers if better(p["Rate"], rate)) + 1
            tq, med, bq = row["top_quartile"], row["median"], row["bottom_quartile"]
            gap_tq = None if tq is None else round(max((tq - rate) if hib else (rate - tq), 0), 1)
            row.update(rate=rate, reported=True, denominator=den, rank=rank, of=len(peers),
                       vs_median=round(rate - med, 1) if med is not None else None,
                       target=tq, target_source=f"Public: top-quartile state rate, {year} Core Set ({len(peers)} states)",
                       gap_to_top_quartile=gap_tq,
                       sample_denominator=sample,
                       rate_display=(f"{rate:.1f}% (hybrid sample of {fmt_n(den)} records)" if den and sample else
                                     f"{rate:.1f}% ({fmt_n(den * rate / 100)} / {fmt_n(den)})" if den
                                     else f"{rate:.1f}% (denominator not published)"),
                       members_to_top_quartile=(None if sample or not den else
                                                (math.ceil(den * gap_tq / 100) if gap_tq else 0)),
                       members_not_meeting=(round(den * ((100 - rate) if hib else rate) / 100)
                                            if den and not sample else None))
            if tq is not None and not better(tq, rate):
                row["status"] = "Top quartile"
            elif med is not None and not better(med, rate):
                row["status"] = "Above median"
            elif bq is not None and not better(rate, bq):
                row["status"] = "Bottom quartile"
            else:
                row["status"] = "Below median"
            t = self.trend(code)
            row["trend_pts"], row["trend_span"] = t.get("change_pts"), t.get("span")
            out.append(row)
        self._measures = self._prioritize(out)
        return self._measures

    @staticmethod
    def _prioritize(rows: list[dict]) -> list[dict]:
        """Illustrative: 35 gap to top quartile + 30 members affected + 20 below median + 15 worsening trend."""
        rep = [r for r in rows if r["reported"]]
        max_gap = max((r["gap_to_top_quartile"] or 0 for r in rep), default=0) or 1
        max_n = max((r["members_to_top_quartile"] or 0 for r in rep), default=0) or 1
        for r in rows:
            if not r["reported"]:
                r["priority_score"] = 0
                r["reasons"] = [f"not reported by {FOCUS_STATE_NAME}, so it cannot be tracked publicly"]
                continue
            hib = r["higher_is_better"]
            below_med = (r["vs_median"] or 0) < 0 if hib else (r["vs_median"] or 0) > 0
            worse = (r.get("trend_pts") or 0) < 0 if hib else (r.get("trend_pts") or 0) > 0
            r["priority_score"] = round(35 * (r["gap_to_top_quartile"] or 0) / max_gap
                                        + 30 * (r["members_to_top_quartile"] or 0) / max_n
                                        + 20 * below_med + 15 * worse, 1)
            reasons = [f"{r['status'].lower()} (#{r['rank']} of {r['of']} states)"]
            if r["gap_to_top_quartile"]:
                reasons.append(f"{r['gap_to_top_quartile']} pts below the top quartile")
            if r["members_to_top_quartile"]:
                reasons.append(f"~{r['members_to_top_quartile']:,} more members needed to reach it")
            elif r.get("sample_denominator") and r["gap_to_top_quartile"]:
                reasons.append("member count not estimable (hybrid sample)")
            if r.get("trend_pts") is not None:
                reasons.append(f"{r['trend_pts']:+.1f} pts over {r['trend_span']}")
            r["reasons"] = reasons
        rows.sort(key=lambda r: (-r["priority_score"], r["measure"]))
        for i, r in enumerate(rows, 1):
            r["rank_priority"] = i
        return rows

    # ------------------------------------------------------------ trend
    def trend(self, code: str) -> dict:
        pts = []
        for y in self.years:
            f, peers = self._focus(y, code), self._year_rows(y, code)
            med = peers[0]["PeerMedian"] if peers else None
            if f is not None or med is not None:
                pts.append({"year": y, "rate": f["Rate"] if f else None, "median": med,
                            "top_quartile": peers[0]["PeerTopQuartile"] if peers else None,
                            "abbr": (f or (peers[0] if peers else {})).get("RuleVersion", ""),
                            "methodology": f["Methodology"] if f else ""})
        rated = [p for p in pts if p["rate"] is not None]
        out = {"measure": code, "name": CORE_SET_MEASURES[code]["name"], "points": pts, "comparability_notes": []}
        if len(rated) >= 2:
            a, b = rated[0], rated[-1]
            out.update(change_pts=round(b["rate"] - a["rate"], 1), span=f"{a['year']}–{b['year']}")
            if a["median"] is not None and b["median"] is not None:
                out["median_change_pts"] = round(b["median"] - a["median"], 1)
                out["vs_national_trend_pts"] = round(out["change_pts"] - out["median_change_pts"], 1)
            if len({p["abbr"] for p in rated}) > 1:
                out["comparability_notes"].append(
                    "re-specified: " + " → ".join(dict.fromkeys(p["abbr"] for p in rated)))
            meths = list(dict.fromkeys(p["methodology"] for p in rated if p["methodology"]))
            if len(meths) > 1:
                out["comparability_notes"].append("reporting method changed: " + " → ".join(meths))
        return out

    def trends(self) -> list[dict]:
        return [self.trend(c) for c in CORE_SET_MEASURES]

    # ------------------------------------------------------------ state comparison
    def state_grid(self) -> dict:
        codes = [c for c in CORE_SET_MEASURES if any(r["MeasureCode"] == c for r in self.medicaid)]
        latest = {c: max(r["MeasurementYear"] for r in self.medicaid if r["MeasureCode"] == c) for c in codes}
        grid = defaultdict(dict)
        for c in codes:
            for r in self._year_rows(latest[c], c):
                if r["Rate"] is not None:
                    grid[r["Geography"]][c] = {"rate": r["Rate"], "median": r["PeerMedian"],
                                               "higher_is_better": r["HigherIsBetter"]}
        states = sorted(grid, key=lambda s: (s != self.state, s))
        return {"measures": codes, "years": latest, "focus": self.state,
                "states": [{"state": s, "cells": grid[s]} for s in states]}

    # ------------------------------------------------------------ provider groups
    def providers(self, top: int = 12) -> dict:
        out = {}
        for code, meta in MIPS_MEASURES.items():
            rows = [r for r in self.groups if r["MeasureCode"] == code and r["Rate"] is not None]
            if not rows:
                continue
            med, hib = rows[0]["PeerMedian"], meta["higher_is_better"]
            items = []
            for r in rows:
                n = int(r["Denominator"] or 0)
                unmet = n * ((100 - r["Rate"]) if hib else r["Rate"]) / 100
                items.append({"provider_id": r["ProviderId"], "provider": r["ProviderName"].title(),
                              "cities": r["DepartmentName"], "rate": r["Rate"], "patients": n,
                              "patients_not_meeting": round(unmet),
                              "worse_than_national_median": (r["Rate"] < med) if hib else (r["Rate"] > med),
                              "collection_type": r["Methodology"], "clinicians": r["Notes"]})
            items.sort(key=lambda x: -x["patients_not_meeting"])
            vol = statistics.median([i["patients"] for i in items])
            for i in items:
                i["flags"] = (["High volume + worse than national median"]
                              if i["patients"] >= vol and i["worse_than_national_median"] else [])
                if i["patients"] < 20:
                    i["flags"].append("Small denominator (<20)")
            tot = sum(i["patients"] for i in items)
            out[code] = {"measure": code, "name": meta["name"], "higher_is_better": hib, "groups": len(items),
                         "patients": tot, "national_median": med,
                         "state_patient_weighted_rate": round(sum(i["rate"] * i["patients"] for i in items) / tot, 1)
                         if tot else None,
                         "patients_not_meeting": sum(i["patients_not_meeting"] for i in items),
                         "worse_than_median_groups": sum(1 for i in items if i["worse_than_national_median"]),
                         "top": items[:top]}
        return {"note": "CMS MIPS clinician-group results (mostly Medicare Part B), PY 2024. Signals describe "
                        "opportunity size, not provider quality; results are not risk-adjusted.", "measures": out}

    # ------------------------------------------------------------ counties
    def counties_table(self) -> dict:
        by, pop = defaultdict(dict), {}
        for r in self.counties:
            by[r["DepartmentName"]][r["MeasureCode"].lower()] = r["Rate"]
            pop[r["DepartmentName"]] = r["AdultPopulation"] or 0
        names = sorted(by, key=lambda c: -pop[c])
        med = {}
        for k in PLACES_INDICATORS:
            vals = [by[c][k] for c in names if by[c].get(k) is not None]
            if vals:
                med[k] = round(statistics.median(vals), 1)
        rows = []
        for c in names:
            ind, adults = by[c], int(pop[c])
            rows.append({"county": c, "adults": adults, "indicators": ind,
                         "est_adults_with_diabetes": round(adults * (ind.get("diabetes") or 0) / 100),
                         "est_adults_with_high_bp": round(adults * (ind.get("bphigh") or 0) / 100),
                         "est_adults_no_checkup": round(adults * (100 - (ind.get("checkup") or 100)) / 100)})
        return {"counties": rows, "county_median": med,
                "indicators": {k: v["name"] for k, v in PLACES_INDICATORS.items()},
                "higher_is_better": {k: v["higher_is_better"] for k, v in PLACES_INDICATORS.items()},
                "note": "CDC PLACES model-based estimates for all adults (all payers). 'Est. adults' = adult "
                        "population × prevalence."}

    # ------------------------------------------------------------ campaigns
    def campaigns(self, top: int = 9) -> dict:
        ms = [m for m in self.measures() if m["reported"]]
        ct = self.counties_table()
        counties, med = ct["counties"], ct["county_median"]
        camps = []

        def community(name, link, key, low_is_bad, size_fn, label_fn, channel):
            m = med.get(key)
            if m is None:
                return
            sel = [c for c in counties if c["indicators"].get(key) is not None
                   and (c["indicators"][key] < m if low_is_bad else c["indicators"][key] > m)]
            sel = sorted(sel, key=lambda c: -size_fn(c))[:5]
            if not sel:
                return
            size = round(sum(size_fn(c) for c in sel))
            camps.append({"kind": "Community", "name": name, "measure": link,
                          "targets": [f"{c['county']} ({c['indicators'][key]:.1f}%)" for c in sel],
                          "size": size, "size_label": label_fn(size), "channel": channel,
                          "why": [f"the {len(sel)} largest counties worse than the {FOCUS_STATE_NAME} county median "
                                  f"({m}%) on {PLACES_INDICATORS[key]['name'].lower()}"]})

        community("Colorectal screening push", "COL", "colon_screen", True,
                  lambda c: c["adults"] * (100 - c["indicators"]["colon_screen"]) / 100,
                  lambda s: f"adults in these counties × unscreened share ≈ {s:,} (rough upper bound)",
                  "FIT-kit mailers and community screening events")
        community("Blood-pressure control", "CBP", "bphigh", False, lambda c: c["est_adults_with_high_bp"],
                  lambda s: f"~{s:,} adults with high blood pressure", "Home BP monitoring and pharmacist follow-up")
        community("Diabetes care", "GSD", "diabetes", False, lambda c: c["est_adults_with_diabetes"],
                  lambda s: f"~{s:,} adults with diagnosed diabetes", "A1c, eye-exam and kidney-test bundles")
        community("Primary-care access", "WCV", "checkup", True, lambda c: c["est_adults_no_checkup"],
                  lambda s: f"~{s:,} adults without a checkup in the past year",
                  "Annual-visit scheduling and coverage enrollment help")
        for m in [x for x in ms if (x["members_to_top_quartile"] or 0) > 0][:3]:
            camps.append({"kind": "Statewide Medicaid", "name": f"{m['name']}: reach the top quartile",
                          "measure": m["measure"], "targets": [f"{FOCUS_STATE_NAME} Medicaid & CHIP members"],
                          "size": m["members_to_top_quartile"],
                          "size_label": f"~{m['members_to_top_quartile']:,} more members meeting the measure",
                          "channel": "Managed-care plan and provider performance programs", "why": m["reasons"]})
        for code, p in self.providers(top=40)["measures"].items():
            t = [g for g in p["top"] if g["worse_than_national_median"] and g["patients"] >= 20][:3]
            if not t:
                continue
            size = sum(g["patients_not_meeting"] for g in t)
            camps.append({"kind": "Provider partnership", "name": f"{p['name'].split(' (')[0]}: group partnership",
                          "measure": code, "targets": [f"{g['provider']} ({g['rate']:.0f}%)" for g in t],
                          "size": size, "size_label": f"~{size:,} patients not meeting the measure",
                          "channel": "Share gap lists and best practices with each group's quality lead",
                          "why": [f"largest {FOCUS_STATE_NAME} groups worse than the national median "
                                  f"({p['national_median']}%)"]})
        # Illustrative score: 60% relative size (square-root scaled) + 40% kind weight
        weight = {"Statewide Medicaid": 1.0, "Community": 0.9, "Provider partnership": 0.8}
        by_kind = defaultdict(list)
        for c in camps:
            by_kind[c["kind"]].append(c)
        for kind, cs in by_kind.items():
            mx = max(c["size"] for c in cs) or 1
            for c in cs:
                c["score"] = round(100 * (0.6 * math.sqrt(c["size"] / mx) + 0.4 * weight[kind]), 1)
        camps.sort(key=lambda c: -c["score"])
        for i, c in enumerate(camps, 1):
            c["rank"] = i
        return {"disclaimer": PRIORITY_DISCLAIMER + " Sizes are estimates from public data and are compared only "
                              "within each campaign type; no response rates are assumed.",
                "campaigns": camps[:top], "total": len(camps)}

    # ------------------------------------------------------------ data quality
    def _source_dates(self) -> dict:
        out = {}
        med = medicaid.load()
        if med:
            out[f"Medicaid Core Set {med['releases'][0]['year']}"] = med["releases"][0].get("modified") or ""
        nat = cms.load_national()
        if nat:
            out["CMS MIPS group reporting"] = nat.get("modified") or ""
        pl = places.load()
        if pl:
            out[f"CDC PLACES {pl['release_year']}"] = pl.get("modified") or ""
        return out

    def data_quality(self) -> dict:
        ms = self.measures()
        checks = []

        def add(check, items, detail=None):
            checks.append({"check": check, "count": len(items) if isinstance(items, list) else items,
                           "detail": detail if detail is not None else (", ".join(items) if items else "none")})

        add(f"Measures {FOCUS_STATE_NAME} did not report in the latest release",
            [m["measure"] for m in ms if not m["reported"]])
        add("Measures reported by fewer than 40 states (weaker comparison)",
            [f"{m['measure']} ({m['states_reporting']})" for m in ms if 0 < m["states_reporting"] < 40])
        add("Rates from the hybrid method (denominator is a sample, not all members)",
            [m["measure"] for m in ms if m["reported"] and "hybrid" in (m["methodology"] or "").lower()])
        add("Measures re-specified or re-methoded during the trend period",
            [t["measure"] for t in self.trends() if t["comparability_notes"]])
        add("Reported rates without a published denominator",
            [m["measure"] for m in ms if m["reported"] and not m.get("denominator")])
        grp = cms.load_groups() or {}
        ex = grp.get("excluded_multistate", {})
        add("Multi-state provider groups left out (national patient counts)", sum(ex.values()),
            f"Groups with under half their clinicians in {FOCUS_STATE_NAME}; per measure: "
            + ", ".join(f"{k} {v}" for k, v in ex.items()) if ex else "none")
        add("Provider-group results with fewer than 20 patients",
            sum(1 for r in self.groups if (r["Denominator"] or 0) < 20), "Small denominators make rates unstable")
        add("County estimates with a 95% confidence interval wider than 10 pts",
            sum(1 for r in self.counties if r["CILow"] is not None and r["CIHigh"] is not None
                and r["CIHigh"] - r["CILow"] > 10), "Treat these county differences with caution")
        stale = []
        for name, mod in self._source_dates().items():
            try:
                age = (date.fromisoformat(self.as_of) - date.fromisoformat(mod[:10])).days
            except ValueError:
                continue
            if age > STALE_DAYS:
                stale.append(f"{name} ({age} days)")
        add(f"Sources last updated more than {STALE_DAYS} days ago", stale)
        for c in checks:
            c["flag"] = c["count"] > 0
        return {"checks": checks, "note": "Findings about the public sources, kept separate from performance."}

    # ------------------------------------------------------------ summaries
    def executive_summary(self) -> dict:
        ms = [m for m in self.measures() if m["reported"]]
        top = [m["measure"] for m in ms if m["status"] == "Top quartile"]
        below = [m["measure"] for m in ms if m["status"] in ("Below median", "Bottom quartile")]
        first = ms[0] if ms else None
        prov = self.providers(top=1)["measures"]
        bp = max(prov.values(), key=lambda p: p["patients_not_meeting"]) if prov else None
        ct = self.counties_table()["counties"]
        dm = max(ct, key=lambda c: c["est_adults_with_diabetes"]) if ct else None
        return {
            "state": FOCUS_STATE_NAME, "as_of": self.as_of, "latest_core_set_year": self.latest,
            "measures_reported": len(ms), "measures_tracked": len(CORE_SET_MEASURES),
            "top_quartile": top, "below_median": below,
            "improving": [m["measure"] for m in ms if ((m.get("trend_pts") or 0) > 0) == m["higher_is_better"]
                          and m.get("trend_pts")],
            "top_priority_measure": (f"{first['measure']} {first['name']}: {first['rate']:.1f}% vs top quartile "
                                     f"{first['top_quartile']}% ({'; '.join(first['reasons'][1:])})") if first else None,
            "members_to_top_quartile_total": sum(m["members_to_top_quartile"] or 0 for m in ms),
            "largest_provider_opportunity": (f"{bp['name']}: {bp['patients_not_meeting']:,} patients not meeting "
                                             f"across {bp['groups']} groups") if bp else None,
            "largest_county_need": (f"{dm['county']} County: ~{dm['est_adults_with_diabetes']:,} adults with "
                                    f"diabetes") if dm else None,
            "data_quality_flags": sum(1 for c in self.data_quality()["checks"] if c["flag"]),
        }

    def headline(self) -> list[str]:
        s = self.executive_summary()
        out = [f"{s['state']} Medicaid reports {s['measures_reported']} of {s['measures_tracked']} tracked HEDIS-based "
               f"measures in the {s['latest_core_set_year']} Core Set: {len(s['top_quartile'])} in the top quartile "
               f"of states, {len(s['below_median'])} below the median."]
        if s["top_priority_measure"]:
            out.append(f"Top priority: {s['top_priority_measure']}.")
        if s["members_to_top_quartile_total"]:
            out.append(f"Reaching the top quartile on every measure with a published denominator would take "
                       f"~{s['members_to_top_quartile_total']:,} more members meeting the measure.")
        if s["largest_provider_opportunity"]:
            out.append(f"Biggest provider-group opportunity: {s['largest_provider_opportunity']}.")
        if s["largest_county_need"]:
            out.append(f"Largest community need: {s['largest_county_need']}.")
        out.append(f"{s['data_quality_flags']} data-quality checks flagged on the public sources.")
        return out

    def daily_plan(self) -> dict:
        ms = [m for m in self.measures() if m["reported"]]
        camps = self.campaigns()["campaigns"]
        comm = next((c for c in camps if c["kind"] == "Community"), None)
        provc = next((c for c in camps if c["kind"] == "Provider partnership"), None)
        dq = [c for c in self.data_quality()["checks"] if c["flag"]]
        pri = []
        if ms:
            pri.append({"title": f"Focus measure: {ms[0]['measure']} {ms[0]['name']}",
                        "why": "; ".join(ms[0]["reasons"]),
                        "action": "Align plans, providers and outreach on this measure first."})
        if comm:
            pri.append({"title": comm["name"], "why": comm["size_label"],
                        "action": f"{comm['channel']} in {', '.join(t.split(' (')[0] for t in comm['targets'][:3])}."})
        if provc:
            pri.append({"title": provc["name"], "why": provc["size_label"],
                        "action": f"Start with {provc['targets'][0].split(' (')[0]}."})
        pri.append({"title": "Close data gaps", "why": "; ".join(f"{c['check']}: {c['detail']}" for c in dq[:2]),
                    "action": "Plan for the internal data public sources cannot provide."})
        for i, p in enumerate(pri, 1):
            p["priority"] = i
        return {"priorities": pri, "disclaimer": PRIORITY_DISCLAIMER}

    def sources(self) -> list[dict]:
        out = []
        med = medicaid.load()
        if med:
            rel = med["releases"]
            out.append({"name": "Medicaid & CHIP Child and Adult Core Set", "kind": "Public API",
                        "url": f"https://data.medicaid.gov/dataset/{rel[0]['id']}",
                        "detail": f"data.medicaid.gov · {rel[-1]['year']}–{rel[0]['year']} releases · fetched {med['fetched']}",
                        "feeds": "State Medicaid rates, national medians and quartiles (targets), trends, state comparison",
                        "notes": [med["caveat"]]})
        nat, grp = cms.load_national(), cms.load_groups()
        if nat:
            out.append({"name": nat["dataset_title"], "kind": "Public API", "url": nat["dataset_url"],
                        "detail": f"data.cms.gov · fetched {nat['fetched']}",
                        "feeds": "Provider-group rates and national medians", "notes": [nat["caveat"]]})
        if grp:
            s = grp["sources"][1]
            out.append({"name": s["dataset_title"], "kind": "Public API", "url": s["dataset_url"],
                        "detail": f"data.cms.gov · {grp['groups_in_directory']:,} groups in {FOCUS_STATE_NAME} · "
                                  f"fetched {grp['fetched']}",
                        "feeds": f"Which provider groups practice in {FOCUS_STATE_NAME}", "notes": []})
        pl = places.load()
        if pl:
            out.append({"name": pl["dataset_title"], "kind": "Public API", "url": pl["dataset_url"],
                        "detail": f"data.cdc.gov · {len(pl['counties'])} counties · fetched {pl['fetched']}",
                        "feeds": "County screening, prevalence and access estimates; community campaigns",
                        "notes": [pl["caveat"]]})
        out.append({"name": "Prioritization rules", "kind": "Model setting",
                    "detail": "Illustrative weights in analytics.py — not data; require business approval",
                    "feeds": "Measure and campaign ranking", "notes": []})
        return out

    def payload(self) -> dict:
        return {"state": FOCUS_STATE_NAME, "state_code": FOCUS_STATE, "as_of": self.as_of,
                "latest_year": self.latest, "years": self.years, "headline": self.headline(),
                "summary": self.executive_summary(), "measures": self.measures(), "trends": self.trends(),
                "states": self.state_grid(), "providers": self.providers(), "counties": self.counties_table(),
                "campaigns": self.campaigns(), "plan": self.daily_plan(), "data_quality": self.data_quality(),
                "not_available": NOT_AVAILABLE, "sources": self.sources(), "public_only": True}
