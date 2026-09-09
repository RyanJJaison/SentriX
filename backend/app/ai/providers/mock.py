"""
Deterministic, key-free provider. It routes the user's message + SentriX context
to the real tool layer and synthesizes an evidence-grounded answer from the
results — SentriX-aware, never a generic chat clone, fully testable.

Two `generate()` steps mirror a real tool-using model:
  pass 1  -> decide which tools to call
  pass 2  -> write the final answer from the (untrusted) tool outputs
"""
from __future__ import annotations

import json
import re

from app.ai.models import ChatTurn, ProviderResult, ProviderToolCall

_NAV_KEYWORDS = [
    (("graph view", "graph"), "graph-view"),
    (("traffic", "anomal", "propagation"), "graph-view"),
    (("explainab",), "explainability"),
    (("recent activity", "transaction activity", "activity feed"), "activity"),
    (("alert",), "alerts"),
    (("risk overview", "risk gauge"), "risk-overview"),
    (("dashboard", "overview", "home", "main screen", "start"), "overview"),
]

_KNOWLEDGE = {
    ("what is bitcoin", "explain bitcoin"): (
        "Bitcoin is a decentralized peer-to-peer payment network. Transactions "
        "spend unspent outputs (UTXOs) and are grouped into blocks roughly every "
        "10 minutes by miners; more confirmations mean a transaction is harder to "
        "reverse. (General knowledge, not live SentriX data.)"
    ),
    ("utxo", "unspent"): (
        "A UTXO is an Unspent Transaction Output — a discrete chunk of bitcoin "
        "locked to a script. A transaction consumes one or more UTXOs as inputs "
        "and creates new UTXOs as outputs; the difference is the miner fee. "
        "(General knowledge.)"
    ),
    ("propagation", "relay", "gossip"): (
        "When a wallet broadcasts a transaction, its node announces it (`inv`) to "
        "peers, who request (`getdata`) and forward it. SentriX's Traffic "
        "Correlation Engine watches this gossip for compressed timing, bursts, "
        "peer concentration and irregular fan-out. (General + SentriX method.)"
    ),
    ("how does sentrix", "risk model", "calculate risk", "score risk"): (
        "SentriX fuses three components into one address risk score: a GNN score "
        "(learned graph structure), a Personalized-PageRank score (proximity to "
        "known-bad clusters) and a traffic-anomaly score (network-propagation "
        "irregularities). The weighted blend is shown as X/100 with a HIGH / "
        "MEDIUM / LOW level and an explainability breakdown."
    ),
    ("gnn", "pagerank", "ppr"): (
        "GNN risk comes from a graph neural network over the transaction graph; "
        "Personalized PageRank measures how much probability mass flows to an "
        "address from seed 'bad' nodes; the traffic component is independent and "
        "comes from P2P propagation analysis. They are combined by fixed weights."
    ),
}

_ADDR_RE = re.compile(r"\b((?:bc1|tb1)[a-z0-9]{8,}|[13][A-Za-z0-9]{20,}|1MockAddr\d{4}|1Sentrix[A-Za-z0-9]+)\b")
_TX_RE = re.compile(r"\b(tx-[a-z0-9-]{3,}|[0-9a-fA-F]{16,64})\b")


def _last_user(turns: list[ChatTurn]) -> str:
    for t in reversed(turns):
        if t.role == "user":
            return t.content
    return ""


def _context(turns: list[ChatTurn]) -> dict:
    for t in turns:
        if t.role == "system" and t.content.startswith("Current SentriX context"):
            ctx: dict = {}
            for line in t.content.splitlines()[1:]:
                if line.startswith("- ") and ": " in line:
                    key, _, val = line[2:].partition(": ")
                    try:
                        ctx[key] = json.loads(val)
                    except json.JSONDecodeError:
                        ctx[key] = val
            return ctx
    return {}


def _tool_outputs(turns: list[ChatTurn]) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for t in turns:
        if t.role != "tool":
            continue
        body = ""
        for line in t.content.splitlines():
            if line and not line.startswith("<<") and not line.startswith("The block above"):
                body = line
                break
        try:
            out.append((t.name or "tool", json.loads(body)))
        except json.JSONDecodeError:
            out.append((t.name or "tool", {"ok": False, "error": "unparseable tool output"}))
    return out


def _pick_address(msg: str, ctx: dict) -> str | None:
    if ctx.get("selected_address"):
        return ctx["selected_address"]
    if isinstance(ctx.get("selected_node"), dict) and ctx["selected_node"].get("id"):
        return ctx["selected_node"]["id"]
    if ctx.get("graph_context", {}).get("focus_address"):
        return ctx["graph_context"]["focus_address"]
    m = _ADDR_RE.search(msg)
    return m.group(1) if m else None


def _pick_txid(msg: str, ctx: dict) -> str | None:
    if ctx.get("selected_transaction"):
        return ctx["selected_transaction"]
    m = _TX_RE.search(msg)
    return m.group(1) if m else None


class MockProvider:
    name = "mock"

    async def generate(self, turns: list[ChatTurn], tools: list[dict]) -> ProviderResult:  # noqa: ARG002
        msg = _last_user(turns)
        low = msg.lower()
        ctx = _context(turns)
        done = _tool_outputs(turns)

        if not done:
            calls = self._plan(low, ctx)
            if calls:
                return ProviderResult(text="", tool_calls=calls)
            return ProviderResult(text=self._knowledge_or_help(low))

        return ProviderResult(text=self._answer(low, ctx, done))

    # -- pass 1 -------------------------------------------------------------- #

    def _plan(self, low: str, ctx: dict) -> list[ProviderToolCall]:
        if any(w in low for w in ("open ", "go to", "take me to", "navigate", "show me the", "bring up")):
            for keys, target in _NAV_KEYWORDS:
                if any(k in low for k in keys):
                    return [ProviderToolCall("c1", "emit_action", {"type": "navigate", "target": target})]

        address = _pick_address(low, ctx)
        txid = _pick_txid(low, ctx)

        if any(w in low for w in ("summar", "dashboard situation", "situation", "brief me", "overview of")):
            return [ProviderToolCall("c1", "get_dashboard_summary", {})]

        if any(w in low for w in ("audit", "who queried", "who accessed")):
            return [ProviderToolCall("c1", "get_audit_context", {"limit": 20})]

        if txid and any(w in low for w in ("traffic", "anomal", "propagation", "burst", "peer concentration", "suspicious")):
            calls = [ProviderToolCall("c1", "get_transaction_correlation", {"txid": txid})]
            if "propagation" in low:
                calls.append(ProviderToolCall("c2", "get_transaction_propagation", {"txid": txid}))
            return calls

        if any(w in low for w in ("traffic", "anomal", "propagation pattern", "unusual propagation")):
            return [
                ProviderToolCall("c1", "get_traffic_anomalies", {"limit": 5}),
                ProviderToolCall("c2", "get_traffic_status", {}),
            ]

        if address and any(w in low for w in ("connected", "related", "counterpart", "flow", "graph", "neighbou")):
            return [ProviderToolCall("c1", "get_address_graph", {"address": address, "depth": 1})]

        if address and any(w in low for w in ("risk", "risky", "suspicious", "why", "score", "flag", "dangerous")):
            return [
                ProviderToolCall("c1", "get_address_risk", {"address": address}),
                ProviderToolCall("c2", "get_address_alerts", {"address": address}),
            ]

        if address:
            return [ProviderToolCall("c1", "get_address_risk", {"address": address})]

        if any(w in low for w in ("alert", "flagged", "high-risk address", "high risk address")):
            return [ProviderToolCall("c1", "get_recent_alerts", {"limit": 8})]

        return []

    # -- pass 2 -------------------------------------------------------------- #

    def _knowledge_or_help(self, low: str) -> str:
        for keys, text in _KNOWLEDGE.items():
            if any(k in low for k in keys):
                return text
        return (
            "I'm SentriX AI. I can explain an address's risk, list recent alerts, "
            "walk a transaction graph, interpret traffic anomalies, summarise the "
            "dashboard, or take you to a section. Try: “Why is this address "
            "risky?”, “Show recent alerts”, or “Summarise my "
            "dashboard”."
        )

    def _answer(self, low: str, ctx: dict, done: list[tuple[str, dict]]) -> str:  # noqa: ARG002, C901
        by_name = {name: data for name, data in done}
        parts: list[str] = []
        evidence: list[str] = []

        if "emit_action" in by_name:
            act = by_name["emit_action"].get("action", {})
            t = act.get("type")
            tgt = act.get("target") or (act.get("payload") or {}).get("level") or ""
            verb = {"navigate": "Opening", "open_address": "Opening address", "open_transaction": "Opening transaction",
                    "focus_graph_node": "Focusing the graph on", "filter_risk": "Filtering risk to",
                    "open_alert": "Opening alert"}.get(t, "Doing")
            return f"{verb} {tgt}.".replace("  ", " ")

        r = by_name.get("get_address_risk")
        if r and r.get("ok"):
            f = r["contributing_factors"]
            parts.append(
                f"Address `{r['address']}` is **{r['risk_level']}** risk — "
                f"**{r['risk_score_100']}/100**. That fuses a GNN score of "
                f"{round(f['gnn_score'] * 100)}/100 (weight {f['weights'].get('gnn')}), "
                f"Personalized PageRank {round(f['ppr_score'] * 100)}/100 "
                f"(weight {f['weights'].get('ppr')}) and a traffic-anomaly score of "
                f"{round(f['traffic_anomaly_score'] * 100)}/100 (weight {f['weights'].get('traffic')})."
            )
            evidence += [
                f"Risk score       {r['risk_score_100']}/100",
                f"Risk level       {r['risk_level']}",
                f"Traffic anomaly  {round(f['traffic_anomaly_score'] * 100)}/100",
            ]

        a = by_name.get("get_address_alerts")
        if a and a.get("ok"):
            if a["count"]:
                parts.append(
                    f"{a['count']} alert(s) name this address: "
                    + "; ".join(f"{x['reason']} ({x['risk_score_100']}/100)" for x in a["alerts"][:3])
                    + "."
                )
                evidence.append(f"Alerts           {a['count']}")
            else:
                parts.append("No alerts currently name this address.")

        g = by_name.get("get_address_graph")
        if g and g.get("ok"):
            parts.append(
                f"Its sub-graph (depth {g['depth']}) has {g['node_count']} nodes and "
                f"{g['edge_count']} edges. Direct counterparts: "
                + ", ".join(f"`{n['id']}` ({n['risk_score_100']}/100)" for n in g["nodes"][:4] if n["id"] != g["center"])
                + "."
            )
            evidence += [f"Connected nodes  {g['node_count']}", f"Edges            {g['edge_count']}"]

        tc = by_name.get("get_transaction_correlation")
        if tc and tc.get("ok"):
            top = tc["factors"][0] if tc.get("factors") else None
            parts.append(
                f"Transaction `{tc['entity_id']}` has a traffic-anomaly score of "
                f"**{round(tc['anomaly_score'] * 100)}/100** (confidence "
                f"{round(tc['confidence'] * 100)}%), from {tc['event_count']} events across "
                f"{tc['peer_count']} peers."
                + (f" Strongest signal: **{top['name']}** ({round(top['score'] * 100)}/100) — {top['explanation']}" if top else "")
            )
            feats = tc.get("features", {})
            evidence += [f"{k:<24}{round(v * 100)}/100" for k, v in feats.items()]

        pr = by_name.get("get_transaction_propagation")
        if pr and pr.get("ok"):
            parts.append(
                f"Propagation spanned {pr['propagation_duration_ms']:.0f} ms across "
                f"{pr['peer_count']} peers (median delay {pr['median_delay_ms']:.0f} ms, "
                f"p95 {pr['p95_delay_ms']:.0f} ms)."
            )

        an = by_name.get("get_traffic_anomalies")
        if an and an.get("ok"):
            if an["count"]:
                parts.append(
                    "Top traffic anomalies: "
                    + "; ".join(
                        f"`{x['entity_id']}` {round(x['anomaly_score'] * 100)}/100"
                        f" ({x['factors'][0]['name'] if x.get('factors') else 'n/a'})"
                        for x in an["anomalies"][:4]
                    )
                    + "."
                )
            else:
                parts.append(
                    "No traffic anomalies are currently available — the correlation "
                    "window does not contain enough captured events."
                )

        ts = by_name.get("get_traffic_status")
        if ts and ts.get("ok"):
            evidence.append(
                f"Traffic window   {ts.get('event_count', 0)} events / "
                f"{ts.get('transaction_count', 0)} txs ({ts.get('mode')})"
            )

        al = by_name.get("get_recent_alerts")
        if al and al.get("ok"):
            parts.append(
                f"{al['count']} recent high-risk alerts. Highest: "
                + "; ".join(f"`{x['address']}` {x['risk_score_100']}/100 ({x['risk_level']})" for x in al["alerts"][:4])
                + "."
            )

        ds = by_name.get("get_dashboard_summary")
        if ds and ds.get("ok"):
            t = ds["traffic"]
            parts.append(
                "**Current situation**\n"
                f"• {ds['high_risk_alert_count']} high-risk alerts need attention.\n"
                f"• Traffic monitoring is watching {t['transactions_in_window']} transactions "
                f"({t['events_in_window']} events); {len(t['notable_anomalies'])} notable anomalies.\n\n"
                "**Priority**\n"
                + "".join(
                    f"{i}. `{x['address']}` — {x['risk_score_100']}/100 ({x['reason']})\n"
                    for i, x in enumerate(ds["top_alerts"][:3], 1)
                )
                + (
                    f"\n**Recommended next step**\nInvestigate `{ds['top_alerts'][0]['address']}` "
                    "and trace its counterparties in Graph View."
                    if ds["top_alerts"]
                    else ""
                )
            )

        au = by_name.get("get_audit_context")
        if au and au.get("ok"):
            parts.append(f"The audit log holds {au['count']} recent API requests (admin view).")
        elif au and not au.get("ok"):
            parts.append(f"Audit context unavailable: {au.get('error')}")

        if not parts:
            failed = [d.get("error") for _, d in done if not d.get("ok") and d.get("error")]
            if failed:
                return f"I couldn't retrieve that: {failed[0]}."
            return self._knowledge_or_help(low)

        answer = " ".join(parts)
        if evidence:
            answer += "\n\nEvidence\n──────────\n" + "\n".join(evidence)
        return answer
