import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.models import Show, Season, Episode, Artwork, PublishRun

CATALOG_DIR = Path(os.environ.get("STORAGE_PATH", "/app/storage"))
LIVE_CATALOG_PATH = CATALOG_DIR / "catalogue.json"


def run_publish(session: Session, triggered_by: str) -> dict:
    """
    Builds catalogue.json from published shows/episodes and atomically
    swaps it into place. Records the outcome in publish_runs regardless
    of success or failure.
    """
    run = PublishRun(
        triggered_by=triggered_by,
        started_at=datetime.utcnow(),
        status="started",
    )
    session.add(run)
    session.commit()  # commit immediately so a crash mid-build still leaves a record

    try:
        catalogue, show_count, episode_count = _build_catalogue(session)
        _write_atomic(catalogue)

        run.status = "success"
        run.finished_at = datetime.utcnow()
        run.show_count = show_count
        run.episode_count = episode_count
        session.commit()

        return {
            "status": "success",
            "shows": show_count,
            "episodes": episode_count,
            "run_id": str(run.id),
        }

    except Exception as e:
        run.status = "failed"
        run.finished_at = datetime.utcnow()
        run.error_detail = str(e)
        session.commit()
        raise


def _build_catalogue(session: Session):
    """
    Queries published shows + their published episodes, collapses
    language variants by content_group, excludes season 0 from the
    normal season listing, and returns a deterministic structure.
    """
    shows = (
        session.query(Show)
        .filter(Show.status == "published")
        .order_by(Show.title)
        .all()
    )

    catalogue_shows = []
    total_episodes = 0

    for show in shows:
        seasons = (
            session.query(Season)
            .filter(Season.show_id == show.id)
            .order_by(Season.number)
            .all()
        )

        catalogue_seasons = []
        trailers = []

        for season in seasons:
            episodes = (
                session.query(Episode)
                .filter(
                    Episode.season_id == season.id,
                    Episode.status == "published",
                )
                .order_by(Episode.content_group)
                .all()
            )

            # group by content_group -> collapse language variants
            grouped = {}
            for ep in episodes:
                grouped.setdefault(ep.content_group, []).append(ep)

            collapsed_entries = []
            for content_group, variants in sorted(grouped.items()):
                # canonical row: prefer English if present, else first alphabetically by language
                variants_sorted = sorted(variants, key=lambda e: (e.language != "en", e.language))
                canonical = variants_sorted[0]

                entry = {
                    "content_group": content_group,
                    "title": canonical.title,
                    "languages": sorted(v.language for v in variants),
                    "duration_seconds": canonical.duration_seconds,
                    "categories": canonical.categories or [],
                    "artwork": _artwork_urls(session, canonical.id),
                }
                collapsed_entries.append(entry)
                total_episodes += 1

            if season.number == 0:
                trailers.extend(collapsed_entries)
            else:
                catalogue_seasons.append({
                    "number": season.number,
                    "episodes": collapsed_entries,
                })

        catalogue_shows.append({
            "slug": show.slug,
            "title": show.title,
            "synopsis": show.synopsis,
            "section": show.section,
            "seasons": catalogue_seasons,
            "trailers": trailers,
        })

    catalogue = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "shows": catalogue_shows,
    }
    return catalogue, len(catalogue_shows), total_episodes


def _artwork_urls(session: Session, episode_id) -> dict:
    rows = session.query(Artwork).filter(Artwork.episode_id == episode_id).all()
    return {a.type: a.storage_key for a in rows}


def _write_atomic(catalogue: dict):
    """
    Writes to a temp file then os.replace()'s it over the live file.
    This is the core atomicity guarantee: readers only ever see the
    fully-old file or the fully-new file, never a partial write.
    """
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = CATALOG_DIR / f"catalogue.tmp-{uuid.uuid4().hex}.json"

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(catalogue, f, indent=2)

    os.replace(tmp_path, LIVE_CATALOG_PATH)  # atomic on POSIX filesystems