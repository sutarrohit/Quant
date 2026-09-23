"""The vocabulary the risk kernel speaks (ADR-001).

Pure data. `live/risk.py` holds the decision; these are what it decides over.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class Verdict(StrEnum):
    ALLOW = "ALLOW"
    REJECT = "REJECT"


class Breach(StrEnum):
    KILL_SWITCH = "KILL_SWITCH"
    MANDATE_REVOKED = "MANDATE_REVOKED"
    MAX_ORDER_NOTIONAL = "MAX_ORDER_NOTIONAL"
    MAX_POSITION_NOTIONAL = "MAX_POSITION_NOTIONAL"
    MAX_OPEN_POSITIONS = "MAX_OPEN_POSITIONS"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"


@dataclass(frozen=True, slots=True)
class RiskLimits:
    """What an account may do. ``None`` means unlimited, and is a choice.

    Every value is ``Decimal``: these multiply notionals and compare against
    money, and a float here would be a rounding error in a safety check.
    """

    max_order_notional: Decimal | None = None
    max_position_notional: Decimal | None = None
    max_open_positions: int | None = None
    #: A positive number. Realized loss today beyond this stops new risk.
    daily_loss_limit: Decimal | None = None

    @property
    def is_unlimited(self) -> bool:
        return all(
            value is None
            for value in (
                self.max_order_notional,
                self.max_position_notional,
                self.max_open_positions,
                self.daily_loss_limit,
            )
        )


@dataclass(frozen=True, slots=True)
class AccountRisk:
    """What the account is currently carrying."""

    open_notional: Decimal = Decimal(0)
    open_positions: int = 0
    #: Negative when down. Compared against the loss limit's magnitude.
    realized_pnl_today: Decimal = Decimal(0)


@dataclass(frozen=True, slots=True)
class OrderIntent:
    """An order about to be submitted."""

    instrument_id: str
    notional: Decimal
    #: A closing order reduces risk, so most limits do not apply to it.
    reduce_only: bool = False


@dataclass(frozen=True, slots=True)
class Decision:
    verdict: Verdict
    reason: str = ""
    breach: Breach | None = None

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW


ALLOWED = Decision(Verdict.ALLOW)
