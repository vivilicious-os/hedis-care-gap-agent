"""Medicaid & CHIP Child and Adult Core Set quality measures (data.medicaid.gov).

Public, no key. Each yearly release has, for every state and measure: the
state's rate, and the national median, mean and quartiles of state rates.
The 2025 release also publishes each state's denominator. We pull the last
few releases for all states so we can compare states and show real trends.
"""
from __future__ import annotations

import json
import re
from datetime import date

from .config import CORE_SET_MEASURES, CORE_SET_YEARS, MEDICAID_FILE, PUBLIC_DIR
from .http import get_json

META = "https://data.medicaid.gov/api/1/metastore/schemas/dataset/items"
QUERY = "https://data.medicaid.gov/api/1/datastore/query/{id}/0"
TITLE = re.compile(r"^(\d{4}) Child and Adult Health Care Quality Measures")
NOT_REPORTED = {"NR", "NPR", "DNPR", "DS", "NA", ""}


def releases(n: int = CORE_SET_YEARS) -> list[dict]:
    """The newest `n` yearly Core Set releases: [{year, id, title, modified}], newest first."""
    items = get_json(META, {"show-reference-ids": "false"}, timeout=120)
    by_year = {}
    for x in items:
        m = TITLE.match(x.get("title", ""))
        if m:
            y = int(m.group(1))
            if y not in by_year or (x.get("modified") or "") > (by_year[y].get("modified") or ""):
                by_year[y] = {"year": y, "id": x["identifier"], "title": x["title"], "modified": x.get("modified")}
    return [by_year[y] for y in sorted(by_year, reverse=True)[:n]]


def _f(x):
    x = (x or "").strip()
    if x in NOT_REPORTED:
        return None
    try:
        return float(x.replace(",", ""))
    except ValueError:
        return None


def _pick(rows: list[dict], match: list[str]) -> dict | None:
    """The rate row for one state: matching definition, preferring the one CMS used for the median."""
    hits = [r for r in rows if all(t.lower() in (r.get("rate_definition") or "").lower() for t in match)]
    if not hits:
        return None
    hits.sort(key=lambda r: (r.get("rate_used_in_calculating_state_mean_and_median") != "Yes",
                             _f(r.get("state_rate")) is None))
    return hits[0]


def refresh(progress=print) -> dict:
    rels = releases()
    out = {
        "source": "data.medicaid.gov — Medicaid & CHIP Child and Adult Core Set",
        "fetched": date.today().isoformat(),
        "releases": rels,
        "caveat": ("State Medicaid/CHIP program rates as reported to CMS (Mathematica analysis of QMR system "
                   "reports). HEDIS-based but not NCQA HEDIS results; specifications, age bands and reporting "
                   "methods (administrative vs. hybrid vs. electronic) can differ by year and state."),
        "rows": [],
    }
    for rel in rels:
        for code, m in CORE_SET_MEASURES.items():
            for abbr in m["abbr"]:
                data = get_json(QUERY.format(id=rel["id"]), {
                    "limit": 2000, "conditions[0][property]": "measure_abbreviation",
                    "conditions[0][value]": abbr, "conditions[0][operator]": "="}, timeout=120)
                rows = data.get("results") or []
                if not rows:
                    continue
                by_state = {}
                for r in rows:
                    by_state.setdefault(r.get("state", ""), []).append(r)
                for state, srows in by_state.items():
                    r = _pick(srows, m["match"])
                    if not r:
                        continue
                    out["rows"].append({
                        "year": rel["year"], "state": state, "code": code, "abbr": abbr,
                        "definition": r.get("rate_definition"), "measure_name": r.get("measure_name"),
                        "rate": _f(r.get("state_rate")), "rate_raw": r.get("state_rate"),
                        "denominator": _f(r.get("denominator")),
                        "median": _f(r.get("median")), "mean": _f(r.get("mean")),
                        "top_quartile": _f(r.get("top_quartile")), "bottom_quartile": _f(r.get("bottom_quartile")),
                        "states_reporting": int(_f(r.get("number_of_states_reporting")) or 0),
                        "higher_is_better": "lower" not in (r.get("measure_type") or "").lower(),
                        "methodology": r.get("methodology"), "population": r.get("population"),
                        "used_in_median": r.get("rate_used_in_calculating_state_mean_and_median"),
                        "notes": (r.get("notes") or "")[:300],
                    })
                break  # first abbreviation with data wins for this year
        if progress:
            progress(f"  Core Set {rel['year']}: {sum(1 for x in out['rows'] if x['year'] == rel['year']):,} rows")
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    MEDICAID_FILE.write_text(json.dumps(out, indent=0))
    return out


def load() -> dict | None:
    try:
        return json.loads(MEDICAID_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
