from pydantic import BaseModel


class ZipMemberOut(BaseModel):
    """One member of a stored zip file."""

    path: str
    size: int
