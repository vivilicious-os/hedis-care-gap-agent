"""Claude-powered HEDIS agent over public data.

Claude gets the public-data analytics engine as tools and answers questions
like "How is our state doing?" or "Which campaign should we start?". The
system prompt is the project's CLAUDE.md plus a note that only public data is
available, so patient-level questions get "not available in public data".

Needs ANTHROPIC_API_KEY (or another credential the Anthropic SDK accepts).
"""
from __future__ import annotations

import json

from . import nppes
from .analytics import NOT_AVAILABLE, PublicAnalyzer
from .config import FOCUS_STATE_NAME, ROOT

MODEL = "claude-opus-5-5"
MAX_TOOL_RESULT_CHARS = 60_000

TOOL_GUIDE = f"""
## Deployment: public data only
This deployment has NO patient-level, payer-file or EHR data. Every number comes from public APIs:
the Medicaid & CHIP Core Set (state Medicaid rates, national medians and quartiles), CMS MIPS
clinician-group results, and CDC PLACES county estimates. The focus state is {FOCUS_STATE_NAME}.
Read the CLAUDE.md rules at the levels this data supports: state program, provider group, county.
- Always call tools for numbers; never estimate them.
- "How are we doing?" -> executive_summary, then measures. "What should we work on?" -> daily_plan, campaigns.
- Targets are the public top-quartile state rate. Name that source whenever you quote a target.
- Hybrid-method rates use sample denominators; never convert them to member counts.
- For patients, payer-vs-EHR reconciliation, commercial/MA plan rates, contract targets or incentive dollars,
  say "This information is not available in the supplied public data" and name the data needed
  (the not_available tool lists it).
Keep answers short: Observation -> Why it matters -> Recommended action.
"""

_EMPTY = {"type": "object", "properties": {}}
TOOLS = [
    {"name": "executive_summary", "description": f"Headline view of {FOCUS_STATE_NAME} Medicaid quality: measures "
     "reported, top-quartile and below-median measures, top priority, biggest provider-group and county needs.",
     "input_schema": _EMPTY},
    {"name": "measures", "description": "Every tracked HEDIS-based Core Set measure: state rate, denominator, national "
     "median/top/bottom quartile, rank among states, status, gap and members to top quartile, trend, priority.",
     "input_schema": _EMPTY},
    {"name": "trend", "description": "Year-by-year state rate vs. national median for one measure, with change and "
     "comparability notes (re-specification, method changes).",
     "input_schema": {"type": "object", "properties": {"measure": {"type": "string",
                      "description": "Measure code, e.g. WCV, CBP, GSD, BCS"}}, "required": ["measure"]}},
    {"name": "state_comparison", "description": "Latest rates for every state on every measure (for peer comparison).",
     "input_schema": _EMPTY},
    {"name": "provider_groups", "description": f"CMS MIPS results for provider groups practicing in {FOCUS_STATE_NAME}: "
     "rate, patients, patients not meeting, vs. national median, flags.",
     "input_schema": {"type": "object", "properties": {"top": {"type": "integer", "description": "Groups per measure (default 10)"}}}},
    {"name": "counties", "description": "CDC PLACES county estimates: screening, prevalence, access, adult population, "
     "estimated adults affected.", "input_schema": {"type": "object", "properties": {
         "top": {"type": "integer", "description": "Largest N counties (default 20)"}}}},
    {"name": "campaigns", "description": "Ranked campaign ideas: statewide Medicaid measure pushes, county community "
     "campaigns and provider-group partnerships, with sizes and reasons.", "input_schema": _EMPTY},
    {"name": "daily_plan", "description": "What to work on first, with reasons and actions.", "input_schema": _EMPTY},
    {"name": "data_quality", "description": "Data-quality checks on the public sources.", "input_schema": _EMPTY},
    {"name": "data_sources", "description": "Where every number comes from, with dataset links and fetch dates.",
     "input_schema": _EMPTY},
    {"name": "not_available", "description": "Questions public data cannot answer and the data each would need.",
     "input_schema": _EMPTY},
    {"name": "lookup_npi", "description": "Look up a provider in the public NPPES NPI Registry by 10-digit NPI.",
     "input_schema": {"type": "object", "properties": {"npi": {"type": "string"}}, "required": ["npi"]}},
]


def run_tool(a: PublicAnalyzer, name: str, args: dict):
    """Execute one agent tool (no API key needed)."""
    if name == "executive_summary":
        return a.executive_summary()
    if name == "measures":
        return a.measures()
    if name == "trend":
        return a.trend(str(args["measure"]).upper())
    if name == "state_comparison":
        return a.state_grid()
    if name == "provider_groups":
        p = a.providers(top=min(int(args.get("top") or 10), 40))
        return p
    if name == "counties":
        c = a.counties_table()
        return dict(c, counties=c["counties"][: min(int(args.get("top") or 20), 100)])
    if name == "campaigns":
        return a.campaigns()
    if name == "daily_plan":
        return a.daily_plan()
    if name == "data_quality":
        return a.data_quality()
    if name == "data_sources":
        return a.sources()
    if name == "not_available":
        return NOT_AVAILABLE
    if name == "lookup_npi":
        return nppes.lookup_npi(args["npi"])
    raise ValueError(f"Unknown tool: {name}")


class HedisAgent:
    def __init__(self, analyzer: PublicAnalyzer | None = None, model: str = MODEL, effort: str = "medium",
                 verbose: bool = True):
        import anthropic  # imported here so the rest of the package runs without the SDK
        self.anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.a = analyzer or PublicAnalyzer()
        self.model = model
        self.effort = effort
        self.verbose = verbose
        rules = (ROOT / "CLAUDE.md").read_text()
        self.system = [{"type": "text", "text": rules + "\n" + TOOL_GUIDE, "cache_control": {"type": "ephemeral"}}]
        self.messages: list[dict] = []

    # ------------------------------------------------------------ tools
    def run_tool(self, name: str, args: dict):
        return run_tool(self.a, name, args)

    def _tool_result(self, block) -> dict:
        try:
            out = json.dumps(self.run_tool(block.name, block.input or {}), default=str)
            if len(out) > MAX_TOOL_RESULT_CHARS:
                out = out[:MAX_TOOL_RESULT_CHARS] + '... [truncated — ask for a smaller limit or a filter]'
            return {"type": "tool_result", "tool_use_id": block.id, "content": out}
        except Exception as e:  # report tool failures back to Claude instead of crashing
            return {"type": "tool_result", "tool_use_id": block.id, "content": f"Error: {e}", "is_error": True}

    # ------------------------------------------------------------ loop
    def ask(self, question: str, max_turns: int = 12) -> str:
        self.messages.append({"role": "user", "content": question})
        for _ in range(max_turns):
            resp = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=self.system,
                tools=TOOLS,
                messages=self.messages,
                thinking={"type": "adaptive"},
                output_config={"effort": self.effort},
                # If a safety classifier declines, the API retries on a fallback model in the same call.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            self.messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason == "refusal":
                return "The model declined this request."
            if resp.stop_reason == "pause_turn":
                continue
            tool_calls = [b for b in resp.content if b.type == "tool_use"]
            if resp.stop_reason == "tool_use" and tool_calls:
                if self.verbose:
                    print("  ↳ tools:", ", ".join(f"{b.name}({json.dumps(b.input)})" for b in tool_calls))
                self.messages.append({"role": "user", "content": [self._tool_result(b) for b in tool_calls]})
                continue
            text = "\n".join(b.text for b in resp.content if b.type == "text").strip()
            if resp.stop_reason == "max_tokens":
                text += "\n\n[Answer cut off at the token limit.]"
            return text
        return "Stopped after too many tool rounds without a final answer."


def _safe_ask(agent: HedisAgent, q: str) -> bool:
    """Print the answer; return False when the session should stop."""
    api = agent.anthropic
    try:
        print("\n" + agent.ask(q))
        return True
    except (api.AuthenticationError, TypeError) as e:
        if isinstance(e, TypeError) and "authentication" not in str(e).lower():
            raise
        print("No valid Anthropic credentials. Set ANTHROPIC_API_KEY (https://console.anthropic.com) and retry.")
        return False
    except api.RateLimitError:
        print("Rate limited — wait a moment and try again.")
    except api.APIStatusError as e:
        print(f"API error {e.status_code}: {e.message}")
    except api.APIConnectionError:
        print("Could not reach the Anthropic API — check your network.")
    agent.messages.clear()  # drop the half-finished exchange so the next question starts clean
    return True


def chat(question: str | None = None, effort: str = "medium") -> None:
    try:
        agent = HedisAgent(effort=effort)
    except ImportError:
        print("The agent needs the Anthropic SDK: pip install -r requirements.txt")
        return
    if question:
        _safe_ask(agent, question)
        return
    print("HEDIS agent — ask a question (blank line to quit). Try: How are we doing? / What should we work on today?")
    while True:
        try:
            q = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q or not _safe_ask(agent, q):
            break
