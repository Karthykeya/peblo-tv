# Peblo TV Mini

A CMS → API → publish pipeline → viewer system for managing multi-language episodic content.

## How to run

    cp .env.example .env
    docker compose up --build

Brings up Postgres, the FastAPI backend, the CMS, and the viewer. On first boot the API container runs migrations and seeds `seed-data/seed_shows.json` automatically. Subsequent restarts skip seeding if data already exists.

- API: `http://localhost:8000` (docs at `/docs`)
- Viewer: `http://localhost:5173`
- CMS: `http://localhost:5174`

**Note:** `.env` is gitignored and must be created from `.env.example` before first run — Postgres fails to start with a blank password if this step is skipped. Confirmed via a genuine cold-clone test (see notes.md, Session 3).

**Auth (dev shortcut):** role-gated via an `X-Role: admin`/`X-Role: editor` header instead of real JWTs (documented shortcut, CMS has a role switcher for testing). Enforcement is server-side via a FastAPI dependency on the publish endpoint — confirmed `X-Role: editor` on `/admin/catalog/publish` returns a real 403.

## Decisions & trade-offs

**1. Publish atomicity.** Writes the new catalogue to a uniquely-named temp file, then `os.replace()`s it over the live `catalogue.json` — atomic on POSIX, so readers only ever see fully-old or fully-new. A `publish_runs` row is created with `status=started` before the build begins, so a crash mid-build still leaves a record; a failed run leaves only an orphaned temp file. Deterministic ordering: `ORDER BY show.title, season.number, episode.content_group`. Tested in `api/tests/test_publish.py`.

**2. Storage abstraction.** Artwork and the catalogue file go through a `StorageBackend` Protocol (`save`/`read`/`delete`), implemented by `LocalDiskStorage`. Swapping to R2/S3 means writing one new class against the S3-compatible API; nothing else changes. Found and fixed during review: the fallback storage path was hardcoded to `/app/storage` (Docker-only), which silently broke CI on a bare runner — fixed to a relative `./storage` default with `STORAGE_PATH` set explicitly in CI.

**3. Search.** `/catalog/search` currently supports `q` (title substring, case-insensitive) and `section` filtering, read directly from the published catalogue with no caching layer — every request reads the file fresh from disk. **Not yet implemented:** `category`/`language` filters from the original spec — a stated cut, not an oversight. Doesn't scale past a small catalogue; at real scale this moves to Postgres full-text search or Meilisearch/Elasticsearch.

**4. Why a published file instead of querying per request.** Keeps viewer reads fast and fully decoupled from the DB — confirmed via DevTools that the viewer only ever calls `/catalog` and `/catalog/search`, nothing under `/admin/*`. Trade-off: staleness between publishes, and no pagination on a large catalogue yet. Note: publish counts reflect catalogue entries *after* language-collapse (e.g. 84 published episode rows → 66 catalogue entries, 18 EN/HI pairs collapsed).

**5. Health check.** `/health` checks DB connectivity and the status of the most recent publish run — a silent publish failure (editors think content is live when it isn't) is the worst failure mode for this product, so it's the strongest alert signal.

**6. Canonical row for language variants.** Shared fields (title, duration, artwork) come from the English variant if present, else alphabetically-first language. Covered by `test_canonical_row_prefers_english`.

**7. Episode creation.** `POST /admin/episodes` enforces the same validation as the rest of CRUD — tested for both success and a clean 409 (not a raw Postgres traceback) on a duplicate `(content_group, language)`. The CMS UI's full show/season creation flow is a scope cut; new shows currently enter via the seed script.

**8. Why Alembic, not `create_all()`.** Migrations are versioned and reviewable (`alembic/versions/`), matching how a real schema evolves over multiple deploys — `create_all()` has no history and can't express a change like adding a constraint to an existing table.

**9. Why artwork is its own table, not columns on episodes.** Each episode needs up to three independently-uploadable, independently-validatable artwork records (poster/banner/thumbnail). Modeling these as columns on `episodes` would mean three sets of width/height/size columns and no clean way to represent "this type is missing" — a separate table with `UNIQUE(episode_id, type)` lets re-uploads upsert cleanly and lets validation check "which types exist" with a simple query.

**10. Index justification.** `ix_episodes_content_group` supports the publish job's group-by-content_group query (run on every publish). `ix_shows_section_status` supports the common admin/viewer filter pattern of "published shows in section X" — both are queried far more often than the tables are written to.

**11. CMS state handling.** Every fetch in the CMS (episode list, publish page) has explicit loading / empty ("No episodes match your filters") / error (with a retry button) states. A non-admin reaching the publish page sees a clear "Admins only" message rather than a disabled button with no explanation. Data fetching uses plain `fetch` + `useState`/`useEffect` rather than TanStack Query — scope was small enough (a handful of screens, no complex cache invalidation chains) that the extra dependency wasn't justified here.

## What we cut, and why
- CMS UI flow for creating a brand-new show/season (API endpoint exists and is tested; UI form doesn't)
- `category`/`language` filters on `/catalog/search`
- CI deploy step — stubbed intentionally, no real infra to deploy to
- CMS styling — functional only
- Pagination — fine at this data scale (95 episodes)
- Stretch goals explicitly declined: rollback, dry-run diff/preview before publish, and an audit log of who-changed-what. None of these are needed to prove the core pipeline works correctly, and each would have taken meaningfully more time than the core publish/validation logic they'd sit on top of.

## Ambiguous calls made, and why
- **Show status derivation.** A show is marked `published` if *any* of its episodes are published, `draft` otherwise — the source data doesn't have an explicit show-level status field. Documented rather than guessed silently.
- **`Show.section` nullable.** The "Rhyme Rangers" episodes (`ep_0085`–`ep_0092`) have `section: null` but `status: draft` — treated as intentional (drafts don't need a section yet) rather than a data bug, but flagged since it could go either way.
- **Season-0 artwork requirement.** The spec doesn't explicitly say trailers need less artwork, but `ep_0093` (a real season-0 record) only ships a thumbnail — inferred from the data that season-0 episodes only require a thumbnail, not the full set, and validation logic reflects that.

## AI tools used
Claude was used throughout for scaffolding (models, migrations, seed script, publish job, endpoints) and a structured verification pass. Two examples of catching real bugs rather than accepting generated code as-is:
1. The seed script's first version used `session.rollback()` on a duplicate-insert error, which rolled back the *entire* transaction and silently corrupted later inserts depending on already-flushed IDs. Fixed with `session.begin_nested()` savepoints after tracing the actual foreign-key error.
2. A full cold-start pass found `docker-compose.yml` was missing the `cms`/`viewer` services entirely, both frontend Dockerfiles were missing from disk, and the frontend image's Node 18 crashed against a newer Vite dependency needing Node 20.12+ — all caught by actually running `docker compose up --build` from zero, not by trusting an earlier "done" status.

## Data issues found in seed_shows.json

| Issue | Detail |
|---|---|
| True duplicate `(content_group, language)` | `ep_0004`/`ep_9001`, same content_group+language, different titles — caught by the DB unique constraint at seed time and re-confirmed live via `POST /admin/episodes` (409) |
| Published episode missing artwork | `ep_0036`, `status=published`, `artwork_available=[]` — blocks the publish status transition |
| Null section on a whole show | `ep_0085`–`ep_0092` ("Rhyme Rangers"), all `status=draft` — likely intentional, flagged as ambiguous |
| Season-0 trailers have partial artwork | `ep_0093` has only `thumbnail` — validation treats season-0 as thumbnail-only |

## Schema
`shows`, `seasons`, `episodes`, `artwork`, `publish_runs`.
- `UNIQUE(content_group, language)` on `episodes` — catches the duplicate above
- `UNIQUE(episode_id, type)` on `artwork` — re-upload upserts
- `shows.section` nullable, matching real draft data
- See "Index justification" and "Why artwork is its own table" above for indexing/modeling rationale

## Testing
`test_publish.py` — language collapse, season-0 exclusion, draft exclusion, canonical-row selection (5 passing).
`test_artwork_validation.py` — spec matching (2 passing, 1 skipped — a size-limit fixture that landed under threshold, a known test-data limitation, not a real pass).

    cd api
    STORAGE_PATH=./test-storage DATABASE_URL="postgresql://peblo:peblo_dev_password@localhost:5432/peblo_tv" python -m pytest tests/ -v

Also manually verified via a genuine cold-start (`git clone` into a fresh directory, `docker compose up --build` from zero): health check, publish job, `content_group` collapse (checked in raw `catalogue.json`), zero `season_number: 0` outside the `trailers` key, role enforcement returns real 403s, viewer network calls limited to `/catalog*`, artwork validation against the actual sample assets.

## Known issues
- `.env` must be created from `.env.example` before first run, or Postgres fails to start on a blank password — a real first-contact risk on any fresh clone, not a one-off mistake.
- `docker compose config` catches YAML indentation errors fast — worth running after any edit to `docker-compose.yml`.

## Time spent

| Part | Time |
|---|---|
| Setup + data exploration + schema | ~1h 45m |
| Seed script + publish job | ~1h 15m |
| Verification pass + bugfixes | ~3h 45m |
| **Total** | **~5h 45m** |

See `notes.md` for the full build log.