import asyncio

from app.ai import service
from app.ai.models import ProviderResult, ProviderToolCall
from app.ai.provider import ProviderError
from app.models.schemas import UserPublic

ANALYST = UserPublic(username="a1", role="analyst", agency="X")


def _chat(msg, ctx=None, cid=None):
    return asyncio.run(service.chat(ANALYST, msg, cid, ctx))


def test_mock_provider_is_deterministic():
    a = _chat("Why is this address risky?", _ctx("1MockAddr0016"))
    b = _chat("Why is this address risky?", _ctx("1MockAddr0016"))
    assert a.message == b.message
    assert [s.model_dump() for s in a.sources] == [s.model_dump() for s in b.sources]


def _ctx(addr):
    from app.ai.models import AIContext

    return AIContext(selected_address=addr)


def test_dashboard_summary_uses_real_counts():
    res = _chat("Summarise my dashboard")
    assert "current situation" in res.message.lower()
    assert "high-risk alerts" in res.message.lower()


def test_provider_failure_is_graceful(monkeypatch):
    class Boom:
        name = "boom"

        async def generate(self, turns, tools):  # noqa: ARG002
            raise ProviderError("upstream down")

    monkeypatch.setattr(service, "get_provider", lambda: Boom())
    res = _chat("hello")
    assert "couldn't reach the SentriX intelligence service" in res.message
    assert res.actions == [] and res.provider == "boom"


def test_tool_call_limit_is_bounded(monkeypatch):
    calls = {"n": 0}

    class Loopy:
        name = "loopy"

        async def generate(self, turns, tools):  # noqa: ARG002
            calls["n"] += 1
            return ProviderResult(text="", tool_calls=[ProviderToolCall("c", "get_traffic_status", {})])

    monkeypatch.setattr(service, "get_provider", lambda: Loopy())
    res = _chat("go")
    assert "tool-call limit" in res.message
    assert calls["n"] <= service.settings.ai_max_tool_calls + 1


def test_history_persists_within_a_conversation():
    first = _chat("What is Bitcoin?")
    again = _chat("and a UTXO?", cid=first.conversation_id)
    assert again.conversation_id == first.conversation_id
    assert service._store.get(first.conversation_id)  # non-empty history
