from fastapi import APIRouter
from sqlalchemy import select

from silo.api.dependencies import SessionDep
from silo.models.secret import Secret as SecretModel
from silo.schemas.secret import SecretPut

router = APIRouter(prefix="/secrets", tags=["secrets"])


@router.get("", operation_id="list_secrets")
async def list_secrets(session: SessionDep) -> list[str]:
    stmt = select(SecretModel.name).order_by(SecretModel.name.asc())
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


@router.put("/{name}", operation_id="set_secret", status_code=204)
async def set_secret(
    session: SessionDep,
    name: str,
    body: SecretPut,
) -> None:
    existing_secret = await session.get(SecretModel, name)
    if existing_secret is None:
        session.add(SecretModel(name=name, value=body.value))
    else:
        existing_secret.value = body.value
    await session.flush()


@router.delete("/{name}", operation_id="delete_secret", status_code=204)
async def delete_secret(session: SessionDep, name: str) -> None:
    secret = await session.get(SecretModel, name)
    if secret is not None:
        await session.delete(secret)
        await session.flush()
