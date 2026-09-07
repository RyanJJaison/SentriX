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

## Tests

```bash
pytest
```
