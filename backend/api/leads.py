from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response

from backend.domain.lead_export import to_csv
from backend.domain.leads import LeadExport, LeadFilters, LeadPage
from backend.storage.leads import LeadRepository


def lead_router(leads: LeadRepository, authenticate) -> APIRouter:
    router = APIRouter(prefix="/v1/leads", dependencies=[Depends(authenticate)])

    @router.get("")
    def dashboard(filters: Annotated[LeadPage, Query()]):
        return leads.page(filters)

    @router.get("/export")
    def export(filters: Annotated[LeadExport, Query()]):
        document = leads.export(LeadFilters(**filters.model_dump(exclude={"format"})))
        filename = f"leaddesk-{filters.mode}-leads.{filters.format}"
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        if filters.format == "csv":
            return Response("\ufeff" + to_csv(document), media_type="text/csv; charset=utf-8", headers=headers)
        return JSONResponse(document, headers=headers)

    return router
