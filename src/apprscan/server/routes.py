"""FastAPI routes for the companion service."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .service import new_run_id, process_maps_ingest, read_company_package


router = APIRouter()


class MapsIngestRequest(BaseModel):
    maps_url: str = Field(..., min_length=8)
    note: str | None = ""
    tags: List[str] | None = Field(default_factory=list)


def _require_token(request: Request, x_apprscan_token: str | None = Header(default=None)) -> None:
    token = getattr(request.app.state, "token", None)
    if not token:
        raise HTTPException(status_code=500, detail="Server token not configured.")
    if x_apprscan_token != token:
        raise HTTPException(status_code=401, detail="Invalid token.")


@router.post("/ingest/maps")
def ingest_maps(
    payload: MapsIngestRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    x_apprscan_token: str | None = Header(default=None),
):
    _require_token(request, x_apprscan_token)
    run_id = new_run_id()
    background_tasks.add_task(
        process_maps_ingest,
        maps_url=payload.maps_url,
        note=payload.note or "",
        tags=payload.tags or [],
        run_id=run_id,
    )
    return {"status": "queued", "run_id": run_id}


@router.get("/result/{run_id}")
def get_result(run_id: str, request: Request, x_apprscan_token: str | None = Header(default=None)):
    _require_token(request, x_apprscan_token)
    package = read_company_package(run_id)
    if not package:
        raise HTTPException(status_code=202, detail="Result not ready.")
    return package
