# Friday 9:33Pm

## Session 1 — Day 0 setup + data exploration + schema
- Started: [fill in actual start time]
- Set up repo skeleton: api/, cms/, viewer/, docker-compose.yml, .env.example
- Fixed PowerShell vs Git Bash heredoc issue — switched to Git Bash for the rest of the project
- Got docker-compose up bringing up Postgres + FastAPI /health check
  - Hit .env being empty after a failed `cp` — recreated it directly with a heredoc
  - Fixed a healthcheck false-positive (pg_isready needs -d flag matching POSTGRES_DB, not just -U)
- Connected the repo to GitHub Desktop (had to manually "Add local repository" — it doesn't auto-detect)
- Read reference.json — confirmed real spec values (NOT the placeholder examples used early on):
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
- Stopped at: [fill in actual end time]

## Session 2 — Seed script + publish job
- Started: [fill in actual start time]
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
  running the publish job locally via `python3` silently wrote nowhere findable, while
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
- Stopped at: [fill in actual end time]

## Open items / things to flag in README
- AI tools used: Claude, for scaffolding schema/migration/seed/publish code — rewrote/debugged
  the seed script's transaction handling myself after finding the savepoint bug
- Cut so far: no tests written yet (planned: publish job collapse logic, artwork validation,
  role enforcement — none built yet)
- Judgment calls made: canonical-language-row selection (English-first), show status derived
  as "published if any episode is published", artwork requirement relaxed for season-0 trailers
- Known gap: local vs Docker STORAGE_PATH mismatch fails silently — needs either a .env.local
  or an explicit runbook note about overriding it for local runs
# Stoppin at 12:33 Am Saturday
