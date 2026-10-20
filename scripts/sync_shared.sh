#!/usr/bin/env bash
# Copy the shared agent package into both deployable agents.
# Run after every change to shared/bakeoff, before deploying either side.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

for dest in \
  "$ROOT/side_a_agentcore/app/card_agent/bakeoff" \
  "$ROOT/side_b_atlas/agents/card-agent/bakeoff"; do
  rm -rf "$dest"
  cp -R "$ROOT/shared/bakeoff" "$dest"
  find "$dest" -name '__pycache__' -prune -exec rm -rf {} +
  echo "synced -> ${dest#$ROOT/}"
done

# Identical code on both sides is the point of the demo. Prove it:
diff -r "$ROOT/side_a_agentcore/app/card_agent/bakeoff" "$ROOT/side_b_atlas/agents/card-agent/bakeoff" \
  && echo "OK: both sides run the same agent code"
