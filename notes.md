# Build log

## Session 1 — Day 0 setup + data exploration + schema
- Set up repo skeleton: api/, cms/, viewer/, docker-compose.yml, .env.example
- Fixed PowerShell vs Git Bash heredoc issue — switched to Git Bash for the rest of the project
- Got docker-compose up bringing up Postgres + FastAPI /health check
  - Hit .env being empty after a failed cp — recreated it directly with a heredoc
  - Fixed a healthcheck false-positive (pg_isready needs -d flag matching POSTGRES_DB, not just -U)
- Connected the repo to GitHub Desktop (had to manually "Add local repository" — it doesn't auto-detect)
- Read reference.json — confirmed real spec values:
  - sections: featured, series, minisodes, songs
  - categories: adventure, folk, friendship, india, language, learning, maths, music,
    nature, reading, science, singalong, stories, travel, values
  - languages: en, hi
  - artwork specs: poster 600x900 (2:3, 200KB max), banner 1280x720 (16:9, 200KB max),
    thumbnail 640x360 (16:9, 200KB max)
  - conventions confirmed: season 0 = trailers only; content_group = language variants,
    must collapse into ONE catalogue entry
- Read seed_shows.json (95 flat episode records, NOT nested shows->seasons->episodes)
  - Found content_group language-variant example: motis-many-lives-s01e01
    (ep_0001 en "The Lost Kite" 510s / ep_0002 hi same title 480s — different duration,
    dub timing, both should collapse into one entry with languages:[en,hi])
  - Found season 0 example: ep_0093, season_number 0, "Trailer",
    content_group motis-many-lives-s00e01, artwork_available=[thumbnail] ONLY
    -> trailers don't need full artwork set, noted as a validation exception
  - Found planted bad data:
    1. TRUE DUPLICATE (content_group, language): ep_0004 vs ep_9001, both
       content_group=motis-many-lives-s01e02, language=hi, different titles
       -> exactly what the (content_group, language) unique constraint should catch
    2. Published episode missing artwork: ep_0036, status=published, artwork_available=[]
       -> should block publish
    3. Null section on a whole show: ep_0085-ep_0092 ("Rhyme Rangers"), all status=draft
       -> likely fine since they're drafts, flagged as ambiguous in README
  - Wrote findings to notes-data-exploration.md
- Sketched DB schema (5 tables): shows, seasons, episodes, artwork, publish_runs
  - UniqueConstraint(content_group, language) on episodes — catches the ep_0004/ep_9001 bug directly
  - UniqueConstraint(episode_id, type) on artwork — allows re-upload to upsert
  - shows.section nullable (matches real data — draft shows can have null section)
- Wrote SQLAlchemy models (api/app/models/models.py)
- Set up Alembic, wired target_metadata to Base.metadata, loaded DATABASE_URL via dotenv in env.py
- Generated + ran first migration — confirmed all 5 tables + constraints landed correctly
  via `\d episodes` (uq_episode_content_group_language present as expected)
- Gotcha: Alembic run locally needs DATABASE_URL overridden to use `localhost` instead of
  the `db` hostname (which only resolves inside the Docker network)
- Committed: "Part A1: DB schema (shows, seasons, episodes, artwork, publish_runs) + initial migration"
- Cleaned up __pycache__ files that got accidentally committed; added to .gitignore

## Session 2 — Seed script + publish job
- Wrote seed script (api/app/seed.py):
  - Groups flat seed_shows.json records by slug -> shows, by (slug, season_number) -> seasons
  - Inserts episodes, creates fake artwork rows matching exact spec dimensions for each
    type listed in artwork_available (no real image files yet — placeholders only)
  - Truncates all 4 tables at start for idempotent re-runs
- Bug found + fixed: session.rollback() on a duplicate-episode IntegrityError was rolling
  back the WHOLE transaction, not just the bad insert — wiped out all previously-flushed
  episode IDs still referenced later in the artwork step, causing a ForeignKeyViolation.
  Fixed by wrapping each episode insert in session.begin_nested() (a SAVEPOINT) so only
  the failing insert rolls back.
- Ran seed script successfully: 8 shows, 10 seasons, 94 episodes inserted (1 skipped —
  the ep_9001 true duplicate, as expected), 275 artwork rows
- Verified in DB: motis-many-lives-s01e01 has 2 separate rows (en/hi) pre-collapse, as expected
- Committed: "Add seed script, load seed_shows.json into DB"
- Built the publish job (api/app/publish.py):
  - run_publish() creates a publish_runs row immediately (status="started") before doing
    any work, so a crash mid-build still leaves a record
  - Queries published shows -> published seasons -> published episodes
  - Groups episodes by content_group, collapses language variants into one entry with
    languages: [...] (canonical row picks English if present, else alphabetical — documented
    as a judgment call)
  - Season 0 episodes routed into a separate `trailers` list per show, never into `seasons`
  - Writes to a uniquely-named temp file, then os.replace() to swap it live atomically
  - On success: updates publish_runs to status=success with counts; on exception:
    status=failed with error_detail, then re-raises
- Bug found: STORAGE_PATH default in .env (/app/storage) only makes sense inside Docker;
  running the publish job locally via python3 silently wrote nowhere findable, while
  the DB-side publish_runs row still reported "success" — a real gap (DB status and file
  write aren't verified to be in sync). Worth revisiting: should run_publish() actually
  verify the file exists on disk after write before marking success?
- Fix (workaround, not a real fix yet): override STORAGE_PATH="../storage" explicitly
  when running publish locally, outside Docker
- Verified via manual Python shell run: {'status': 'success', 'shows': 7, 'episodes': 66}
- catalogue.json generated at ~/peblo-tv/storage/catalogue.json (45695 bytes)
- Still TODO before trusting this fully: confirm motis-many-lives-s01e01 appears exactly
  once in catalogue.json with languages:[en,hi], confirm zero "number": 0 entries under
  any seasons array, spot check one show's season ordering

## Session 3 — Full verification pass
- Goal: shut everything down, cold-start from scratch, and verify every graded requirement
  against real output rather than assuming prior "done" status was accurate.
- Found: docker-compose.yml only had db and api services — cms/viewer had never
  actually been added despite thinking this was done earlier. Added both service blocks;
  hit a YAML indentation bug twice (once nested inside api:, once with api:'s own
  properties landing inside db:) before rewriting the file cleanly via heredoc.
  docker compose config was the tool that actually caught these — visually reading
  the file in an editor wasn't enough.
- Found: cms/Dockerfile and viewer/Dockerfile didn't exist on disk at all (0 bytes /
  missing). Created both.
- Found: Dockerfiles used node:18-alpine, which crashed against a newer Vite/rolldown
  dependency needing Node 20.12+ (util.styleText not available in 18). Bumped to
  node:22-alpine, fixed.
- Verified end-to-end (all confirmed via actual command output, not assumption):
  - /health returns real DB + publish-freshness checks
  - Publish job: 84 published DB rows -> 66 catalogue entries (18 EN/HI pairs collapsed
    into 18, 48 single-language rows unchanged) -- confirmed via direct SQL count,
    not just trusting the response body
  - motis-many-lives-s01e01 collapses correctly into one entry, languages:[en,hi]
  - Season 0: zero "season_number": 0 entries in the main structure; 7 trailers
    (matching 7 published shows), correctly isolated under a separate "trailers" key
  - Role enforcement: X-Role: editor on /admin/catalog/publish returns actual HTTP 403
    (checked status code directly, not just response body)
  - Viewer network isolation: browser DevTools Network tab shows only 2 requests,
    both to /catalog, both 200 -- zero calls to anything under /admin/*
- Found + fixed a real gap: POST /admin/episodes didn't exist at all (only GET list,
  PATCH status, and POST artwork existed). Built it, matching existing code style
  (header-role dependency, direct SQLAlchemy queries). Hit a NameError on first attempt
  because the new EpisodeCreate pydantic model was pasted below the function that
  referenced it -- Python needs the class defined before first use. Moved it above.
  Tested: new episode creation succeeds (200); duplicate (content_group, language)
  returns a clean 409 with a plain-English message, not a raw Postgres traceback --
  proving the constraint is reachable through a real write path, not just at seed time.
- Found + fixed a real CI regression: pushing the new endpoint broke CI, unrelated to
  the endpoint itself. Root cause: app/storage.py's LocalDiskStorage had a hardcoded
  fallback default of "/app/storage", which only exists inside Docker. CI runs on a
  bare GitHub Actions runner with no /app directory and no permission to create one
  at filesystem root -- PermissionError. Fixed by changing the fallback to a relative
  "./storage" and explicitly setting STORAGE_PATH=/tmp/storage in the CI test step's
  env block. Confirmed locally first (7 passed, 1 skipped) before pushing; CI went
  green on the next commit.
- Did a genuinely fresh clean-clone test (git clone into /tmp, not the working repo):
  hit the exact same .env-not-copied issue as Day 0 (blank POSTGRES_PASSWORD caused
  Postgres to refuse to start) -- confirms this is a real, repeatable first-contact
  risk for anyone (including a grader) cloning the repo, not a one-off mistake.
  Recreated .env via heredoc, retried, and got a fully clean boot: migrations ran,
  seed skipped the planted duplicate correctly, all 4 containers up, health check
  and publish both succeeded with the same numbers as the main working copy.
- Rewrote README.md to reflect actual current state: corrected two places where the
  README undersold or misstated what's built (storage abstraction IS a proper
  Protocol-based interface, not just "one path variable" as previously written;
  episode creation now exists at the API level via POST /admin/episodes).

## Session 4 — Final README pass
- Reviewed README against the original assignment spec line-by-line rather than just
  re-reading what was already written, to catch omissions rather than typos.
- Found several explicitly-graded items from the original guide that were never
  written down anywhere: index justification (ix_episodes_content_group,
  ix_shows_section_status), why Alembic over create_all(), why artwork is a separate
  table rather than columns on episodes, and an explicit statement of which stretch
  goals (rollback, dry-run diff, audit log) were declined and why.
- Added a dedicated "Ambiguous calls made, and why" section — previously these were
  scattered inside the data-issues table, which undersold them as data bugs rather
  than judgment calls.
- Fixed a real inconsistency: README had CMS and Viewer ports swapped (said CMS:5173,
  Viewer:5174 — actually Viewer came up first on 5173, CMS on 5174 since 5173 was
  taken). Would have sent a grader to the wrong URL for each app.
- Fixed a Windows-breaking command in the Testing section: `STORAGE_PATH=/tmp/storage`
  doesn't work in Git Bash on Windows (no real /tmp path) — same issue hit earlier
  when generating test images. Changed to a relative `./test-storage` path.

## Summary of gaps this session caught between "I thought this was done" and "verified working"
1. docker-compose.yml missing cms/viewer services entirely
2. Both frontend Dockerfiles missing from disk
3. Node 18 incompatible with a newer Vite dependency
4. POST /admin/episodes didn't exist
5. Storage path hardcoded default broke CI
6. .env silently empty/missing breaks Postgres on any fresh clone
7. README understated the storage abstraction and episode-creation status vs actual code