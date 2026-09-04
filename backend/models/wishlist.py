"""Wishlist model — saved strains for users."""
import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base


class WishlistItem(Base):
    __tablename__ = "wishlist_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: uuid.uuid4().hex[:12])
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    strain_id: Mapped[str] = mapped_column(String, ForeignKey("strains.id"), nullable=False, index=True)
    notes: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "strain_id", name="uq_wishlist"),
    )

    user = relationship("User", lazy="joined")
    strain = relationship("Strain", lazy="joined")

    def __repr__(self) -> str:
        return f"<WishlistItem {self.user_id} → {self.strain_id}>"


class DispensaryVisit(Base):
    """Track dispensary visits with strain purchases and reviews."""
    __tablename__ = "dispensary_visits"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: uuid.uuid4().hex[:12])
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    dispensary_id: Mapped[str] = mapped_column(String, ForeignKey("dispensaries.id"), nullable=False, index=True)
    visit_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(String(1000), default="")
    latitude: Mapped[float | None] = mapped_column(nullable=True)
    longitude: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user = relationship("User", lazy="joined")
    dispensary = relationship("Dispensary", lazy="joined")

    def __repr__(self) -> str:
        return f"<DispensaryVisit {self.user_id} → {self.dispensary_id}>"