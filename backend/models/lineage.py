"""Genetic lineage model — tracks parent/child relationships between strains."""
import uuid
from datetime import datetime
from sqlalchemy import String, Text, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base


class StrainLink(Base):
    """A directed genetic relationship between two strains.
    
    Relationship types:
      - parent: strain_a is a direct parent of strain_b (the classic "X x Y" cross)
      - phenotype: strain_b is a phenotype/cut selection of strain_a
      - alias: strain_a and strain_b are the same strain under different names
      - descendant: strain_b is a later-generation descendant of strain_a
      - bred_by: strain_a was bred/created by the breeder named in strain_b's genetics field
    """
    __tablename__ = "strain_links"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: uuid.uuid4().hex[:12])
    parent_id: Mapped[str] = mapped_column(String, ForeignKey("strains.id"), nullable=False, index=True)
    child_id: Mapped[str] = mapped_column(String, ForeignKey("strains.id"), nullable=False, index=True)
    rel_type: Mapped[str] = mapped_column(String(50), default="parent", index=True)
    confidence: Mapped[float] = mapped_column(default=1.0)  # 0.0-1.0 how confident we are
    source: Mapped[str] = mapped_column(String(100), default="manual")  # description_extract, leafly, manual
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("parent_id", "child_id", "rel_type", name="uq_strain_link"),
    )

    # Relationships
    parent = relationship("Strain", foreign_keys="StrainLink.parent_id", lazy="joined", innerjoin=True)
    child = relationship("Strain", foreign_keys="StrainLink.child_id", lazy="joined", innerjoin=True)

    def __repr__(self) -> str:
        return f"<StrainLink {self.parent_id} → {self.child_id} [{self.rel_type}]>"

    @property
    def relationship_label(self) -> str:
        labels = {
            "parent": "Direct Parent",
            "cross": "Cross",
            "phenotype": "Phenotype",
            "descendant": "Descendant",
            "genetics_source": "Genetic Source",
            "bred_by": "Bred By",
        }
        return labels.get(self.rel_type, self.rel_type)