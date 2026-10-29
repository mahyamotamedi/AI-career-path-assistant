import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace as NS

import pytest
from pydantic import BaseModel

from app.config import settings
from app.llm import client
from app.session import get_session


class Output(BaseModel):
    value: int


def response(content='{"value": 7}', usage=True, finish="stop", refusal=None):
    return NS(usage=NS(prompt_tokens=10, completion_tokens=2) if usage else None,
              choices=[NS(finish_reason=finish, message=NS(content=content, refusal=refusal))])


@pytest.fixture
def gateway(monkeypatch):
    monkeypatch.setattr(settings, "chat_model", "chat-test")
    monkeypatch.setattr(settings, "extract_model", "extract-test")
    monkeypatch.setattr(settings, "embed_model", "embed-test")
    calls, replies = [], []
    def create(**kwargs):
        calls.append(kwargs)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
    fake = NS(chat=NS(completions=NS(create=create)), embeddings=NS(create=create))
    monkeypatch.setattr(client, "_get_client", lambda: fake)
    return calls, replies


@pytest.mark.parametrize("outputs,ok,count", [(['{"value":7}'], True, 1),
    (["no", '{"value":8}'], True, 2), (["no", "no", '{"value":7}'], False, 2),
    (['{"value":"bad"}', '{}'], False, 2)])
def test_json_schema_and_bounded_repair(gateway, outputs, ok, count):
    calls, replies = gateway
    replies.extend(response(x) for x in outputs)
    result = client.chat_json("s", [], Output)
    assert result.ok is ok and len(calls) == count
    assert '"value"' in calls[0]["messages"][0]["content"]
    assert all(c["response_format"] == {"type":"json_object"} for c in calls)
    assert get_session("s").usage.calls == count
    assert get_session("s").usage.prompt_tokens == 10 * count


@pytest.mark.parametrize("reply", [NS(usage=None, choices=[]), NS(usage=None),
    response(""), response(refusal="secret refusal"), response(finish="length"),
    response(finish="content_filter"), response(content=["malformed"])])
def test_malformed_responses(gateway, reply):
    gateway[1].append(reply)
    assert not client.chat("s", []).ok
    assert len(gateway[0]) == 1


@pytest.mark.parametrize("exc,kind", [(TimeoutError("private prompt"), "timeout"),
                                         (RuntimeError("private key"), "api")])
def test_safe_provider_failure(gateway, caplog, exc, kind):
    gateway[1].append(exc)
    result = client.chat("s", [])
    assert result.error.kind == kind
    assert "private" not in str(result) + caplog.text
    assert get_session("s").usage.calls == 1
    assert not get_session("s").usage_complete


def test_configuration_and_constructor_failures(monkeypatch):
    assert client.chat("s", []).error.kind == "not_configured"
    monkeypatch.setattr(settings, "chat_model", "chat-test")
    assert client.chat("s", []).error.kind == "not_configured"
    monkeypatch.setattr(client, "_get_client", lambda: (_ for _ in ()).throw(ValueError("secret")))
    assert not client.chat("s", []).ok
    assert get_session("s").usage.calls == 0


def test_missing_usage_and_unknown_prices(gateway):
    gateway[1].extend([response(usage=False), response()])
    client.chat("s", [])
    client.chat("s", [])
    session = get_session("s")
    assert session.usage.calls == 2 and session.usage.prompt_tokens == 10
    assert not session.usage_complete and not session.cost_complete
    assert get_session("other").usage.calls == 0


def test_embeddings_and_precise_cost(gateway, monkeypatch):
    monkeypatch.setattr(settings, "price_table", {"embed-test": (0.02, 0), "chat-test": (0.15, 0.6)})
    gateway[1].append(NS(usage=NS(prompt_tokens=1, total_tokens=1), data=[NS(index=0, embedding=[0.1, 0.2])]))
    assert client.embed("s", ["data"]).ok
    assert get_session("s").usage.est_cost_usd == pytest.approx(0.00000002)
    gateway[1].append(response())
    assert client.chat("s", []).ok
    assert get_session("s").usage.est_cost_usd == pytest.approx(0.00000272)


def test_concurrent_accounting(monkeypatch):
    monkeypatch.setattr(settings, "price_table", {"m": (1, 1)})
    def record(_):
        client._attempt("s")
        client._record_usage("s", "m", NS(prompt_tokens=1, completion_tokens=1))
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(record, range(300)))
    assert get_session("s").usage.calls == 300
    assert get_session("s").usage.prompt_tokens == 300
    assert get_session("s").usage.est_cost_usd == pytest.approx(0.0006)


def test_shared_deadline(gateway, monkeypatch):
    ticks = iter([0, 0, 9])
    monkeypatch.setattr(client.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(settings, "llm_json_budget_s", 8)
    gateway[1].append(response("invalid"))
    assert client.chat_json("s", [], Output).error.kind == "timeout"
    assert len(gateway[0]) == 1 and gateway[0][0]["timeout"] <= 8


def test_optional_parameters_are_configured(gateway, monkeypatch):
    monkeypatch.setattr(settings, "llm_json_mode", False)
    gateway[1].append(response())
    assert client.chat_json("s", [], Output).ok
    assert "temperature" not in gateway[0][0] and "response_format" not in gateway[0][0]


def test_embed_configuration_independent(gateway, monkeypatch):
    monkeypatch.setattr(settings, "chat_model", "")
    gateway[1].append(NS(usage=NS(prompt_tokens=1), data=[NS(index=0, embedding=[1.0])]))
    assert client.embed("s", ["data"]).ok


def test_client_uses_configured_gateway_and_disables_retries(monkeypatch):
    calls = []
    monkeypatch.setattr(settings, "llm_api_key", "synthetic-test-key")
    monkeypatch.setattr(settings, "llm_base_url", "https://gateway.invalid/v1")
    monkeypatch.setattr(client, "_client", None)
    monkeypatch.setattr(client, "OpenAI", lambda **kw: calls.append(kw) or object())
    client._get_client()
    assert calls[0]["max_retries"] == 0 and calls[0]["base_url"] == "https://gateway.invalid/v1"


@pytest.mark.parametrize("data", [[], [NS(index=1, embedding=[1])], [NS(index=0, embedding=[])], [NS(index=0, embedding=[float("nan")])]])
def test_embedding_bad_response(gateway, data):
    gateway[1].append(NS(usage=None, data=data))
    assert not client.embed("s", ["text"]).ok
