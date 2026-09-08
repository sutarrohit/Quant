"""The raw response store -- the audit trail.

Spec section 4.1(2): every exchange response is persisted **before** any
transformation, and raw data is never overwritten. When a backtest number looks
wrong two months from now, this is what answers "was the data wrong, or did we
convert it wrong?"

Records are content-addressed on the payload alone:

    <root>/<source>/<endpoint>/<key>.<payload_sha256[:16]>.json

Two consequences, both deliberate:

* **Re-fetching identical data is a no-op.** Same bytes, same hash, same
  filename -- the existing file is kept and nothing is rewritten.
* **A restatement becomes a second file, not a lost one.** Exchanges do revise
  historical candles (spec section 13). A changed payload hashes differently and
  lands beside the original, so both versions survive and the change is visible.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Self

import fsspec

from engine.settings import Settings

_HASH_LENGTH = 16


def payload_digest(payload: Any) -> str:
    """SHA-256 over the payload in canonical form.

    Sorted keys and fixed separators, so an identical response always produces
    an identical digest regardless of dict ordering.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class RawRecord:
    """One exchange response, exactly as received."""

    source: str
    endpoint: str
    key: str
    params: dict[str, str]
    payload: Any
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    response_headers: dict[str, str] = field(default_factory=dict)

    @property
    def digest(self) -> str:
        return payload_digest(self.payload)

    def to_document(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "endpoint": self.endpoint,
            "key": self.key,
            "params": self.params,
            "fetched_at": self.fetched_at.isoformat(),
            "payload_sha256": self.digest,
            "response_headers": self.response_headers,
            "payload": self.payload,
        }


class RawStore:
    """Append-only storage for exchange responses.

    Backed by fsspec, so ``NT_RAW_PATH`` may be a local directory or an
    object-storage URI.
    """

    def __init__(self, root: str) -> None:
        self.root = root.rstrip("/")
        self._fs, self._base = fsspec.core.url_to_fs(self.root)

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls(settings.raw_path)

    def path_for(self, record: RawRecord) -> str:
        return f"{self._base}/{record.source}/{record.endpoint}/{record.key}.{record.digest[:_HASH_LENGTH]}.json"

    def write(self, record: RawRecord) -> str:
        """Persist a record and return its path.

        Idempotent: an existing path holds byte-identical payload data by
        construction, so it is left untouched.
        """
        path = self.path_for(record)
        if self._fs.exists(path):
            return path
        self._fs.makedirs(path.rsplit("/", 1)[0], exist_ok=True)
        with self._fs.open(path, "w") as handle:
            json.dump(record.to_document(), handle, sort_keys=True, separators=(",", ":"), default=str)
        return path

    def read(self, path: str) -> dict[str, Any]:
        with self._fs.open(path, "r") as handle:
            document: dict[str, Any] = json.load(handle)
        return document

    def list(self, source: str, endpoint: str) -> list[str]:
        """Every stored path for one endpoint, sorted."""
        prefix = f"{self._base}/{source}/{endpoint}"
        if not self._fs.exists(prefix):
            return []
        return sorted(str(path) for path in self._fs.glob(f"{prefix}/*.json"))
