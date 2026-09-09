# SentriX Backend API & Live Loop

Backend module for **SIH26146 — AI-Powered Monitoring & Analysis of Bitcoin
Transaction Traffic** (Team ZENITH). Covers Technical Architecture §3.7
(Live Monitoring & Rescoring Loop) and §3.9 (Backend API): REST endpoints,
JWT auth with role-based access control, audit logging, and the periodic
rescoring scheduler.

## Setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env
```

## Run

```bash
uvicorn app.main:app --reload --port 8000
```

Interactive API docs: http://127.0.0.1:8000/docs

## Demo users

| username | password | role | agency |
|---|---|---|---|
| admin | admin123 | admin | NTRO |
| investigator1 | investigate123 | investigator | NTRO |
| analyst1 | analyst123 | analyst | FIU-IND |

(See `app/db/users_store.py` — swap for a real user table post-hackathon.)

## Endpoints

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/health` | none | liveness check |
| POST | `/auth/login` | none | form body: `username`, `password` → JWT |
| GET | `/auth/me` | any role | current user's identity |
| GET | `/address/{id}/risk` | admin/investigator/analyst | fused risk score + contributing factors |
| GET | `/alerts?threshold=&limit=` | admin/investigator/analyst | addresses above a risk threshold |
| GET | `/graph/{id}?depth=` | admin/investigator/analyst | subgraph around an address |
| GET | `/traffic/status` | admin/investigator/analyst | capture mode + window stats |
| GET | `/traffic/anomalies?min_score=&limit=` | admin/investigator/analyst | ranked traffic anomalies |
| GET | `/traffic/{id}/correlation` | admin/investigator/analyst | explainable anomaly result (transaction or peer) |
| GET | `/traffic/{txid}/propagation` | admin/investigator/analyst | per-peer broadcast timeline (frontend viz) |
| GET | `/ai/status` | admin/investigator/analyst | AI enabled? provider / model |
| POST | `/ai/chat` | admin/investigator/analyst | SentriX AI assistant (tool-using) |
| GET | `/audit/logs?limit=` | admin only | who queried what, and when |

Every request (successful or not) is logged to `audit.log` as JSON lines:
timestamp, resolved user (or `anonymous`), method, path, status code.

## Live rescoring loop

`app/scheduler/rescoring.py` runs an APScheduler background job every
`RESCORE_INTERVAL_MINUTES` (default 5) that recomputes risk scores for
addresses touched by recent activity — not the whole graph, matching the
incremental-PPR-plus-GNN-inference design in Technical Architecture §3.7.
It logs a `rescoring_cycle` system event into the same audit log each run.

APScheduler is used in place of the architecture doc's "Celery beat / cron"
line item — same periodic-rescoring role, no Redis/worker infra needed for
a hackathon demo. Swapping to Celery beat later doesn't require touching
`risk_service.py` or any router.

## Integration points for the rest of the team

This module currently runs entirely on **mock data** so it's demoable
standalone. Two files are the integration seam:

- **`app/db/neo4j_client.py`** — wraps the Neo4j driver. Fill in `.env`
  (`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`) once the graph store
  (§3.3) is up; `run_query()` then hits the real database instead of
  raising "mock mode."
- **`app/services/risk_service.py`** — every function here (`get_address_risk`,
  `list_alerts`, `get_subgraph`, `rescore_neighborhood`) currently returns
  deterministic pseudo-random data. Replace each function body with the
  real call into the Graph Analysis Engine / Traffic Correlation Engine /
  Fusion Engine (§3.4–3.6), keeping the same signatures — no router or
  test needs to change.

## Traffic Correlation Engine (§3.5)

```
tshark / PCAP ─> TrafficCapture ─> TrafficEvent ─> TrafficCorrelationEngine
   ─> CorrelationResult (features + factors) ─> Fusion / Risk Service ─> REST / alerts
```

Bitcoin P2P traffic is captured, normalized to `TrafficEvent`s, held in a
bounded in-memory window (`TRAFFIC_WINDOW_SECONDS`, `TRAFFIC_MAX_EVENTS`), and
correlated per transaction / per peer into four heuristic, explainable,
deterministic features in `[0, 1]`:

| feature | what it measures |
|---|---|
| `broadcast_timing` | how compressed the propagation is across peers (many peers seeing a tx within `TRAFFIC_NEAR_SIMULTANEOUS_MS`) plus a lopsided-tail term |
| `burst_activity` | this tx's event volume vs. the median *other* tx in the window, and the overall window rate vs. `TRAFFIC_BURST_BASELINE_RATE` scaled by the tx's share |
| `peer_concentration` | low peer entropy / one dominant peer (`0.45·(1−normEntropy) + 0.55·dominantShare`) |
| `propagation_irregularity` | duplicate announcements, uneven inter-arrival gaps (coefficient of variation), fan-out above `TRAFFIC_EXPECTED_FANOUT`, compression |

`anomaly_score = Σ weightᵢ·featureᵢ / Σ weightᵢ` with configurable
`TRAFFIC_WEIGHT_*`. Each response carries `factors` — name, score, weight,
contribution and a plain-language `explanation` — so the score is auditable.
**Heuristic traffic anomalies are signals, not proof of malicious activity.**

### Modes

- **Demo (default)** — `TRAFFIC_CAPTURE_ENABLED=false`, no `PCAP_REPLAY_PATH`.
  The engine seeds deterministic fixtures (`tx-normal-001`, `tx-burst-001`,
  `tx-concentration-001`, `tx-irregular-001`, `tx-suspicious-001` — all clearly
  marked demo data). `/traffic/*` works with zero setup.
- **PCAP replay** — `PCAP_REPLAY_PATH=/path/to/capture.pcap` (parsed via
  `tshark -r`) or `.jsonl` of `TrafficEvent` lines. Falls back to demo fixtures
  if tshark is missing or the capture has no dissectable Bitcoin traffic.
- **Live tshark** — `TRAFFIC_CAPTURE_ENABLED=true` + `TSHARK_INTERFACE=<iface>`
  (a name like `eth0` on Linux, or the **number** from `tshark -D` on Windows).
  Runs `tshark -i <iface> -f "<filter>" -T ek -l -n` on a daemon thread (no
  `shell=True`, fixed argv). A missing tshark logs a clear error and the app
  still starts in demo mode.

  Live capture only yields packets if this host actually speaks the Bitcoin
  wire protocol. Run a node, or start the bundled passive listener alongside
  the backend:

  ```bash
  python scripts/btc_p2p_feed.py --peers 8      # genuine mainnet inv/tx/addr/ping
  ```

  `btc_p2p_feed.py` is read-only: it does the real version/verack handshake with
  DNS-seed peers (relay=1), answers `ping`, and never sends anything that could
  relay a transaction. It exists purely to give `tshark -f "tcp port 8333"`
  real traffic to see.

### Fusion & scheduler integration

- `risk_service._compute_address_risk()` now pulls its `traffic` component from
  `traffic_correlation.get_address_traffic_anomaly(address)`; if the engine has
  no data it keeps the previous deterministic fallback, so existing behaviour
  and tests are unchanged. *(Bitcoin traffic carries txids/peer IPs, not
  addresses — the address↔tx association is the graph/ingestion layer's job;
  until that index exists the adapter maps each address deterministically to one
  correlated transaction's profile.)*
- `rescoring.run_rescoring_cycle()` calls `traffic_correlation.refresh()` first
  (recompute the anomaly snapshot; a no-op on an empty window) and logs a
  `traffic_refresh` system event.

### Demo commands

```bash
uvicorn app.main:app --reload --port 8000          # demo mode
PCAP_REPLAY_PATH=./sample.pcap uvicorn app.main:app --port 8000   # replay a capture

# live: one terminal feeds real Bitcoin P2P traffic, the other captures it
python scripts/btc_p2p_feed.py --peers 10
TRAFFIC_CAPTURE_ENABLED=true TSHARK_INTERFACE=5 \
  TSHARK_PATH="C:\Program Files\Wireshark\tshark.exe" uvicorn app.main:app --port 8000
```

On Windows set env vars with `set VAR=value` (cmd) or `$env:VAR="value"`
(PowerShell) before `uvicorn`, or just put them in `backend/.env`.
`TSHARK_INTERFACE` is the **number** from `tshark -D` on Windows, an interface
name (`eth0`, `wlan0`) on Linux.

### Limitations

tshark must be installed for live/PCAP parsing (Wireshark 4.6 + Npcap 1.88
verified). Bitcoin P2P visibility is limited to what the Wireshark `bitcoin`
dissector exposes: message type always, txid from `inv` announcements (the first
vector entry per packet, internal byte order), nothing for encrypted BIP-324 v2
transport. `scripts/btc_p2p_feed.py` is a passive listener — it never relays a
transaction. The address↔tx association is still the ingestion layer's job (see
Fusion note above); anomaly detection is heuristic and the burst thresholds
(`TRAFFIC_BURST_*`) are tuned for the demo fixtures — raise them for a busy
multi-peer live capture.

## SentriX AI assistant (`/ai/chat`)

```
Next.js ──JWT──▶ POST /ai/chat ──▶ SentriX AI service
                     ▲                    │  system prompt + trimmed history + structured context
                     │                    ▼
                     │              AIProvider  (mock | openai-compatible)
                     │                    │  tool calls
                     │                    ▼
                     └──────────── tool layer (RBAC + arg validation)
                                          │  calls existing services only
                        risk_service · traffic_correlation · alerts · audit
```

A tool-using forensic assistant, not a chat clone. The model can only call the
registered SentriX tools (`get_address_risk`, `get_address_graph`,
`get_address_alerts`, `get_recent_alerts`, `get_dashboard_summary`,
`get_traffic_status`, `get_traffic_anomalies`, `get_transaction_correlation`,
`get_transaction_propagation`, `search_address/transaction`,
`get_crypto_price`, `get_coin_market_data`, `get_crypto_market_overview`
[live CoinGecko market data], `get_audit_context` [admin only], `emit_action`).
Each tool validates its arguments and enforces the
same roles as the equivalent REST endpoint; nothing else is reachable — no
URLs, shell, filesystem, code or Neo4j. Every `/ai/chat` request is audit-logged
(path by the middleware; an `ai_chat` system event records user, role,
conversation id, tools used and action types — never message content, tokens or
secrets).

- **Provider** — `AI_PROVIDER=mock` (default) needs no key and routes the
  message + context over the real tools, returning an evidence-grounded answer.
  `AI_PROVIDER=openai` + `AI_API_KEY` uses an OpenAI-compatible chat-completions
  API (`AI_BASE_URL` for Azure / local gateways). The key never reaches the
  browser. If a real provider is selected without a key, it falls back to mock.
- **Context** — the frontend sends a trimmed, structured snapshot (route,
  selected address/transaction/node, graph counts, role). The backend trusts
  the JWT role, not the client's.
- **Risk scale** — tools return 0–1 and also `*_100`; the assistant presents
  `87/100, HIGH`.
- **Navigation** — the model calls `emit_action` with a supported action
  (`navigate` to a known section id, `open_address`, `focus_graph_node`,
  `filter_risk`, `open_alert`); the frontend executes only those.
- **Injection resistance** — tool output is fenced as untrusted data; the
  system prompt forbids following instructions found inside it.
- **Market data** — `get_crypto_price` / `get_coin_market_data` /
  `get_crypto_market_overview` fetch live prices, market cap, dominance and ATH
  from CoinGecko (`app/services/market_data.py`: 60 s cache, tolerant
  ticker→id resolution, graceful `not configured` when `COINGECKO_API_KEY` is
  unset). The key lives only in `backend/.env`, is sent only as the
  `x-cg-(demo|pro)-api-key` header, and is never logged or returned to the model.

```bash
uvicorn app.main:app --reload --port 8000            # mock provider, no key
AI_PROVIDER=openai AI_API_KEY=sk-... uvicorn app.main:app --port 8000   # real LLM
```

## Tests

```bash
pytest
```

Traffic suite: `test_traffic_models`, `test_broadcast_timing`,
`test_burst_detection`, `test_peer_concentration`,
`test_propagation_irregularity`, `test_anomaly_scoring`, `test_tshark_parser`,
`test_pcap_replay`, `test_traffic_api`, `test_traffic_rbac`,
`test_fusion_integration` — covering empty/single/duplicate input, malformed
packets, huge timestamps, window/memory bounds, score `∈ [0,1]`, determinism,
auth, RBAC, audit logging and scheduler compatibility.
