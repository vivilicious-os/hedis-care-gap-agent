"""Daily run: refresh the public APIs, rebuild the fact table, report and dashboard."""
from __future__ import annotations

import json
from datetime import date

from . import cms, facts, medicaid, nppes, places
from .analytics import PublicAnalyzer
from .config import OUTPUT_DIR, SERVICE_AREA
from .report import write_report
from .server import _state, write_static_site


def refresh_all(progress=print) -> list[str]:
    notes = []
    for name, fn in [("Medicaid Core Set", lambda: medicaid.refresh(progress)),
                     ("CDC PLACES", places.refresh),
                     ("CMS MIPS groups", lambda: cms.refresh(progress=progress)),
                     ("NPPES supply", lambda: nppes.provider_supply(*SERVICE_AREA, use_cache=False))]:
        try:
            fn()
            notes.append(f"{name}: refreshed")
        except Exception as e:  # keep going on cached copies
            notes.append(f"{name}: refresh failed, using cached copy ({e})")
    return notes


def run_morning(refresh: bool = True) -> dict:
    notes = refresh_all() if refresh else ["Offline: using cached public data"]
    built = facts.build()
    a = PublicAnalyzer()
    payload = a.payload()
    _state.update(analyzer=a, payload=payload)
    out = {"notes": notes, "facts": built, **write_report(a), **write_static_site()}
    brief_dir = OUTPUT_DIR / "morning"
    brief_dir.mkdir(parents=True, exist_ok=True)
    path = brief_dir / f"brief_{date.today().isoformat()}.json"
    path.write_text(json.dumps({"run_date": date.today().isoformat(), "headline": payload["headline"],
                                "plan": payload["plan"], "campaigns": payload["campaigns"]["campaigns"][:5]},
                               indent=1, default=str))
    out.update(brief=str(path), headline=payload["headline"])
    return out
