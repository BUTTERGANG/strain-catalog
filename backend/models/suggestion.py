"""GeneticsSuggestion model — community-proposed lineage, admin-approved."""
import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from backend.database import Base


class GeneticsSuggestion(Base):
    __tablename__ = "genetics_suggestions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: uuid.uuid4().hex[:12])
    strain_id: Mapped[str] = mapped_column(String, ForeignKey("strains.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)

    parent_1: Mapped[str] = mapped_column(String(120), nullable=False)
    parent_2: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/approved/rejected
    decided_by: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return f"<GeneticsSuggestion {self.strain_id}: {self.parent_1} x {self.parent_2} [{self.status}]>"