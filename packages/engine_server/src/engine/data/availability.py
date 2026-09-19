"""Is this symbol something we can get data for?

The validator asks one question on the request path: *is this instrument
knowable*. Before automatic provisioning that meant "is it in the catalog", and
the answer was wrong for every symbol nobody had ingested by hand yet -- which
is the exact case automatic provisioning exists to serve.

So the question moved: an instrument is knowable if the catalog **already holds
it** or the **venue lists it**. The first answer is free. The second costs one
`exchangeInfo` call, cached in Redis, and only for symbols the catalog misses.

**Why ask at all, rather than let the worker find out.** A typo should come back
as a `422` on submit, not as a job that is accepted, queued, picked up and then
failed. Fast feedback on a bad spec is what the handler is for (spec section
7.2); it is only *slow* work that belongs in the worker.

**Why an outage is permissive.** If the venue cannot be reached, this reports the
symbol as knowable and lets the job proceed to the worker, which will fail it
with an upstream error if the outage persists. The alternative -- rejecting the
spec -- would tell a user their strategy names a symbol that does not exist,
which is both false and the kind of error somebody spends an afternoon chasing.
"""

from __future__ import annotations

import asyncio
import logging

from redis.asyncio import Redis

from engine.data.catalog import Catalog
from engine.data.provision import VenueUnsupported, source_for
from engine.data.sources.binance import SymbolUnknownAtVenue, UpstreamError
from engine.settings import Settings

logger = logging.getLogger(__name__)

#: Cache key for one symbol's existence at one venue.
SYMBOL_KEY = "venue:{venue}:symbol:{symbol}"

#: A listing does not disappear, so a positive answer can be held a while. A
#: negative one is short-lived: a symbol listed today should not be refused for
#: an hour because somebody asked an hour too early.
KNOWN_TTL_SECONDS = 24 * 3600
UNKNOWN_TTL_SECONDS = 300


class SymbolAvailability:
    """What the validator may treat as a knowable instrument."""

    def __init__(self, catalog: Catalog, settings: Settings, redis: Redis | None = None) -> None:
        self._catalog = catalog
        self._settings = settings
        self._redis = redis

    async def knowable(self, instrument_ids: tuple[str, ...]) -> list[str]:
        """Of the ids asked about, those the service can produce data for.

        The return value is what `validate_spec(known_instruments=...)` wants:
        everything already in the catalog, plus any requested id the venue
        confirms. An id missing from the result is one the caller got wrong.
        """
        held = self._catalog.backtestable_instrument_ids()
        missing = [name for name in instrument_ids if name not in set(held)]
        if not missing:
            return held

        fetchable = [name for name in missing if await self._venue_lists(name)]
        return [*held, *fetchable]

    async def _venue_lists(self, instrument_id: str) -> bool:
        symbol, _, venue = instrument_id.partition(".")
        if not venue:
            return False

        cached = await self._cached(venue, symbol)
        if cached is not None:
            return cached

        try:
            # A probe, not an ingest: one attempt and a short timeout, because
            # this runs inside a request.
            source = source_for(venue, self._settings, probe=True)
        except VenueUnsupported:
            # No source for the venue, so nothing can be fetched for it. The
            # spec error names the symbol; the worker would name the venue.
            return False

        try:
            await asyncio.to_thread(source.fetch_instrument, symbol)
        except SymbolUnknownAtVenue:
            await self._remember(venue, symbol, listed=False)
            return False
        except UpstreamError as exc:
            # Reachability is not the caller's problem. Let it through.
            logger.warning(
                "could not check symbol at venue, allowing",
                extra={"symbol": symbol, "venue": venue, "error": str(exc)},
            )
            return True
        finally:
            source.close()

        await self._remember(venue, symbol, listed=True)
        return True

    async def _cached(self, venue: str, symbol: str) -> bool | None:
        if self._redis is None:
            return None
        try:
            value = await self._redis.get(SYMBOL_KEY.format(venue=venue, symbol=symbol))
        except Exception:  # noqa: BLE001 -- a cache miss and a broken cache are the same thing
            return None
        if value is None:
            return None
        return str(value) == "1"

    async def _remember(self, venue: str, symbol: str, *, listed: bool) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.set(
                SYMBOL_KEY.format(venue=venue, symbol=symbol),
                "1" if listed else "0",
                ex=KNOWN_TTL_SECONDS if listed else UNKNOWN_TTL_SECONDS,
            )
        except Exception:  # noqa: BLE001 -- never fail a request over a cache write
            logger.warning("could not cache symbol lookup", extra={"symbol": symbol})
