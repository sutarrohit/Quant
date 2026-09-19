"""Errors raised while acquiring or reading market data.

Ingest, the catalog, the quality monitors and the venue sources. The split that
matters here is `SymbolUnknownAtVenue` against the rest of `UpstreamError`:
"this coin does not exist" and "Binance is down" arrive as 4xx and 5xx from the
same endpoint, and conflating them means telling a user their symbol is invalid
during an outage.
"""

from __future__ import annotations

from engine.errors.base import EngineError, ErrorCode


class CatalogError(EngineError):
    code = ErrorCode.CATALOG_INVALID
    http_status = 500


class InstrumentError(EngineError):
    code = ErrorCode.INSTRUMENT_INVALID
    http_status = 422


class TimestampDisciplineError(EngineError):
    code = ErrorCode.TIMESTAMP_DISCIPLINE
    http_status = 422


class QualityError(EngineError):
    code = ErrorCode.DATA_QUALITY
    http_status = 422


class IngestError(EngineError):
    code = ErrorCode.REQUEST_INVALID
    http_status = 422


class UnsupportedTimeframe(EngineError):
    """A bar type naming an interval outside the closed set."""

    code = ErrorCode.REQUEST_INVALID
    http_status = 422


class VenueUnsupported(EngineError):
    """No data source exists for the venue the request names."""

    code = ErrorCode.VENUE_UNSUPPORTED
    http_status = 422


class DataRangeUnavailable(EngineError):
    """The venue cannot cover the window that was asked for.

    Raised rather than silently shrinking the window. A backtest quietly run
    over two years when seven were requested is a result the caller will read
    as seven, and no amount of metadata further down makes that safe.
    """

    code = ErrorCode.DATA_RANGE_UNAVAILABLE
    http_status = 422


class UpstreamError(EngineError):
    code = ErrorCode.UPSTREAM_UNAVAILABLE
    http_status = 502


class SymbolUnknownAtVenue(UpstreamError):
    """The venue has no such symbol.

    A 4xx that names the request, not the venue's health -- and the difference
    matters: an unknown symbol is the caller's typo and must be reported as
    such, while an outage must never be reported as "that coin does not exist".
    """

    code = ErrorCode.SYMBOL_UNKNOWN_AT_VENUE
    http_status = 422


class UpstreamRateLimited(UpstreamError):
    code = ErrorCode.UPSTREAM_RATE_LIMITED
    http_status = 429


class UpstreamResponseInvalid(UpstreamError):
    code = ErrorCode.UPSTREAM_RESPONSE_INVALID
    http_status = 502


class CsvSourceError(EngineError):
    code = ErrorCode.UPSTREAM_RESPONSE_INVALID
    http_status = 422
