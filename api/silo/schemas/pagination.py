from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class Page(BaseModel, Generic[T]):
    """Cursor-paginated page."""

    items: list[T]
    # Opaque; pass back as `cursor`. Null on the last page.
    next_cursor: str | None = None
