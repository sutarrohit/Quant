from __future__ import annotations

import pytest

from engine.live.desired_state import (
    AccountNotFound,
    DesiredStatus,
    LiveStateStore,
    ObservedState,
    ObservedStatus,
    TradingMode,
)
from tests.live.conftest import Clock, desired


async def test_a_state_round_trips(store: LiveStateStore) -> None:
    stored = await store.put(desired())
    assert await store.get("acct_1") == stored
    assert stored.status is DesiredStatus.RUNNING
    assert stored.revision == 1


async def test_writing_the_same_intent_twice_leaves_one_account(store: LiveStateStore) -> None:
    # A POST that started a node would have started two, both trading the same
    # account. This is the property that makes it a state rather than a request.
    await store.put(desired())
    await store.put(desired())
    assert await store.accounts() == ["acct_1"]


async def test_each_write_bumps_the_revision(store: LiveStateStore) -> None:
    # The revision is how a spec change takes effect: the supervisor restarts a
    # node whose running revision no longer matches.
    first = await store.put(desired())
    second = await store.put(desired(strategy_version_id="sv_2"))
    assert (first.revision, second.revision) == (1, 2)


async def test_an_unknown_account_is_not_found(store: LiveStateStore) -> None:
    assert await store.get("nope") is None
    with pytest.raises(AccountNotFound):
        await store.require("nope")


async def test_stopping_keeps_the_record(store: LiveStateStore) -> None:
    # A deleted record is indistinguishable from one that never existed, and
    # the supervisor still has to act on the stop.
    await store.put(desired())
    stopped = await store.stop("acct_1")
    assert stopped.status is DesiredStatus.STOPPED
    assert await store.get("acct_1") is not None


async def test_forgetting_removes_everything(store: LiveStateStore) -> None:
    await store.put(desired())
    await store.observe(ObservedState(account_id="acct_1", status=ObservedStatus.STOPPED))
    await store.forget("acct_1")
    assert await store.get("acct_1") is None
    assert await store.observed("acct_1") is None
    assert await store.accounts() == []


# --- credentials never land here -----------------------------------------


async def test_the_record_holds_a_reference_not_a_secret(store: LiveStateStore) -> None:
    stored = await store.put(
        desired(mode=TradingMode.LIVE, credential_ref="binance/acct_1")
    )
    assert stored.credential_ref == "binance/acct_1"
    # A reference is a pointer; nothing here is usable on its own.
    assert "secret" not in stored.model_dump_json().lower()


async def test_the_reference_is_not_returned_by_default(store: LiveStateStore) -> None:
    stored = await store.put(desired(mode=TradingMode.LIVE, credential_ref="binance/acct_1"))
    assert "credential_ref" not in stored.to_response()


# --- observed state ------------------------------------------------------


async def test_observed_state_round_trips(store: LiveStateStore, clock: Clock) -> None:
    await store.observe(
        ObservedState(account_id="acct_1", status=ObservedStatus.RUNNING, revision=3)
    )
    observed = await store.observed("acct_1")
    assert observed is not None
    assert observed.status is ObservedStatus.RUNNING
    assert observed.revision == 3


async def test_a_heartbeat_refreshes_the_timestamp(store: LiveStateStore, clock: Clock) -> None:
    await store.observe(
        ObservedState(
            account_id="acct_1", status=ObservedStatus.RUNNING, heartbeat_at=clock.moment
        )
    )
    clock.advance(60)
    await store.heartbeat("acct_1")
    observed = await store.observed("acct_1")
    assert observed is not None and observed.heartbeat_at == clock.moment


@pytest.mark.parametrize(
    ("status", "live"),
    [
        (ObservedStatus.STARTING, True),
        (ObservedStatus.RECONCILING, True),
        (ObservedStatus.RUNNING, True),
        (ObservedStatus.STOPPED, False),
        (ObservedStatus.FAILED, False),
    ],
)
def test_which_statuses_count_as_live(status: ObservedStatus, live: bool) -> None:
    assert status.is_live is live


def test_a_node_that_stopped_heartbeating_is_stale(clock: Clock) -> None:
    observed = ObservedState(
        account_id="acct_1", status=ObservedStatus.RUNNING, heartbeat_at=clock.moment
    )
    clock.advance(30)
    assert observed.is_stale(now=clock.moment, timeout_seconds=90) is False
    clock.advance(120)
    assert observed.is_stale(now=clock.moment, timeout_seconds=90) is True


def test_a_stopped_node_is_never_stale(clock: Clock) -> None:
    # Staleness is about a node that should be alive and is not answering.
    observed = ObservedState(account_id="acct_1", status=ObservedStatus.STOPPED)
    clock.advance(10_000)
    assert observed.is_stale(now=clock.moment, timeout_seconds=90) is False


def test_a_running_node_with_no_heartbeat_is_stale(clock: Clock) -> None:
    observed = ObservedState(account_id="acct_1", status=ObservedStatus.RUNNING)
    assert observed.is_stale(now=clock.moment, timeout_seconds=90) is True


# --- the lease -----------------------------------------------------------


async def test_one_holder_wins_the_lease(store: LiveStateStore) -> None:
    # An account is the unit of risk and reconciliation. Two nodes trading it
    # would each believe they held the whole position.
    assert await store.acquire("acct_1", "supervisor-a") is True
    assert await store.acquire("acct_1", "supervisor-b") is False


async def test_the_holder_can_renew_its_own_lease(store: LiveStateStore) -> None:
    await store.acquire("acct_1", "supervisor-a")
    assert await store.acquire("acct_1", "supervisor-a") is True


async def test_releasing_frees_the_account(store: LiveStateStore) -> None:
    await store.acquire("acct_1", "supervisor-a")
    await store.release("acct_1", "supervisor-a")
    assert await store.acquire("acct_1", "supervisor-b") is True


async def test_only_the_holder_can_release(store: LiveStateStore) -> None:
    await store.acquire("acct_1", "supervisor-a")
    await store.release("acct_1", "supervisor-b")
    assert await store.lease_holder("acct_1") == "supervisor-a"


async def test_different_accounts_are_independent(store: LiveStateStore) -> None:
    assert await store.acquire("acct_1", "supervisor-a") is True
    assert await store.acquire("acct_2", "supervisor-b") is True
