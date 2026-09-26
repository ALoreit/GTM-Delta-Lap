from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_name: Mapped[str] = mapped_column(String(250), nullable=False)
    domain: Mapped[str] = mapped_column(String(253), unique=True, index=True, nullable=False)
    country: Mapped[str] = mapped_column(String(8), default="DACH", nullable=False)
    industry: Mapped[str | None] = mapped_column(String(160))
    employee_count: Mapped[int | None] = mapped_column(Integer)
    icp_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    score_breakdown: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    review_status: Mapped[str] = mapped_column(String(32), default="needs_review", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("account_id", "email_normalized", name="uq_contact_account_email"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    email_normalized: Mapped[str | None] = mapped_column(String(320), index=True)
    phone: Mapped[str | None] = mapped_column(String(80))
    linkedin_url: Mapped[str | None] = mapped_column(String(500))
    source_url: Mapped[str | None] = mapped_column(String(2000))
    source_type: Mapped[str] = mapped_column(String(40), default="inbound_form", nullable=False)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True, nullable=False)
    signal_type: Mapped[str] = mapped_column(String(80), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_url: Mapped[str | None] = mapped_column(String(2000))
    source_type: Mapped[str] = mapped_column(String(40), default="team_provided", nullable=False)
    classification: Mapped[str] = mapped_column(String(16), default="fact", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    contact_id: Mapped[str] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True, nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    purpose: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    consent_source: Mapped[str] = mapped_column(String(200), nullable=False)
    consent_text_version: Mapped[str] = mapped_column(String(80), nullable=False)
    consent_text: Mapped[str] = mapped_column(Text, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, index=True, nullable=False)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True, nullable=False)
    contact_id: Mapped[str] = mapped_column(ForeignKey("contacts.id"), index=True, nullable=False)
    request_summary: Mapped[str] = mapped_column(Text, nullable=False)
    qualification_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    qualification_reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="needs_review", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), index=True)
    contact_id: Mapped[str | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"), index=True)
    lead_id: Mapped[str | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"), index=True)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), default="internal", nullable=False)
    task_summary: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_text: Mapped[str | None] = mapped_column(Text)
    policy_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending_review", index=True, nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)
    requires_legal_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class Suppression(Base):
    __tablename__ = "suppression"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    identifier_normalized: Mapped[str] = mapped_column(String(600), unique=True, index=True, nullable=False)
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ContentIdea(Base):
    __tablename__ = "content_ideas"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    topic: Mapped[str] = mapped_column(String(300), nullable=False)
    audience: Mapped[str] = mapped_column(String(300), nullable=False)
    takeaway: Mapped[str] = mapped_column(Text, nullable=False)
    discussion_question: Mapped[str] = mapped_column(Text, nullable=False)
    source_urls: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    draft_text: Mapped[str] = mapped_column(Text, nullable=False)
    fact_check_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    review_status: Mapped[str] = mapped_column(String(32), default="pending_review", index=True, nullable=False)
    review_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_type: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
