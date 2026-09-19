# How this service handles errors

For a developer who has just cloned the repo and is about to write a function
that can fail.

## The one rule

**Every failure carries a stable, machine-readable `code`. Callers branch on the
code, never on the message.**

```json
{"code": "DATA_RANGE_UNAVAILABLE", "message": "SOLUSDT.BINANCE has no data before 2020-08-11"}
```

The message is for a human and may be reworded any time. The code is part of the
API contract: the TypeScript `api-control` service switches on it, so renaming
one breaks a caller you cannot see from here. `ErrorCode`
(`src/engine/errors/base.py`) is append-only — values are never renamed and never
reused.

That is the whole philosophy. Everything below is machinery for keeping it true
across three very different boundaries.

## The two response shapes

There are exactly two, both defined in `src/engine/errors/base.py`.

**Single error** — something went wrong:

```json
{"code": "JOB_NOT_FOUND", "message": "no such job job_abc", "details": {"jobId": "job_abc"}}
```

**Validation** — *several* things are wrong and the user should see all of them:

```json
{"errors": [
  {"path": "market.symbols[0]", "code": "SYMBOL_NOT_IN_CATALOG", "message": "..."},
  {"path": "exit", "code": "MISSING_STOP_LOSS", "message": "..."}
]}
```

A strategy spec is rejected as a **list**, because fixing one error at a time
through six round trips is a miserable way to author anything. `SpecInvalid`
(`errors/base.py`) is the only error that renders this shape, by overriding
`to_payload`.

Note the two enums that go with them: `ErrorCode` for transport-level failures,
and `SpecErrorCode` (`src/engine/dsl/validator.py`) for *what is wrong with this
strategy* — `UNKNOWN_INDICATOR`, `MISSING_STOP_LOSS`, `AMBIGUOUS_COMPARISON`.
Both are append-only for the same reason.

## `EngineError`, and how to add one

```python
class EngineError(Exception):
    code: ClassVar[ErrorCode] = ErrorCode.INTERNAL
    http_status: ClassVar[int] = 500

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None: ...
```

An error is a class with two class variables. That is deliberately all it is:

```python
class DataRangeUnavailable(EngineError):
    """The venue cannot cover the window that was asked for."""

    code = ErrorCode.DATA_RANGE_UNAVAILABLE
    http_status = 422
```

Every error lives in **`src/engine/errors/`**, one file per area, each named for
the package that raises it:

```
src/engine/errors/
  __init__.py     re-exports everything
  base.py         ErrorCode, EngineError, the two response shapes, and the
                  errors that belong to no single area
  backtest.py     engine.backtest    -- builder and runner
  data.py         engine.data        -- catalog, ingest, quality, venue sources
  dsl.py          engine.dsl         -- interpreter, indicator registry
  live.py         engine.live        -- supervisor, node, mandate, recovery
  simulation.py   engine.simulation
  store.py        engine.store       -- the job store
  strategies.py   engine.strategies
```

Import from the package; which submodule a class sits in is an organising
detail:

```python
from engine.errors import EngineError, ErrorCode, NoDataForWindow
```

Import the submodule directly (`from engine.errors.live import LiveNotPermitted`)
when naming the area reads better. Both work — `__init__` re-exports every name.

The trade-off, because the alternative is defensible: errors used to sit beside
the code that raised them, which made "what can this module fail with" a scroll
away. Collecting them makes *the set of failures this service has* legible in one
place — which is the question asked more often, and asked hardest by whoever
writes the TypeScript that branches on the codes.

**`details` is for machine-readable context**, not prose. It is what lets a
caller act without parsing English:

```python
raise DataRangeUnavailable(
    f"{bar_type} has no data before {coverage.start.isoformat()}",
    details={"earliestAvailable": coverage.start.isoformat(), ...},
)
```

The frontend can now prefill the date picker. Had that date only been in the
message, it would have to regex it out.

## Where exceptions become responses

Nothing in a route builds an error response by hand. Four handlers in
`src/engine/api/app.py` do all of it:

| Handler | Catches | Produces | Line |
|---|---|---|---|
| `handle_engine_error` | any `EngineError` | `exc.to_payload()` at `exc.http_status` | `app.py:79` |
| `handle_http_exception` | Starlette's `HTTPException` | same shape, code via `status_to_code` | `app.py:84` |
| `handle_validation_error` | Pydantic's `RequestValidationError` | the `{"errors": [...]}` list, 422 | `app.py:92` |
| `handle_unexpected` | bare `Exception` | `{"code": "INTERNAL"}`, 500 | `app.py:106` |

Two consequences worth internalising:

**Route code just raises.** No try/except, no `JSONResponse`. Raise the right
`EngineError` and the envelope, the status and the code follow.

**Shapes never leak in from a framework.** FastAPI's default 401 body and
Pydantic's default 422 body look nothing like ours, so both are intercepted and
reshaped. This is also why `HTTPBearer(auto_error=False)` is used in
`api/auth.py` — letting FastAPI raise its own 401 would put a foreign shape on
the wire.

## The journey of one error: `raise` → caught → delivered

Nobody in this codebase catches an `EngineError` in order to respond to it. The
framework does, in a layer you never see. Here is the whole path.

### The layers a request passes through

Starlette wraps the app in middleware, outermost first. An exception travels
**back up** this stack until something catches it:

```
   request
      |
      v
  ServerErrorMiddleware      <- the LAST resort; holds the Exception handler
      |
      v
  bind_request_context       <- ours: binds request_id, adds the response header
      |
      v
  ExceptionMiddleware        <- holds every OTHER registered handler
      |
      v
  your route  ->  raise DataRangeUnavailable(...)
```

### Step by step

**1. You raise.** Nothing else. No response, no status code, no try/except:

```python
raise DataRangeUnavailable("SOLUSDT.BINANCE has no data before 2020-08-11",
                           details={"earliestAvailable": "2020-08-11T00:00:00+00:00"})
```

**2. `ExceptionMiddleware` catches it.** It looks the exception up in the handler
table FastAPI built from the `@app.exception_handler(...)` decorators in
`create_app`. The lookup walks the class's MRO, so `DataRangeUnavailable` →
`EngineError` finds `handle_engine_error` even though nobody registered the
subclass.

**3. The handler turns it into a response** (`app.py:79`):

```python
@app.exception_handler(EngineError)
async def handle_engine_error(_: Request, exc: EngineError) -> JSONResponse:
    logger.warning("request failed", extra={"code": exc.code.value})
    return JSONResponse(status_code=exc.http_status, content=exc.to_payload())
```

Three things come off the *exception object itself* — `exc.http_status` is the
status, `exc.code` goes to the log, `exc.to_payload()` is the body. This is why
an error class declares its own `http_status`: the decision was made once, where
the error was defined, and no route re-decides it.

**4. The response travels back out** through `bind_request_context`, which stamps
the correlation header on it:

```python
response.headers["x-request-id"] = request_id
```

From the middleware's point of view nothing failed — it is holding a perfectly
ordinary `JSONResponse` that happens to say 422.

**5. The user gets it.** Verified against the running app:

```
GET /probe/engine-error   (x-request-id: req_TRACE_ME)

  422
  {"code":"NO_DATA_FOR_WINDOW","message":"the catalog holds nothing","details":{"barType":"X"}}
  x-request-id: req_TRACE_ME
```

and the matching log line, carrying the same id:

```json
{"code": "NO_DATA_FOR_WINDOW", "level": "WARNING", "logger": "engine.api.app",
 "message": "request failed", "request_id": "req_TRACE_ME"}
```

### The other four entry points

The same four handlers cover everything that can go wrong, not just our own
exceptions:

| What raised | Caught by | User sees |
|---|---|---|
| Your `raise SomeEngineError(...)` | `handle_engine_error` | that error's code and status |
| `raise SpecInvalid([...])` | `handle_engine_error`, but `to_payload` is overridden | `{"errors": [...]}`, 422 |
| Pydantic, on a malformed body | `handle_validation_error` | `{"errors": [...]}`, 422, one entry per bad field |
| FastAPI/Starlette internals | `handle_http_exception` | our shape, code from `status_to_code` |
| Anything unplanned (`ValueError`, `KeyError`) | `handle_unexpected` | `{"code": "INTERNAL"}`, 500 |

The `handle_validation_error` case is worth a look, because it is translation
rather than pass-through. Pydantic's error list is reshaped field by field into
*our* envelope, so a caller renders one format whether the spec was malformed or
merely wrong:

```python
errors = [{"path": ".".join(str(p) for p in error["loc"]),
           "code": ErrorCode.REQUEST_INVALID.value,
           "message": error["msg"]} for error in exc.errors()]
```

### An unplanned 500 takes a different route

`@app.exception_handler(Exception)` is **not** stored with the others. Starlette
installs it on `ServerErrorMiddleware`, the outermost layer, because by
definition it handles the case where everything else has already failed.

That placement is a trap, and this service works around it. An exception left to
reach that handler has already blown **past** `bind_request_context` on its way
up: the middleware never gets a response to stamp the header on, and the
`log_context` it bound is already unwound by the time the traceback is logged.
The result was a 500 with **no `request_id` at either end** — on the one failure
a developer most needs to find in the logs.

So the middleware catches it first, inside the context it owns:

```python
with log_context(request_id=request_id):
    try:
        response = await call_next(request)
    except Exception as exc:  # noqa: BLE001
        logger.exception("unhandled exception", exc_info=exc)
        response = internal_error_response()
response.headers["x-request-id"] = request_id
```

The registered `Exception` handler stays as a **backstop** for anything raised
outside that block, and both paths return `internal_error_response()` so the two
cannot drift apart.

Verified, with the same header sent as above:

```
GET /probe/unexpected   (x-request-id: req_TRACE_ME)

  500
  {"code":"INTERNAL","message":"internal server error"}
  x-request-id: req_TRACE_ME
```

```json
{"message": "unhandled exception", "request_id": "req_TRACE_ME",
 "exception": "Traceback (most recent call last): ... ValueError: boom"}
```

The body is still anonymous — a traceback must never reach a caller (spec 7.4) —
but the id ties it to the log line that holds the real story. Two tests in
`tests/api/test_error_envelope.py` pin both halves.

Even so, prefer raising a typed `EngineError` over letting a `ValueError` escape.
A typed error carries a code the caller can branch on and a message that says
something true. A 500 is a traceable apology, which is better than an untraceable
one, but it is still an apology.

### When it happens in the worker, nobody sends anything

Everything above assumes a request is still waiting. In the worker there is no
open connection — the caller got its `202` minutes ago. So the delivery model
inverts: **the failure is written down, and the user collects it.**

```
worker: raise  ->  task catches  ->  store.mark_failed(job_id, code, message)
                                            |
                                            v
                                     Redis job record
                                            |
user:  GET /v1/backtests/{job_id}  ---------+  ->  200 with the error inside
```

Note the status code: polling a failed job is a **successful request**. You get
`200`, and the failure lives in the body:

```json
{
  "jobId": "job_b04a86...",
  "status": "FAILED",
  "finishedAt": "2026-09-18T07:35:01.906451+00:00",
  "error": {"code": "DATA_RANGE_UNAVAILABLE", "message": "SOLUSDT.BINANCE has no data before 2020-08-11"},
  "result": null
}
```

A client that only checks HTTP status will think everything is fine. **Branch on
`status`, then on `error.code`** — the same codes from the same enum, just
arriving by a different road.

## Three boundaries, three meanings of "failed"

This is the part that is not obvious from reading any single file. The same
exception means something different depending on where it is raised.

### 1. The request path — fail fast, tell the caller

Validation happens **synchronously on submit** so a bad spec costs a round trip
rather than a worker slot:

```python
if errors:
    raise SpecInvalid([error.model_dump(mode="json") for error in errors])
```

Anything cheap enough to check here, is. Anything slow is not — see the worker
below.

### 2. The job path — a job must always reach a terminal state

`src/engine/worker/tasks.py` is the one place in the codebase where a broad
`except Exception` is not only allowed but required:

```python
except Exception as exc:  # noqa: BLE001 -- a job must always terminate
    logger.exception("unexpected worker failure")
    await store.mark_failed(job_id, ErrorCode.INTERNAL.value, type(exc).__name__)
    return "failed"
```

A caller is polling `GET /v1/backtests/{job_id}`. An exception that escapes
leaves that job `RUNNING` forever, and the caller waits forever. So every path
out of `run_backtest` ends in `mark_succeeded` or `mark_failed`, and the failure
is recorded **on the job record** rather than raised at anybody:

```json
{"status": "FAILED", "error": {"code": "SYMBOL_UNKNOWN_AT_VENUE", "message": "..."}}
```

Note the `noqa` comment: the rule is broad-except-is-banned, and each exemption
states its reason inline.

Note also the ordering in `run_backtest` — `except EngineError` first, then bare
`Exception`. An `EngineError` already knows its own code, so it is preserved
verbatim; only genuinely unknown failures collapse to `INTERNAL`.

### 3. The live path — a failed pass changes nothing

The supervisor is a **reconciliation loop**, not a command processor, and that
changes what an error even is:

```python
except Exception:
    logger.exception("could not reconcile an account; leaving it as it is",
                     extra={"account_id": account_id})
    continue
```

One account failing must not strand the other five. A pass that fails changes
nothing except that the next pass tries again — a desire that is not yet met is
simply not yet met.

**Except when retrying is wrong.** `ReconciliationFailed` — the node and the
venue disagree about money — moves the account to `HALTED`, which
`ObservedStatus.needs_operator` marks as a state the supervisor must never clear
by itself:

> Crashing is a fact about the process, and restarting is the right answer.
> Disagreeing with the venue is a fact about the money, and a node that hammers
> the exchange every five seconds while wrong is not recovering — it is being
> wrong faster.

That distinction — *retry* versus *stop and get a human* — is the one to copy
when you add a failure mode to the live path.

## Failures that cross a process boundary

A backtest runs in a **spawned child process**, so an exception cannot simply
propagate. The child serialises it; the parent re-raises it as a local error
(`backtest/runner.py`):

```python
_, exception_name, detail, tb = message
logger.error("backtest failed", extra={"exception": exception_name, "traceback": tb})
raise BacktestFailed(f"{exception_name}: {detail}")
```

The traceback crosses as a **string, into the log**. It never enters the raised
error, so it cannot reach an HTTP response by accident.

The child dying without saying anything — OOM killer, segfault in a native
extension — is its own case, because no exception exists to catch:

```python
raise BacktestFailed(f"the backtest process exited without a result (exit code {process.exitcode})")
```

If you add any cross-process work, both paths need an answer. "The worker hangs"
is the failure mode this design exists to prevent.

## What never leaves the process

**Tracebacks.** Logged with `logger.exception`, persisted to the job record,
never in a response body. `handle_unexpected` returns a fixed string:

```python
content={"code": ErrorCode.INTERNAL.value, "message": "internal server error"}
```

**Secrets.** `src/engine/logging.py:59` redacts by *field name*, on every log
record, including ambient `log_context`:

```python
SECRET_FIELD_MARKERS = ("secret", "api_key", "apikey", "password", "passphrase", "token")
```

Blunt and name-based on purpose — a value-based check cannot work, because an
API key is an opaque string and so is half of everything else that gets logged.
Over-redacting a log line costs nothing; under-redacting one costs a key. The
subtle case this also covers: a malformed credential file must not quote itself
into an error message, because a JSON decode error prints the document it failed
on, and that document is the key.

**Infrastructure detail.** Even `/ready` launders its own failures:

```python
except Exception as exc:
    logger.warning("catalog probe failed", extra={"error": str(exc)})
    return False, "catalog is unreachable"
```

The caller gets `"catalog is unreachable"`; the S3 error string stays in the log.

## Errors are never swallowed

`DslStrategy` contains **zero** `except` clauses, and that is enforced by review,
not by accident (rule 9 in `CLAUDE.md`).

An unknown indicator or a bad operator must raise. The tempting alternative —
a broad `except` that returns `False` — converts a broken strategy into a
silently inert one: it runs for two months, never trades, and reports zero
return as though that were an answer. A strategy that crashes at startup is
found in a minute.

The interpreter shows the one legitimate use of `except` in this layer —
**translating**, never absorbing:

```python
except KeyError as exc:
    raise InterpreterError(f"series {key!r} was not supplied; ...") from exc
```

A `KeyError` becomes a typed error with a code and an explanation, and `from exc`
keeps the original chained for the log. What never happens is the failure
quietly turning into `False`.

The same instinct applies to the validator and anything in the order path.
**A wrong answer that looks like an answer is worse than a crash.**

## Observability: `request_id` and `log_context`

Every request gets an id — honoured from the caller's `x-request-id` if present,
so a failure can be traced across services — bound for the life of the request
and echoed back on the response (`app.py`). The worker binds `job_id` and
`request_id` the same way, so every line a job emits carries both without any
call site threading them through:

```python
with log_context(job_id=job_id, request_id=record.request_id):
```

When someone reports "my backtest failed", the `jobId` in their response is
enough to pull every log line the run produced.

## The taxonomy

Every error in the service, grouped by the file it lives in. The pattern to
notice is that `http_status` is a property of the *error*, decided once where it
is defined, and never something a route chooses.

| Error | Code | Status |
|---|---|---|
| **`backtest.py`** | | |
| `BacktestConfigError` | `REQUEST_INVALID` | 422 |
| `BacktestFailed` | `BACKTEST_FAILED` | 500 |
| `BacktestIncomplete` | `BACKTEST_INCOMPLETE` | 500 |
| `BacktestTimeout` | `TIMEOUT` | 504 |
| `NoDataForWindow` | `NO_DATA_FOR_WINDOW` | 422 |
| **`base.py`** | | |
| `ConfigurationError` | `CONFIGURATION_INVALID` | 500 |
| `EngineError` | `INTERNAL` | 500 |
| `NotFoundError` | `NOT_FOUND` | 404 |
| `NotReadyError` | `NOT_READY` | 503 |
| `SpecInvalid` | `REQUEST_INVALID` | 422 |
| `UnauthenticatedError` | `UNAUTHENTICATED` | 401 |
| **`data.py`** | | |
| `CatalogError` | `CATALOG_INVALID` | 500 |
| `CsvSourceError` | `UPSTREAM_RESPONSE_INVALID` | 422 |
| `DataRangeUnavailable` | `DATA_RANGE_UNAVAILABLE` | 422 |
| `IngestError` | `REQUEST_INVALID` | 422 |
| `InstrumentError` | `INSTRUMENT_INVALID` | 422 |
| `QualityError` | `DATA_QUALITY` | 422 |
| `SymbolUnknownAtVenue` | `SYMBOL_UNKNOWN_AT_VENUE` | 422 |
| `TimestampDisciplineError` | `TIMESTAMP_DISCIPLINE` | 422 |
| `UnsupportedTimeframe` | `REQUEST_INVALID` | 422 |
| `UpstreamError` | `UPSTREAM_UNAVAILABLE` | 502 |
| `UpstreamRateLimited` | `UPSTREAM_RATE_LIMITED` | 429 |
| `UpstreamResponseInvalid` | `UPSTREAM_RESPONSE_INVALID` | 502 |
| `VenueUnsupported` | `VENUE_UNSUPPORTED` | 422 |
| **`dsl.py`** | | |
| `InterpreterError` | `REQUEST_INVALID` | 422 |
| `UnknownIndicatorError` | `REQUEST_INVALID` | 422 |
| **`live.py`** | | |
| `AccountNotFound` | `ACCOUNT_NOT_FOUND` | 404 |
| `CacheNotIsolated` | `CACHE_NOT_ISOLATED` | 500 |
| `CredentialUnavailable` | `CREDENTIAL_UNAVAILABLE` | 502 |
| `LiveNotPermitted` | `LIVE_NOT_PERMITTED` | 409 |
| `MandateMissing` | `LIVE_NOT_PERMITTED` | 409 |
| `MandateRevoked` | `LIVE_NOT_PERMITTED` | 409 |
| `PreflightFailed` | `CACHE_NOT_ISOLATED` | 503 |
| `ReconciliationFailed` | `RECONCILIATION_FAILED` | 409 |
| **`simulation.py`** | | |
| `VenueNotSupported` | `REQUEST_INVALID` | 422 |
| **`store.py`** | | |
| `JobNotCancellable` | `JOB_NOT_CANCELLABLE` | 409 |
| `JobNotFound` | `JOB_NOT_FOUND` | 404 |
| `RequestIdConflict` | `REQUEST_ID_CONFLICT` | 409 |
| **`strategies.py`** | | |
| `StrategySetupError` | `REQUEST_INVALID` | 422 |

Note `SymbolUnknownAtVenue` subclassing `UpstreamError`. That split exists
because "this coin does not exist" and "Binance is down" are both 4xx/5xx
responses from the same endpoint, and confusing them means telling a user their
symbol is invalid during an outage.

## Adding an error: the checklist

1. **Can an existing code carry it?** Prefer reuse. A new code is a new thing the
   TypeScript caller has to learn.
2. Append to `ErrorCode`. Never rename, never reuse a value.
3. Define the class in `src/engine/errors/<area>.py`, with `code` and
   `http_status`, then add it to `__all__` in `errors/__init__.py`.
4. Put anything a caller might act on into `details`, as camelCase keys — the
   HTTP surface is camelCase.
5. Decide the boundary semantics:
   - request path → raise, the handler renders it;
   - job path → the task must catch it and `mark_failed` with the code;
   - live path → retry next pass, or `HALTED` if a human is needed.
6. **Test the code, not the message.** `assert record.error["code"] == "..."`,
   never a substring of English.

## Reading further

- `src/engine/errors/` — every error, one file per area.
- `src/engine/errors/base.py` — the base classes and the code enum.
- `src/engine/api/app.py:79-115` — every exception-to-response conversion.
- `src/engine/worker/tasks.py` — the "always terminate" pattern in full.
- `src/engine/live/supervisor.py` — retry-versus-halt, with the reasoning.
- `docs/runbook-live.md` — what an operator does when the live path fails.
