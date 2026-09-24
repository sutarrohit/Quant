"""Every error this service can raise.

One package, one file per area, mirroring the package that raises them:
`engine.errors.data` for `engine.data`, `engine.errors.live` for `engine.live`,
and so on. `base` holds the machinery -- `ErrorCode`, `EngineError`, the two
response shapes -- and the errors that belong to no single area.

Import from here:

    from engine.errors import EngineError, ErrorCode, NoDataForWindow

Everything is re-exported, so the submodule a class lives in is an organising
detail rather than something every call site has to track. Import the submodule
directly (`from engine.errors.live import LiveNotPermitted`) when it reads
better to name the area.

**Adding one:** append to `ErrorCode` in `base` -- values are never renamed or
reused, because the TypeScript caller branches on them -- then define the class
in the file for its area and add it to `__all__` below. See
`docs/explanations/error-handling.md`.
"""

from __future__ import annotations

from engine.errors.backtest import (
    BacktestConfigError,
    BacktestFailed,
    BacktestIncomplete,
    BacktestTimeout,
    NoDataForWindow,
)
from engine.errors.base import (
    ConfigurationError,
    EngineError,
    ErrorCode,
    NotFoundError,
    NotReadyError,
    SpecInvalid,
    UnauthenticatedError,
    status_to_code,
)
from engine.errors.data import (
    CatalogError,
    CsvSourceError,
    DataRangeUnavailable,
    IngestError,
    InstrumentError,
    QualityError,
    SymbolUnknownAtVenue,
    TimestampDisciplineError,
    UnsupportedTimeframe,
    UpstreamError,
    UpstreamRateLimited,
    UpstreamResponseInvalid,
    VenueUnsupported,
)
from engine.errors.dsl import (
    InterpreterError,
    UnknownIndicatorError,
)
from engine.errors.live import (
    AccountNotFound,
    CacheNotIsolated,
    CredentialUnavailable,
    LiveNotPermitted,
    MandateMissing,
    MandateRevoked,
    PreflightFailed,
    ReconciliationFailed,
    SnapshotNotFound,
)
from engine.errors.simulation import (
    VenueNotSupported,
)
from engine.errors.store import (
    JobNotCancellable,
    JobNotFound,
    RequestIdConflict,
)
from engine.errors.strategies import (
    StrategySetupError,
)

__all__ = [
    "AccountNotFound",
    "SnapshotNotFound",
    "BacktestConfigError",
    "BacktestFailed",
    "BacktestIncomplete",
    "BacktestTimeout",
    "CacheNotIsolated",
    "CatalogError",
    "ConfigurationError",
    "CredentialUnavailable",
    "CsvSourceError",
    "DataRangeUnavailable",
    "EngineError",
    "ErrorCode",
    "IngestError",
    "InstrumentError",
    "InterpreterError",
    "JobNotCancellable",
    "JobNotFound",
    "LiveNotPermitted",
    "MandateMissing",
    "MandateRevoked",
    "NoDataForWindow",
    "NotFoundError",
    "NotReadyError",
    "PreflightFailed",
    "QualityError",
    "ReconciliationFailed",
    "RequestIdConflict",
    "SpecInvalid",
    "StrategySetupError",
    "SymbolUnknownAtVenue",
    "TimestampDisciplineError",
    "UnauthenticatedError",
    "UnknownIndicatorError",
    "UnsupportedTimeframe",
    "UpstreamError",
    "UpstreamRateLimited",
    "UpstreamResponseInvalid",
    "VenueNotSupported",
    "VenueUnsupported",
    "status_to_code",
]
