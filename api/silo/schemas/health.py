from typing import Literal

from pydantic import BaseModel


class Health(BaseModel):
    """Service health."""

    status: Literal["ok"] = "ok"
