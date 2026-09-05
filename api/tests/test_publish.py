import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.models import Base, Show, Season, Episode, Artwork
from app.publish import _build_catalogue

# Uses the same Postgres instance — tests run against a real DB, not mocks,
# since the constraint-driven logic (collapse, exclusion) is DB-query-based.
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://peblo:peblo_dev_password@localhost:5432/peblo_tv",
)


@pytest.fixture
def session():
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    s = Session()
    # clean slate for this test file's rows only
    s.query(Artwork).delete()
    s.query(Episode).delete()
    s.query(Season).delete()
    s.query(Show).delete()
    s.commit()
    yield s
    s.rollback()
    s.close()


def make_show(session, slug="test-show", status="published", section="series"):
    show = Show(slug=slug, title="Test Show", section=section, status=status)
    session.add(show)
    session.flush()
    return show


def make_season(session, show, number):
    season = Season(show_id=show.id, number=number)
    session.add(season)
    session.flush()
    return season


def make_episode(session, season, content_group, language, status="published", duration=100):
    ep = Episode(
        season_id=season.id, content_group=content_group, language=language,
        title=f"Episode {language}", status=status, duration_seconds=duration,
    )
    session.add(ep)
    session.flush()
    return ep


def test_language_variants_collapse_into_one_entry(session):
    show = make_show(session)
    season = make_season(session, show, number=1)
    make_episode(session, season, content_group="cg-1", language="en")
    make_episode(session, season, content_group="cg-1", language="hi")

    catalogue, show_count, episode_count = _build_catalogue(session)

    entries = catalogue["shows"][0]["seasons"][0]["episodes"]
    assert len(entries) == 1, "language variants should collapse into ONE catalogue entry"
    assert sorted(entries[0]["languages"]) == ["en", "hi"]


def test_season_zero_excluded_from_seasons_list(session):
    show = make_show(session)
    season0 = make_season(session, show, number=0)
    make_episode(session, season0, content_group="trailer-1", language="en")

    catalogue, _, _ = _build_catalogue(session)

    show_entry = catalogue["shows"][0]
    assert show_entry["seasons"] == [], "season 0 must not appear in the seasons list"
    assert len(show_entry["trailers"]) == 1, "season 0 content should appear under trailers"


def test_draft_episodes_excluded_from_publish(session):
    show = make_show(session)
    season = make_season(session, show, number=1)
    make_episode(session, season, content_group="cg-draft", language="en", status="draft")

    catalogue, _, episode_count = _build_catalogue(session)

    show_entry = catalogue["shows"][0]
    all_episodes = [e for s in show_entry["seasons"] for e in s["episodes"]]
    assert len(all_episodes) == 0, "draft episodes must not appear in the published catalogue"


def test_unpublished_show_excluded_entirely(session):
    make_show(session, slug="draft-show", status="draft")

    catalogue, show_count, _ = _build_catalogue(session)

    assert show_count == 0
    assert catalogue["shows"] == []


def test_canonical_row_prefers_english(session):
    show = make_show(session)
    season = make_season(session, show, number=1)
    make_episode(session, season, content_group="cg-1", language="hi")
    make_episode(session, season, content_group="cg-1", language="en")

    catalogue, _, _ = _build_catalogue(session)

    entry = catalogue["shows"][0]["seasons"][0]["episodes"][0]
    assert entry["title"] == "Episode en", "canonical row should prefer English when both languages present"