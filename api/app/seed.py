import json
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from app.models.models import Base, Show, Season, Episode, Artwork

# --- setup ---
DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)

SEED_FILE = Path(__file__).resolve().parents[1] / "seed-data" / "seed_shows.json"

# artwork specs from reference.json (hardcoded here, matches the spec exactly)
ARTWORK_SPECS = {
    "poster": {"width": 600, "height": 900, "size_bytes": 150_000},
    "banner": {"width": 1280, "height": 720, "size_bytes": 150_000},
    "thumbnail": {"width": 640, "height": 360, "size_bytes": 100_000},
}


def run():
    with open(SEED_FILE, "r", encoding="utf-8") as f:
        records = json.load(f)

    session = Session()

    # wipe existing data (dev convenience — order matters due to FKs)
    session.query(Artwork).delete()
    session.query(Episode).delete()
    session.query(Season).delete()
    session.query(Show).delete()
    session.commit()

    # --- Step 1: collect show-level info ---
    shows_by_slug = {}
    for r in records:
        slug = r["slug"]
        if slug not in shows_by_slug:
            shows_by_slug[slug] = {
                "title": r["show_title"],
                "synopsis": r.get("synopsis"),
                "section": None,
                "statuses": [],
            }
        if shows_by_slug[slug]["section"] is None and r.get("section"):
            shows_by_slug[slug]["section"] = r["section"]
        shows_by_slug[slug]["statuses"].append(r["status"])

    # --- Step 2: insert shows ---
    show_ids = {}
    for slug, info in shows_by_slug.items():
        final_status = "published" if "published" in info["statuses"] else "draft"
        show = Show(
            slug=slug,
            title=info["title"],
            synopsis=info["synopsis"],
            section=info["section"],
            status=final_status,
        )
        session.add(show)
        session.flush()  # get generated id
        show_ids[slug] = show.id

    # --- Step 3: insert seasons (unique per slug+season_number) ---
    season_ids = {}
    for r in records:
        key = (r["slug"], r["season_number"])
        if key not in season_ids:
            season = Season(show_id=show_ids[r["slug"]], number=r["season_number"])
            session.add(season)
            session.flush()
            season_ids[key] = season.id

       # --- Step 4: insert episodes (skip true duplicates on content_group+language) ---
    episode_ids = {}
    skipped = []

    for r in records:
        try:
            with session.begin_nested():  # SAVEPOINT — only this insert rolls back on failure
                episode = Episode(
                    season_id=season_ids[(r["slug"], r["season_number"])],
                    content_group=r["content_group"],
                    language=r["language"],
                    title=r["episode_title"],
                    duration_seconds=r.get("duration_seconds"),
                    status=r["status"],
                    categories=r.get("categories", []),
                )
                session.add(episode)
                session.flush()
        except IntegrityError:
            skipped.append(r.get("episode_id"))
            print(
                f"SKIPPED duplicate (content_group, language): "
                f"{r['content_group']}, {r['language']} "
                f"(source episode_id: {r.get('episode_id')})"
            )
            continue

        episode_ids[r["episode_id"]] = episode.id


        
    # --- Step 5: insert artwork for episodes that survived step 4 ---
    artwork_count = 0
    for r in records:
        source_id = r.get("episode_id")
        if source_id not in episode_ids:
            continue  # this episode was skipped as a duplicate
        for art_type in r.get("artwork_available", []):
            spec = ARTWORK_SPECS.get(art_type)
            if not spec:
                continue
            artwork = Artwork(
                episode_id=episode_ids[source_id],
                type=art_type,
                storage_key=f"seed/{episode_ids[source_id]}/{art_type}.jpg",
                width=spec["width"],
                height=spec["height"],
                file_size_bytes=spec["size_bytes"],
            )
            session.add(artwork)
            artwork_count += 1

    session.commit()

    print("\n--- Seed summary ---")
    print(f"Shows:    {len(show_ids)}")
    print(f"Seasons:  {len(season_ids)}")
    print(f"Episodes: {len(episode_ids)} inserted, {len(skipped)} skipped as duplicates")
    print(f"Artwork:  {artwork_count} rows")


if __name__ == "__main__":
    run()