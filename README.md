# Card Agent Bake-off

One LangGraph credit card agent for a fictional bank (Harbourline Bank), deployed twice:

- **Side A**: AWS Bedrock AgentCore Runtime + AgentCore Memory, bank data in Aurora PostgreSQL
- **Side B**: MongoDB Atlas Agent Engine + its memory, bank data in the same Atlas cluster

Same graph, prompt, tools, model (Claude via the Anthropic API) and seed data. Only the platform changes. The five demo scenes match the click-through simulation.

```
shared/bakeoff/          the agent: graph, prompt, tools, interfaces   <- edit here only
data/seed.json           customer, card, dispute, offer, procedures, glossary
side_a_agentcore/
  app/card_agent/        AgentCore entrypoint, Aurora + AgentCore Memory adapters
  scripts/               schema, seeding, memory setup
  stale_sync/            Scene 2 pipeline: Aurora trigger -> Lambda -> delete memory
side_b_atlas/
  project-config.yaml    memory config (all four memory types)
  agents/card-agent/     agent.yaml, entrypoint, Atlas + memory adapters
  scripts/               seeding, change-stream watcher, audit join
demo/                    run scenes on both sides, freeze card, measure context
scripts/sync_shared.sh   copies shared/bakeoff into both agents and diffs them
tests/                   offline tests (no cloud needed)
```

---

## 0. Prerequisites

| Need | For |
|---|---|
| Python 3.11+, Node 20+, Docker | both CLIs, local runs |
| AWS account + credentials, AgentCore CLI (`npm install -g @aws/agentcore`) | Side A |
| Atlas account, `agentengine` CLI (see step 2.0) | Side B |
| Anthropic API key, Voyage AI key | model on both sides, Atlas memory embeddings |

```bash
cp .env.example .env    # fill it in as you go
set -a; source .env; set +a
pip install -r demo/requirements.txt
./scripts/sync_shared.sh   # prints "OK: both sides run the same agent code"
```

**Watch:** `ANTHROPIC_MODEL`, `MAX_CONTEXT_TOKENS` and `VERIFY_BEFORE_OFFER` must be identical on both sides. That's the fairness contract.

---

## 1. Deploy Side A (AgentCore)

**1.1 Check the region.** Confirm AgentCore Runtime and Memory are offered in the region, e.g. `ap-southeast-1` (AgentCore console). If not, use the nearest supported region for Side A.

**1.2 Create the bank database.** Create an Aurora PostgreSQL cluster (database `harbourline`), put its connection settings in `.env`, then:
```bash
python side_a_agentcore/scripts/seed_aurora.py --reset
```
Connection settings:
`BANK_PG_IAM_AUTH=true` with `BANK_PG_HOST` (plus optional `BANK_PG_PORT`, `BANK_PG_DBNAME`, `BANK_PG_USER`): IAM database auth. A fresh token is generated for every connection, so nothing expires mid-demo.

**1.3 Scaffold and drop in the agent.**
```bash
agentcore create --project-name CardAgentA --name CardAgent --framework LangChain_LangGraph \
  --model-provider Anthropic --api-key "$ANTHROPIC_API_KEY" --memory longAndShortTerm \
  --network-mode PUBLIC
cp -R side_a_agentcore/app/card_agent/* CardAgentA/app/CardAgent/
```
Why PUBLIC mode: this setup uses Aurora express configuration, which has no VPC. The runtime reaches Aurora over the internet, and IAM database auth (`BANK_PG_IAM_AUTH=true`) is the access control. 

**1.3b Give the runtime its settings and permissions.**
```bash
python side_a_agentcore/scripts/configure_runtime.py && (cd CardAgentA && agentcore validate)
```
This copies the settings from `.env` into `CardAgentA/agentcore/agentcore.json` and writes `CardAgentA/app/CardAgent/runtime-policy.json`, which gives the runtime's IAM role what `agentcore deploy` leaves out: `rds-db:connect` for Aurora, `BatchCreate`/`BatchDeleteMemoryRecords`, and searching the `/bakeoff/*` and `/episodes/<customer>` memory namespaces. Run it again whenever you change `.env`.

**1.4 Deploy, then wire memory.**

Deploy, and note the memory ID or ARN that `status` prints:
```bash
cd CardAgentA
agentcore deploy
agentcore status --type memory
cd ..
```
Record the memory's namespaces and copy them into the agent:
```bash
python side_a_agentcore/scripts/describe_memory.py --memory-id <id or ARN>
cp side_a_agentcore/app/card_agent/memory_config.json CardAgentA/app/CardAgent/
```
Deploy again so the agent ships with `memory_config.json`:
```bash
cd CardAgentA
agentcore deploy
cd ..
```
Why: `describe_memory.py` records which namespace each built-in strategy writes to, and prints the Scene 1 security facts (key type, event expiry).

**1.5 Seed memory and smoke-test.**
```bash
python side_a_agentcore/scripts/seed_memory.py --reset
export SIDE_A_RUNTIME_ARN=<from agentcore status>
python demo/run_scene.py --side a --message "Hi, what card do I have?"
```

**1.6 (Scene 2 only) Stale-memory pipeline.** Deploy `stale_sync/handler.py` as Lambda `card-agent-stale-sync`, attach an IAM role to the Aurora cluster that allows `lambda:InvokeFunction`, then run `stale_sync/aurora_trigger.sql`. Keep it switched off for the first half of Scene 2.

---

## 2. Deploy Side B (Atlas Agent Engine)

**2.0 Install the `agentengine` CLI.** It isn't on npm or pip. Sign in at https://agentengine.mongodb.com/download-cli, pick **Linux x86_64** (also for WSL; there's no Windows build) and copy the SHA-256 checksum the page shows. Then:
```bash
cd ~/Downloads                    # WSL with a Windows browser: /mnt/c/Users/<you>/Downloads
sha256sum agentengine             # must match the checksum on the download page
chmod +x agentengine
mkdir -p ~/.local/bin && mv agentengine ~/.local/bin/
echo "$PATH" | tr ':' '\n' | grep -qx "$HOME/.local/bin" \
  || { echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc; source ~/.bashrc; }
agentengine version
```
**Watch:** the CLI needs Docker with Compose v2 (`docker compose version`). With Docker Desktop on Windows, turn on WSL integration for your distro. In WSL, log in with `agentengine auth login --no-browser` and open the printed URL in your Windows browser.

**2.1 Scaffold and drop in the agent.**
```bash
agentengine auth login
agentengine create          # LangGraph + Python, Hello World template, Anthropic, memory: yes
A=<project>/agents/<agent>
cp -R side_b_atlas/agents/card-agent/{card_agent,bakeoff} $A/src/
```
Then merge three files by hand, because the scaffold's versions carry values you must keep:
- **`$A/agent.yaml`:** take ours, but keep the scaffold's `name`. That's the slug the platform registered.
- **`$A/pyproject.toml`:** add our extra dependencies (`langgraph`, `langchain-core`, `pymongo`). Set the wheel `packages` to `["src/card_agent", "src/bakeoff"]`, and point `[project.scripts]` at `card_agent.main:main`.
- **`<project>/project-config.yaml`:** the scaffold's values already match ours: Voyage embeddings, Claude extraction through `LLM_API_KEY`, and procedural plus taxonomic extraction. Keep it, and check that it still matches.

Check the result with `agentengine agent validate` from `$A`.
**Watch:** with LangGraph + Python, the scaffold uses a `src/` layout. The `entrypoint` (`card_agent.main:app`) has no `src.` prefix. Keep the scaffold's own `src/agent_<name>/` package, because nothing imports it.

**2.2 Link the cluster and set secrets.** From the agent directory:
```bash
agentengine init
agentengine atlas setup                       # pick or create the cluster; stores MONGODB_URI
agentengine secret set VOYAGE_API_KEY        # project-scoped by default
agentengine secret set LLM_API_KEY --sync    # Anthropic key: the agent and memory extraction both read it
agentengine memory configure && agentengine memory apply
```
Use an M10 or larger cluster in AWS Singapore. Database auditing, which Scene 1 relies on, needs a dedicated tier.
**Watch:** if the deployed agent can't reach the bank collections, run `agentengine atlas link` so the cluster is on the agent's egress policy.

**2.3 Seed and deploy.**
```bash
python side_b_atlas/scripts/seed_atlas.py --reset
agentengine deploy --auto                     # 10 to 20 minutes the first time
agentengine service-account create bakeoff --role PROJECT_OWNER   # save client ID/secret in .env
agentengine secret set AE_CLIENT_ID --sync       # the agent reads per-customer memory as this service account
agentengine secret set AE_CLIENT_SECRET --sync
agentengine deploy                               # pick up the two new secrets
pip install agent-engine-sdk-memory              # on PyPI
python side_b_atlas/scripts/seed_memory.py    # run once (procedures are create-only)
```

**2.4 Learn the memory schema (one time).**
```bash
python side_b_atlas/scripts/audit_join.py --inspect
```
Why: the memory collection layout isn't documented in the preview. Put the semantic collection name, user field and text field into `.env` (`MEMORY_SEMANTIC_COLL`, `MEMORY_USER_FIELD`, `MEMORY_TEXT_FIELD`).
**Optional:** set `MONGOMEM_DB_NAME=harbourline` before deploying so memory lives in the bank database. Then the Scene 2 audit runs as a single `$lookup`.

**2.5 Smoke-test.** Set `AE_PROJECT_ID` and `AE_WORKSPACE_ID` (from `agentengine workspace list`), then:
```bash
python demo/run_scene.py --side b --message "Hi, what card do I have?"
```

---

## 3. Run the demo

Each scene prints both replies side by side with latency. Scene numbers match the simulation.

**Scene 1 · Where memory lives**
```bash
python demo/run_scene.py 1
python demo/where_memory_lives.py
```
Watch: Side A prints two systems (Aurora row, AgentCore records via API). Side B prints the account and the memory documents from one cluster connection.

**Scene 2 · Fraud freeze**
```bash
python side_b_atlas/scripts/stale_watcher.py &     # Side B freshness, same cluster
python demo/freeze_card.py --status frozen
python demo/run_scene.py 2                         # Side A repeats the stale offer
python side_b_atlas/scripts/audit_join.py          # one query: held customers whose memory still has an offer
```
Then enable the Side A trigger and Lambda (step 1.6), reset with `--status active`, re-seed the offer, and freeze again to show Side A also fixed, at the cost of five extra moving parts.
For the "obvious challenge", redeploy both sides with `VERIFY_BEFORE_OFFER=true` and compare tool calls and latency.
Reset afterwards: `python demo/freeze_card.py --status active`, then restore the offer with `seed_memory.py --offer-only` on each side.

**Scene 3 · Fee-waiver procedure**
```bash
python demo/run_scene.py 3
```
Watch: both should call `find_procedure` then `apply_fee_waiver`. Side A reads it from a namespace you designed; Side B from built-in procedural memory.

**Scene 4 · Bank vocabulary**
```bash
python demo/run_scene.py 4
```

**Scene 5 · Context assembly**
```bash
python demo/run_scene.py 5
python demo/measure_context.py
```
Watch: quote these measured tokens and latencies, not the simulation's placeholders.

---

## 4. Verify before a customer sees it

1. **Side B SDK names.** `app.prepare_agent_input`, `app.memory.build_context(max_tokens=...)`, `discover_procedures`, `search_taxonomic(visibility="org")` follow the preview docs. Run `python demo/run_scene.py 3 --side b` early.
2. **Side B memory identity.** The platform auto-records turns under the caller's identity (the service account). The agent writes customer facts with `user_id=customer_id` explicitly, so customer memory is consistent across sides. Auto-extracted memories won't appear under the customer ID.
3. **Extraction is asynchronous on both sides.** A fact said in Scene 1 shows up in long-term memory minutes later. Scene 5 relies on the explicit `remember_customer_fact` write, so it works immediately.
4. **Side A memory ID variable.** `memory_agentcore.py` looks for `AGENTCORE_MEMORY_ID`, `MEMORY_ID`, any `MEMORY_*_ID`, then `memory_config.json`.
5. **Model ID.** `claude-sonnet-5-5` by default. Check it's available on your Anthropic account.
6. **Public preview.** Atlas Agent Engine is for evaluation and prototyping, not production. Present this as a POC.

## 5. Tests

```bash
pip install langgraph langchain-core boto3
python tests/test_local.py      # shared graph end to end with a scripted model
python tests/test_adapters.py   # both memory adapters against fake clients
```
