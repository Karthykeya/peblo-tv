# Data exploration findings — seed_shows.json

## Structure
Flat list of 95 episode objects. Each record mixes show-level fields (show_title,
slug, section, synopsis) and episode-level fields (episode_number, episode_title,
duration_seconds, language, content_group, artwork_available) on the same object.
Shows are derived by grouping on `slug` during seeding — there is no separate
shows/seasons array in the source file.

## content_group language-variant example
content_group: motis-many-lives-s01e01
- ep_0001: language=en, "The Lost Kite", 510s
- ep_0002: language=hi, "The Lost Kite", 480s
Same content_group, different language + duration (dub runtime differs).
Must collapse into ONE catalogue entry: languages: [en, hi].

## Season 0 example
ep_0093: season_number=0, episode_title="Trailer", content_group=motis-many-lives-s00e01,
artwork_available=[thumbnail] only. Trailers apparently only require thumbnail,
not the full poster/banner/thumbnail set — validation should account for this
when checking "published episodes must have all artwork."

## Planted bad data found
1. TRUE DUPLICATE (content_group, language) pair — should trip the unique
   constraint / 409 on write:
   - ep_0004: content_group=motis-many-lives-s01e02, language=hi, "Rain on the Roof", 660s
   - ep_9001: content_group=motis-many-lives-s01e02, language=hi, "The Lost Kite (v2)", 660s
   Same content_group + language, different titles. This is the case the
   (content_group, language) unique constraint exists to catch.

2. PUBLISHED EPISODE MISSING ARTWORK:
   - ep_0036 ("Discover India with Moti", S1E4 "The Midnight Market")
     status=published, artwork_available=[] (empty)
   Should block publish per validation rules (published requires full artwork set).

3. NULL SECTION on a whole show:
   - ep_0085 through ep_0092 (8 episodes, show "Rhyme Rangers")
     all have section=null, status=draft
   Likely intentional (drafts don't need section yet) rather than a bug, but
   flagged in README as an ambiguous case either way.

4. No invalid section/language/category enum values found elsewhere.
   No missing/zero durations elsewhere.
