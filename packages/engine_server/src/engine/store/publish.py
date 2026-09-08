"""Handing a finished result to api-control (spec section 9.4).

This service never writes the platform's PostgreSQL. Two writers on the same
financial tables is how a fill exists in one schema and not the other, so the
Python side proposes and the TypeScript side records.

**Inert until configured.** ``NT_API_CONTROL_URL`` is unset by default, and
with it unset this does nothing and says so. The alternative -- adding the
hand-off later -- means retrofitting it at exactly the moment the TypeScript
side is being built.

**A publish failure never fails the job.** The backtest ran and its result is
stored; a caller polling the job still gets the answer. Losing the hand-off is
recoverable by re-publishing, whereas failing a completed run is not.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from engine.settings import Settings

logger = logging.getLogger(__name__)

RESULTS_PATH = "/internal/backtest-results"
TIMEOUT_SECONDS = 10.0


def publish_result(
    job_id: str,
    result: dict[str, Any],
    settings: Settings,
    *,
    client: httpx.Client | None = None,
) -> bool:
    """POST a completed backtest summary. Returns whether it was delivered."""
    if not settings.api_control_url:
        logger.debug("api-control not configured; result stays local", extra={"job_id": job_id})
        return False

    url = settings.api_control_url.rstrip("/") + RESULTS_PATH
    headers = {"Content-Type": "application/json"}
    if settings.internal_api_key is not None:
        # The same shared secret, in the other direction.
        headers["Authorization"] = f"Bearer {settings.internal_api_key.get_secret_value()}"

    payload = {"jobId": job_id, **result}
    owns_client = client is None
    http = client or httpx.Client(timeout=TIMEOUT_SECONDS)
    try:
        response = http.post(url, json=payload, headers=headers)
        response.raise_for_status()
        logger.info("result published", extra={"job_id": job_id, "status": response.status_code})
        return True
    except Exception as exc:
        logger.warning(
            "could not publish result", extra={"job_id": job_id, "error": str(exc)[:200]}
        )
        return False
    finally:
        if owns_client:
            http.close()
