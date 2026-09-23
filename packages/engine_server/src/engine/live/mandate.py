"""Authority to trade, held rather than requested (ADR-002).

`trading-core` decides what an account may do, but is never asked at order time:
**a `trading-core` outage must not stop trading**, and a node that asks
permission stops exactly when the thing it asks is unreachable. So authority
arrives ahead of time and is enforced from this service's own store.

**No expiry.** A TTL is an outage dependency wearing a schedule. Valid until
`trading-core` revokes it.

**Revocation blocks new risk and nothing else.** Exits keep running; flattening
on revoke would let a control-plane event decide a trade at whatever price the
market happens to be. The kill switch is the deliberate exception.

**Absent is not permissive.** A node refuses to start without an active mandate.

The cost, per ADR-002: **a revocation issued while `trading-core` cannot reach
this store does not arrive.** The kill switch depends on neither service.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis

from engine.errors import MandateMissing, MandateRevoked
from engine.types.risk import RiskLimits
from engine.types.state import RiskLimitsModel

logger = logging.getLogger(__name__)

MANDATE_KEY = "live:mandate:{account_id}"


class Mandate(BaseModel):
    """What `trading-core` has authorised for one account.

    Carries the limits itself rather than pointing at them. ADR-002 asks that a
    mandate's limits and the account's limits be *one* thing: two copies that
    can disagree is how an account ends up trading inside a limit nobody set.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: str = Field(min_length=1, max_length=128)
    #: Identifies this grant of authority. Changes when the terms change, so a
    #: node can say which mandate an order was placed under.
    mandate_id: str = Field(min_length=1, max_length=128)
    #: Who granted it. Free text, and it belongs in every audit line.
    issued_by: str = Field(min_length=1, max_length=128)
    issued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    #: What the account may do. The single source once a mandate exists.
    limits: RiskLimitsModel = Field(default_factory=lambda: RiskLimitsModel())
    #: Instruments this authority covers. Empty means "any this account trades"
    #: -- a deliberate choice, since the desired state already names exactly one
    #: instrument and a second list would be a second thing to keep in step.
    instruments: tuple[str, ...] = ()

    #: Set on revocation. Presence, not a timestamp comparison, is what makes a
    #: mandate inactive -- there is no clock in the decision.
    revoked_at: datetime | None = None
    revoked_by: str | None = Field(default=None, max_length=128)
    revoked_reason: str | None = Field(default=None, max_length=512)

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None

    def covers(self, instrument_id: str) -> bool:
        return not self.instruments or instrument_id in self.instruments

    def to_limits(self) -> RiskLimits:
        return self.limits.to_limits()

    def to_response(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class MandateStore:
    """Reads and writes mandates. One per account."""

    def __init__(
        self, redis: Redis, *, now: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._redis = redis
        self._now = now

    @classmethod
    def from_redis(cls, redis: Redis) -> Self:
        return cls(redis)

    async def put(self, mandate: Mandate) -> Mandate:
        """Grant authority. Replaces whatever was there.

        A re-grant is how a revoked account is authorised again: `trading-core`
        writes a fresh mandate rather than un-revoking the old one, so the
        record of what was withdrawn is not edited away.
        """
        await self._redis.set(
            MANDATE_KEY.format(account_id=mandate.account_id), mandate.model_dump_json()
        )
        logger.info(
            "mandate granted",
            extra={
                "account_id": mandate.account_id,
                "mandate_id": mandate.mandate_id,
                "issued_by": mandate.issued_by,
                "limits_set": not mandate.to_limits().is_unlimited,
            },
        )
        return mandate

    async def get(self, account_id: str) -> Mandate | None:
        raw = await self._redis.get(MANDATE_KEY.format(account_id=account_id))
        if raw is None:
            return None
        return Mandate.model_validate_json(raw.decode() if isinstance(raw, bytes) else raw)

    async def revoke(
        self, account_id: str, *, by: str, reason: str | None = None
    ) -> Mandate | None:
        """Withdraw authority. The account stops opening risk on the next refresh.

        Returns `None` if there was nothing to revoke, which is not an error:
        revoking an account that was never authorised leaves it exactly as
        unauthorised as it was.
        """
        current = await self.get(account_id)
        if current is None:
            logger.warning("nothing to revoke", extra={"account_id": account_id})
            return None
        if not current.is_active:
            return current

        revoked = current.model_copy(
            update={"revoked_at": self._now(), "revoked_by": by, "revoked_reason": reason}
        )
        await self._redis.set(
            MANDATE_KEY.format(account_id=account_id), revoked.model_dump_json()
        )
        logger.warning(
            "mandate revoked",
            extra={
                "account_id": account_id,
                "mandate_id": revoked.mandate_id,
                "revoked_by": by,
                "reason": reason,
            },
        )
        return revoked

    async def forget(self, account_id: str) -> None:
        """Remove the record entirely. For an account being decommissioned."""
        await self._redis.delete(MANDATE_KEY.format(account_id=account_id))

    async def require_active(self, account_id: str, instrument_id: str) -> Mandate:
        """The check a live node makes before it starts. Raises, never returns None.

        Three refusals rather than one, because "this account may not trade" is
        not an answer an operator can act on. Missing, revoked and out-of-scope
        need different responses.
        """
        mandate = await self.get(account_id)
        if mandate is None:
            raise MandateMissing(
                f"account {account_id} has no mandate; live trading needs recorded "
                "authority and absent is not permissive (docs/adr-002-risk-kernel.md)",
                details={"accountId": account_id},
            )
        if not mandate.is_active:
            raise MandateRevoked(
                f"the mandate for account {account_id} was revoked",
                details={
                    "accountId": account_id,
                    "mandateId": mandate.mandate_id,
                    "revokedAt": mandate.revoked_at.isoformat() if mandate.revoked_at else None,
                    "reason": mandate.revoked_reason,
                },
            )
        if not mandate.covers(instrument_id):
            raise MandateRevoked(
                f"the mandate for account {account_id} does not cover {instrument_id}",
                details={
                    "accountId": account_id,
                    "mandateId": mandate.mandate_id,
                    "instruments": list(mandate.instruments),
                },
            )
        return mandate
