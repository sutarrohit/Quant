# API Coverage — Binance (public data + public REST)

> Full coverage by default. Opt-outs are explicit, reasoned decisions.
>
> **Detector note:** `api-coverage.cjs` returned `{"detected":false}` when run at plan
> time, because the only available scope was the ROADMAP Phase 1 section (no PLAN.md
> existed yet) and that section names neither "API" nor "integration". The phase
> nevertheless integrates two external Binance surfaces (`data.binance.vision` bulk
> files and `GET /api/v3/exchangeInfo`), and the PLAN.md bodies written this session do
> name them — so the seal-time re-run at `verify:pre` will fire. This matrix is written
> deliberately rather than left to that later failure.

## Surface 1 — `data.binance.vision` (bulk historical files, HTTPS, no auth)

| capability | decision | reason |
|---|---|---|
| `spot/daily/klines` | INTEGRATE | |
| `spot/monthly/klines` | INTEGRATE | full-history ingest per D-22 uses monthly archives; daily fills the tail |
| `CHECKSUM` sidecars | INTEGRATE | D-25 hard-fail on mismatch is a phase success condition |
| `spot/daily/trades` | OPT-OUT | not needed — D-22 fixes Phase 1 at pre-aggregated 1h klines; raw trades are a Phase 2 fill-realism input (SIM-03) |
| `spot/monthly/trades` | OPT-OUT | not needed — same reason as `spot/daily/trades` |
| `spot/daily/aggTrades` | OPT-OUT | not needed — no tick-level aggregation in Phase 1 |
| `spot/monthly/aggTrades` | OPT-OUT | not needed — same reason as `spot/daily/aggTrades` |
| `futures/*` (um/cm klines, markPriceKlines, indexPriceKlines, fundingRate) | OPT-OUT | explicitly out of scope — PROJECT.md scopes v1 to spot; `AccountType.CASH` venue only |
| `option/*` | OPT-OUT | explicitly out of scope — spot only |
| `spot/daily/bookDepth`, `bookTicker` | OPT-OUT | not needed yet — order-book realism is Phase 2 (SIM-03), Phase 1 uses the stock `FillModel()` |

## Surface 2 — Binance public REST (`api.binance.com`, no credentials)

| capability | decision | reason |
|---|---|---|
| `GET /api/v3/exchangeInfo` | INTEGRATE | DATA-03 daily snapshot — the non-backfillable history |
| `GET /api/v3/ping` | INTEGRATE | cron liveness probe before the snapshot write, so a network failure is distinguishable from an empty universe |
| `GET /api/v3/time` | OPT-OUT | not needed — the snapshot records `captured_at` from the cron's own clock; D-14 counts rows per day, not exchange time |
| `GET /api/v3/klines` | OPT-OUT | not needed — bulk files (Surface 1) are the DATA-01 source; the REST kline endpoint is rate-limited and would duplicate it |
| `GET /api/v3/depth` | OPT-OUT | not needed yet — order-book data is Phase 2 (SIM-03) |
| `GET /api/v3/trades`, `/historicalTrades`, `/aggTrades` | OPT-OUT | not needed — same reason as the bulk trades files |
| `GET /api/v3/ticker/*`, `/avgPrice` | OPT-OUT | not needed — Phase 1 is historical backtest only, no live pricing surface |
| Signed endpoints (`/api/v3/order`, `/account`, `/myTrades`, …) | OPT-OUT | explicitly out of scope — PROJECT.md's core rule keeps credentials out of every plane until Phase 5+; Phase 1 places no orders and holds no keys |
| WebSocket streams (`wss://stream.binance.com`) | OPT-OUT | explicitly out of scope — live market data is Phase 5 (PAPER-01) |
| User Data Streams (`listenKey`) | OPT-OUT | explicitly out of scope — requires credentials, Phase 5+ |

## Standing decision

Every `OPT-OUT` above is scoped to Phase 1 only. A later phase that needs one of these
re-decides it from the same full-coverage baseline; none of these opt-outs carries
forward silently.
