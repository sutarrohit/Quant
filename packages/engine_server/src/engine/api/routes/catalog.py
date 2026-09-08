"""What can actually be backtested (spec section 7.2)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from engine.api.auth import InternalAuth
from engine.api.deps import SettingsDep
from engine.data.catalog import Catalog

router = APIRouter(prefix="/v1/catalog", tags=["catalog"], dependencies=[InternalAuth])


@router.get("/instruments")
async def instruments(settings: SettingsDep) -> dict[str, Any]:
    """Instruments with bar data, and the ranges held for each bar type.

    A caller uses this to build a request it knows will validate, rather than
    discovering the window is empty after a job has run.
    """
    catalog = Catalog.from_settings(settings)
    held = []
    for bar_type in catalog.bar_types():
        coverage = catalog.coverage(bar_type)
        held.append(
            {
                "barType": bar_type,
                "start": coverage.start.isoformat() if coverage else None,
                "end": coverage.end.isoformat() if coverage else None,
            }
        )
    return {
        "instruments": [
            {"instrumentId": instrument_id}
            for instrument_id in catalog.backtestable_instrument_ids()
        ],
        "barTypes": held,
    }
