"""Seed script — imports cannabis.json into the database."""
import json
import asyncio
from pathlib import Path
from sqlalchemy import select, func
from backend.database import async_session, init_db
from backend.models.strain import Strain
from backend.models.user import User
from backend.config import settings
import bcrypt

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


async def seed():
    """Seed strains from cannabis.json and create demo user if empty."""
    async with async_session() as db:
        # Check if already seeded
        count = (await db.execute(select(func.count()).select_from(Strain))).scalar() or 0
        if count > 0:
            print(f"[seed] {count} strains already in DB, skipping strain seed")
        else:
            # Load cannabis.json
            json_path = DATA_DIR / "cannabis.json"
            if not json_path.exists():
                print("[seed] cannabis.json not found, skipping")
                return

            with open(json_path) as f:
                raw_strains = json.load(f)

            seen = set()
            batch = []
            skipped = 0
            for item in raw_strains:
                name = str(item.get("Strain", "")).strip()
                if not name or name.lower() in seen:
                    skipped += 1
                    continue
                seen.add(name.lower())

                strain_type_raw = str(item.get("Type", "hybrid")).lower().strip()
                if strain_type_raw not in ("indica", "sativa", "hybrid"):
                    strain_type_raw = "hybrid"

                rating = float(item.get("Rating", 0) or 0)

                # Parse effects
                effects_raw = str(item.get("Effects", "None"))
                effects = [e.strip() for e in effects_raw.split(",") if e.strip() and e.strip() != "None"]

                # Parse flavors
                flavors_raw = str(item.get("Flavor", "None"))
                flavors = [f.strip() for f in flavors_raw.split(",") if f.strip() and f.strip() != "None"]

                description = str(item.get("Description", "")).strip()

                batch.append(Strain(
                    name=name,
                    strain_type=strain_type_raw,
                    rating=rating,
                    effects=json.dumps(effects),
                    flavors=json.dumps(flavors),
                    description=description,
                    source="kaggle",
                ))

            db.add_all(batch)
            await db.commit()
            print(f"[seed] Imported {len(batch)} strains ({skipped} skipped as duplicates)")

        # Seed demo user if none exist
        user_count = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
        if user_count == 0:
            pw_hash = bcrypt.hashpw("weed420".encode(), bcrypt.gensalt()).decode()
            demo = User(
                username="stoner_sam",
                email="sam@weed.app",
                password_hash=pw_hash,
                display_name="Stoner Sam",
                bio="Just here for the terpenes 🌿",
            )
            db.add(demo)
            await db.commit()
            print("[seed] Created demo user: stoner_sam / weed420")


if __name__ == "__main__":
    asyncio.run(init_db())
    asyncio.run(seed())