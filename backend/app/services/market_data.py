"""
CoinGecko market-data client — the source for the assistant's live crypto
price / market tools (`app/ai/tools.py`).

Design notes:
  * Synchronous `httpx` with a tight timeout. The AI tool loop calls tools
    synchronously; a single-tenant investigator backend can afford a short
    blocking call, and a 60 s in-process cache keeps us well under CoinGecko's
    free-tier rate limit (~30 req/min).
  * The API key is read from settings (backend/.env) and sent only as the
    documented header. It is never logged or returned to the model.
  * Every failure raises `MarketDataError`; the tool layer turns that into
    `{"ok": False, "error": ...}` so the assistant degrades gracefully.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

from app.core.config import settings

log = logging.getLogger("market_data")

_DEMO_BASE = "https://api.coingecko.com/api/v3"
_PRO_BASE = "https://pro-api.coingecko.com/api/v3"

_CACHE_TTL_S = 60.0
_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()

# Tests set this to an httpx.MockTransport; None => real network.
_TRANSPORT: httpx.BaseTransport | None = None

# Common ticker -> CoinGecko id. Anything not here falls through to /search.
_SYMBOL_TO_ID = {
    "btc": "bitcoin", "xbt": "bitcoin", "eth": "ethereum", "usdt": "tether",
    "usdc": "usd-coin", "bnb": "binancecoin", "sol": "solana", "xrp": "ripple",
    "ada": "cardano", "doge": "dogecoin", "trx": "tron", "ton": "the-open-network",
    "dot": "polkadot", "matic": "matic-network", "pol": "polygon-ecosystem-token",
    "ltc": "litecoin", "bch": "bitcoin-cash", "link": "chainlink", "xmr": "monero",
    "avax": "avalanche-2", "shib": "shiba-inu", "uni": "uniswap", "atom": "cosmos",
    "etc": "ethereum-classic", "xlm": "stellar", "near": "near", "algo": "algorand",
    "aave": "aave", "arb": "arbitrum", "op": "optimism", "fil": "filecoin",
}


class MarketDataError(RuntimeError):
    """A market-data lookup could not be completed."""


def configured() -> bool:
    return bool(settings.coingecko_api_key.strip())


def _base() -> str:
    return _PRO_BASE if settings.coingecko_pro else _DEMO_BASE


def _headers() -> dict[str, str]:
    key = settings.coingecko_api_key.strip()
    header = "x-cg-pro-api-key" if settings.coingecko_pro else "x-cg-demo-api-key"
    return {"accept": "application/json", header: key}


def _cache_key(path: str, params: dict[str, Any]) -> str:
    return path + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    """GET {base}{path}. Cached for `_CACHE_TTL_S`. Raises MarketDataError."""
    if not configured():
        raise MarketDataError("market data is not configured (no CoinGecko API key)")

    params = params or {}
    ck = _cache_key(path, params)
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(ck)
        if hit and now - hit[0] < _CACHE_TTL_S:
            return hit[1]

    try:
        with httpx.Client(
            timeout=settings.coingecko_timeout_seconds, transport=_TRANSPORT
        ) as client:
            resp = client.get(_base() + path, params=params, headers=_headers())
    except httpx.HTTPError as exc:
        raise MarketDataError(f"could not reach CoinGecko: {exc.__class__.__name__}") from exc

    if resp.status_code == 429:
        raise MarketDataError("CoinGecko rate limit reached — try again shortly")
    if resp.status_code in (401, 403):
        raise MarketDataError("CoinGecko rejected the API key (check plan / key)")
    if resp.status_code >= 400:
        raise MarketDataError(f"CoinGecko returned HTTP {resp.status_code}")

    try:
        data = resp.json()
    except ValueError as exc:
        raise MarketDataError("CoinGecko sent a non-JSON response") from exc

    with _cache_lock:
        _cache[ck] = (now, data)
    return data


def reset_cache() -> None:
    """Test hook."""
    with _cache_lock:
        _cache.clear()


# --------------------------------------------------------------------------- #
# Coin-id resolution
# --------------------------------------------------------------------------- #
def resolve_coin_ids(tokens: list[str]) -> list[str]:
    """Map user-supplied symbols / names / ids to CoinGecko ids, order-preserving."""
    ids: list[str] = []
    for raw in tokens:
        t = raw.strip().lower()
        if not t:
            continue
        # Known ticker -> id directly; otherwise ask CoinGecko's /search, which
        # also resolves exact ids ("usd-coin") and full names ("the open network").
        cid = _SYMBOL_TO_ID.get(t) or _search_one(t)
        if cid and cid not in ids:
            ids.append(cid)
    return ids


def _search_one(query: str) -> str | None:
    try:
        hits = _get("/search", {"query": query}).get("coins", [])
    except MarketDataError:
        return None
    return hits[0]["id"] if hits else None


# --------------------------------------------------------------------------- #
# Public queries (return plain dicts/lists; raise MarketDataError on failure)
# --------------------------------------------------------------------------- #
def simple_price(coin_ids: list[str], vs_currency: str = "usd") -> dict[str, Any]:
    if not coin_ids:
        raise MarketDataError("no recognizable coins in the request")
    vs = _clean_vs(vs_currency)
    raw = _get(
        "/simple/price",
        {
            "ids": ",".join(coin_ids),
            "vs_currencies": vs,
            "include_market_cap": "true",
            "include_24hr_vol": "true",
            "include_24hr_change": "true",
            "include_last_updated_at": "true",
        },
    )
    out: dict[str, Any] = {}
    for cid, row in raw.items():
        out[cid] = {
            "price": row.get(vs),
            "market_cap": row.get(f"{vs}_market_cap"),
            "volume_24h": row.get(f"{vs}_24h_vol"),
            "change_24h_pct": _round(row.get(f"{vs}_24h_change")),
            "last_updated_at": row.get("last_updated_at"),
        }
    if not out:
        raise MarketDataError("CoinGecko had no price for those coins")
    return {"vs_currency": vs, "coins": out}


def coin_markets(coin_ids: list[str], vs_currency: str = "usd") -> list[dict[str, Any]]:
    if not coin_ids:
        raise MarketDataError("no recognizable coins in the request")
    vs = _clean_vs(vs_currency)
    rows = _get(
        "/coins/markets",
        {"vs_currency": vs, "ids": ",".join(coin_ids), "price_change_percentage": "1h,24h,7d"},
    )
    if not isinstance(rows, list) or not rows:
        raise MarketDataError("CoinGecko had no market data for those coins")
    return [
        {
            "id": r.get("id"),
            "symbol": (r.get("symbol") or "").upper(),
            "name": r.get("name"),
            "price": r.get("current_price"),
            "market_cap": r.get("market_cap"),
            "market_cap_rank": r.get("market_cap_rank"),
            "volume_24h": r.get("total_volume"),
            "high_24h": r.get("high_24h"),
            "low_24h": r.get("low_24h"),
            "change_1h_pct": _round(r.get("price_change_percentage_1h_in_currency")),
            "change_24h_pct": _round(r.get("price_change_percentage_24h_in_currency")),
            "change_7d_pct": _round(r.get("price_change_percentage_7d_in_currency")),
            "ath": r.get("ath"),
            "ath_change_pct": _round(r.get("ath_change_percentage")),
            "circulating_supply": r.get("circulating_supply"),
            "total_supply": r.get("total_supply"),
            "last_updated": r.get("last_updated"),
        }
        for r in rows
    ]


def global_overview() -> dict[str, Any]:
    data = _get("/global").get("data", {})
    if not data:
        raise MarketDataError("CoinGecko returned no global data")
    mcap = data.get("total_market_cap", {}) or {}
    vol = data.get("total_volume", {}) or {}
    dom = data.get("market_cap_percentage", {}) or {}
    return {
        "total_market_cap_usd": mcap.get("usd"),
        "total_volume_24h_usd": vol.get("usd"),
        "market_cap_change_24h_pct": _round(data.get("market_cap_change_percentage_24h_usd")),
        "btc_dominance_pct": _round(dom.get("btc")),
        "eth_dominance_pct": _round(dom.get("eth")),
        "active_cryptocurrencies": data.get("active_cryptocurrencies"),
        "markets": data.get("markets"),
        "updated_at": data.get("updated_at"),
    }


# --------------------------------------------------------------------------- #
def _clean_vs(vs: Any) -> str:
    s = str(vs or "usd").strip().lower()
    return s if s.isalpha() and len(s) <= 8 else "usd"


def _round(value: Any) -> float | None:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None
