"""The backtest submission contract (spec section 7.2).

``api-control`` is the only caller, and this is exactly the JSON it sends.

**Fees and slippage have no defaults.** Omitting either is a ``422``, never a
zero. A backtest run at zero cost produces the fantasy numbers this platform
exists to refute (spec section 13, pitfall 3) -- and once such a number is
stored, nothing downstream marks it as unrealistic.

Every cost is a ``Decimal`` parsed from a string, so a basis-point figure that
multiplies every notional in the result cannot arrive as a float.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel


class RequestModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        alias_generator=to_camel,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class Fees(RequestModel):
    """Venue commission, in basis points. Both sides required."""

    maker_bps: Decimal = Field(ge=0, le=10_000)
    taker_bps: Decimal = Field(ge=0, le=10_000)


class BacktestRequest(RequestModel):
    #: The idempotency key. A repeat submission returns the existing job.
    request_id: str = Field(min_length=1, max_length=128)
    strategy_version_id: str = Field(min_length=1, max_length=128)
    spec: dict[str, Any]

    venue: str = Field(min_length=1, max_length=32)
    instrument_id: str = Field(min_length=1, max_length=64)
    bar_type: str = Field(min_length=1, max_length=128)

    start: datetime
    end: datetime
    starting_balances: list[str] = Field(min_length=1, max_length=8)

    fees: Fees
    slippage_bps: Decimal = Field(ge=0, le=10_000)

    @field_validator("start", "end")
    @classmethod
    def _must_be_timezone_aware(cls, value: datetime) -> datetime:
        # A naive timestamp would mean a different window on a different
        # machine, and the result would not be reproducible.
        if value.tzinfo is None:
            raise ValueError("timestamps must carry a timezone")
        return value

    @field_validator("end")
    @classmethod
    def _end_after_start(cls, value: datetime, info: Any) -> datetime:
        start = info.data.get("start")
        if start is not None and value <= start:
            raise ValueError("end must be after start")
        return value

    def payload_hash(self) -> str:
        """Identity of everything *except* the request id.

        ``requestId`` is the key; this is what it points at. Two submissions
        sharing an id but differing here are a conflict, not a repeat
        (spec section 7.2).
        """
        payload = self.model_dump(mode="json", by_alias=True, exclude={"request_id"})
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(canonical.encode()).hexdigest()
