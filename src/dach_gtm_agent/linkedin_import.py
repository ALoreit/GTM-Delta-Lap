from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from .models import Account, AuditEvent, Contact
from .schemas import EvidenceSignal, ResearchRequest

router = APIRouter()


class LinkedInVisibleProfileImport(BaseModel):
    company_name: str = Field(min_length=1, max_length=250)
    domain: str = Field(min_length=3, max_length=253)
    country: str = Field(default="DACH", min_length=2, max_length=8)
    industry: str | None = Field(default=None, max_length=160)
    employee_count: int | None = Field(default=None, ge=0, le=10_000_000)
    name: str = Field(min_length=1, max_length=200)
    role: str | None = Field(default=None, max_length=200)
    profile_location: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=80)
    linkedin_url: str = Field(min_length=8, max_length=500)

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        parsed = urlsplit(value.strip() if "://" in value else f"//{value.strip()}")
        if not parsed.hostname or "." not in parsed.hostname:
            raise ValueError("domain must contain a host name")
        return parsed.hostname.casefold().removeprefix("www.")

    @field_validator("linkedin_url")
    @classmethod
    def validate_linkedin_profile(cls, value: str) -> str:
        parsed = urlsplit(value)
        hostname = (parsed.hostname or "").casefold()
        if parsed.scheme not in {"http", "https"} or not (
            hostname == "linkedin.com" or hostname.endswith(".linkedin.com")
        ) or not parsed.path.startswith("/in/"):
            raise ValueError("linkedin_url must be an individual LinkedIn profile URL")
        return value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip().casefold()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", normalized):
            raise ValueError("email must be a valid email address")
        return normalized

    @field_validator("name", "company_name", "role", "profile_location", "phone", "industry")
    @classmethod
    def trim_text(cls, value: str | None) -> str | None:
        return value.strip() if value else value


@router.post("/v1/import/linkedin-visible-profile")
def import_visible_profile(payload: LinkedInVisibleProfileImport, request: Request):
    """Persist user-reviewed profile fields and run the existing account research graph."""
    account_request = ResearchRequest(
        company_name=payload.company_name,
        domain=payload.domain,
        country=payload.country,
        industry=payload.industry,
        employee_count=payload.employee_count,
        signals=[EvidenceSignal(
            signal_type="linkedin_visible_profile",
            summary=f"Profile import reviewed by user for {payload.name} ({payload.role or 'role not supplied'}).",
            evidence_url=payload.linkedin_url,
            source_type="manual_link",
            classification="fact",
            confidence=0.7,
            observed_at=datetime.now(timezone.utc),
        )],
    )
    scored = request.app.state.graphs["research"].invoke(
        {"account": account_request.model_dump(mode="json")},
        config={"configurable": {"thread_id": f"linkedin-import-{payload.linkedin_url.rsplit('/', 1)[-1]}"}},
    )
    account_id = scored.get("account_id")
    if not account_id:
        raise HTTPException(500, "Account research graph did not return an account")

    now = datetime.now(timezone.utc)
    with request.app.state.database.session_factory() as db:
        account = db.get(Account, account_id)
        if account is None:
            raise HTTPException(404, "Account not found after research")

        linkedin_url_normalized = payload.linkedin_url.strip().rstrip("/").casefold()
        contact = db.scalar(
            select(Contact).where(
                Contact.account_id == account_id,
                Contact.linkedin_url == linkedin_url_normalized,
            )
        )
        if contact is None and payload.email:
            contact = db.scalar(
                select(Contact).where(
                    Contact.account_id == account_id,
                    Contact.email_normalized == payload.email,
                )
            )

        if contact is None:
            contact = Contact(
                account_id=account_id,
                name=payload.name,
                role=payload.role,
                profile_location=payload.profile_location,
                email=payload.email,
                email_normalized=payload.email,
                phone=payload.phone,
                linkedin_url=linkedin_url_normalized,
                source_url=payload.linkedin_url,
                source_type="linkedin_visible_profile",
                last_verified_at=now,
            )
            db.add(contact)
        else:
            contact.name = payload.name
            contact.role = payload.role or contact.role
            contact.profile_location = payload.profile_location or contact.profile_location
            if payload.email:
                contact.email = payload.email
                contact.email_normalized = payload.email
            contact.phone = payload.phone or contact.phone
            contact.linkedin_url = linkedin_url_normalized
            contact.source_url = payload.linkedin_url
            contact.source_type = "linkedin_visible_profile"
            contact.last_verified_at = now

        db.flush()
        db.add(AuditEvent(
            event_type="linkedin_visible_profile_imported",
            entity_type="contact",
            entity_id=contact.id,
            payload={
                "source_type": "linkedin_visible_profile",
                "profile_url": payload.linkedin_url,
                "fields_present": {
                    "role": bool(payload.role),
                    "location": bool(payload.profile_location),
                    "email": bool(payload.email),
                    "phone": bool(payload.phone),
                },
                "user_confirmed": True,
            },
        ))
        db.commit()
        return {
            "outcome": "needs_review",
            "account_id": account_id,
            "contact_id": contact.id,
            "score": scored.get("score"),
            "review_activity_id": scored.get("activity_id"),
            "source_url": payload.linkedin_url,
        }
