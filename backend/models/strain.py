"""Strain model — cannabis strain catalog."""
import uuid
from datetime import datetime
from sqlalchemy import String, Float, Integer, Text, DateTime, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base


class Strain(Base):
    __tablename__ = "strains"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: uuid.uuid4().hex[:12])
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    strain_type: Mapped[str] = mapped_column(String(50), default="hybrid", index=True)  # indica, sativa, hybrid
    rating: Mapped[float] = mapped_column(Float, default=0.0)
    review_count: Mapped[int] = mapped_column(Integer, default=0)

    # Cannabinoids
    thc_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    thc_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    cbd_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    cbd_max: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Terpenes (JSON array: [{"name":"myrcene","percentage":0.5}, ...])
    terpenes: Mapped[str] = mapped_column(Text, default="[]")

    # Effects (JSON array: ["Relaxed","Happy","Creative"])
    effects: Mapped[str] = mapped_column(Text, default="[]")

    # Flavors (JSON array: ["Earthy","Sweet","Citrus"])
    flavors: Mapped[str] = mapped_column(Text, default="[]")

    # Genetics / lineage
    genetics: Mapped[str] = mapped_column(String(500), default="")  # "Blueberry x Northern Lights"
    breeder: Mapped[str] = mapped_column(String(200), default="")
    is_landrace: Mapped[bool] = mapped_column(default=False)
    landrace_origin: Mapped[str] = mapped_column(String(200), default="")

    # Flowering / seed info
    flowering_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seed_type: Mapped[str] = mapped_column(String(50), default="")  # feminized, regular, clone only

    # Precise genetics percentages
    sativa_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    indica_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Description
    description: Mapped[str] = mapped_column(Text, default="")

    # Photos
    image_url: Mapped[str] = mapped_column(String(500), default="")

    # Source
    source: Mapped[str] = mapped_column(String(50), default="kaggle")  # kaggle, leafly, user

    # SEO-friendly URL slug (e.g. "blue-dream")
    slug: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)

    # Admin-curated homepage feature
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    reviews = relationship("Review", back_populates="strain", lazy="select")
    # Lineage relationships — populated by backend.models.lineage import
    parent_links = relationship(
        "StrainLink",
        foreign_keys="StrainLink.child_id",
        lazy="select",
        viewonly=True,
    )
    child_links = relationship(
        "StrainLink",
        foreign_keys="StrainLink.parent_id",
        lazy="select",
        viewonly=True,
    )

    def __repr__(self) -> str:
        return f"<Strain {self.name} ({self.strain_type})>"

    @property
    def terpene_list(self) -> list:
        import json
        try:
            return json.loads(self.terpenes)
        except (json.JSONDecodeError, TypeError):
            return []

    @property
    def effect_list(self) -> list:
        import json
        try:
            return json.loads(self.effects)
        except (json.JSONDecodeError, TypeError):
            return []

    @property
    def flavor_list(self) -> list:
        import json
        try:
            return json.loads(self.flavors)
        except (json.JSONDecodeError, TypeError):
            return []

    @property
    def avg_user_rating(self) -> float | None:
        """Average rating from user reviews (not Leafly rating)."""
        if not self.reviews:
            return None
        ratings = [r.rating for r in self.reviews if r.rating]
        return round(sum(ratings) / len(ratings), 1) if ratings else None

    @property
    def display_name(self) -> str:
        return self.name or "Unnamed strain"

    @property
    def thc_display(self) -> str:
        if self.thc_min and self.thc_max:
            return f"{self.thc_min}%-{self.thc_max}%"
        if self.thc_min:
            return f"{self.thc_min}%+"
        return "Unknown"

    @property
    def cbd_display(self) -> str:
        if self.cbd_min and self.cbd_max:
            return f"{self.cbd_min}%-{self.cbd_max}%"
        if self.cbd_min:
            return f"{self.cbd_min}%+"
        if self.cbd_min == 0 and self.cbd_max == 0:
            return "0%"
        return "—"

    @property
    def type_emoji(self) -> str:
        return {"indica": "🔵", "sativa": "🟠", "hybrid": "🟣"}.get(self.strain_type, "🟢")