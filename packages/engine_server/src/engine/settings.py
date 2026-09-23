"""Service configuration.

Read from the environment with the ``NT_`` prefix, per spec section 3.

There is deliberately no ``NT_DATABASE_URL``. This service never connects to the
platform PostgreSQL, in any phase (spec section 9.4).

Settings for a later phase arrive in the step that needs them, not as stubs now:
``NT_CACHE_REDIS_URL`` (Phase 5), ``NT_BUS_REDIS_URL`` and
``NT_TRADING_CORE_URL`` (Phase 6), ``NT_API_CONTROL_URL`` (Step 5).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from engine.errors import ConfigurationError

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def env_file() -> str:
    """Which env file this process reads.

    One file per environment, all of them beside each other. ``NT_ENV`` picks --
    and is read from the real environment rather than from a file, because a file
    cannot name itself.
    """
    return ".env.production" if os.getenv("NT_ENV") == "production" else ".env"


def export_unprefixed(path: str) -> None:
    """Put the file's non-``NT_`` variables into the process environment.

    Some settings are not read through this class at all. ``AWS_ACCESS_KEY_ID``
    and friends are read by botocore straight out of ``os.environ``, and
    pydantic-settings parses the file itself without ever populating it -- so an
    ``s3://`` artifact path fails with ``NoCredentialsError`` while the keys sit
    in the very file that was just loaded.

    **Only the unprefixed ones.** ``NT_*`` belongs to pydantic-settings, and
    exporting those would make ``Settings(_env_file=None)`` -- how a test asks
    for the declared defaults -- read the developer's ``.env`` instead. Three
    tests catch exactly that.

    ``setdefault``, so a real environment variable always wins over the file and
    a container's injected credentials are never shadowed by a stale checkout.
    """
    for key, value in dotenv_values(path).items():
        if value is None or key.startswith("NT_"):
            continue  # NT_* belongs to pydantic-settings, which reads the file itself.
        os.environ.setdefault(key, value)


export_unprefixed(env_file())


def is_remote_uri(value: str) -> bool:
    """True for an object-storage URI (``s3://``, ``gs://``, ...) rather than a local path.

    Storage roots are typed as ``str``, not ``Path``, precisely because of this:
    spec section 3 allows ``s3://...`` for the catalog, and ``Path("s3://b/k")``
    silently collapses to ``s3:/b/k``.
    """
    scheme, separator, _ = value.partition("://")
    return bool(separator) and scheme != "file"


def as_local_path(value: str) -> Path:
    """Resolve a storage root to a local path, rejecting remote URIs."""
    if is_remote_uri(value):
        raise ConfigurationError(f"expected a local path, got a remote URI: {value!r}")
    return Path(value.removeprefix("file://")).expanduser()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NT_",
        env_file=env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Phase 0: data catalog ---
    catalog_path: str = "./catalog"
    """Parquet catalog root. Local path or object-storage URI."""

    raw_path: str = "./raw"
    """Unmodified exchange responses. Append-only audit trail; never overwritten."""

    log_level: LogLevel = "INFO"

    # --- Phase 3: job service ---
    artifact_path: str = "./artifacts"
    """Backtest result artifacts: summary JSON, equity/drawdown/trade parquet."""

    redis_url: str = "redis://localhost:6379/0"
    """arq job queue.

    Phase 5's Nautilus cache database must use a *different* logical DB: a
    FLUSHDB aimed at the queue must never be able to erase live trading state
    (spec section 9.2).
    """

    backtest_timeout_seconds: int = 900
    """Wall-clock ceiling for one backtest.

    A run that exceeds it is killed and the job marked FAILED with code
    TIMEOUT (spec section 7.4). Enforced by terminating the child process, not
    by asking it to stop -- a CPU-bound Rust loop does not check for
    cancellation.
    """

    cache_redis_url: str | None = None
    """Redis backing the Nautilus cache in live trading (spec section 9.2).

    Required for live, forbidden in backtests: without it a restart loses open
    orders and positions, and startup recovery has nothing to compare the venue
    against.

    **It must be a different Redis instance from NT_REDIS_URL**, not merely a
    different logical database. Nautilus's DatabaseConfig exposes only host and
    port -- there is no way to select a DB index (D15) -- so instance is the
    only separation available. A FLUSHDB aimed at the job queue must never be
    able to erase live position state.
    """

    live_lease_seconds: int = 30
    """How long a supervisor's claim on an account survives without renewal.

    An account is the unit of risk, credentials and reconciliation, so exactly
    one node may run it. Short enough that a dead supervisor's claim expires
    quickly; long enough to survive a slow pass.
    """

    live_allow_env_credentials: bool = False
    """Permit venue keys from environment variables in live trading.

    **ADR-001 forbids this**, and the default keeps that rule. It exists as a
    setting rather than a deleted check so that the exception is visible where
    it is taken -- in a diff, in a deployment's config, and in a WARNING on
    every node start -- instead of being a guardrail somebody quietly removed.

    What the rule was protecting against, so the trade is a known one:

    * an environment variable is inherited by every child process, and this
      service spawns one per account;
    * it appears in ``/proc/<pid>/environ``, readable by the same user;
    * it lands in `docker inspect`, in a compose file, in shell history, and in
      whatever CI wrote the deployment;
    * a file has a mode that can be checked before it is read, and an
      environment variable has nothing.

    Set it only where the operator has decided those are acceptable. The
    secrets-file path stays the default and stays recommended.
    """

    live_secrets_dir: str = "./run/secrets"
    """Where a venue key is mounted at runtime, one file per credential ref.

    Never in the image, never an environment variable, never the repo
    (ADR-001). A secrets manager projects onto this directory -- a Kubernetes
    `Secret` volume, `docker secret` at ``/run/secrets``, systemd
    ``LoadCredential=`` at ``$CREDENTIALS_DIRECTORY``, or Vault's CSI driver.

    Each file is named for the `credentialRef` on the account and holds
    ``{"api_key": "...", "api_secret": "..."}``. **A file readable beyond its
    owner is refused rather than loaded**: a world-readable secret is not a
    secret, and a mode that permissive usually means it was written by
    something that did not know it was handling a key.
    """

    live_kill_switch_dir: str = "./run/kill"
    """Where the on-disk kill switch lives.

    The path that works when Redis is down, this service's API is wedged, or
    the network is partitioned: an operator with a shell on the node can always
    ``touch`` a file here. Read alongside the Redis flag, never instead of it.
    """

    live_kill_switch_interval_seconds: float = 5.0
    """How often a running node re-reads its kill switch.

    Bounded well below ``engine.live.gate.DEFAULT_MAX_AGE_NS`` so an ordinary
    slow tick does not stale a gate, and short enough that an operator's stop
    takes effect in seconds rather than minutes.
    """

    live_restart_backoff_seconds: float = 5.0
    """Base delay before a failed account is started again.

    Doubles on each consecutive failure. Without it a node that dies during
    startup is respawned every pass, forever -- and every defect found so far
    has been a *startup* failure, which is exactly the shape that loops. A
    crash loop against a venue is also how an IP gets rate-limited.
    """

    live_restart_backoff_max_seconds: float = 300.0
    """The ceiling on that doubling.

    Bounded rather than unbounded so an account that starts failing at 03:00
    is still being retried at 09:00, roughly every five minutes, instead of
    once a day.
    """

    live_healthy_after_seconds: float = 60.0
    """How long a node must run before its start counts as a success.

    A node that comes up and dies in ten seconds has not started, whatever the
    process table said in between. Passing this resets the backoff.
    """

    live_heartbeat_timeout_seconds: int = 90
    """After this, a node that has stopped heartbeating is presumed dead.

    A node holding a position with nobody managing its stop is the worst state
    the system can be in, so the supervisor acts rather than waits.
    """

    job_ttl_seconds: int = 7 * 24 * 3600
    """How long a finished job record is readable.

    Long enough that a caller polling after a weekend still finds its result,
    short enough that Redis is not a permanent store. The durable record is
    api-control's, not ours (spec section 9.4).
    """

    api_control_url: str | None = None
    """Where completed backtest summaries are POSTed.

    Spec section 9.4: this service never writes the platform's PostgreSQL, so
    a result reaches the durable record by being handed to api-control, which
    owns that table. Unset by default -- the hand-off is built and tested, and
    inert until the endpoint exists.
    """

    internal_api_key: SecretStr | None = None
    """Shared bearer token presented by the TypeScript api-control service.

    Optional so the Phase 0 ingest CLI runs without one. The API refuses to
    start without it -- see ``require_internal_api_key``, called from the app
    factory once auth lands in Step 14.
    """

    def require_internal_api_key(self) -> SecretStr:
        if self.internal_api_key is None:
            raise ConfigurationError("NT_INTERNAL_API_KEY is required to serve the API")
        return self.internal_api_key


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings.

    Cached, so the environment is read once. Tests construct ``Settings``
    directly with ``_env_file=None`` rather than clearing this cache.
    """
    return Settings()
