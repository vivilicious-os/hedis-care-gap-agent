"""CDC PLACES: local model-based estimates of health measures (data.cdc.gov).

Public, no key. County-level estimates for adults 18+: screening rates,
chronic-disease prevalence and access indicators, with 95% confidence
intervals and the county's adult population.
"""
from __future__ import annotations

import json
import re
from datetime import date

from .config import FOCUS_STATE, PLACES_FILE, PLACES_INDICATORS, PUBLIC_DIR
from .http import get_json

CATALOG = "https://data.cdc.gov/api/catalog/v1"
RESOURCE = "https://data.cdc.gov/resource/{id}.json"
TITLE = re.compile(r"PLACES: County Data \(GIS Friendly Format\), (\d{4}) release")


def latest_release() -> dict:
    data = get_json(CATALOG, {"q": "PLACES County Data GIS Friendly Format", "limit": 30})
    best = None
    for r in data.get("results", []):
        res = r["resource"]
        m = TITLE.match(res.get("name", ""))
        if m and (best is None or (int(m.group(1)), res.get("updatedAt", "")) > (best["year"], best["updated"])):
            best = {"year": int(m.group(1)), "id": res["id"], "title": res["name"],
                    "updated": res.get("updatedAt", "")[:10]}
    if not best:
        raise RuntimeError("No PLACES county release found on data.cdc.gov")
    return best


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _ci(s):
    nums = re.findall(r"[\d.]+", s or "")
    return (float(nums[0]), float(nums[1])) if len(nums) == 2 else (None, None)


def refresh(state: str = FOCUS_STATE) -> dict:
    rel = latest_release()
    rows = get_json(RESOURCE.format(id=rel["id"]), {"stateabbr": state, "$limit": 5000})
    counties = []
    for r in rows:
        c = {"county": r.get("countyname"), "fips": r.get("countyfips"),
             "population": int(_f(r.get("totalpopulation")) or 0), "adults": int(_f(r.get("totalpop18plus")) or 0),
             "indicators": {}}
        for key in PLACES_INDICATORS:
            lo, hi = _ci(r.get(f"{key}_crude95ci"))
            c["indicators"][key] = {"crude": _f(r.get(f"{key}_crudeprev")), "adjusted": _f(r.get(f"{key}_adjprev")),
                                    "ci_low": lo, "ci_high": hi}
        counties.append(c)
    out = {"source": "data.cdc.gov — CDC PLACES", "dataset_id": rel["id"], "dataset_title": rel["title"],
           "dataset_url": f"https://data.cdc.gov/d/{rel['id']}", "release_year": rel["year"],
           "modified": rel["updated"], "fetched": date.today().isoformat(), "state": state,
           "caveat": ("Model-based small-area estimates from BRFSS survey data, for all adults in the county "
                      "regardless of insurance. Not HEDIS rates; use for where-to-focus, not for performance."),
           "counties": sorted(counties, key=lambda c: -c["adults"])}
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    PLACES_FILE.write_text(json.dumps(out, indent=0))
    return out


def load() -> dict | None:
    try:
        return json.loads(PLACES_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
