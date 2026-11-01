"""CMS Provider Data Catalog — public MIPS quality results for clinician groups.

Two public datasets:
  * PY 2024 Group Public Reporting: MIPS Measures and Attestations (0ba7-2cb0)
    -> every reporting group's performance rate and patient count per measure
  * National Downloadable File (mj5m-pzi6) -> which groups practice in the
    focus state (group name, cities, number of clinicians)

Joining them gives real, published performance for provider groups in the
focus state. These are MIPS rates (mostly Medicare Part B), not HEDIS rates.
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import date

from .config import CMS_GROUPS_FILE, CMS_NATIONAL_FILE, FOCUS_STATE, MIPS_MEASURES, PUBLIC_DIR
from .http import get_json

MEASURES_ID = "0ba7-2cb0"
MEASURES_TITLE = "PY 2024 Group Public Reporting: MIPS Measures and Attestations"
DIRECTORY_ID = "mj5m-pzi6"
DIRECTORY_TITLE = "Doctors and Clinicians National Downloadable File"
QUERY = "https://data.cms.gov/provider-data/api/1/datastore/query/{id}/0"
META = "https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/items/{id}"
PAGE = 1500  # API maximum


def _meta(dataset_id: str) -> dict:
    m = get_json(META.format(id=dataset_id), {"show-reference-ids": "true"})
    dist = (m.get("distribution") or [{}])[0]
    return {"title": m.get("title"), "modified": m.get("modified"), "issued": m.get("issued"),
            "distribution": dist.get("identifier"),
            "url": f"https://data.cms.gov/provider-data/dataset/{dataset_id}"}


def _paged(url: str, params: dict) -> list[dict]:
    rows, offset = [], 0
    while True:
        data = get_json(url, dict(params, limit=PAGE, offset=offset), timeout=120)
        batch = data.get("results") or []
        rows.extend(batch)
        if len(batch) < PAGE:
            return rows
        offset += PAGE


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def refresh_national() -> dict:
    """All reporting groups' rates for the MIPS measures we track, plus national statistics."""
    meta = _meta(MEASURES_ID)
    out = {"source": "data.cms.gov Provider Data Catalog", "dataset_id": MEASURES_ID, "dataset_title": meta["title"],
           "dataset_url": meta["url"], "modified": meta["modified"], "fetched": date.today().isoformat(),
           "caveat": ("CMS MIPS clinician-group public reporting (largely Medicare Part B). Related to, but not the "
                      "same as, HEDIS measures; not NCQA benchmarks or payer targets."),
           "measures": {}}
    for code, m in MIPS_MEASURES.items():
        rows = _paged(QUERY.format(id=MEASURES_ID), {
            "conditions[0][property]": "measure_cd", "conditions[0][value]": m["measure_cd"],
            "conditions[0][operator]": "=",
            "properties[]": ["org_pac_id", "facility_name", "prf_rate", "patient_count", "collection_type",
                             "five_star_benchmark", "star_value"]})
        groups = []
        for r in rows:
            rate, n = _f(r.get("prf_rate")), _f(r.get("patient_count"))
            if rate is None:
                continue
            groups.append({"org_pac_id": r["org_pac_id"], "name": r.get("facility_name", ""), "rate": rate,
                           "patients": int(n or 0), "collection_type": r.get("collection_type", ""),
                           "five_star_benchmark": _f(r.get("five_star_benchmark")), "stars": _f(r.get("star_value"))})
        rates = sorted(g["rate"] for g in groups)
        q = statistics.quantiles(rates, n=4) if len(rates) >= 4 else [None, None, None]
        pts = sum(g["patients"] for g in groups)
        out["measures"][code] = {
            "measure_cd": m["measure_cd"], "title": m["name"], "higher_is_better": m["higher_is_better"],
            "groups": len(groups), "patients": pts,
            "median": round(statistics.median(rates), 1) if rates else None,
            "p25": round(q[0], 1) if q[0] is not None else None, "p75": round(q[2], 1) if q[2] is not None else None,
            "patient_weighted_rate": round(sum(g["rate"] * g["patients"] for g in groups) / pts, 1) if pts else None,
            "_groups": groups,
        }
    _save_national(out)
    return out


def _save_national(out: dict) -> None:
    """National stats are small and committed; per-group rows are kept only for the focus state."""
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    slim = json.loads(json.dumps(out))
    for m in slim["measures"].values():
        m.pop("_groups", None)
    CMS_NATIONAL_FILE.write_text(json.dumps(slim, indent=1))


def refresh_state_groups(national: dict | None = None, state: str = FOCUS_STATE, progress=print) -> dict:
    """Join group rates to the clinician directory to keep groups practicing in `state`."""
    national = national or refresh_national()
    meta = _meta(DIRECTORY_ID)
    url = f"https://data.cms.gov/provider-data/api/1/datastore/query/{meta['distribution']}"
    directory, offset = {}, 0
    while True:
        data = get_json(url, {"limit": PAGE, "offset": offset, "count": "false", "schema": "false",
                              "properties[]": ["npi", "org_pac_id", "facility_name", "citytown", "num_org_mem"],
                              "conditions[0][property]": "state", "conditions[0][value]": state}, timeout=120)
        batch = data.get("results") or []
        for r in batch:
            pac = r.get("org_pac_id")
            if not pac:
                continue
            d = directory.setdefault(pac, {"name": r.get("facility_name", ""), "cities": set(), "npis": set(),
                                           "clinicians": int(_f(r.get("num_org_mem")) or 0)})
            if r.get("npi"):
                d["npis"].add(r["npi"])
            if r.get("citytown"):
                d["cities"].add(r["citytown"].title())
        offset += PAGE
        if progress and offset % (PAGE * 10) == 0:
            progress(f"  clinician directory: {offset:,} rows read, {len(directory):,} groups in {state}")
        if len(batch) < PAGE:
            break
    out = {"state": state, "fetched": date.today().isoformat(),
           "sources": [{"dataset_title": national["dataset_title"], "dataset_url": national["dataset_url"],
                        "modified": national["modified"]},
                       {"dataset_title": meta["title"], "dataset_url": meta["url"], "modified": meta["modified"]}],
           "groups_in_directory": len(directory), "measures": {}}
    # Keep groups based in the state: at least half of their clinicians practice there.
    # Multi-state systems report national patient counts, which would overstate in-state need.
    out["rule"] = "group kept if >= 50% of its clinicians (num_org_mem) have a practice address in the state"
    out["excluded_multistate"] = {}
    for code, m in national["measures"].items():
        rows, excluded = [], 0
        for g in m["_groups"]:
            d = directory.get(g["org_pac_id"])
            if not d:
                continue
            share = len(d["npis"]) / d["clinicians"] if d["clinicians"] else 1.0
            if share < 0.5:
                excluded += 1
                continue
            rows.append(dict(g, name=d["name"] or g["name"], cities=sorted(d["cities"])[:6],
                             clinicians=d["clinicians"], in_state_share=round(min(share, 1.0), 2)))
        out["measures"][code] = rows
        out["excluded_multistate"][code] = excluded
    CMS_GROUPS_FILE.write_text(json.dumps(out, indent=1))
    return out


def refresh(state: str = FOCUS_STATE, progress=print) -> dict:
    nat = refresh_national()
    return refresh_state_groups(nat, state, progress)


def load_national() -> dict | None:
    try:
        return json.loads(CMS_NATIONAL_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def load_groups() -> dict | None:
    try:
        return json.loads(CMS_GROUPS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
