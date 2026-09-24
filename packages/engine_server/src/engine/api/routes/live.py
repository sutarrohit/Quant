"""Live trading control plane (spec section 10.1).

`PUT` rather than `POST` is the whole design: live is a **state** that should
still be true after a deploy or a restart, so this records what an account should
be doing and a supervisor converges on it.

Three consequences visible in these routes:

* keyed by **account**, not by request, so writing twice leaves one account
  rather than two nodes trading it;
* `DELETE` asks an account to *stop* without deleting the record -- the
  supervisor still has to act, and a missing record looks like one that never
  existed;
* stopping and flattening are different verbs, because only one closes a
  position.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status

from engine.api.auth import InternalAuth
from engine.api.deps import RedisDep, SettingsDep
from engine.dsl.hashing import spec_hash
from engine.dsl.validator import validate_spec
from engine.errors import AccountNotFound, SnapshotNotFound, SpecInvalid
from engine.live.desired_state import LiveStateStore
from engine.live.kill_switch import RedisKillSwitch
from engine.live.mandate import Mandate, MandateStore
from engine.live.publisher import StateFeed
from engine.settings import Settings
from engine.types.dsl import StrategySpec
from engine.types.live import LiveRequest, MandateRequest, RevokeRequest
from engine.types.state import DesiredState, DesiredStatus, TradingMode

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/live", tags=["live"], dependencies=[InternalAuth])


async def get_live_store(settings: SettingsDep, redis: RedisDep) -> LiveStateStore:
    return LiveStateStore.from_settings(settings, redis)


LiveStoreDep = Annotated[LiveStateStore, Depends(get_live_store)]


def _validate(payload: LiveRequest, settings: Settings) -> StrategySpec:
    spec = StrategySpec.model_validate(payload.spec)
    errors = validate_spec(spec)
    if errors:
        raise SpecInvalid([error.model_dump(mode="json") for error in errors])
    return spec


@router.put("/{account_id}", status_code=status.HTTP_200_OK)
async def put_live(
    account_id: str,
    payload: LiveRequest,
    settings: SettingsDep,
    store: LiveStoreDep,
) -> dict[str, Any]:
    """Record that an account should be trading this strategy."""
    spec = _validate(payload, settings)

    if payload.mode is TradingMode.LIVE and not payload.credential_ref:
        raise SpecInvalid(
            [
                {
                    "path": "credentialRef",
                    "code": "MISSING_CREDENTIAL_REF",
                    "message": "live trading needs a credential reference; simulation does not",
                }
            ]
        )

    stored = await store.put(
        DesiredState(
            account_id=account_id,
            venue=payload.venue,
            instrument_id=payload.instrument_id,
            bar_type=payload.bar_type,
            spec=spec.model_dump(mode="json", by_alias=True),
            strategy_version_id=payload.strategy_version_id,
            spec_hash=spec_hash(spec),
            mode=payload.mode,
            credential_ref=payload.credential_ref,
            risk=payload.risk,
            fees=payload.fees,
            status=DesiredStatus.RUNNING,
        )
    )
    logger.info(
        "live state recorded",
        extra={
            "account_id": account_id,
            "revision": stored.revision,
            "mode": stored.mode.value,
            "spec_hash": stored.spec_hash,
        },
    )
    return stored.to_response()


@router.get("/{account_id}")
async def get_live(account_id: str, store: LiveStoreDep) -> dict[str, Any]:
    """What an account should be doing, and what it is doing."""
    desired = await store.require(account_id)
    observed = await store.observed(account_id)
    return {
        "desired": desired.to_response(),
        "observed": observed.model_dump(mode="json") if observed else None,
        "leaseHolder": await store.lease_holder(account_id),
    }


# --- what an account is doing (docs/simulation-state-plan.md) ----------------


async def get_state_feed(redis: RedisDep) -> StateFeed:
    return StateFeed(redis)


StateFeedDep = Annotated[StateFeed, Depends(get_state_feed)]

#: A stream id: milliseconds, a dash, a sequence number. Checked because it is
#: spliced into an `XRANGE` bound.
STREAM_ID = r"^\d{1,20}-\d{1,20}$"


@router.get("/{account_id}/snapshot")
async def get_snapshot(
    account_id: str, store: LiveStoreDep, feed: StateFeedDep, settings: SettingsDep
) -> dict[str, Any]:
    """Balances, the position, P&L and what the strategy is waiting for.

    A snapshot older than the heartbeat timeout is returned with `stale: true`
    rather than hidden: a dead node's last known state is still the most useful
    thing to show.
    """
    await store.require(account_id)
    snapshot = await feed.snapshot(account_id)
    if snapshot is None:
        raise SnapshotNotFound(f"account {account_id} has not published its state yet")
    age = datetime.now(UTC) - datetime.fromisoformat(snapshot["at"])
    snapshot["stale"] = age.total_seconds() > settings.live_heartbeat_timeout_seconds
    return snapshot


@router.get("/{account_id}/events")
async def get_events(
    account_id: str,
    store: LiveStoreDep,
    feed: StateFeedDep,
    after: Annotated[str | None, Query(pattern=STREAM_ID)] = None,
    limit: Annotated[int, Query(ge=1, le=1_000)] = 100,
) -> dict[str, Any]:
    """Oldest first. Without `after`, the latest `limit`; with it, what came since."""
    await store.require(account_id)
    events, last = await feed.events(account_id, after=after, limit=limit)
    return {"events": events, "last": last}


@router.get("/{account_id}/equity")
async def get_equity(
    account_id: str,
    store: LiveStoreDep,
    feed: StateFeedDep,
    after: Annotated[str | None, Query(pattern=STREAM_ID)] = None,
) -> dict[str, Any]:
    """One point per closed bar, oldest first. Bounded at ~5,000 by the stream."""
    await store.require(account_id)
    points, last = await feed.equity(account_id, after=after)
    return {"points": points, "last": last}


@router.get("")
async def list_live(store: LiveStoreDep) -> dict[str, Any]:
    return {"accounts": await store.accounts()}


@router.delete("/{account_id}")
async def stop_live(account_id: str, store: LiveStoreDep) -> dict[str, Any]:
    """Ask an account to stop trading.

    Stops signalling; it does not close an open position. Turning an
    infrastructure action into a realised loss should never be implicit.
    """
    stopped = await store.stop(account_id)
    logger.info("live stop requested", extra={"account_id": account_id})
    return stopped.to_response()


async def get_kill_switch(redis: RedisDep) -> RedisKillSwitch:
    return RedisKillSwitch(redis)


KillSwitchDep = Annotated[RedisKillSwitch, Depends(get_kill_switch)]


@router.post("/{account_id}/kill", status_code=status.HTTP_200_OK)
async def engage_kill(account_id: str, switch: KillSwitchDep) -> dict[str, Any]:
    """Stop this account submitting new orders, immediately.

    Not routed through api-control: an operator must be able to stop a node when
    the service that sets policy is unreachable (ADR-001).

    **A total stop, exits included.** A strategy you do not trust should not be
    closing positions either -- its idea of an exit may be the bug, and the
    position becomes yours to close at the exchange. To stop *new* risk while it
    keeps managing what it holds, revoke the mandate instead.

    It does not flatten; that is a different decision with a different verb.
    """
    await switch.engage(account_id)
    logger.warning("kill switch engaged", extra={"account_id": account_id})
    return {"accountId": account_id, "killSwitch": "ENGAGED"}


@router.delete("/{account_id}/kill")
async def release_kill(account_id: str, switch: KillSwitchDep) -> dict[str, Any]:
    await switch.release(account_id)
    logger.warning("kill switch released", extra={"account_id": account_id})
    return {"accountId": account_id, "killSwitch": "RELEASED"}


@router.get("/{account_id}/kill")
async def kill_status(account_id: str, switch: KillSwitchDep) -> dict[str, Any]:
    engaged = await switch.is_engaged(account_id)
    return {"accountId": account_id, "killSwitch": "ENGAGED" if engaged else "RELEASED"}


# --- mandates (ADR-002) --------------------------------------------------


async def get_mandates(redis: RedisDep) -> MandateStore:
    return MandateStore(redis)


MandateDep = Annotated[MandateStore, Depends(get_mandates)]


@router.put("/{account_id}/mandate", status_code=status.HTTP_200_OK)
async def grant_mandate(
    account_id: str, payload: MandateRequest, mandates: MandateDep
) -> dict[str, Any]:
    """Authorise an account to trade, on these terms.

    A `PUT` because a mandate is a state, not an event: writing twice leaves one.

    **It does not expire** (ADR-002). A TTL is an outage dependency wearing a
    schedule. Re-granting is how a revoked account is authorised again -- a fresh
    mandate replaces the old one rather than editing away what was withdrawn.
    """
    granted = await mandates.put(
        Mandate(
            account_id=account_id,
            mandate_id=payload.mandate_id,
            issued_by=payload.issued_by,
            limits=payload.limits,
            instruments=tuple(payload.instruments),
        )
    )
    return granted.to_response()


@router.delete("/{account_id}/mandate")
async def revoke_mandate(
    account_id: str, payload: RevokeRequest, mandates: MandateDep
) -> dict[str, Any]:
    """Withdraw authority. The account stops opening new positions.

    **Exits keep running** -- flattening on revoke would turn a control-plane
    action into a market one at whatever price happens to be there. For a total
    stop, use the kill switch.

    Takes effect on the node's next mandate read. Nothing is pushed, so a
    `trading-core` that cannot reach this store cannot stop an account -- the
    cost ADR-002 states and the kill switch covers.
    """
    revoked = await mandates.revoke(account_id, by=payload.revoked_by, reason=payload.reason)
    if revoked is None:
        raise AccountNotFound(f"no mandate for account {account_id}")
    return revoked.to_response()


@router.get("/{account_id}/mandate")
async def read_mandate(account_id: str, mandates: MandateDep) -> dict[str, Any]:
    mandate = await mandates.get(account_id)
    if mandate is None:
        raise AccountNotFound(f"no mandate for account {account_id}")
    return mandate.to_response()


async def get_supervisor_holder(request: Request) -> str:
    holder: str = getattr(request.app.state, "supervisor_holder", "api")
    return holder
