from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from engine.settings import Settings
from engine.store.publish import RESULTS_PATH, publish_result

BASE = "http://api-control:3000"
URL = BASE + RESULTS_PATH

RESULT: dict[str, Any] = {"summary": {"totalReturn": "5.0"}, "artifacts": {"trades": "/x.parquet"}}


def settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, internal_api_key="shared-secret", **overrides)


def test_nothing_is_sent_when_unconfigured() -> None:
    # api-control does not exist yet. The hand-off is built and tested; with
    # the URL unset it is inert, and a result stays local.
    assert publish_result("job_1", RESULT, settings()) is False


@respx.mock
def test_a_result_is_posted_when_configured() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(202))

    assert publish_result("job_1", RESULT, settings(api_control_url=BASE)) is True

    request = route.calls[0].request
    import json

    body = json.loads(request.content)
    assert body["jobId"] == "job_1"
    assert body["summary"] == RESULT["summary"]
    assert request.headers["authorization"] == "Bearer shared-secret"


@respx.mock
def test_a_trailing_slash_does_not_double_up() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(202))
    publish_result("job_1", RESULT, settings(api_control_url=BASE + "/"))
    assert route.called


@respx.mock
@pytest.mark.parametrize("status", [400, 401, 500, 503])
def test_a_rejected_publish_is_reported_not_raised(status: int) -> None:
    # The backtest ran and its result is stored. Failing a completed run
    # because a downstream service was unhappy loses more than it protects.
    respx.post(URL).mock(return_value=httpx.Response(status))
    assert publish_result("job_1", RESULT, settings(api_control_url=BASE)) is False


@respx.mock
def test_an_unreachable_endpoint_is_reported_not_raised() -> None:
    respx.post(URL).mock(side_effect=httpx.ConnectError("refused"))
    assert publish_result("job_1", RESULT, settings(api_control_url=BASE)) is False


@respx.mock
def test_the_token_is_omitted_when_there_is_none() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(202))
    unauthenticated = Settings(_env_file=None, api_control_url=BASE)
    publish_result("job_1", RESULT, unauthenticated)
    assert "authorization" not in route.calls[0].request.headers
