"""Our sandbox execution client: Nautilus's, with our fees and a memory.

`SandboxExecutionClient` (nautilus_trader 1.231.0) is right about everything
except two things this platform cannot live with (D25, D26):

* **Fees.** It hard-codes `MakerTakerFeeModel`, which reads the rate off the
  instrument, and a Binance instrument from the public endpoint says zero. A
  simulation charged nothing while the account asked for 10 bps. The model is a
  read-only field, so it cannot be swapped after construction.
* **Balances.** It starts every node from `starting_balances`, so a restart put
  an account holding SOL back to 10,000 USDT and no SOL -- while the cache still
  held the position.

So this builds the same exchange with `BpsFeeModel` -- the class a backtest
charges with, so the two cost a trade identically -- and seeds it from the
account the node loaded from its cache, when there is one.

`__init__` repeats Nautilus's rather than calling it, because the parent's
emits a 10,000 USDT account state on the way out. The version is pinned; the
boot test builds a real node, which is what catches an upgrade that moves this.
"""

from __future__ import annotations

import asyncio
from typing import Any

from nautilus_trader.adapters.sandbox.config import SandboxExecutionClientConfig
from nautilus_trader.adapters.sandbox.execution import SandboxExecutionClient
from nautilus_trader.backtest.engine import SimulatedExchange
from nautilus_trader.backtest.execution_client import BacktestExecClient
from nautilus_trader.backtest.models import FillModel, LatencyModel
from nautilus_trader.common.component import TestClock
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.live.execution_client import LiveExecutionClient
from nautilus_trader.live.factories import LiveExecClientFactory
from nautilus_trader.model.enums import (
    account_type_from_str,
    book_type_from_str,
    oms_type_from_str,
)
from nautilus_trader.model.identifiers import AccountId, ClientId, Venue
from nautilus_trader.model.objects import Currency, Money

from engine.backtest.fees import BpsFeeModel, BpsFeeModelConfig


class SimulationExecClientConfig(SandboxExecutionClientConfig, frozen=True, kw_only=True):
    """The sandbox config plus the account's costs, as basis-point strings."""

    maker_bps: str
    taker_bps: str
    slippage_bps: str


def opening_balances(cache: Any, venue: str, fallback: list[str]) -> list[Money]:
    """What the account holds now, if the cache remembers; else the fallback.

    Zero balances are dropped: a CASH account that sold all its SOL still lists
    it at 0, and seeding the exchange with it buys nothing.
    """
    account = cache.account_for_venue(Venue(venue))
    if account is not None:
        held = [money for money in account.balances_total().values() if money.as_decimal() > 0]
        if held:
            return held
    return [Money.from_str(balance) for balance in fallback]


class SimulationExecutionClient(SandboxExecutionClient):
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        portfolio: Any,
        msgbus: Any,
        cache: Any,
        clock: Any,
        config: SimulationExecClientConfig,
    ) -> None:
        venue = Venue(config.venue)
        oms_type = oms_type_from_str(config.oms_type)
        account_type = account_type_from_str(config.account_type)
        base_currency = Currency.from_str(config.base_currency) if config.base_currency else None

        self.test_clock = TestClock()

        LiveExecutionClient.__init__(
            self,
            loop=loop,
            client_id=ClientId(config.venue),
            venue=venue,
            oms_type=oms_type,
            account_type=account_type,
            base_currency=base_currency,
            instrument_provider=InstrumentProvider(),
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            config=None,
        )
        self._set_account_id(AccountId(f"{config.venue}-001"))

        self.exchange = SimulatedExchange(
            venue=venue,
            oms_type=oms_type,
            account_type=account_type,
            starting_balances=opening_balances(cache, config.venue, config.starting_balances),
            base_currency=base_currency,
            default_leverage=config.default_leverage,
            leverages=config.leverages or {},
            modules=[],
            portfolio=portfolio,
            msgbus=self._msgbus,
            cache=cache,
            clock=self.test_clock,
            fill_model=FillModel(),
            fee_model=BpsFeeModel(
                BpsFeeModelConfig(
                    maker_bps=config.maker_bps,
                    taker_bps=config.taker_bps,
                    slippage_bps=config.slippage_bps,
                )
            ),
            latency_model=LatencyModel(0),
            book_type=book_type_from_str(config.book_type),
            frozen_account=config.frozen_account,
            bar_execution=config.bar_execution,
            trade_execution=config.trade_execution,
            reject_stop_orders=config.reject_stop_orders,
            support_gtd_orders=config.support_gtd_orders,
            support_contingent_orders=config.support_contingent_orders,
            use_position_ids=config.use_position_ids,
            use_random_ids=config.use_random_ids,
            use_reduce_only=config.use_reduce_only,
            use_message_queue=False,
        )
        self._client = BacktestExecClient(
            exchange=self.exchange,
            msgbus=msgbus,
            cache=cache,
            clock=self.test_clock,
        )
        self.exchange.register_client(self._client)
        self.exchange.initialize_account()


class SandboxLiveExecClientFactory(LiveExecClientFactory):
    """Named exactly as Nautilus's: `TradingNodeBuilder` passes the portfolio only
    to a factory whose `__name__` is this string (D17)."""

    @staticmethod
    def create(  # type: ignore[override]
        loop: asyncio.AbstractEventLoop,
        name: str,
        config: SimulationExecClientConfig,
        portfolio: Any,
        msgbus: Any,
        cache: Any,
        clock: Any,
    ) -> SimulationExecutionClient:
        del name
        return SimulationExecutionClient(
            loop=loop,
            portfolio=portfolio,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            config=config,
        )
