"""Scene 5: measure context assembly on both sides with the same query and budget.

Prints the context size each side would send to the model, retrieval latency, and
how many lines of glue code Side A owns for it. Use these numbers, not the
placeholders in the simulation.

Usage:
  python demo/measure_context.py ["query"] [--runs 5]
Needs Side A (AWS credentials, memory_config.json or AGENTCORE_MEMORY_ID) and
Side B (AE_PROJECT_ID, AE_CLIENT_ID, AE_CLIENT_SECRET) environment.
"""
from __future__ import annotations

import argparse
import inspect
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "shared"),
    str(ROOT / "side_a_agentcore" / "app" / "card_agent"),
    str(ROOT / "side_b_atlas" / "scripts"),
]

from bakeoff.ports import estimate_tokens  # noqa: E402

CUSTOMER_ID = "C-1001"
BUDGET = 1500


def timed(fn, runs: int):
    out, times = None, []
    for _ in range(runs):
        t = time.perf_counter()
        out = fn()
        times.append((time.perf_counter() - t) * 1000)
    return out, statistics.median(times)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("query", nargs="?", default="Remind me what we discussed about my Melbourne move.")
    p.add_argument("--runs", type=int, default=5)
    args = p.parse_args()

    from memory_agentcore import AgentCoreMemory

    a = AgentCoreMemory(max_context_tokens=BUDGET)
    ctx_a, ms_a = timed(lambda: a.context(CUSTOMER_ID, args.query), args.runs)
    glue = len([ln for ln in inspect.getsource(AgentCoreMemory.context).splitlines() if ln.strip()])

    from _common import hosted_memory

    mem = hosted_memory()
    res_b, ms_b = timed(lambda: mem.build_context(query=args.query, user_id=CUSTOMER_ID,
                                                  enabled_sources={"semantic", "episodic"},
                                                  max_tokens=BUDGET + 500, include_memories=True), args.runs)
    text_b = res_b.formatted_context if not isinstance(res_b.formatted_context, list) else str(res_b.formatted_context)
    tokens_b = getattr(res_b.metadata, "token_count", None) or estimate_tokens(text_b)
    picked_b = len(res_b.selected_memories or [])

    print(f"\nQuery: {args.query}\nBudget for memories: {BUDGET} tokens, median of {args.runs} runs\n")
    print(f"{'':28}{'Side A · AgentCore':>22}{'Side B · Atlas':>20}")
    print(f"{'Context tokens (approx.)':28}{ctx_a.token_estimate:>22,}{tokens_b:>20,}")
    print(f"{'Memories selected':28}{sum(ctx_a.sources.values()):>22}{picked_b:>20}")
    print(f"{'Retrieval latency (ms)':28}{ms_a:>22,.0f}{ms_b:>20,.0f}")
    print(f"{'Retrieval calls':28}{4:>22}{1:>20}")
    print(f"{'Glue code you own (lines)':28}{glue:>22}{'1 call':>20}")
    print("\nSide A context:\n" + (ctx_a.text or "(empty)"))
    print("\nSide B context:\n" + (text_b or "(empty)"))


if __name__ == "__main__":
    main()
