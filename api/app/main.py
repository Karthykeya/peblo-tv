import uuid
from datetime import datetime
from pathlib import Path


from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
import os

from app.models.models import Base, Show, Season, Episode, Artwork, PublishRun
from app.publish import run_publish
from sqlalchemy import text

from fastapi import UploadFile, File, Form
from PIL import Image
import io

DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

app = FastAPI(title="Peblo TV API")
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev-only; would restrict in production
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_role(required_role: str):
    def dep(x_role: str = "editor"):  # header default fallback; overridden below
        return x_role
    return dep


# --- simple header-based fake auth (documented shortcut in README) ---
from fastapi import Header

def get_current_role(x_role: str = Header(default="editor")):
    if x_role not in ("editor", "admin"):
        raise HTTPException(400, "Invalid role header")
    return x_role


def require_admin(role: str = Depends(get_current_role)):
    if role != "admin":
        raise HTTPException(403, "Admins only")
    return role


@app.get("/health")
def health(db: Session = Depends(get_db)):
    checks = {"database": "ok"}
    overall_ok = True

    try:
        db.execute(text("SELECT 1"))
    except Exception as e:
        checks["database"] = f"error: {e}"
        overall_ok = False

    # Alert signal: last publish run status/age. A silent publish failure
    # means editors believe content is live when it isn't — the worst
    # failure mode for this product, so this is the one thing worth
    # actively alerting on beyond basic DB connectivity.
    last_run = db.query(PublishRun).order_by(PublishRun.started_at.desc()).first()
    if last_run is None:
        checks["last_publish"] = "no publishes yet"
    else:
        checks["last_publish"] = {
            "status": last_run.status,
            "started_at": last_run.started_at.isoformat() if last_run.started_at else None,
        }
        if last_run.status == "failed":
            checks["last_publish"]["warning"] = "most recent publish failed"
            overall_ok = False

    return {"status": "ok" if overall_ok else "degraded", "checks": checks}


# --- CRUD: episodes ---
@app.get("/admin/episodes")
def list_episodes(db: Session = Depends(get_db), role: str = Depends(get_current_role)):
    episodes = db.query(Episode).all()
    return [
        {
            "id": str(e.id), "content_group": e.content_group, "language": e.language,
            "title": e.title, "status": e.status, "duration_seconds": e.duration_seconds,
        }
        for e in episodes
    ]


@app.patch("/admin/episodes/{episode_id}/status")
def update_episode_status(episode_id: str, status: str, db: Session = Depends(get_db), role: str = Depends(get_current_role)):
    episode = db.query(Episode).filter(Episode.id == episode_id).first()
    if not episode:
        raise HTTPException(404, "Episode not found")
    if status == "published":
        artwork_types = {a.type for a in db.query(Artwork).filter(Artwork.episode_id == episode.id).all()}
        season = db.query(Season).filter(Season.id == episode.season_id).first()
        required = {"thumbnail"} if season.number == 0 else {"poster", "banner", "thumbnail"}
        missing = required - artwork_types
        if missing:
            raise HTTPException(400, f"Cannot publish: missing artwork {sorted(missing)}")
        if not episode.duration_seconds:
            raise HTTPException(400, "Cannot publish: missing duration_seconds")
    episode.status = status
    db.commit()
    return {"id": str(episode.id), "status": episode.status}


# --- validation report ---
@app.get("/admin/validation-report")
def validation_report(db: Session = Depends(get_db), role: str = Depends(get_current_role)):
    missing_artwork = []
    missing_duration = []
    for e in db.query(Episode).filter(Episode.status == "published").all():
        artwork_types = {a.type for a in db.query(Artwork).filter(Artwork.episode_id == e.id).all()}
        season = db.query(Season).filter(Season.id == e.season_id).first()
        required = {"thumbnail"} if season.number == 0 else {"poster", "banner", "thumbnail"}
        missing = required - artwork_types
        if missing:
            missing_artwork.append({"episode_id": str(e.id), "title": e.title, "missing": sorted(missing)})
        if not e.duration_seconds:
            missing_duration.append({"episode_id": str(e.id), "title": e.title})

    shows_without_section = [
        {"id": str(s.id), "title": s.title}
        for s in db.query(Show).filter(Show.status == "published", Show.section.is_(None)).all()
    ]

    return {
        "missing_artwork": missing_artwork,
        "missing_duration": missing_duration,
        "shows_without_section": shows_without_section,
    }


# --- publish ---
@app.post("/admin/catalog/publish")
def publish_catalog(db: Session = Depends(get_db), role: str = Depends(require_admin)):
    try:
        result = run_publish(db, triggered_by=f"role:{role}")
        return result
    except Exception as e:
        raise HTTPException(500, f"Publish failed: {e}")


@app.get("/admin/catalog/publish-runs")
def list_publish_runs(db: Session = Depends(get_db), role: str = Depends(get_current_role)):
    runs = db.query(PublishRun).order_by(PublishRun.started_at.desc()).all()
    return [
        {
            "id": str(r.id), "triggered_by": r.triggered_by, "status": r.status,
            "show_count": r.show_count, "episode_count": r.episode_count,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "error_detail": r.error_detail,
        }
        for r in runs
    ]
ARTWORK_SPECS = {
    "poster": {"width": 600, "height": 900, "max_kb": 200},
    "banner": {"width": 1280, "height": 720, "max_kb": 200},
    "thumbnail": {"width": 640, "height": 360, "max_kb": 200},
}


@app.post("/admin/episodes/{episode_id}/artwork")
async def upload_artwork(
    episode_id: str,
    type: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    role: str = Depends(get_current_role),
):
    episode = db.query(Episode).filter(Episode.id == episode_id).first()
    if not episode:
        raise HTTPException(404, "Episode not found")

    spec = ARTWORK_SPECS.get(type)
    if not spec:
        raise HTTPException(400, f"Unknown artwork type '{type}'. Must be one of {list(ARTWORK_SPECS)}")

    if file.content_type not in ("image/jpeg", "image/png"):
        raise HTTPException(400, f"File must be JPEG or PNG, got {file.content_type}")

    data = await file.read()
    size_kb = len(data) / 1024
    if size_kb > spec["max_kb"]:
        raise HTTPException(400, f"{type.capitalize()} must be under {spec['max_kb']} KB — this file is {size_kb:.0f} KB.")

    try:
        img = Image.open(io.BytesIO(data))
        width, height = img.size
    except Exception:
        raise HTTPException(400, "File is not a valid image")

    if (width, height) != (spec["width"], spec["height"]):
        raise HTTPException(
            400,
            f"{type.capitalize()} must be {spec['width']}x{spec['height']} — this image is {width}x{height}."
        )

    storage_dir = Path(os.environ.get("STORAGE_PATH", "/app/storage")) / "artwork" / episode_id
    storage_dir.mkdir(parents=True, exist_ok=True)
    storage_key = f"artwork/{episode_id}/{type}.jpg"
    (storage_dir / f"{type}.jpg").write_bytes(data)

    existing = db.query(Artwork).filter(Artwork.episode_id == episode.id, Artwork.type == type).first()
    if existing:
        existing.storage_key = storage_key
        existing.width = width
        existing.height = height
        existing.file_size_bytes = len(data)
    else:
        db.add(Artwork(
            episode_id=episode.id, type=type, storage_key=storage_key,
            width=width, height=height, file_size_bytes=len(data),
        ))
    db.commit()

    return {"type": type, "url": f"/static/{storage_key}", "width": width, "height": height}


# --- public catalog read (viewer-facing, no auth) ---
@app.get("/catalog")
def get_catalog():
    storage_path = Path(os.environ.get("STORAGE_PATH", "/app/storage")) / "catalogue.json"
    if not storage_path.exists():
        raise HTTPException(404, "Catalogue not published yet")
    import json
    return json.loads(storage_path.read_text())


@app.get("/catalog/search")
def search_catalog(q: str = "", category: str = "", language: str = "", section: str = ""):
    storage_path = Path(os.environ.get("STORAGE_PATH", "/app/storage")) / "catalogue.json"
    if not storage_path.exists():
        raise HTTPException(404, "Catalogue not published yet")
    import json
    catalog = json.loads(storage_path.read_text())
    results = []
    for show in catalog["shows"]:
        if section and show.get("section") != section:
            continue
        if q and q.lower() not in show["title"].lower():
            continue
        results.append(show)
    return {"results": results}