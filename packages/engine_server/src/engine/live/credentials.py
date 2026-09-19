"""Resolving a credential reference to a key (ADR-001).

The desired-state record carries a **reference**, never a secret. A key written
into that record would be a key in Redis, in every backup of Redis, and in
anything that reads it back — including an HTTP response that forgot to
redact it.

So the API never sees a key. A node resolves the reference at startup, holds
the result in memory, and nothing writes it down.

The resolver is a protocol because the secret lives somewhere this service
cannot reach: the platform's own PostgreSQL, which spec §9.4 forbids this
service from connecting to. An HTTP implementation against api-control comes
when that service exists; until then the environment resolver is enough for
simulation, which needs no credentials at all.
"""

from __future__ import annotations

import json
import logging
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from engine.errors import CredentialUnavailable

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VenueCredentials:
    """An exchange key pair, held in memory and never written down."""

    api_key: str
    api_secret: str

    def __repr__(self) -> str:
        # A key that reaches a traceback has reached a log.
        return "VenueCredentials(api_key='***', api_secret='***')"

    def __str__(self) -> str:
        return self.__repr__()


class CredentialResolver(Protocol):
    def resolve(self, reference: str) -> VenueCredentials:
        """Exchange a reference for a key pair. Called once, at node startup."""
        ...


class EnvironmentCredentialResolver:
    """Reads from the environment. Development and simulation only.

    ADR-001 is explicit that production keys come from a secrets manager, never
    from an environment variable in a compose file. This exists so the node can
    be built and tested before that manager does, and a live node must not use
    it.
    """

    def __init__(self, prefix: str = "NT_VENUE_") -> None:
        self._prefix = prefix

    def resolve(self, reference: str) -> VenueCredentials:
        slug = reference.upper().replace("-", "_")
        key = os.environ.get(f"{self._prefix}{slug}_KEY")
        secret = os.environ.get(f"{self._prefix}{slug}_SECRET")
        if not key or not secret:
            # The reference is named; the values never are.
            raise CredentialUnavailable(f"no credentials for reference {reference!r}")
        return VenueCredentials(api_key=key, api_secret=secret)


class NoCredentialsResolver:
    """Refuses everything. The default, so a key is never resolved by accident."""

    def resolve(self, reference: str) -> VenueCredentials:
        raise CredentialUnavailable(
            "no credential resolver is configured; live trading requires one"
        )


class SecretsFileResolver:
    """Reads a key pair from a file mounted into the container at runtime.

    This is the production resolver, and it is deliberately not a cloud SDK.
    ADR-001's requirement is about **where a key must not be** — not in the
    image, not in an environment variable, not in the repo — and every secrets
    manager worth using already knows how to satisfy that by projecting a
    secret onto a filesystem:

    | Platform | How the file gets there |
    |---|---|
    | Kubernetes | a `Secret` volume, or a CSI driver fronting Vault/AWS/GCP |
    | Docker / compose | `secrets:`, mounted under `/run/secrets` |
    | systemd | `LoadCredential=`, exposed at `$CREDENTIALS_DIRECTORY` |
    | Vault | `vault agent` template, or the CSI driver above |

    Binding to one vendor's SDK would buy nothing over this and would put a
    cloud dependency in the order path's startup. When a specific manager is
    chosen, it either projects a file — in which case this is already the
    integration — or a resolver is written against its API, which is why
    `CredentialResolver` is a protocol.

    **The file is checked before it is read.** A world-readable secret is not a
    secret, and a mode that permissive usually means it was written by
    something that did not know it was handling a key.
    """

    def __init__(self, directory: str | Path, *, require_private: bool = True) -> None:
        self._directory = Path(directory)
        self._require_private = require_private

    def _path(self, reference: str) -> Path:
        # A reference reaches this from a stored record. Anything that could
        # walk out of the directory is refused rather than sanitised, because
        # silently reading a different file is worse than failing.
        if not reference or "/" in reference or "\\" in reference or reference.startswith("."):
            raise CredentialUnavailable(f"invalid credential reference {reference!r}")
        return self._directory / reference

    def resolve(self, reference: str) -> VenueCredentials:
        path = self._path(reference)
        if not path.is_file():
            # Named, never quoted with its contents.
            raise CredentialUnavailable(f"no credential file for reference {reference!r}")

        if self._require_private:
            mode = stat.S_IMODE(path.stat().st_mode)
            if mode & (stat.S_IRGRP | stat.S_IROTH):
                raise CredentialUnavailable(
                    f"credential file for {reference!r} is readable beyond its owner "
                    f"(mode {mode:04o}); refusing to load it"
                )

        try:
            document = json.loads(path.read_text())
            key = document["api_key"]
            secret = document["api_secret"]
        except Exception as exc:
            # `exc` is not interpolated: a JSON error quotes the document it
            # failed on, and that document is the key.
            raise CredentialUnavailable(
                f"credential file for {reference!r} is not readable as "
                f"{{'api_key': ..., 'api_secret': ...}} ({type(exc).__name__})"
            ) from None

        if not key or not secret:
            raise CredentialUnavailable(f"credential file for {reference!r} is incomplete")
        logger.info("credentials resolved", extra={"reference": reference, "source": "file"})
        return VenueCredentials(api_key=key, api_secret=secret)


def assert_usable_in_live(resolver: object, *, allow_environment: bool = False) -> None:
    """Refuse a resolver that ADR-001 forbids in production.

    Enforced rather than documented, because "development only" in a docstring
    is a comment and this is a rule. The environment resolver exists so the
    node could be built and tested before a secrets manager did; a live node
    reaching for it is normally a deployment mistake that must not reach a
    venue.

    ``allow_environment`` is the repo owner's documented exception
    (`NT_LIVE_ALLOW_ENV_CREDENTIALS`, ADR-001 addendum 2026-09-08). It is a
    parameter rather than a deleted check so the choice is visible at the point
    it is made, and so this function still says what the default is.
    """
    if isinstance(resolver, EnvironmentCredentialResolver):
        if not allow_environment:
            raise CredentialUnavailable(
                "the environment credential resolver must not be used for live trading: "
                "ADR-001 requires keys from a secrets manager, never an environment "
                "variable. Set NT_LIVE_ALLOW_ENV_CREDENTIALS=true to override, "
                "having read the addendum in docs/adr-001-live-execution.md"
            )
        logger.warning(
            "live credentials are being read from the environment; ADR-001's "
            "default forbids this and it is enabled by NT_LIVE_ALLOW_ENV_CREDENTIALS",
            extra={"resolver": "environment"},
        )
        return
    if isinstance(resolver, NoCredentialsResolver):
        raise CredentialUnavailable(
            "live trading requires a credential resolver; none is configured"
        )
