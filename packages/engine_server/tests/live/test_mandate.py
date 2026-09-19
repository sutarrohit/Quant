"""Authority to trade, held rather than requested (ADR-002).

The decisions under test are all about failure: what happens when a mandate is
absent, withdrawn, or unreadable. Each has a different right answer, and
picking the wrong one either stops trading during an outage or lets an account
trade without authority.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import fakeredis
import fakeredis.aioredis
import pytest

from engine.errors import MandateMissing, MandateRevoked
from engine.live.desired_state import RiskLimitsModel
from engine.live.mandate import Mandate, MandateStore


@pytest.fixture
def store() -> MandateStore:
    redis = fakeredis.aioredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)
    return MandateStore(redis, now=lambda: datetime(2026, 1, 1, tzinfo=UTC))


def mandate(**overrides: object) -> Mandate:
    payload: dict[str, object] = {
        "account_id": "acct_1",
        "mandate_id": "m_1",
        "issued_by": "trading-core",
        "limits": RiskLimitsModel(max_order_notional=Decimal(5_000)),
    }
    payload.update(overrides)
    return Mandate(**payload)  # type: ignore[arg-type]


# --- granting ------------------------------------------------------------


async def test_a_granted_mandate_is_active(store: MandateStore) -> None:
    await store.put(mandate())

    found = await store.get("acct_1")

    assert found is not None
    assert found.is_active


async def test_granting_twice_leaves_one_mandate(store: MandateStore) -> None:
    # A PUT because a mandate is a state, not an event -- the same reason the
    # desired state is a PUT.
    await store.put(mandate())
    await store.put(mandate(mandate_id="m_2"))

    found = await store.get("acct_1")

    assert found is not None
    assert found.mandate_id == "m_2"


async def test_a_mandate_carries_its_own_limits(store: MandateStore) -> None:
    """One source, not two.

    ADR-002 asks that a mandate's limits and the account's limits be the same
    thing: two copies that can disagree is how an account ends up trading
    inside a limit nobody set.
    """
    await store.put(mandate())

    found = await store.get("acct_1")

    assert found is not None
    assert found.to_limits().max_order_notional == Decimal(5_000)


async def test_there_is_no_expiry_field() -> None:
    """Revoke-only, and the absence is the decision.

    A TTL is an outage dependency wearing a schedule: set it to 24 hours and a
    25-hour `trading-core` outage stops trading, which is the forbidden outcome
    arriving a day late. Asserted so nobody adds one back as a courtesy.
    """
    assert "expires_at" not in Mandate.model_fields
    assert "ttl" not in Mandate.model_fields
    assert not any("expir" in name for name in Mandate.model_fields)


# --- revocation ----------------------------------------------------------


async def test_revoking_makes_it_inactive(store: MandateStore) -> None:
    await store.put(mandate())

    revoked = await store.revoke("acct_1", by="an operator", reason="spec looks wrong")

    assert revoked is not None
    assert not revoked.is_active
    assert revoked.revoked_by == "an operator"
    assert revoked.revoked_reason == "spec looks wrong"


async def test_a_revoked_mandate_keeps_its_history(store: MandateStore) -> None:
    # Revocation annotates rather than deletes: what was authorised, by whom,
    # and when it was withdrawn all survive.
    await store.put(mandate())
    await store.revoke("acct_1", by="an operator")

    found = await store.get("acct_1")

    assert found is not None
    assert found.mandate_id == "m_1"
    assert found.issued_by == "trading-core"
    assert found.revoked_at is not None


async def test_revoking_twice_does_not_move_the_timestamp(store: MandateStore) -> None:
    await store.put(mandate())
    first = await store.revoke("acct_1", by="a")

    second = await store.revoke("acct_1", by="b")

    assert first is not None and second is not None
    assert second.revoked_at == first.revoked_at
    assert second.revoked_by == "a"


async def test_revoking_nothing_is_not_an_error(store: MandateStore) -> None:
    # An account that was never authorised is exactly as unauthorised after.
    assert await store.revoke("never_seen", by="an operator") is None


async def test_a_fresh_grant_re_authorises(store: MandateStore) -> None:
    """How a revoked account trades again.

    `trading-core` writes a new mandate rather than un-revoking the old one, so
    the record of what was withdrawn is not edited away.
    """
    await store.put(mandate())
    await store.revoke("acct_1", by="an operator")

    await store.put(mandate(mandate_id="m_2"))

    found = await store.get("acct_1")
    assert found is not None and found.is_active


# --- what a live node demands --------------------------------------------


async def test_a_missing_mandate_refuses(store: MandateStore) -> None:
    """Absent is not permissive.

    Trading real money with no recorded authority is worse than not trading,
    and "there was no record" is not a defence anyone wants to give afterwards.
    """
    with pytest.raises(MandateMissing, match="no mandate"):
        await store.require_active("acct_1", "BTCUSDT.BINANCE")


async def test_a_revoked_mandate_refuses(store: MandateStore) -> None:
    await store.put(mandate())
    await store.revoke("acct_1", by="an operator", reason="drawdown")

    with pytest.raises(MandateRevoked) as raised:
        await store.require_active("acct_1", "BTCUSDT.BINANCE")

    # The operator needs the reason, not just the refusal.
    assert raised.value.details is not None
    assert raised.value.details["reason"] == "drawdown"


async def test_the_refusals_are_distinguishable(store: MandateStore) -> None:
    # "This account may not trade" is not an answer anyone can act on. Missing
    # and revoked need different responses.
    assert MandateMissing is not MandateRevoked


async def test_an_instrument_outside_the_mandate_refuses(store: MandateStore) -> None:
    await store.put(mandate(instruments=("ETHUSDT.BINANCE",)))

    with pytest.raises(MandateRevoked, match="does not cover"):
        await store.require_active("acct_1", "BTCUSDT.BINANCE")


async def test_no_instruments_means_any(store: MandateStore) -> None:
    """A deliberate default.

    The desired state already names exactly one instrument; a second list would
    be a second thing to keep in step, and drift between them would be silent.
    """
    await store.put(mandate())

    assert await store.require_active("acct_1", "BTCUSDT.BINANCE")


async def test_an_active_mandate_is_returned(store: MandateStore) -> None:
    await store.put(mandate())

    found = await store.require_active("acct_1", "BTCUSDT.BINANCE")

    assert found.mandate_id == "m_1"


# --- the record ----------------------------------------------------------


async def test_it_survives_a_round_trip(store: MandateStore) -> None:
    # It lives in Redis as JSON; every field has to come back.
    original = mandate(instruments=("BTCUSDT.BINANCE",))
    await store.put(original)

    found = await store.get("acct_1")

    assert found == original


async def test_forgetting_removes_it(store: MandateStore) -> None:
    await store.put(mandate())

    await store.forget("acct_1")

    assert await store.get("acct_1") is None
