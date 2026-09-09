"""
CoinGecko market-data client + the assistant's price tools.

No test touches the network: `_get` is driven either through an
`httpx.MockTransport` (for status / cache behaviour) or by stubbing it
directly (for the higher-level shaping + tool tests).
"""
from __future__ import annotations

import httpx
import pytest

from app.ai.tools import execute_tool
from app.core.config import settings
from app.models.schemas import UserPublic
from app.services import market_data

ANALYST = UserPublic(username="a1", role="analyst", agency="NTRO")


@pytest.fixture
def demo_key(monkeypatch):
    monkeypatch.setattr(settings, "coingecko_api_key", "CG-testkey")
    monkeypatch.setattr(settings, "coingecko_pro", False)
    market_data.reset_cache()
    yield
    market_data._TRANSPORT = None
    market_data.reset_cache()


def _mock(handler):
    market_data._TRANSPORT = httpx.MockTransport(handler)


# --------------------------------------------------------------------------- #
# transport / status / cache
# --------------------------------------------------------------------------- #
def test_not_configured_raises_and_tool_degrades(monkeypatch):
    monkeypatch.setattr(settings, "coingecko_api_key", "")
    assert market_data.configured() is False
    with pytest.raises(market_data.MarketDataError):
        market_data._get("/global")

    out = execute_tool("get_crypto_price", {"coins": "btc"}, ANALYST)
    assert out["ok"] is False and "not configured" in out["error"]


def test_sends_demo_header_and_base(demo_key):
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["key"] = req.headers.get("x-cg-demo-api-key")
        seen["pro"] = req.headers.get("x-cg-pro-api-key")
        return httpx.Response(200, json={"data": {"active_cryptocurrencies": 1}})

    _mock(handler)
    market_data.global_overview()
    assert seen["url"].startswith("https://api.coingecko.com/api/v3/global")
    assert seen["key"] == "CG-testkey" and seen["pro"] is None


def test_pro_flag_switches_host_and_header(demo_key, monkeypatch):
    monkeypatch.setattr(settings, "coingecko_pro", True)
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["pro"] = req.headers.get("x-cg-pro-api-key")
        return httpx.Response(200, json={"data": {"x": 1}})

    _mock(handler)
    market_data.global_overview()
    assert seen["url"].startswith("https://pro-api.coingecko.com/api/v3/")
    assert seen["pro"] == "CG-testkey"


@pytest.mark.parametrize(
    "status, needle",
    [(429, "rate limit"), (401, "rejected the API key"), (403, "rejected the API key"), (500, "HTTP 500")],
)
def test_status_codes_map_to_messages(demo_key, status, needle):
    _mock(lambda req: httpx.Response(status, json={}))
    with pytest.raises(market_data.MarketDataError) as ei:
        market_data._get("/global")
    assert needle in str(ei.value)


def test_network_error_is_wrapped(demo_key):
    def boom(req):
        raise httpx.ConnectError("no route", request=req)

    _mock(boom)
    with pytest.raises(market_data.MarketDataError) as ei:
        market_data._get("/global")
    assert "could not reach CoinGecko" in str(ei.value)


def test_responses_are_cached(demo_key):
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(200, json={"data": {"active_cryptocurrencies": 42}})

    _mock(handler)
    a = market_data._get("/global")
    b = market_data._get("/global")
    assert a == b and calls["n"] == 1  # second call served from cache


# --------------------------------------------------------------------------- #
# shaping
# --------------------------------------------------------------------------- #
def test_simple_price_shape(demo_key, monkeypatch):
    raw = {
        "bitcoin": {
            "usd": 64000.5, "usd_market_cap": 1.26e12,
            "usd_24h_vol": 3.1e10, "usd_24h_change": -1.2345678, "last_updated_at": 1_760_000_000,
        }
    }
    monkeypatch.setattr(market_data, "_get", lambda path, params=None: raw)
    out = market_data.simple_price(["bitcoin"], "usd")
    assert out["vs_currency"] == "usd"
    row = out["coins"]["bitcoin"]
    assert row["price"] == 64000.5 and row["market_cap"] == 1.26e12
    assert row["change_24h_pct"] == -1.2346  # rounded to 4dp


def test_resolve_coin_ids_symbol_and_search(demo_key, monkeypatch):
    def fake_get(path, params=None):
        assert path == "/search"
        return {"coins": [{"id": "pepe"}]} if params["query"] == "pepe" else {"coins": []}

    monkeypatch.setattr(market_data, "_get", fake_get)
    assert market_data.resolve_coin_ids(["btc", "ETH", "pepe", "nonsense-xyzzy"]) == [
        "bitcoin", "ethereum", "pepe",
    ]


def test_global_overview_shape(demo_key, monkeypatch):
    raw = {"data": {
        "total_market_cap": {"usd": 2.4e12}, "total_volume": {"usd": 9e10},
        "market_cap_percentage": {"btc": 52.1234, "eth": 17.02},
        "market_cap_change_percentage_24h_usd": 0.87, "active_cryptocurrencies": 12345,
    }}
    monkeypatch.setattr(market_data, "_get", lambda path, params=None: raw)
    o = market_data.global_overview()
    assert o["total_market_cap_usd"] == 2.4e12
    assert o["btc_dominance_pct"] == 52.1234 and o["eth_dominance_pct"] == 17.02


# --------------------------------------------------------------------------- #
# AI tools
# --------------------------------------------------------------------------- #
def test_get_crypto_price_tool(demo_key, monkeypatch):
    monkeypatch.setattr(market_data, "resolve_coin_ids", lambda toks: ["bitcoin", "ethereum"])
    monkeypatch.setattr(
        market_data, "simple_price",
        lambda ids, vs="usd": {"vs_currency": vs, "coins": {i: {"price": 1} for i in ids}},
    )
    out = execute_tool("get_crypto_price", {"coins": "btc, eth"}, ANALYST)
    assert out["ok"] is True and out["source"] == "coingecko"
    assert set(out["coins"]) == {"bitcoin", "ethereum"}


def test_get_crypto_price_tool_rejects_empty_coins(demo_key):
    out = execute_tool("get_crypto_price", {"coins": "  "}, ANALYST)
    assert out["ok"] is False


def test_market_overview_tool_reports_rate_limit(demo_key):
    _mock(lambda req: httpx.Response(429, json={}))
    out = execute_tool("get_crypto_market_overview", {}, ANALYST)
    assert out["ok"] is False and "rate limit" in out["error"]


def test_market_tools_visible_to_analyst():
    from app.ai.tools import tool_schemas

    names = {s["function"]["name"] for s in tool_schemas("analyst")}
    assert {"get_crypto_price", "get_coin_market_data", "get_crypto_market_overview"} <= names
