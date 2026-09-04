import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, ForeignKey,
    UniqueConstraint, Index, ARRAY, Text
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Show(Base):
    __tablename__ = "shows"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug = Column(String, unique=True, nullable=False)
    title = Column(String, nullable=False)
    synopsis = Column(Text)
    section = Column(String, nullable=True)  # nullable: drafts may not have one yet
    status = Column(String, nullable=False, default="draft")  # draft/published
    created_at = Column(DateTime, default=datetime.utcnow)

    seasons = relationship("Season", back_populates="show", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_shows_section_status", "section", "status"),
    )


class Season(Base):
    __tablename__ = "seasons"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    show_id = Column(UUID(as_uuid=True), ForeignKey("shows.id"), nullable=False)
    number = Column(Integer, nullable=False)  # 0 reserved for trailers

    show = relationship("Show", back_populates="seasons")
    episodes = relationship("Episode", back_populates="season", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("show_id", "number", name="uq_season_show_number"),
    )


class Episode(Base):
    __tablename__ = "episodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    season_id = Column(UUID(as_uuid=True), ForeignKey("seasons.id"), nullable=False)
    content_group = Column(String, nullable=False)
    language = Column(String, nullable=False)
    title = Column(String, nullable=False)
    duration_seconds = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="draft")  # draft/published
    categories = Column(ARRAY(String), default=list)

    season = relationship("Season", back_populates="episodes")
    artwork = relationship("Artwork", back_populates="episode", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("content_group", "language", name="uq_episode_content_group_language"),
        Index("ix_episodes_content_group", "content_group"),
    )


class Artwork(Base):
    __tablename__ = "artwork"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    episode_id = Column(UUID(as_uuid=True), ForeignKey("episodes.id"), nullable=False)
    type = Column(String, nullable=False)  # poster / banner / thumbnail
    storage_key = Column(String, nullable=False)
    width = Column(Integer)
    height = Column(Integer)
    file_size_bytes = Column(Integer)

    episode = relationship("Episode", back_populates="artwork")

    __table_args__ = (
        UniqueConstraint("episode_id", "type", name="uq_artwork_episode_type"),
    )


class PublishRun(Base):
    __tablename__ = "publish_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    triggered_by = Column(String, nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String, nullable=False, default="started")  # started/success/failed
    show_count = Column(Integer, default=0)
    episode_count = Column(Integer, default=0)
    error_detail = Column(Text, nullable=True)