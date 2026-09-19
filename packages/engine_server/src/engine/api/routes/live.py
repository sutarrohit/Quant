"""Live trading control plane (spec section 10.1).

`PUT` rather than `POST`, and that is the whole design. A backtest is a request
that runs and finishes; live is a **state** that should still be true after a
deploy, a crash, or this process restarting.

So this endpoint does not start a node. It records what an account should be
doing, and a supervisor converges on it. Restarting the API changes nothing
about what is trading, which is the property that matters.

Three consequences worth noticing in the shape of these routes:

* the resource is keyed by **account**, not by request, so writing the same
  intent twice leaves one account rather than two nodes trading it;
* `DELETE` asks an account to *stop*; it does not delete the record, because
  the supervisor still has to act and a missing record is indistinguishable
  from one that never existed;
* stopping and flattening are different verbs, because "cancel" means two
  different things and only one of them closes a position.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from engine.api.auth import InternalAuth
from engine.api.deps import RedisDep, SettingsDep
from engine.dsl.hashing import spec_hash
from engine.dsl.schema import StrategySpec
from engine.dsl.validator import validate_spec
from engine.errors import AccountNotFound, SpecInvalid
from engine.live.desired_state import (
    DesiredState,
    DesiredStatus,
    LiveStateStore,
    RiskLimitsModel,
    TradingMode,
    VenueFees,
)
from engine.live.kill_switch import RedisKillSwitch
from engine.live.mandate import Mandate, MandateStore
from engine.settings import Settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/live", tags=["live"], dependencies=[InternalAuth])


async def get_live_store(settings: SettingsDep, redis: RedisDep) -> LiveStateStore:
    return LiveStateStore.from_settings(settings, redis)


LiveStoreDep = Annotated[LiveStateStore, Depends(get_live_store)]


class LiveRequest(BaseModel):
    """What an account should be trading.

    The same spec a backtest takes -- identical JSON, identical strategy class,
    identical config factory. Only the lifecycle differs.
    """

    model_config = ConfigDict(
        frozen=True, extra="forbid", alias_generator=to_camel, populate_by_name=True
    )

    spec: dict[str, Any]
    strategy_version_id: str = Field(min_length=1, max_length=128)
    venue: str = Field(min_length=1, max_length=32)
    instrument_id: str = Field(min_length=1, max_length=64)
    bar_type: str = Field(min_length=1, max_length=128)
    mode: TradingMode = TradingMode.SIMULATION
    #: A pointer to a key held elsewhere. **Never a key.** A secret in this
    #: body would reach a request log, the stored record, and every backup of
    #: it (ADR-001).
    credential_ref: str | None = Field(default=None, max_length=256)
    #: Account-level limits. Absent means unlimited, which is a choice rather
    #: than a default worth relying on.
    risk: RiskLimitsModel = Field(default_factory=lambda: RiskLimitsModel())
    #: What the venue charges. **Required**, exactly as on a backtest request
    #: (rule 5): omitted is a 422, never a zero. The venue cannot supply it --
    #: public instrument data reports zero fees and the real rates need a key
    #: (D20) -- so the operator declares it.
    fees: VenueFees


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


@router.get("")
async def list_live(store: LiveStoreDep) -> dict[str, Any]:
    return {"accounts": await store.accounts()}


@router.delete("/{account_id}")
async def stop_live(account_id: str, store: LiveStoreDep) -> dict[str, Any]:
    """Ask an account to stop trading.

    Stops signalling; it does not close an open position. Flattening is a
    different decision and gets its own verb, because turning an
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

    Deliberately not routed through api-control: an operator must be able to
    stop a node when the service that sets policy is unreachable, which is
    exactly when they are most likely to want to (ADR-001).

    **A total stop, exits included.** You reach for a kill switch when you do
    not trust the strategy, and a strategy you do not trust should not be
    closing positions either -- its idea of an exit may be the bug. The
    position becomes yours to close at the exchange.

    To stop an account taking on *new* risk while it keeps managing what it
    holds, revoke its mandate instead. That is the softer instrument and it is
    a different endpoint on purpose.

    It does not flatten -- turning an operator's "stop" into a realised loss is
    a different decision and gets a different verb again.
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


class MandateRequest(BaseModel):
    """Authority for one account, as `trading-core` grants it."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", alias_generator=to_camel, populate_by_name=True
    )

    mandate_id: str = Field(min_length=1, max_length=128)
    issued_by: str = Field(min_length=1, max_length=128)
    limits: RiskLimitsModel = Field(default_factory=lambda: RiskLimitsModel())
    #: Empty means every instrument this account is configured to trade.
    instruments: list[str] = Field(default_factory=list, max_length=64)


class RevokeRequest(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", alias_generator=to_camel, populate_by_name=True
    )

    revoked_by: str = Field(min_length=1, max_length=128)
    reason: str | None = Field(default=None, max_length=512)


async def get_mandates(redis: RedisDep) -> MandateStore:
    return MandateStore(redis)


MandateDep = Annotated[MandateStore, Depends(get_mandates)]


@router.put("/{account_id}/mandate", status_code=status.HTTP_200_OK)
async def grant_mandate(
    account_id: str, payload: MandateRequest, mandates: MandateDep
) -> dict[str, Any]:
    """Authorise an account to trade, on these terms.

    A `PUT` because a mandate is a state rather than an event, exactly as the
    desired state is: writing the same authority twice leaves one mandate.

    **It does not expire.** ADR-002 chose revoke-only, because a TTL is an
    outage dependency wearing a schedule -- a mandate that lapses during a
    `trading-core` outage stops trading, which is the outcome that decision
    exists to prevent.

    Re-granting is also how a revoked account is authorised again: a fresh
    mandate replaces the old one rather than un-revoking it, so the record of
    what was withdrawn is not edited away.
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

    **Exits keep running.** Stops and take-profits are how a position is shed,
    and flattening on revoke would turn a control-plane action into a market
    one at whatever price happens to be there. For a total stop, use the kill
    switch -- a different instrument for a different situation.

    Takes effect on the node's next mandate read, within seconds. Nothing is
    pushed: the node reads, so a `trading-core` that cannot reach this store
    cannot stop an account, which is the cost ADR-002 states and the kill
    switch exists to cover.
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
