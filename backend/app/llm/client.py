"""Synchronous organiser-gateway wrapper. No content or exception strings are logged."""
import json
import math
import re
import time
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.session import get_session

T = TypeVar("T", bound=BaseModel)
ErrorKind = Literal["not_configured", "timeout", "bad_json", "api"]


@dataclass
class LLMError:
    kind: ErrorKind
    message: str


@dataclass
class LLMResult:
    ok: bool
    data: Any = None
    error: LLMError | None = None


_client: OpenAI | None = None
_client_config: tuple | None = None


def _get_client() -> OpenAI | None:
    global _client, _client_config
    if not settings.llm_api_key.strip() or not settings.llm_base_url.strip():
        return None
    config = (settings.llm_base_url, settings.llm_api_key, settings.llm_timeout_s)
    if _client is None or _client_config != config:
        _client = OpenAI(base_url=config[0], api_key=config[1], timeout=config[2], max_retries=0)
        _client_config = config
    return _client


def _failure(kind: ErrorKind) -> LLMResult:
    return LLMResult(False, error=LLMError(kind, kind))


def _classify(exc: Exception) -> LLMError:
    # SDK messages can contain prompts or keys. Never forward them.
    kind: ErrorKind = "timeout" if "Timeout" in type(exc).__name__ else "api"
    return LLMError(kind, kind)


def _attempt(session_id: str) -> None:
    session = get_session(session_id)
    with session.usage_lock:
        session.usage.calls += 1


def _record_usage(session_id: str, model: str, usage: Any) -> None:
    session = get_session(session_id)
    with session.usage_lock:
        if usage is None:
            session.usage_complete = session.cost_complete = False
            return
        pt = getattr(usage, "prompt_tokens", None)
        ct = getattr(usage, "completion_tokens", 0)
        if not isinstance(pt, int) or not isinstance(ct, int) or pt < 0 or ct < 0:
            session.usage_complete = session.cost_complete = False
            return
        session.usage.prompt_tokens += pt
        session.usage.completion_tokens += ct
        price = settings.price_table.get(model)
        if price is None or any(not math.isfinite(p) or p < 0 for p in price):
            session.cost_complete = False
            return
        session.usage.est_cost_usd += (pt * price[0] + ct * price[1]) / 1e6


def chat(session_id: str, messages: list[dict], model: str | None = None,
         temperature: float = 0.3, json_mode: bool = False,
         *, timeout_s: float | None = None) -> LLMResult:
    model = settings.chat_model if model is None else model
    if not model.strip():
        return _failure("not_configured")
    try:
        client = _get_client()
    except (ValueError, TypeError, RuntimeError, OSError, OpenAIError):
        return _failure("not_configured")
    if client is None:
        return _failure("not_configured")
    kwargs: dict[str, Any] = {"timeout": min(settings.llm_timeout_s, timeout_s or settings.llm_timeout_s)}
    if kwargs["timeout"] <= 0:
        return _failure("timeout")
    if json_mode and settings.llm_json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if settings.llm_send_temperature:
        kwargs["temperature"] = temperature
    _attempt(session_id)
    try:
        resp = client.chat.completions.create(model=model, messages=messages, **kwargs)
    except Exception as exc:  # External SDK boundary; programming errors below are not swallowed.
        _record_usage(session_id, model, None)
        return LLMResult(False, error=_classify(exc))
    _record_usage(session_id, model, getattr(resp, "usage", None))
    try:
        choices = resp.choices
        if not choices:
            return _failure("api")
        choice = choices[0]
        if getattr(choice.message, "refusal", None):
            return _failure("api")
        if choice.finish_reason not in ("stop", None):
            return _failure("api")
        content = choice.message.content
        if not isinstance(content, str) or not content.strip():
            return _failure("api")
        return LLMResult(True, data=content)
    except (AttributeError, TypeError, IndexError):
        return _failure("api")


def _parse(text: str, schema: type[T]) -> T:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    return schema.model_validate(json.loads(text))


def chat_json(session_id: str, messages: list[dict], schema: type[T],
              model: str | None = None, temperature: float = 0.0) -> LLMResult:
    model = settings.extract_model if model is None else model
    deadline = time.monotonic() + settings.llm_json_budget_s
    instruction = "Return only a JSON object matching this schema: " + json.dumps(schema.model_json_schema())
    attempts = [{"role": "system", "content": instruction}, *messages]
    for attempt in range(2):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return _failure("timeout")
        res = chat(session_id, attempts, model, temperature, json_mode=True, timeout_s=remaining)
        if not res.ok:
            return res
        try:
            return LLMResult(True, data=_parse(res.data, schema))
        except (json.JSONDecodeError, ValidationError, ValueError):
            if attempt:
                return _failure("bad_json")
            attempts = [*attempts, {"role": "assistant", "content": res.data},
                        {"role": "user", "content": "Invalid JSON/schema. Correct it using the schema above. Do not add facts."}]
    return _failure("bad_json")


def embed(session_id: str, texts: list[str], model: str | None = None) -> LLMResult:
    model = settings.embed_model if model is None else model
    if not model.strip():
        return _failure("not_configured")
    try:
        client = _get_client()
    except (ValueError, TypeError, RuntimeError, OSError, OpenAIError):
        return _failure("not_configured")
    if client is None:
        return _failure("not_configured")
    _attempt(session_id)
    try:
        resp = client.embeddings.create(model=model, input=texts, timeout=settings.embed_timeout_s)
    except Exception as exc:
        _record_usage(session_id, model, None)
        return LLMResult(False, error=_classify(exc))
    _record_usage(session_id, model, getattr(resp, "usage", None))
    try:
        rows = sorted(resp.data, key=lambda d: d.index)
        if len(rows) != len(texts) or [d.index for d in rows] != list(range(len(texts))):
            return _failure("api")
        vectors = [d.embedding for d in rows]
        if any(not v or any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in v) for v in vectors):
            return _failure("api")
        return LLMResult(True, data=vectors)
    except (AttributeError, TypeError, ValueError):
        return _failure("api")
