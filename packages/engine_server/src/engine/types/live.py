"""The bodies the live control plane accepts (spec section 10.1).

camelCase on the wire, snake_case in Python; ``populate_by_name`` keeps both
working, because records already in Redis were written with field names.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from engine.types.state import RiskLimitsModel, TradingMode, VenueFees


class LiveRequest(BaseModel):
    """What an account should be trading.

    The same spec a backtest takes -- identical JSON, strategy class and config
    factory. Only the lifecycle differs.
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
    #: A pointer to a key held elsewhere. **Never a key** -- a secret here would
    #: reach a request log, the stored record and every backup of it (ADR-001).
    credential_ref: str | None = Field(default=None, max_length=256)
    #: Account-level limits. Absent means unlimited -- a choice, not a default.
    risk: RiskLimitsModel = Field(default_factory=lambda: RiskLimitsModel())
    #: What the venue charges. **Required**; omitted is a 422, never a zero. The
    #: venue cannot supply it -- public data reports zero fees (D20).
    fees: VenueFees


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
