from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _validate_http_url(value: str | None) -> str | None:
    if value is None:
        return value
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("URL must be an absolute http(s) URL")
    return value


class InboundSubmission(BaseModel):
    company_name: str = Field(min_length=1, max_length=250)
    company_domain: str = Field(min_length=3, max_length=253)
    country: str = Field(default="DACH", min_length=2, max_length=8)
    industry: str | None = Field(default=None, max_length=160)
    contact_name: str = Field(min_length=1, max_length=200)
    contact_email: str = Field(min_length=3, max_length=320)
    contact_role: str | None = Field(default=None, max_length=200)
    request_text: str = Field(min_length=1, max_length=10000)
    form_source: str = Field(default="website_form", max_length=200)
    marketing_consent: bool = False
    consent_wording_version: str | None = Field(default=None, max_length=80)
    consent_text: str | None = Field(default=None, max_length=4000)
    consent_captured_at: datetime | None = None

    @field_validator("contact_email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", normalized):
            raise ValueError("contact_email must be a valid email address")
        return normalized

    @field_validator("company_domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        value = value.strip()
        parsed = urlsplit(value if "://" in value else f"//{value}")
        if not parsed.hostname or "." not in parsed.hostname:
            raise ValueError("company_domain must contain a host name")
        return value

    @model_validator(mode="after")
    def consent_must_be_evidenced(self) -> "InboundSubmission":
        if self.marketing_consent and not (
            self.consent_wording_version and self.consent_text and self.consent_captured_at
        ):
            raise ValueError(
                "marketing consent requires wording version, exact text, and capture timestamp"
            )
        return self


class EvidenceSignal(BaseModel):
    signal_type: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=3000)
    evidence_url: str | None = Field(default=None, max_length=2000)
    source_type: Literal["public_web", "team_provided", "authorized_provider", "manual_link"] = "team_provided"
    classification: Literal["fact", "inference"] = "fact"
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    observed_at: datetime = Field(default_factory=now_utc)

    @field_validator("evidence_url")
    @classmethod
    def validate_evidence_url(cls, value: str | None) -> str | None:
        return _validate_http_url(value)


class ResearchRequest(BaseModel):
    company_name: str = Field(min_length=1, max_length=250)
    domain: str = Field(min_length=3, max_length=253)
    country: str = Field(default="DACH", min_length=2, max_length=8)
    industry: str | None = Field(default=None, max_length=160)
    employee_count: int | None = Field(default=None, ge=0, le=10_000_000)
    signals: list[EvidenceSignal] = Field(default_factory=list, max_length=100)

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        parsed = urlsplit(value.strip() if "://" in value else f"//{value.strip()}")
        if not parsed.hostname or "." not in parsed.hostname:
            raise ValueError("domain must contain a host name")
        return value.strip()


class ContactCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    role: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=80)
    linkedin_url: str | None = Field(default=None, max_length=500)
    source_url: str = Field(min_length=8, max_length=2000)
    source_type: Literal["public_web", "team_provided", "authorized_provider", "manual_link"] = "team_provided"

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip().casefold()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", normalized):
            raise ValueError("email must be a valid email address")
        return normalized

    @field_validator("source_url", "linkedin_url")
    @classmethod
    def validate_urls(cls, value: str | None) -> str | None:
        return _validate_http_url(value)

    @model_validator(mode="after")
    def has_contact_method(self) -> "ContactCreate":
        if not any((self.email, self.phone, self.linkedin_url)):
            raise ValueError("provide at least one contact method")
        return self


class OutreachTaskRequest(BaseModel):
    contact_id: str = Field(min_length=1, max_length=36)
    channel: Literal["email", "phone", "linkedin"]
    reason: str = Field(min_length=10, max_length=3000)
    evidence_url: str = Field(min_length=8, max_length=2000)
    suggested_text: str | None = Field(default=None, max_length=5000)
    due_at: datetime | None = None

    @field_validator("evidence_url")
    @classmethod
    def validate_evidence_url(cls, value: str) -> str:
        return _validate_http_url(value) or value


class ContentIdeaRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=300)
    audience: str = Field(min_length=2, max_length=300)
    takeaway: str = Field(min_length=10, max_length=3000)
    discussion_question: str = Field(min_length=5, max_length=1000)
    source_urls: list[str] = Field(min_length=1, max_length=30)

    @field_validator("source_urls")
    @classmethod
    def validate_source_urls(cls, values: list[str]) -> list[str]:
        return [_validate_http_url(value) or value for value in values]


class ReviewRequest(BaseModel):
    decision: Literal["approve", "edit", "defer", "do_not_contact"]
    note: str | None = Field(default=None, max_length=3000)
    edited_text: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def edit_requires_text(self) -> "ReviewRequest":
        if self.decision == "edit" and not self.edited_text:
            raise ValueError("edited_text is required when decision='edit'")
        return self


class ContentReviewRequest(BaseModel):
    decision: Literal["approve", "edit", "reject"]
    note: str | None = Field(default=None, max_length=3000)
    edited_text: str | None = Field(default=None, max_length=10000)

    @model_validator(mode="after")
    def edit_requires_text(self) -> "ContentReviewRequest":
        if self.decision == "edit" and not self.edited_text:
            raise ValueError("edited_text is required when decision='edit'")
        return self
