from datetime import datetime
from typing import List, Optional
from sqlalchemy import (
    Column,
    String,
    DateTime,
    ForeignKey,
    CheckConstraint,
    ARRAY,
    Boolean,
    Float,
    Integer,
    SmallInteger,
    Text,
    text as sql_text,
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func
import uuid

from ..database import Base


def generate_uuid_string():
    """Generate a UUID as a string for compatibility with Prisma"""
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid_string
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    emailVerified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    image: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    createdAt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updatedAt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        default=func.now(),
    )

    first_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    notify_on_completion: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("'true'")
    )
    is_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("'false'")
    )
    plan: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=sql_text("'free'")
    )
    subscription_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=sql_text("'inactive'")
    )
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, unique=True
    )
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, unique=True
    )
    billing_period_start: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    billing_period_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trial_ends_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    youtube_credentials: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tiktok_credentials: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    instagram_credentials: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    slack_webhook_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    discord_webhook_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    email_notifications: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("'true'")
    )

    tasks: Mapped[List["Task"]] = relationship(
        "Task", back_populates="user", cascade="all, delete-orphan"
    )


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid_string
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    generated_clips_ids: Mapped[Optional[List[str]]] = mapped_column(
        ARRAY(String(36)), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), server_default=sql_text("'pending'"), nullable=False
    )

    font_family: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, server_default=sql_text("'TikTokSans-Regular'")
    )
    font_size: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, server_default=sql_text("'24'")
    )
    font_color: Mapped[Optional[str]] = mapped_column(
        String(7), nullable=True, server_default=sql_text("'#FFFFFF'")
    )

    caption_template: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, server_default=sql_text("'default'")
    )
    include_broll: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, server_default=sql_text("'false'")
    )
    processing_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=sql_text("'fast'")
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cache_hit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("'false'")
    )
    error_code: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    stage_timings_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    completion_notification_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Phase 10 / 11 Feature flags (per-task opt-in)
    enable_timeline: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("'false'")
    )
    enable_vision_ai: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("'false'")
    )
    enable_timeline_render: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("'false'")
    )

    target_language: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=sql_text("'eng'")
    )
    auto_center_face: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("'true'")
    )
    eye_contact_correction: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("'false'")
    )
    split_screen: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("'false'")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="tasks")
    source: Mapped[Optional["Source"]] = relationship("Source", back_populates="tasks")
    generated_clips: Mapped[List["GeneratedClip"]] = relationship(
        "GeneratedClip", back_populates="task", cascade="all, delete-orphan"
    )


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid_string
    )
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("type IN ('youtube', 'video_url')", name="check_source_type"),
    )

    tasks: Mapped[List["Task"]] = relationship("Task", back_populates="source")

    def decide_source_type(self, source_url: str) -> str:
        if "youtube" in source_url:
            return "youtube"
        return "video_url"


class GeneratedClip(Base):
    __tablename__ = "generated_clips"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid_string,
        server_default=sql_text("gen_random_uuid()::text"),
    )
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    start_time: Mapped[str] = mapped_column(String(20), nullable=False)
    end_time: Mapped[str] = mapped_column(String(20), nullable=False)
    duration: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False)
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    clip_order: Mapped[int] = mapped_column(Integer, nullable=False)

    virality_score: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, server_default=sql_text("'0'")
    )
    hook_score: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, server_default=sql_text("'0'")
    )
    engagement_score: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, server_default=sql_text("'0'")
    )
    value_score: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, server_default=sql_text("'0'")
    )
    shareability_score: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, server_default=sql_text("'0'")
    )
    hook_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    strategic_advice: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    conversion_tips: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_rating: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)

    clip_metadata: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    thumbnail_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    youtube_video_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    tiktok_video_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    instagram_media_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    youtube_views: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, server_default=sql_text("'0'"))
    youtube_likes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, server_default=sql_text("'0'"))
    youtube_comments: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, server_default=sql_text("'0'"))
    youtube_watch_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    youtube_ctr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    youtube_engagement_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    tiktok_views: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, server_default=sql_text("'0'"))
    tiktok_likes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, server_default=sql_text("'0'"))
    tiktok_comments: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, server_default=sql_text("'0'"))
    tiktok_shares: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, server_default=sql_text("'0'"))
    tiktok_completion_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tiktok_engagement_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    instagram_impressions: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, server_default=sql_text("'0'"))
    instagram_reach: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, server_default=sql_text("'0'"))
    instagram_engagement: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, server_default=sql_text("'0'"))
    instagram_likes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, server_default=sql_text("'0'"))
    instagram_comments: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, server_default=sql_text("'0'"))
    instagram_shares: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, server_default=sql_text("'0'"))
    instagram_saves: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, server_default=sql_text("'0'"))
    instagram_engagement_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    metrics_last_updated: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    ab_test_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    ab_variant: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Phase 10: Viral polish flags + A/B variant paths
    cta_overlay_applied: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("'false'")
    )
    emoji_overlays_applied: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("'false'")
    )
    variants_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # JSON list of {path, variant, label, type} dicts from variant_generator

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    task: Mapped["Task"] = relationship("Task", back_populates="generated_clips")


class ProcessingCache(Base):
    __tablename__ = "processing_cache"

    cache_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    video_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transcript_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    analysis_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
