from __future__ import annotations

import copy
from typing import Any

import fakeredis
import pytest
from fastapi.testclient import TestClient

from engine.live.desired_state import LiveStateStore, ObservedState, ObservedStatus
from engine.settings import Settings
from tests.conftest import AUTH, build_client, make_settings
from tests.live.conftest import SPEC


@pytest.fixture
def settings() -> Settings:
    return make_settings(catalog_path="./catalog", log_level="ERROR")


@pytest.fixture
def redis_server() -> fakeredis.FakeServer:
    return fakeredis.FakeServer()


@pytest.fixture
def api(settings: Settings, redis_server: fakeredis.FakeServer) -> TestClient:
    return build_client(settings, redis_server)


@pytest.fixture
def store(settings: Settings, redis_server: fakeredis.FakeServer) -> LiveStateStore:
    import fakeredis.aioredis

    return LiveStateStore.from_settings(
        settings,
        fakeredis.aioredis.FakeRedis(server=redis_server, decode_responses=True),
    )


def body(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "spec": copy.deepcopy(SPEC),
        "strategyVersionId": "sv_1",
        "venue": "BINANCE",
        "instrumentId": "BTCUSDT.BINANCE",
        "barType": "BTCUSDT.BINANCE-15-MINUTE-LAST-EXTERNAL",
        "mode": "SIMULATION",
        "fees": {"maker_bps": "1", "taker_bps": "10", "slippage_bps": "5"},
    }
    payload.update(overrides)
    return payload


# --- the resource is an account ------------------------------------------


def test_put_records_a_desired_state(api: TestClient) -> None:
    response = api.put("/v1/live/acct_1", json=body(), headers=AUTH)

    assert response.status_code == 200
    document = response.json()
    assert document["account_id"] == "acct_1"
    assert document["status"] == "RUNNING"
    assert document["revision"] == 1
    assert document["spec_hash"]


def test_putting_twice_leaves_one_account(api: TestClient) -> None:
    """The property a POST could not give.

    Two POSTs would have started two nodes trading one account. Two PUTs leave
    one record, with a bumped revision.
    """
    api.put("/v1/live/acct_1", json=body(), headers=AUTH)
    second = api.put("/v1/live/acct_1", json=body(), headers=AUTH)

    assert second.json()["revision"] == 2
    assert api.get("/v1/live", headers=AUTH).json()["accounts"] == ["acct_1"]


def test_the_api_does_not_start_anything(api: TestClient) -> None:
    # It records a desire; a supervisor converges on it. Restarting this
    # process must change nothing about what is trading.
    api.put("/v1/live/acct_1", json=body(), headers=AUTH)
    observed = api.get("/v1/live/acct_1", headers=AUTH).json()["observed"]
    assert observed is None


def test_get_reports_desired_and_observed(api: TestClient, store: LiveStateStore) -> None:
    import asyncio

    api.put("/v1/live/acct_1", json=body(), headers=AUTH)
    asyncio.run(
        store.observe(
            ObservedState(account_id="acct_1", status=ObservedStatus.RUNNING, revision=1)
        )
    )

    document = api.get("/v1/live/acct_1", headers=AUTH).json()

    assert document["desired"]["status"] == "RUNNING"
    assert document["observed"]["status"] == "RUNNING"


def test_an_unknown_account_is_404(api: TestClient) -> None:
    response = api.get("/v1/live/nope", headers=AUTH)
    assert response.status_code == 404
    assert response.json()["code"] == "ACCOUNT_NOT_FOUND"


def test_delete_asks_it_to_stop_and_keeps_the_record(api: TestClient) -> None:
    # Stopping is not deleting: the supervisor still has to act, and a missing
    # record is indistinguishable from one that never existed.
    api.put("/v1/live/acct_1", json=body(), headers=AUTH)

    stopped = api.delete("/v1/live/acct_1", headers=AUTH)

    assert stopped.status_code == 200
    assert stopped.json()["status"] == "STOPPED"
    assert api.get("/v1/live/acct_1", headers=AUTH).status_code == 200


# --- credentials ---------------------------------------------------------


def test_live_mode_requires_a_credential_reference(api: TestClient) -> None:
    response = api.put("/v1/live/acct_1", json=body(mode="LIVE"), headers=AUTH)
    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "MISSING_CREDENTIAL_REF"


def test_simulation_mode_needs_no_credentials(api: TestClient) -> None:
    # Simulation is the integration test for the whole system and risks
    # nothing, so it must not be gated on a key.
    assert api.put("/v1/live/acct_1", json=body(mode="SIMULATION"), headers=AUTH).status_code == 200


def test_a_reference_is_accepted_and_not_echoed(api: TestClient) -> None:
    response = api.put(
        "/v1/live/acct_1",
        json=body(mode="LIVE", credentialRef="binance/acct_1"),
        headers=AUTH,
    )
    assert response.status_code == 200
    assert "credential_ref" not in response.json()
    assert "credentialRef" not in response.text


def test_a_secret_in_the_body_is_rejected(api: TestClient) -> None:
    # extra="forbid" means a caller cannot invent an apiKey field and have it
    # quietly stored. A key in this body would reach a request log and the
    # record (ADR-001).
    response = api.put(
        "/v1/live/acct_1",
        json=body(apiKey="AK_real", apiSecret="SK_real"),
        headers=AUTH,
    )
    assert response.status_code == 422
    assert "AK_real" not in response.text


# --- validation ----------------------------------------------------------


def test_an_invalid_spec_is_rejected(api: TestClient) -> None:
    payload = body()
    payload["spec"]["exit"] = {"any": [{"type": "takeProfitPercent", "value": 4}]}

    response = api.put("/v1/live/acct_1", json=payload, headers=AUTH)

    assert response.status_code == 422
    assert "MISSING_STOP_LOSS" in [e["code"] for e in response.json()["errors"]]


def test_the_same_spec_a_backtest_takes(api: TestClient) -> None:
    # Identical JSON, identical strategy class, identical config factory. Only
    # the lifecycle differs.
    assert api.put("/v1/live/acct_1", json=body(), headers=AUTH).status_code == 200


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_every_route_is_authenticated(api: TestClient, method: str) -> None:
    call = getattr(api, method)
    response = call("/v1/live/acct_1", json=body()) if method == "put" else call("/v1/live/acct_1")
    assert response.status_code == 401


# --- the kill switch over HTTP -------------------------------------------


def test_a_kill_can_be_engaged_and_released(api: TestClient) -> None:
    """The operator's direct line to a node.

    Deliberately not routed through api-control: an operator must be able to
    stop a node when the service that sets policy is unreachable, which is
    exactly when they are most likely to want to (ADR-001).
    """
    api.put("/v1/live/acct_1", json=body(), headers=AUTH)

    assert api.get("/v1/live/acct_1/kill", headers=AUTH).json()["killSwitch"] == "RELEASED"

    engaged = api.post("/v1/live/acct_1/kill", headers=AUTH)
    assert engaged.status_code == 200
    assert api.get("/v1/live/acct_1/kill", headers=AUTH).json()["killSwitch"] == "ENGAGED"

    api.delete("/v1/live/acct_1/kill", headers=AUTH)
    assert api.get("/v1/live/acct_1/kill", headers=AUTH).json()["killSwitch"] == "RELEASED"


def test_a_kill_needs_no_existing_account(api: TestClient) -> None:
    # Stopping something must not depend on the record being readable.
    assert api.post("/v1/live/never_seen/kill", headers=AUTH).status_code == 200


def test_the_kill_routes_are_authenticated(api: TestClient) -> None:
    assert api.post("/v1/live/acct_1/kill").status_code == 401
    assert api.delete("/v1/live/acct_1/kill").status_code == 401


# --- risk limits ---------------------------------------------------------


def test_limits_are_recorded_with_the_account(api: TestClient) -> None:
    response = api.put(
        "/v1/live/acct_1",
        json=body(
            risk={
                "max_order_notional": "5000",
                "max_position_notional": "10000",
                "max_open_positions": 2,
                "daily_loss_limit": "500",
            }
        ),
        headers=AUTH,
    )

    assert response.status_code == 200
    assert response.json()["risk"]["max_order_notional"] == "5000"


def test_absent_limits_mean_unlimited(api: TestClient) -> None:
    # A choice rather than a default worth relying on.
    document = api.put("/v1/live/acct_1", json=body(), headers=AUTH).json()
    assert document["risk"]["max_order_notional"] is None


def test_a_nonsensical_limit_is_rejected(api: TestClient) -> None:
    response = api.put(
        "/v1/live/acct_1", json=body(risk={"max_order_notional": "-1"}), headers=AUTH
    )
    assert response.status_code == 422


def test_a_typo_in_a_limit_is_rejected(api: TestClient) -> None:
    # extra="forbid": a misspelt limit silently ignored is an account trading
    # without the protection its operator believes it has.
    response = api.put(
        "/v1/live/acct_1", json=body(risk={"maxOrderNotinal": "5000"}), headers=AUTH
    )
    assert response.status_code == 422


# --- fees are declared, never defaulted ----------------------------------


def test_fees_are_required(api: TestClient) -> None:
    """Rule 5, and it binds harder here than on a backtest.

    A backtest with no fees is a marketing number. A simulation with no fees is
    a marketing number someone may act on.
    """
    payload = body()
    del payload["fees"]

    assert api.put("/v1/live/acct_1", json=payload, headers=AUTH).status_code == 422


def test_fees_are_recorded_with_the_account(api: TestClient) -> None:
    document = api.put("/v1/live/acct_1", json=body(), headers=AUTH).json()

    assert document["fees"]["taker_bps"] == "10"
    assert document["fees"]["slippage_bps"] == "5"


def test_a_negative_fee_is_rejected(api: TestClient) -> None:
    response = api.put(
        "/v1/live/acct_1",
        json=body(fees={"maker_bps": "-1", "taker_bps": "10", "slippage_bps": "5"}),
        headers=AUTH,
    )
    assert response.status_code == 422


def test_a_half_declared_fee_is_rejected(api: TestClient) -> None:
    # Slippage omitted would otherwise be the zero the rule exists to forbid.
    response = api.put(
        "/v1/live/acct_1",
        json=body(fees={"maker_bps": "1", "taker_bps": "10"}),
        headers=AUTH,
    )
    assert response.status_code == 422


def test_zero_fees_are_allowed_but_must_be_said(api: TestClient) -> None:
    """A venue that charges nothing is a real answer.

    The rule is against a *defaulted* zero, not a declared one -- an operator
    who states zero has made a claim that can be held against a result.
    """
    response = api.put(
        "/v1/live/acct_1",
        json=body(fees={"maker_bps": "0", "taker_bps": "0", "slippage_bps": "0"}),
        headers=AUTH,
    )
    assert response.status_code == 200


# --- one casing across both endpoints -------------------------------------


def test_camel_case_is_accepted_inside_fees_and_risk(api: TestClient) -> None:
    """The wire is camelCase, including the nested objects.

    `risk` and `fees` were the only snake_case objects on an otherwise
    camelCase surface, so a caller that moved a working backtest across got a
    422 on `makerBps` while `strategyVersionId` beside it was fine.
    """
    response = api.put(
        "/v1/live/acct_1",
        json=body(
            risk={"maxOrderNotional": "2000", "maxOpenPositions": 1},
            fees={"makerBps": "1", "takerBps": "10", "slippageBps": "5"},
        ),
        headers=AUTH,
    )

    assert response.status_code == 200
    assert response.json()["fees"]["taker_bps"] == "10"
    assert response.json()["risk"]["max_order_notional"] == "2000"


def test_snake_case_is_still_accepted(api: TestClient) -> None:
    """Both spellings, deliberately.

    Records already in Redis were written with field names, so reading one back
    must not become a validation error -- and a caller mid-migration should not
    have to switch in one commit.
    """
    response = api.put(
        "/v1/live/acct_1",
        json=body(fees={"maker_bps": "1", "taker_bps": "10", "slippage_bps": "5"}),
        headers=AUTH,
    )

    assert response.status_code == 200


def test_the_two_spellings_record_the_same_thing(api: TestClient) -> None:
    camel = api.put(
        "/v1/live/acct_camel",
        json=body(fees={"makerBps": "1", "takerBps": "10", "slippageBps": "5"}),
        headers=AUTH,
    ).json()
    snake = api.put(
        "/v1/live/acct_snake",
        json=body(fees={"maker_bps": "1", "taker_bps": "10", "slippage_bps": "5"}),
        headers=AUTH,
    ).json()

    assert camel["fees"] == snake["fees"]


def test_a_typo_is_still_rejected_in_either_spelling(api: TestClient) -> None:
    # `extra="forbid"` survives the alias generator: a silently ignored fee
    # field is the zero rule 5 exists to forbid.
    for fees in (
        {"makerBps": "1", "takerBps": "10", "slipageBps": "5"},
        {"maker_bps": "1", "taker_bps": "10", "slipage_bps": "5"},
    ):
        response = api.put("/v1/live/acct_1", json=body(fees=fees), headers=AUTH)
        assert response.status_code == 422


def test_responses_stay_snake_case(api: TestClient) -> None:
    """The response shape is unchanged, and that is not an oversight.

    `api-control` reads these keys today. Accepting camelCase on the way in is
    additive; renaming what comes back is a migration with a caller on the
    other side of it.
    """
    document = api.put("/v1/live/acct_1", json=body(), headers=AUTH).json()

    assert set(document["fees"]) == {"maker_bps", "taker_bps", "slippage_bps"}
    assert "makerBps" not in document["fees"]


def test_a_mandate_takes_camel_case_limits(api: TestClient) -> None:
    granted = api.put(
        "/v1/live/acct_1/mandate",
        json={"mandateId": "m_1", "issuedBy": "trading-core", "limits": {"maxOrderNotional": "5000"}},
        headers=AUTH,
    )

    assert granted.status_code == 200
    assert granted.json()["limits"]["max_order_notional"] == "5000"


# --- mandates (ADR-002) --------------------------------------------------


def grant(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "mandateId": "m_1",
        "issuedBy": "trading-core",
        "limits": {"max_order_notional": "5000"},
    }
    payload.update(overrides)
    return payload


def test_a_mandate_can_be_granted_and_read(api: TestClient) -> None:
    granted = api.put("/v1/live/acct_1/mandate", json=grant(), headers=AUTH)

    assert granted.status_code == 200
    assert granted.json()["mandate_id"] == "m_1"
    assert api.get("/v1/live/acct_1/mandate", headers=AUTH).json()["revoked_at"] is None


def test_granting_twice_leaves_one_mandate(api: TestClient) -> None:
    # A PUT, because authority is a state rather than an event.
    api.put("/v1/live/acct_1/mandate", json=grant(), headers=AUTH)
    api.put("/v1/live/acct_1/mandate", json=grant(mandateId="m_2"), headers=AUTH)

    assert api.get("/v1/live/acct_1/mandate", headers=AUTH).json()["mandate_id"] == "m_2"


def test_revoking_records_who_and_why(api: TestClient) -> None:
    api.put("/v1/live/acct_1/mandate", json=grant(), headers=AUTH)

    revoked = api.request(
        "DELETE",
        "/v1/live/acct_1/mandate",
        json={"revokedBy": "an operator", "reason": "drawdown"},
        headers=AUTH,
    )

    assert revoked.status_code == 200
    assert revoked.json()["revoked_by"] == "an operator"
    assert revoked.json()["revoked_reason"] == "drawdown"


def test_revoking_something_that_does_not_exist_is_a_404(api: TestClient) -> None:
    response = api.request(
        "DELETE", "/v1/live/never_seen/mandate", json={"revokedBy": "x"}, headers=AUTH
    )
    assert response.status_code == 404


def test_reading_a_mandate_that_does_not_exist_is_a_404(api: TestClient) -> None:
    assert api.get("/v1/live/never_seen/mandate", headers=AUTH).status_code == 404


def test_a_mandate_has_no_expiry_to_set(api: TestClient) -> None:
    """Revoke-only, enforced at the edge.

    `extra="forbid"`, so a caller that thinks it is setting a TTL gets a 422
    rather than having it silently ignored -- which would be a caller believing
    authority lapses when it does not.
    """
    response = api.put("/v1/live/acct_1/mandate", json=grant(expiresAt="2027-01-01"), headers=AUTH)
    assert response.status_code == 422


def test_the_mandate_routes_are_authenticated(api: TestClient) -> None:
    assert api.put("/v1/live/acct_1/mandate", json=grant()).status_code == 401
    assert api.get("/v1/live/acct_1/mandate").status_code == 401
    assert api.request("DELETE", "/v1/live/acct_1/mandate", json={"revokedBy": "x"}).status_code == 401


def test_a_mandate_carries_limits(api: TestClient) -> None:
    granted = api.put("/v1/live/acct_1/mandate", json=grant(), headers=AUTH).json()

    assert granted["limits"]["max_order_notional"] == "5000"
