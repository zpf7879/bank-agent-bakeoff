"""Play a demo scene against both deployed agents and print the replies side by side.

Usage:
  python demo/run_scene.py 2                 # both sides
  python demo/run_scene.py 3 --side b        # one side
  python demo/run_scene.py --message "..."   # free text, both sides

Scenes match the click-through simulation:
  1 Where memory lives      (then run demo/where_memory_lives.py)
  2 Fraud freeze            (run demo/freeze_card.py first; see README)
  3 Fee-waiver procedure
  4 Bank vocabulary
  5 Context assembly        (then run demo/measure_context.py)
"""
from __future__ import annotations

import argparse
import sys
import textwrap
import uuid
from concurrent.futures import ThreadPoolExecutor

from clients import Reply, SideA, SideB

CUSTOMER_ID = "C-1001"
SCENES = {
    1: ("Where memory lives", "I'm moving to Melbourne for work next month. I'll keep using this card there."),
    2: ("Fraud freeze", "Hi, can you go ahead with the credit limit increase we talked about?"),
    3: ("Fee-waiver procedure", "I paid three days late because I was travelling. Can you waive the late fee?"),
    4: ("Bank vocabulary", "My dispute says 'provisional credit'. Is that my money now?"),
    5: ("Context assembly", "Remind me what we discussed about my Melbourne move. Anything I still need to do?"),
}
WIDTH = 58


def column(reply: Reply) -> list[str]:
    lines = [f"{reply.side}  ({reply.elapsed_ms:,} ms)", "-" * WIDTH]
    if reply.error:
        lines += textwrap.wrap(f"ERROR: {reply.error}", WIDTH)
    else:
        for para in reply.text.split("\n"):
            lines += textwrap.wrap(para, WIDTH) or [""]
    for key, value in reply.extra.items():
        if value not in (None, [], {}):
            lines += textwrap.wrap(f"[{key}] {value}", WIDTH)
    return lines


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("scene", nargs="?", type=int, choices=sorted(SCENES))
    p.add_argument("--message")
    p.add_argument("--side", choices=["a", "b", "both"], default="both")
    p.add_argument("--session", help="reuse a session ID across turns")
    args = p.parse_args()
    if not args.scene and not args.message:
        p.error("give a scene number or --message")

    title, message = SCENES.get(args.scene, ("Free text", ""))
    message = args.message or message
    # >= 33 chars for AgentCore runtimeSessionId; letters, digits, hyphens for Atlas X-Session-ID.
    session = args.session or f"bakeoff-s{args.scene or 0}-{uuid.uuid4().hex}"

    sides = []
    if args.side in ("a", "both"):
        sides.append(SideA())
    if args.side in ("b", "both"):
        sides.append(SideB())

    print(f"\nScene {args.scene or '-'}: {title}\nCustomer: {message}\nSession: {session}\n")
    with ThreadPoolExecutor(len(sides)) as pool:
        replies = list(pool.map(lambda s: s.ask(message, session, CUSTOMER_ID), sides))

    cols = [column(r) for r in replies]
    height = max(len(c) for c in cols)
    for i in range(height):
        print("   ".join((c[i] if i < len(c) else "").ljust(WIDTH) for c in cols))
    print()
    sys.exit(1 if any(r.error for r in replies) else 0)


if __name__ == "__main__":
    main()
