"""NPPES NPI Registry client (CMS, public, no API key).

Docs: https://npiregistry.cms.hhs.gov/registry/help-api
Only provider identifiers are ever sent to this API — never patient data.
"""
from __future__ import annotations

import json
from datetime import date

from .config import NPPES_CACHE, NPPES_SUPPLY
from .http import get_json

API = "https://npiregistry.cms.hhs.gov/api/"
PRIMARY_CARE_TAXONOMIES = ["Family Medicine", "Internal Medicine", "Obstetrics & Gynecology", "Nurse Practitioner"]


def is_valid_npi(npi: str) -> bool:
    """NPI check digit (Luhn over the '80840' prefix + first 9 digits)."""
    if not (isinstance(npi, str) and len(npi) == 10 and npi.isdigit()):
        return False
    digits = [int(c) for c in "80840" + npi[:9]]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10 == int(npi[9])


def _load_cache() -> dict:
    try:
        return json.loads(NPPES_CACHE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"npi": {}}


def _save_cache(cache: dict) -> None:
    NPPES_CACHE.parent.mkdir(parents=True, exist_ok=True)
    NPPES_CACHE.write_text(json.dumps(cache, indent=1, sort_keys=True))


def _summarize(r: dict) -> dict:
    basic = r.get("basic", {})
    tax = next((t for t in r.get("taxonomies", []) if t.get("primary")), (r.get("taxonomies") or [{}])[0])
    loc = next((a for a in r.get("addresses", []) if a.get("address_purpose") == "LOCATION"), {})
    if r.get("enumeration_type") == "NPI-2":
        name = basic.get("organization_name", "")
    else:
        name = " ".join(x for x in [basic.get("first_name", ""), basic.get("last_name", "")] if x).title()
    return {
        "npi": r.get("number"),
        "name": name,
        "credential": basic.get("credential", ""),
        "type": "Organization" if r.get("enumeration_type") == "NPI-2" else "Individual",
        "status": basic.get("status", ""),
        "primary_taxonomy": tax.get("desc", ""),
        "taxonomy_code": tax.get("code", ""),
        "practice_city": loc.get("city", "").title(),
        "practice_state": loc.get("state", ""),
        "practice_phone": loc.get("telephone_number", ""),
        "last_updated": basic.get("last_updated", ""),
    }


def lookup_npi(npi: str, use_cache: bool = True) -> dict:
    """Return a provider summary for one NPI, or {'found': False}."""
    npi = str(npi).strip()
    if not is_valid_npi(npi):
        return {"npi": npi, "found": False, "error": "Not a valid 10-digit NPI (check digit failed)"}
    cache = _load_cache()
    if use_cache and npi in cache["npi"]:
        return cache["npi"][npi]
    data = get_json(API, {"version": "2.1", "number": npi})
    results = data.get("results") or []
    out = dict(_summarize(results[0]), found=True) if results else {"npi": npi, "found": False}
    cache["npi"][npi] = out
    _save_cache(cache)
    return out


def search(taxonomy: str | None = None, city: str | None = None, state: str | None = None,
           last_name: str | None = None, first_name: str | None = None, limit: int = 20) -> list[dict]:
    params = {"version": "2.1", "limit": min(limit, 200)}
    for k, v in [("taxonomy_description", taxonomy), ("city", city), ("state", state),
                 ("last_name", last_name), ("first_name", first_name)]:
        if v:
            params[k] = v
    data = get_json(API, params)
    return [_summarize(r) for r in data.get("results") or []]


def provider_supply(city: str, state: str, taxonomies=PRIMARY_CARE_TAXONOMIES, use_cache: bool = True) -> dict:
    """Count active NPIs per taxonomy in a city (NPPES returns at most 1,200 per query)."""
    key = f"{city.upper()}|{state.upper()}"
    try:
        supply = json.loads(NPPES_SUPPLY.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        supply = {}
    if use_cache and key in supply:
        return supply[key]
    counts = {}
    for tax in taxonomies:
        seen = set()
        for skip in range(0, 1200, 200):
            data = get_json(API, {"version": "2.1", "taxonomy_description": tax, "city": city,
                                  "state": state, "limit": 200, "skip": skip})
            batch = data.get("results") or []
            seen.update(r["number"] for r in batch)
            if len(batch) < 200:
                break
        counts[tax] = {"count": len(seen), "capped": len(seen) >= 1200}
    out = {"city": city.title(), "state": state.upper(), "fetched": date.today().isoformat(),
           "source": "NPPES NPI Registry API v2.1", "counts": counts}
    supply[key] = out
    NPPES_SUPPLY.parent.mkdir(parents=True, exist_ok=True)
    NPPES_SUPPLY.write_text(json.dumps(supply, indent=1, sort_keys=True))
    return out
