"""Review / Tasting note model."""
import uuid
from datetime import datetime
from sqlalchemy import String, Float, Integer, Text, DateTime, ForeignKey, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: uuid.uuid4().hex[:12])
    strain_id: Mapped[str] = mapped_column(String, ForeignKey("strains.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    dispensary_id: Mapped[str | None] = mapped_column(String, ForeignKey("dispensaries.id"), nullable=True)

    # Rating (1-5)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)

    # Structured tasting notes
    aroma: Mapped[str] = mapped_column(Text, default="")
    flavor: Mapped[str] = mapped_column(Text, default="")
    effect: Mapped[str] = mapped_column(Text, default="")
    appearance: Mapped[str] = mapped_column(Text, default="")

    # Experience details
    consumption_method: Mapped[str] = mapped_column(String(50), default="smoked")  # smoked, vaped, edible, tincture, topical
    setting: Mapped[str] = mapped_column(String(100), default="")

    # Price paid
    price_paid: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Notes
    notes: Mapped[str] = mapped_column(Text, default="")
    photo_url: Mapped[str] = mapped_column(String(500), default="")
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    strain = relationship("Strain", back_populates="reviews", lazy="joined")
    user = relationship("User", back_populates="reviews", lazy="joined")
    dispensary = relationship("Dispensary", lazy="joined")

    def __repr__(self) -> str:
        return f"<Review {self.strain_id} by {self.user_id} — {self.rating}/5>"