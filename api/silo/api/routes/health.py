from fastapi import APIRouter

from silo.schemas.health import Health

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", operation_id="get_health")
async def health() -> Health:
    return Health(status="ok")
