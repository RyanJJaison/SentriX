"""
SentriX AI tool layer.

The model may ONLY call the tools registered here. Each tool:
  * validates its own arguments (address / txid format, clamped limits),
  * enforces the same RBAC as the equivalent REST endpoint,
  * calls the existing service — no business logic is duplicated,
  * returns a JSON-serializable dict `{"ok": bool, ...}`.

No tool touches the filesystem, the shell, arbitrary URLs, or Neo4j directly.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.ai.models import ACTION_TYPES, NAV_TARGETS
from app.models.schemas import UserPublic
from app.models.traffic import is_safe_id
from app.services import audit_service, market_data, risk_service, traffic_correlation

logger = logging.getLogger("ai.tools")

_ROLE_RANK = {"analyst": 1, "investigator": 2, "admin": 3}


class ToolError(Exception):
    """Bad arguments or a not-permitted call — reported to the model as data."""


def _clamp(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _require_id(args: dict[str, Any], key: str, label: str) -> str:
    raw = args.get(key)
    if not isinstance(raw, str) or not is_safe_id(raw):
        raise ToolError(f"{label} is missing or has an unsupported format")
    return raw


def _risk_level(score01: float) -> str:
    return "HIGH" if score01 >= 0.8 else "MEDIUM" if score01 >= 0.5 else "LOW"


def _to100(score01: float) -> int:
    return round(score01 * 100)


# --------------------------------------------------------------------------- #
# Tool implementations
# --------------------------------------------------------------------------- #


def _get_address_risk(args, user):  # noqa: ANN001
    address = _require_id(args, "address", "address")
    r = risk_service.get_address_risk(address)
    f = r.contributing_factors
    return {
        "ok": True,
        "address": address,
        "risk_score": r.risk_score,
        "risk_score_100": _to100(r.risk_score),
        "risk_level": _risk_level(r.risk_score),
        "last_updated": r.last_updated,
        "contributing_factors": {
            "gnn_score": f.gnn_score,
            "ppr_score": f.ppr_score,
            "traffic_anomaly_score": f.traffic_anomaly_score,
            "weights": f.weights,
        },
    }


def _get_address_alerts(args, user):  # noqa: ANN001
    address = _require_id(args, "address", "address")
    hits = [
        {
            "id": a.id,
            "address": a.address,
            "reason": a.reason,
            "risk_score": a.risk_score,
            "risk_score_100": _to100(a.risk_score),
            "flagged_at": a.flagged_at,
        }
        for a in risk_service.list_alerts(threshold=0.0, limit=200)
        if a.address == address
    ]
    return {"ok": True, "address": address, "alerts": hits, "count": len(hits)}


def _get_recent_alerts(args, user):  # noqa: ANN001
    limit = _clamp(args.get("limit"), 1, 50, 10)
    alerts = risk_service.list_alerts(threshold=0.8, limit=limit)
    return {
        "ok": True,
        "count": len(alerts),
        "alerts": [
            {
                "id": a.id,
                "address": a.address,
                "reason": a.reason,
                "risk_score_100": _to100(a.risk_score),
                "risk_level": _risk_level(a.risk_score),
            }
            for a in alerts
        ],
    }


def _get_address_graph(args, user):  # noqa: ANN001
    address = _require_id(args, "address", "address")
    depth = _clamp(args.get("depth"), 1, 3, 1)
    sub = risk_service.get_subgraph(address, depth=depth)
    return {
        "ok": True,
        "center": sub.center,
        "depth": sub.depth,
        "node_count": len(sub.nodes),
        "edge_count": len(sub.edges),
        "nodes": [
            {"id": n.id, "label": n.label, "risk_score_100": _to100(n.risk_score)}
            for n in sub.nodes
        ],
        "edges": [
            {"source": e.source, "target": e.target, "amount": e.amount, "tx_id": e.tx_id}
            for e in sub.edges
        ],
    }


def _get_transaction_details(args, user):  # noqa: ANN001
    txid = _require_id(args, "txid", "transaction id")
    result = traffic_correlation.engine.correlate_transaction(txid)
    if result is None:
        return {"ok": False, "error": f"No SentriX detail available for transaction {txid}"}
    return {"ok": True, **result.model_dump(mode="json")}


def _get_traffic_status(args, user):  # noqa: ANN001
    from app.capture.manager import capture_manager

    traffic_correlation.ensure_seeded()
    s = traffic_correlation.engine.stats()
    return {
        "ok": True,
        "mode": capture_manager.mode,
        "capture_running": capture_manager.running,
        "window_seconds": traffic_correlation.engine.window_seconds,
        **{k: v for k, v in s.items() if k not in ("oldest_event", "newest_event")},
    }


def _get_traffic_anomalies(args, user):  # noqa: ANN001
    traffic_correlation.ensure_seeded()
    min_score = args.get("min_score", 0.0)
    try:
        min_score = max(0.0, min(1.0, float(min_score)))
    except (TypeError, ValueError):
        min_score = 0.0
    limit = _clamp(args.get("limit"), 1, 50, 10)
    results = traffic_correlation.engine.detect_anomalies(min_score=min_score, limit=limit)
    return {
        "ok": True,
        "count": len(results),
        "anomalies": [r.model_dump(mode="json", exclude={"propagation"}) for r in results],
    }


def _get_transaction_correlation(args, user):  # noqa: ANN001
    txid = _require_id(args, "txid", "transaction id")
    traffic_correlation.ensure_seeded()
    result = traffic_correlation.engine.correlate_transaction(txid)
    if result is None:
        result = traffic_correlation.engine.score_peer(txid)
    if result is None:
        return {"ok": False, "error": f"No traffic observations for {txid} in the window"}
    return {"ok": True, **result.model_dump(mode="json")}


def _get_transaction_propagation(args, user):  # noqa: ANN001
    txid = _require_id(args, "txid", "transaction id")
    traffic_correlation.ensure_seeded()
    result = traffic_correlation.engine.correlate_transaction(txid)
    if result is None or result.propagation is None:
        return {"ok": False, "error": f"No propagation data for transaction {txid}"}
    return {"ok": True, **result.propagation.model_dump(mode="json")}


def _get_dashboard_summary(args, user):  # noqa: ANN001
    traffic_correlation.ensure_seeded()
    alerts = risk_service.list_alerts(threshold=0.8, limit=25)
    anomalies = traffic_correlation.engine.detect_anomalies(min_score=0.4, limit=5)
    stats = traffic_correlation.engine.stats()
    return {
        "ok": True,
        "high_risk_alert_count": len(alerts),
        "top_alerts": [
            {"address": a.address, "risk_score_100": _to100(a.risk_score), "reason": a.reason}
            for a in alerts[:5]
        ],
        "traffic": {
            "events_in_window": stats["event_count"],
            "transactions_in_window": stats["transaction_count"],
            "notable_anomalies": [
                {"txid": r.entity_id, "anomaly_score": r.anomaly_score, "top_factor": r.factors[0].name if r.factors else None}
                for r in anomalies
            ],
        },
    }


def _search_address(args, user):  # noqa: ANN001
    query = args.get("query", "")
    if not isinstance(query, str) or not is_safe_id(query):
        return {"ok": False, "error": "query is not a valid Bitcoin address / identifier"}
    return _get_address_risk({"address": query}, user)


def _search_transaction(args, user):  # noqa: ANN001
    query = args.get("query", "")
    if not isinstance(query, str) or not is_safe_id(query):
        return {"ok": False, "error": "query is not a valid transaction identifier"}
    return _get_transaction_correlation({"txid": query}, user)


def _get_audit_context(args, user):  # noqa: ANN001
    limit = _clamp(args.get("limit"), 1, 100, 20)
    entries = [e for e in audit_service.read_recent(limit=limit) if "status_code" in e]
    return {"ok": True, "count": len(entries), "recent_requests": entries}


def _emit_action(args, user):  # noqa: ANN001
    action_type = args.get("type")
    if action_type not in ACTION_TYPES:
        raise ToolError(f"unsupported action type {action_type!r}")
    target = args.get("target")
    payload = args.get("payload") if isinstance(args.get("payload"), dict) else None

    if action_type == "navigate":
        if target not in NAV_TARGETS:
            raise ToolError(f"unknown navigation target {target!r}")
    elif action_type in ("open_address", "focus_graph_node", "open_transaction", "open_alert"):
        if not isinstance(target, str) or not is_safe_id(target):
            raise ToolError(f"{action_type} needs a valid target id")
    elif action_type == "filter_risk":
        level = (payload or {}).get("level")
        if level not in ("high", "medium", "low", "all"):
            raise ToolError("filter_risk needs payload.level in high|medium|low|all")

    return {"ok": True, "action": {"type": action_type, "target": target, "payload": payload}}


# --------------------------------------------------------------------------- #
# Market data (CoinGecko) — live prices for the assistant, never touches
# SentriX's own data. Degrades to {"ok": False, ...} when unconfigured.
# --------------------------------------------------------------------------- #


def _coin_tokens(args: dict[str, Any], key: str = "coins", limit: int = 10) -> list[str]:
    raw = args.get(key, "")
    if isinstance(raw, list):
        parts = [str(x) for x in raw]
    else:
        parts = str(raw).replace(",", " ").split()
    tokens = [p.strip() for p in parts if p.strip() and is_safe_id(p.strip(), max_len=40)]
    if not tokens:
        raise ToolError(f"'{key}' must name at least one coin (symbol, name or CoinGecko id)")
    return tokens[:limit]


def _get_crypto_price(args, user):  # noqa: ANN001
    ids = market_data.resolve_coin_ids(_coin_tokens(args))
    if not ids:
        return {"ok": False, "error": "none of those names matched a known coin"}
    try:
        data = market_data.simple_price(ids, args.get("vs_currency", "usd"))
    except market_data.MarketDataError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "source": "coingecko", **data}


def _get_coin_market_data(args, user):  # noqa: ANN001
    ids = market_data.resolve_coin_ids(_coin_tokens(args, "coin", limit=5))
    if not ids:
        return {"ok": False, "error": "that name did not match a known coin"}
    try:
        rows = market_data.coin_markets(ids, args.get("vs_currency", "usd"))
    except market_data.MarketDataError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "source": "coingecko", "count": len(rows), "coins": rows}


def _get_crypto_market_overview(args, user):  # noqa: ANN001
    try:
        data = market_data.global_overview()
    except market_data.MarketDataError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "source": "coingecko", **data}


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #


class Tool:
    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        run: Callable[[dict[str, Any], UserPublic], dict[str, Any]],
        min_role: str = "analyst",
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self._run = run
        self.min_role = min_role

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


_ADDR = {"address": {"type": "string", "description": "Bitcoin address"}}
_TXID = {"txid": {"type": "string", "description": "transaction id"}}
_LIMIT = {"limit": {"type": "integer", "description": "max results"}}

TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool("get_address_risk", "Fused risk score + contributing factors for an address.", _obj(_ADDR, ["address"]), _get_address_risk),
        Tool("get_address_alerts", "Risk alerts raised for a specific address.", _obj(_ADDR, ["address"]), _get_address_alerts),
        Tool("get_recent_alerts", "The most recent high-risk alerts across the system.", _obj(_LIMIT), _get_recent_alerts),
        Tool("get_address_graph", "Transaction sub-graph around an address.", _obj({**_ADDR, "depth": {"type": "integer"}}, ["address"]), _get_address_graph),
        Tool("get_transaction_details", "Best-available SentriX detail for a transaction.", _obj(_TXID, ["txid"]), _get_transaction_details),
        Tool("get_traffic_status", "Traffic Correlation Engine capture mode + window stats.", _obj({}), _get_traffic_status),
        Tool("get_traffic_anomalies", "Ranked traffic anomalies in the current window.", _obj({**_LIMIT, "min_score": {"type": "number"}}), _get_traffic_anomalies),
        Tool("get_transaction_correlation", "Explainable traffic-anomaly result for a transaction or peer.", _obj(_TXID, ["txid"]), _get_transaction_correlation),
        Tool("get_transaction_propagation", "Per-peer broadcast timeline for a transaction.", _obj(_TXID, ["txid"]), _get_transaction_propagation),
        Tool("get_dashboard_summary", "Concise summary of the current investigation dashboard.", _obj({}), _get_dashboard_summary),
        Tool("search_address", "Look up an address by identifier.", _obj({"query": {"type": "string"}}, ["query"]), _search_address),
        Tool("search_transaction", "Look up a transaction by identifier.", _obj({"query": {"type": "string"}}, ["query"]), _search_transaction),
        Tool("get_audit_context", "Recent audited API requests (admin only).", _obj(_LIMIT), _get_audit_context, min_role="admin"),
        Tool(
            "get_crypto_price",
            "Live spot price, market cap, 24h volume and 24h change for one or "
            "more coins (CoinGecko). `coins` is a comma-separated list of tickers, "
            "names or CoinGecko ids, e.g. \"btc, eth, solana\".",
            _obj({"coins": {"type": "string"}, "vs_currency": {"type": "string", "description": "fiat/quote currency, default usd"}}, ["coins"]),
            _get_crypto_price,
        ),
        Tool(
            "get_coin_market_data",
            "Detailed market snapshot for a coin: rank, ath, 1h/24h/7d change, "
            "24h high/low, circulating & total supply (CoinGecko).",
            _obj({"coin": {"type": "string"}, "vs_currency": {"type": "string"}}, ["coin"]),
            _get_coin_market_data,
        ),
        Tool(
            "get_crypto_market_overview",
            "Whole-market snapshot: total market cap, 24h volume, BTC/ETH "
            "dominance, 24h market-cap change (CoinGecko /global).",
            _obj({}),
            _get_crypto_market_overview,
        ),
        Tool(
            "emit_action",
            "Request a supported UI action instead of describing a URL. "
            "For type=navigate, target MUST be exactly one of: "
            + ", ".join(NAV_TARGETS)
            + ". For open_address/focus_graph_node, target is the address; for "
            "open_transaction, target is the txid; for open_alert, target is the "
            "alert id; for filter_risk, set payload.level to high|medium|low|all.",
            _obj(
                {
                    "type": {"type": "string", "enum": list(ACTION_TYPES)},
                    "target": {"type": "string"},
                    "payload": {"type": "object"},
                },
                ["type"],
            ),
            _emit_action,
        ),
    ]
}


def tool_schemas(role: str) -> list[dict[str, Any]]:
    return [t.schema() for t in TOOLS.values() if _ROLE_RANK.get(role, 0) >= _ROLE_RANK[t.min_role]]


def execute_tool(name: str, arguments: dict[str, Any], user: UserPublic) -> dict[str, Any]:
    """Validate + RBAC-check + run a tool. Never raises to the caller."""
    tool = TOOLS.get(name)
    if tool is None:
        return {"ok": False, "error": f"unknown tool {name!r}"}
    if _ROLE_RANK.get(user.role, 0) < _ROLE_RANK[tool.min_role]:
        return {"ok": False, "error": f"role '{user.role}' may not use {name}"}
    if not isinstance(arguments, dict):
        return {"ok": False, "error": "tool arguments must be an object"}
    try:
        return tool._run(arguments, user)
    except ToolError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception:  # noqa: BLE001 - a tool failure is data, not a 500
        logger.exception("tool %s failed", name)
        return {"ok": False, "error": f"{name} could not retrieve the requested data"}
