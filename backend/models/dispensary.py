"""Dispensary and menu models."""
import uuid
from datetime import datetime
from sqlalchemy import String, Float, Integer, Text, DateTime, ForeignKey, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base


class Dispensary(Base):
    __tablename__ = "dispensaries"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: uuid.uuid4().hex[:12])
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    address: Mapped[str] = mapped_column(String(500), default="")
    city: Mapped[str] = mapped_column(String(100), default="", index=True)
    state: Mapped[str] = mapped_column(String(50), default="", index=True)
    zip_code: Mapped[str] = mapped_column(String(20), default="")
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Contact
    phone: Mapped[str] = mapped_column(String(50), default="")
    website: Mapped[str] = mapped_column(String(500), default="")
    email: Mapped[str] = mapped_column(String(255), default="")

    # Hours (JSON dict: {"monday":"9am-9pm", ...})
    hours: Mapped[str] = mapped_column(Text, default="{}")

    # Licensing
    license_type: Mapped[str] = mapped_column(String(50), default="recreational")  # recreational, medical, both
    delivery_available: Mapped[bool] = mapped_column(Boolean, default=False)

    # Ratings
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_count: Mapped[int] = mapped_column(Integer, default=0)

    # Details
    description: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[str] = mapped_column(String(500), default="")
    photo_urls: Mapped[str] = mapped_column(Text, default="[]")
    amenities: Mapped[str] = mapped_column(Text, default="[]")

    # Source
    source: Mapped[str] = mapped_column(String(50), default="manual")
    source_url: Mapped[str] = mapped_column(String(500), default="")  # Leafly URL

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    menu_items = relationship("MenuItem", back_populates="dispensary", lazy="select")

    def __repr__(self) -> str:
        return f"<Dispensary {self.name} — {self.city}, {self.state}>"

    @property
    def hours_dict(self) -> dict:
        import json
        try:
            return json.loads(self.hours)
        except (json.JSONDecodeError, TypeError):
            return {}

    @property
    def amenity_list(self) -> list:
        import json
        try:
            return json.loads(self.amenities)
        except (json.JSONDecodeError, TypeError):
            return []


class MenuItem(Base):
    """A product on a dispensary's menu."""
    __tablename__ = "menu_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: uuid.uuid4().hex[:12])
    dispensary_id: Mapped[str] = mapped_column(String, ForeignKey("dispensaries.id"), nullable=False, index=True)
    strain_id: Mapped[str | None] = mapped_column(String, ForeignKey("strains.id"), nullable=True, index=True)

    name: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="flower")  # flower, edible, concentrate, vape, tincture, topical, preroll
    brand: Mapped[str] = mapped_column(String(200), default="")

    # Pricing
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_unit: Mapped[str] = mapped_column(String(50), default="gram")  # gram, eighth, quarter, half, ounce, each, mg
    price_original: Mapped[float | None] = mapped_column(Float, nullable=True)  # original price before discount

    # Cannabinoids
    thc_content: Mapped[str] = mapped_column(String(50), default="")
    cbd_content: Mapped[str] = mapped_column(String(50), default="")

    # Description
    description: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[str] = mapped_column(String(500), default="")

    # Source
    source_url: Mapped[str] = mapped_column(String(500), default="")
    scraped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    dispensary = relationship("Dispensary", back_populates="menu_items", lazy="joined")
    strain = relationship("Strain", lazy="joined")

    def __repr__(self) -> str:
        return f"<MenuItem {self.name} — ${self.price}>"