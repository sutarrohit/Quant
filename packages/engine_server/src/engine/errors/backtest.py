"""Errors raised while building or running a backtest.

Three of these exist because Nautilus does *not* fail on the condition they
describe -- it returns a perfectly ordinary short result instead. A strategy
that traded three times and a strategy whose account went negative look
identical from the outside, so each is detected and named here.
"""

from __future__ import annotations

from engine.errors.base import EngineError, ErrorCode


class BacktestConfigError(EngineError):
    code = ErrorCode.REQUEST_INVALID
    http_status = 422


class BacktestTimeout(EngineError):
    code = ErrorCode.TIMEOUT
    http_status = 504


class BacktestFailed(EngineError):
    code = ErrorCode.BACKTEST_FAILED
    http_status = 500


class BacktestIncomplete(EngineError):
    """The engine stopped before consuming its data.

    Nautilus halts a backtest on conditions like a negative account balance,
    and ``run()`` returns normally afterwards. The reports then describe only
    the part that ran, and look exactly like an ordinary short result -- a
    strategy that traded three times in 2005 and a strategy whose account
    blew up in 2005 are indistinguishable without this check.
    """

    code = ErrorCode.BACKTEST_INCOMPLETE
    http_status = 500


class NoDataForWindow(EngineError):
    """The catalog holds nothing for the requested bar type and window.

    Checked before the engine starts, because Nautilus does not fail on it: a
    missing instrument makes the strategy's ``on_start`` raise, Nautilus logs
    the error and carries on, and the run returns a perfectly successful
    result with zero fills -- indistinguishable from a strategy that found no
    signals.
    """

    code = ErrorCode.NO_DATA_FOR_WINDOW
    http_status = 422
