import httpx
from fastapi import APIRouter, HTTPException

from silo.api.dependencies import SessionDep
from silo.schemas.igdb import IgdbCredentialsPut, IgdbStatusOut
from silo.sources.igdb import app_token, clear_credentials, is_configured, store_credentials

router = APIRouter(prefix="/igdb", tags=["igdb"])


@router.get("/status", operation_id="get_igdb_status")
async def get_igdb_status(session: SessionDep) -> IgdbStatusOut:
    return IgdbStatusOut(connected=await is_configured(session))


@router.put("/credentials", operation_id="connect_igdb")
async def connect_igdb(session: SessionDep, body: IgdbCredentialsPut) -> IgdbStatusOut:
    try:
        await app_token(body.client_id, body.client_secret)
    except httpx.HTTPError:
        raise HTTPException(status_code=422, detail="credentials were rejected by Twitch") from None
    await store_credentials(session, body.client_id, body.client_secret)
    return IgdbStatusOut(connected=True)


@router.delete("/credentials", operation_id="disconnect_igdb", status_code=204)
async def disconnect_igdb(session: SessionDep) -> None:
    await clear_credentials(session)
