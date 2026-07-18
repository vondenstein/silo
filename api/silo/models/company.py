import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from silo.models.base import Base, ExternalIdentityMixin, UUIDPrimaryKeyMixin


class Company(UUIDPrimaryKeyMixin, Base):
    """Company."""

    __tablename__ = "company"

    slug: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]


class CompanyAlias(Base):
    """Company alias."""

    __tablename__ = "company_alias"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("company.id", ondelete="CASCADE"), primary_key=True
    )
    alias: Mapped[str] = mapped_column(primary_key=True)


class CompanyExternalIdentity(ExternalIdentityMixin, Base):
    """Company external identity."""

    __tablename__ = "company_external_identity"
    # The C2 ladder assumes one entity per (source, uid) — DB-enforced.
    __table_args__ = (UniqueConstraint("source_id", "external_id"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("company.id", ondelete="CASCADE"), primary_key=True
    )
