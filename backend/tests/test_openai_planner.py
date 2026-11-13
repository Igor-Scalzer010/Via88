"""Exercise the real LangChain/OpenAI request path with an offline HTTP transport."""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial

import httpx
import pytest
from langchain_openai import ChatOpenAI
from openai import InternalServerError
from pydantic import ValidationError

from road_safety.agents import planner as planner_module
from road_safety.agents.planner import AnalysisPlan, OpenAIPlanner, OutputTokenLimitError
from road_safety.config import Settings
from road_safety.contracts import Catalog, Filters


def provider_response(
    text: str | None = None, *, incomplete: bool = False, usage: bool = True
) -> httpx.Response:
    """Return a Responses API envelope, including truncated and usage-free variants."""
    if text is None:
        text = AnalysisPlan(
            status="clarification", clarification="private-answer"
        ).model_dump_json()
    return httpx.Response(
        200,
        json={
            "id": "resp_test",
            "object": "response",
            "created_at": 0,
            "model": "gpt-6-luna",
            "status": "incomplete" if incomplete else "completed",
            "incomplete_details": {"reason": "max_output_tokens"} if incomplete else None,
            "error": None,
            "output": [
                {
                    "id": "msg_test",
                    "type": "message",
                    "role": "assistant",
                    "status": "incomplete" if incomplete else "completed",
                    "content": [{"type": "output_text", "text": text, "annotations": []}],
                }
            ],
            "usage": {
                "input_tokens": 123,
                "output_tokens": 45,
                "total_tokens": 168,
                "input_tokens_details": {"cached_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": 12},
            }
            if usage
            else None,
        },
    )


@asynccontextmanager
async def mocked_planner(
    monkeypatch: pytest.MonkeyPatch,
    response: httpx.Response | Exception,
    settings: Settings | None = None,
) -> AsyncIterator[tuple[OpenAIPlanner, list[httpx.Request]]]:
    """Inject only the HTTP boundary, preserving SDK retry and parameter conversion."""
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if isinstance(response, Exception):
            raise response
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(
            planner_module, "ChatOpenAI", partial(ChatOpenAI, http_async_client=client)
        )
        yield (
            OpenAIPlanner(
                settings
                or Settings(
                    _env_file=None, openai_api_key="secret-test-key", openai_model="gpt-6-luna"
                )
            ),
            requests,
        )


async def test_limits_reach_responses_api_and_usage_is_private(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=planner_module.__name__)
    async with mocked_planner(monkeypatch, provider_response()) as (planner, requests):
        plan = await planner.plan("private-question", {}, Filters(), Catalog(available=True))
    assert plan.clarification == "private-answer"
    assert len(requests) == 1
    request = requests[0]
    assert request.url.path == "/v1/responses"
    payload = json.loads(request.content)
    assert payload["max_output_tokens"] == 4096
    assert payload["reasoning"] == {"effort": "low"}
    assert payload["model"] == "gpt-6-luna"
    schema = payload["text"]["format"]
    assert schema["type"] == "json_schema"
    assert schema["strict"] is True
    assert set(schema["schema"]["required"]) == set(schema["schema"]["properties"])
    assert request.extensions["timeout"]["read"] == 60
    assert "outcome=complete" in caplog.text
    assert "input_tokens=123 output_tokens=45 reasoning_tokens=12 total_tokens=168" in caplog.text
    assert "duration_seconds=" in caplog.text
    for secret in ("private-question", "private-answer", "secret-test-key"):
        assert secret not in caplog.text


async def test_configured_limits_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        _env_file=None,
        openai_api_key="secret-test-key",
        openai_model="gpt-6-luna",
        openai_max_output_tokens=8192,
        openai_reasoning_effort="none",
        openai_timeout_seconds=90,
        run_timeout_seconds=30,
    )
    async with mocked_planner(monkeypatch, provider_response(), settings) as (planner, requests):
        await planner.plan("x", {}, Filters(), Catalog(available=True))
    payload = json.loads(requests[0].content)
    assert payload["max_output_tokens"] == 8192
    assert payload["reasoning"] == {"effort": "none"}
    assert requests[0].extensions["timeout"]["read"] == 30


@pytest.mark.parametrize("text", ['{"queries":[', ""])
async def test_truncated_json_is_not_retried_and_keeps_usage(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, text: str
) -> None:
    caplog.set_level(logging.INFO, logger=planner_module.__name__)
    async with mocked_planner(monkeypatch, provider_response(text, incomplete=True)) as (
        planner,
        requests,
    ):
        with pytest.raises(OutputTokenLimitError):
            await planner.plan("x", {}, Filters(), Catalog(available=True))
    assert len(requests) == 1
    assert "outcome=output_token_limit" in caplog.text
    assert "input_tokens=123 output_tokens=45 reasoning_tokens=12 total_tokens=168" in caplog.text


async def test_unavailable_usage_does_not_prevent_a_valid_plan(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=planner_module.__name__)
    async with mocked_planner(monkeypatch, provider_response(usage=False)) as (planner, requests):
        plan = await planner.plan("x", {}, Filters(), Catalog(available=True))
    assert plan.status == "clarification"
    assert len(requests) == 1
    assert "input_tokens=unavailable output_tokens=unavailable" in caplog.text
    assert "reasoning_tokens=unavailable total_tokens=unavailable" in caplog.text


async def test_invalid_plan_still_logs_usage_without_content(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=planner_module.__name__)
    async with mocked_planner(
        monkeypatch, provider_response('{"private-invalid-answer":true}')
    ) as (
        planner,
        requests,
    ):
        with pytest.raises(ValidationError):
            await planner.plan("private-question", {}, Filters(), Catalog(available=True))
    assert len(requests) == 1
    assert "outcome=failed" in caplog.text
    assert "total_tokens=168" in caplog.text
    assert "private-invalid-answer" not in caplog.text


@pytest.mark.parametrize("provider_timeout", [False, True])
async def test_transient_provider_errors_do_not_retry(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, provider_timeout: bool
) -> None:
    caplog.set_level(logging.INFO, logger=planner_module.__name__)
    response = (
        httpx.ReadTimeout("private-timeout-message")
        if provider_timeout
        else httpx.Response(500, json={"error": {"message": "private-provider-error"}})
    )
    async with mocked_planner(monkeypatch, response) as (planner, requests):
        with pytest.raises(TimeoutError if provider_timeout else InternalServerError):
            await planner.plan("private-question", {}, Filters(), Catalog(available=True))
    assert len(requests) == 1
    assert ("outcome=timeout" if provider_timeout else "outcome=failed") in caplog.text
    assert "input_tokens=unavailable" in caplog.text
    for secret in ("private-timeout-message", "private-provider-error", "private-question"):
        assert secret not in caplog.text


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("openai_max_output_tokens", 0),
        ("openai_max_output_tokens", 128001),
        ("openai_reasoning_effort", "invalid"),
        ("openai_max_retries", -1),
        ("openai_max_retries", 4),
        ("openai_timeout_seconds", 0),
        ("openai_timeout_seconds", 601),
    ],
)
def test_invalid_call_limits_fail_at_startup(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_call_limits_can_be_configured_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_MAX_OUTPUT_TOKENS", "8192")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "none")
    monkeypatch.setenv("OPENAI_MAX_RETRIES", "1")
    monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", "45")
    settings = Settings(_env_file=None)
    assert settings.openai_max_output_tokens == 8192
    assert settings.openai_reasoning_effort == "none"
    assert settings.openai_max_retries == 1
    assert settings.openai_timeout_seconds == 45
