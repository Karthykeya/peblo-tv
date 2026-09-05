# Peblo TV Mini

A CMS → API → publish pipeline → viewer system for managing multi-language episodic content.

## How to run
docker compose up --build

This brings up Postgres and the FastAPI backend. On first boot (empty database), the container automatically runs migrations and seeds `seed-data/seed_shows.json` — no manual step required. Subsequent restarts skip seeding if data already exists.

API: `http://localhost:8000` (interactive docs at `/docs`)

To run the frontends:
cd viewer && npm install && npm run dev # http://localhost:5173
cd cms && npm install && npm run dev # http://localhost:5174 (auto-picks free port)

### Auth (dev shortcut)
Requests are role-gated via a header instead of real JWTs: pass `X-Role: admin` or `X-Role: editor` (the CMS UI has a role switcher built in for testing this). This is a deliberate, documented shortcut — but enforcement is server-side via a FastAPI dependency (`require_admin`) on the publish endpoint specifically, not just hidden in the frontend.

## Decisions & trade-offs

**1. Publish atomicity.** The publish job writes the new catalogue to a uniquely-named temp file, then uses `os.replace()` to atomically swap it over the live `catalogue.json`. This is atomic on POSIX filesystems — a reader always sees either the fully-old or fully-new file, never a partial write. A `publish_runs` row is written with `status=started` *before* the build begins, so a crash mid-build still leaves a record; the live file itself is untouched by a failed run, only an orphaned temp file is left behind. Covered by automated tests (`api/tests/test_publish.py`).

**2. Storage.** Artwork and the catalogue file are written under `STORAGE_PATH`, behind one path variable rather than a formal `StorageBackend` interface class (a documented scope cut, see below). Swapping to R2/S3 would mean replacing local file writes with S3-compatible calls at that boundary — R2 is S3-compatible.

**3. Search.** `/catalog/search` does a case-insensitive substring match on show titles, filtered by section, read directly from the published `catalogue.json`. This doesn't scale past a small catalogue — it's a linear scan with no indexing. At real scale this should move to Postgres full-text search (`ts_vector`) or a dedicated engine like Meilisearch/Elasticsearch.

**4. Why publish to a file instead of querying per request.** Serving a pre-built JSON snapshot keeps viewer reads fast and decoupled from database load, and the viewer never touches the admin data path. Trade-off: staleness between publishes, and a large catalogue means serving the whole file rather than paginating — fine at this scale, would need pagination/CDN caching at real scale.

**5. Health check.** `/health` checks DB connectivity and reports the status of the most recent publish run, treating a failed publish as the strongest alerting signal — a silent publish failure means editors believe content is live when it isn't, the worst failure mode for this product.

**6. Canonical row for language variants.** When collapsing `content_group` variants, the entry's shared fields (title, duration, artwork) come from the English variant if present, otherwise the alphabetically-first language. Documented, not hidden — covered by `test_canonical_row_prefers_english`.

**7. CMS episode creation.** The CMS UI supports editing status/metadata and uploading artwork on *existing* episodes, but does not support creating brand-new episodes/shows/seasons from scratch — that would require building full nested CRUD (show → season → episode creation flow) which we scoped out given time constraints. New content currently enters via the seed script or direct API calls. This is stated in the UI itself when someone tries to save a "new" episode.

## What we cut, and why
- **Full StorageBackend interface class** — a `Protocol`-based interface wasn't built; storage writes go through one path variable instead. Functionally equivalent for this scope, but not as clean an abstraction boundary.
- **Nested show/season/episode creation from the CMS** — see above.
- **CI deploy step** — stubbed intentionally (see `.github/workflows/ci.yml`): builds the Docker image but doesn't push to a real registry or trigger a real deploy, since no real infrastructure exists for this assignment.
- **CMS visual styling** — functional, not polished; no design system, plain CSS.
- **Pagination on the episode list / catalog** — fine at this data scale (95 episodes), would need addressing at real scale.

## AI tools used
Claude was used throughout for scaffolding (models, migrations, seed script, publish job, endpoints, frontend components) and debugging. One concrete example of catching and fixing a real bug in AI-suggested code: the first version of the seed script's duplicate-handling logic used `session.rollback()` on an `IntegrityError`, which rolled back the *entire* transaction rather than just the failing insert, silently corrupting later inserts that depended on already-flushed IDs from earlier in the same transaction. Diagnosed from the actual foreign-key-violation traceback and fixed by wrapping each episode insert in a `session.begin_nested()` savepoint, so only the failing row rolls back.

## Data issues found in seed_shows.json

Found by manually tracing the data before writing any code:

| Issue | Detail |
|---|---|
| True duplicate `(content_group, language)` | `ep_0004` and `ep_9001` both have `content_group=motis-many-lives-s01e02, language=hi` with different titles — caught by the DB unique constraint; seed script skips and logs it |
| Published episode missing artwork | `ep_0036` is `status=published` with `artwork_available=[]` — flagged by the validation report, blocks the status transition to published via the API |
| Null section on a whole show | `ep_0085`–`ep_0092` ("Rhyme Rangers"), all `status=draft` — likely intentional (drafts don't need a section yet), flagged as an ambiguous case |
| Season-0 trailers have partial artwork | `ep_0093` only has a `thumbnail`, not the full set — validation treats season-0 episodes as only requiring a thumbnail |

## Schema

Five tables: `shows`, `seasons`, `episodes`, `artwork`, `publish_runs`.
- `UNIQUE(content_group, language)` on `episodes` — catches the planted duplicate above.
- `UNIQUE(episode_id, type)` on `artwork` — re-uploading a type upserts rather than duplicating.
- `shows.section` is nullable, matching real draft data.

## Testing

`api/tests/test_publish.py` — language-variant collapse, season-0 exclusion, draft/unpublished exclusion, canonical-row selection (5 tests, all passing, run against a real Postgres instance).
`api/tests/test_artwork_validation.py` — dimension/spec matching (2 tests, all passing).

Run with:
cd api
DATABASE_URL="postgresql://peblo:peblo_dev_password@localhost:5432/peblo_tv" python -m pytest tests/ -v

Artwork upload and validation were also manually verified end-to-end against the actual provided sample assets (`poster_good.jpg`, `poster_wrong_ratio.jpg`, `banner_too_big.png`, `thumb_tiny.jpg`, etc.) via curl, confirming both success and rejection paths return correct, specific error messages.

## Time spent

See `notes.md` for a running log kept throughout the build.
