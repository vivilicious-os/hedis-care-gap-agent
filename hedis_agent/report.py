"""Markdown report built from the public-data analytics (renders on GitHub)."""
from __future__ import annotations

from .analytics import PublicAnalyzer
from .config import OUTPUT_DIR


def markdown_report(a: PublicAnalyzer) -> str:
    p = a.payload()
    L = [f"# HEDIS Public Intelligence Report — {p['state']}", "",
         f"> Public data only (Medicaid Core Set, CMS MIPS, CDC PLACES). Fetched {p['as_of']}.", "",
         "## Summary", ""] + [f"- {h}" for h in p["headline"]] + ["", "## Measures vs. public top quartile", "",
         f"_{p['plan']['disclaimer']}_", "",
         "| # | Measure | Rate | Median | Top quartile | Rank | Status | Members to top quartile | Trend |",
         "|---:|---|---|---:|---:|---|---|---:|---|"]
    for m in p["measures"]:
        if not m["reported"]:
            L.append(f"| {m['rank_priority']} | **{m['measure']}** {m['name']} | not reported | {m['median']} | "
                     f"{m['top_quartile']} | — | {m['status']} | — | — |")
            continue
        mem = f"{m['members_to_top_quartile']:,}" if m["members_to_top_quartile"] is not None else "sample"
        tr = f"{m['trend_pts']:+.1f} ({m['trend_span']})" if m.get("trend_pts") is not None else "—"
        L.append(f"| {m['rank_priority']} | **{m['measure']}** {m['name']} | {m['rate_display']} | {m['median']} | "
                 f"{m['top_quartile']} | #{m['rank']}/{m['of']} | {m['status']} | {mem} | {tr} |")
    L += ["", "## What to work on first", ""]
    for x in p["plan"]["priorities"]:
        L += [f"**{x['priority']}. {x['title']}**", f"- Why: {x['why']}", f"- Action: {x['action']}", ""]
    L += ["## Campaigns", "", "| # | Type | Campaign | Size | Targets |", "|---:|---|---|---|---|"]
    for c in p["campaigns"]["campaigns"]:
        L.append(f"| {c['rank']} | {c['kind']} | {c['name']} | {c['size_label']} | {', '.join(c['targets'][:3])} |")
    L += ["", "## Data quality (public sources)", "", "| Check | Count | Detail |", "|---|---:|---|"]
    for c in p["data_quality"]["checks"]:
        L.append(f"| {'⚠️ ' if c['flag'] else ''}{c['check']} | {c['count']} | {c['detail']} |")
    L += ["", "## Not available in public data", ""]
    L += [f"- **{x['question']}** {x['why']} Needs: {x['needs']}." for x in p["not_available"]]
    L += ["", "## Sources", ""] + [f"- [{s['name']}]({s.get('url', '')}) — {s['detail']}" for s in p["sources"] if s.get("url")]
    return "\n".join(L) + "\n"


def write_report(a: PublicAnalyzer) -> dict:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    md = OUTPUT_DIR / "hedis_report.md"
    md.write_text(markdown_report(a))
    old = OUTPUT_DIR / "hedis_report.html"
    if old.exists():
        old.unlink()
    return {"report": str(md)}
