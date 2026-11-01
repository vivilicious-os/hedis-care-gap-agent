"""Command line entry point: python -m hedis_agent <command>"""
from __future__ import annotations

import argparse
import json


def _p(x) -> None:
    print(json.dumps(x, indent=2, default=str))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="hedis_agent", description="HEDIS public-data intelligence agent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("refresh", help="Pull Medicaid Core Set, CDC PLACES, CMS MIPS and NPPES data, then build facts")
    sub.add_parser("build", help="Rebuild the fact table from cached public data")
    sub.add_parser("report", help="Write output/hedis_report.md")
    sub.add_parser("summary", help="Print the executive summary")
    sub.add_parser("measures", help="Print measures vs. public benchmarks")
    sub.add_parser("campaigns", help="Print ranked campaigns")
    sub.add_parser("quality", help="Print data-quality checks on the public sources")
    n = sub.add_parser("npi", help="Look up a provider in NPPES")
    n.add_argument("npi")
    sv = sub.add_parser("serve", help="Dashboard + agent chat at http://localhost:8000")
    sv.add_argument("--port", type=int, default=8000)
    sub.add_parser("site", help="Write a static copy of the dashboard to docs/index.html")
    mo = sub.add_parser("morning", help="Daily run: refresh public data, rebuild facts, report and dashboard")
    mo.add_argument("--offline", action="store_true", help="Use cached public data")
    a = sub.add_parser("ask", help="Ask the Claude agent (needs ANTHROPIC_API_KEY); omit the question to chat")
    a.add_argument("question", nargs="*")
    a.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    args = ap.parse_args(argv)

    if args.cmd == "refresh":
        from . import facts
        from .morning import refresh_all
        for line in refresh_all():
            print(line)
        _p(facts.build())
    elif args.cmd == "build":
        from . import facts
        _p(facts.build())
    elif args.cmd in ("report", "summary", "measures", "campaigns", "quality"):
        from .analytics import PublicAnalyzer
        an = PublicAnalyzer()
        if args.cmd == "report":
            from .report import write_report
            _p(write_report(an))
        else:
            _p({"summary": an.executive_summary, "measures": an.measures, "campaigns": an.campaigns,
                "quality": an.data_quality}[args.cmd]())
    elif args.cmd == "npi":
        from . import nppes
        _p(nppes.lookup_npi(args.npi))
    elif args.cmd == "serve":
        from .server import serve
        serve(port=args.port)
    elif args.cmd == "site":
        from .server import write_static_site
        _p(write_static_site())
    elif args.cmd == "morning":
        from .morning import run_morning
        _p(run_morning(refresh=not args.offline))
    elif args.cmd == "ask":
        from .agent import chat
        chat(" ".join(args.question) or None, effort=args.effort)


if __name__ == "__main__":
    main()
