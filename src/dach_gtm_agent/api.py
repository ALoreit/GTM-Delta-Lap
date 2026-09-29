from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .config import Settings
from .db import Database
from .graphs import build_graphs
from .models import Account, Activity, AuditEvent, Contact, ContentIdea, Permission, Signal, Suppression
from .schemas import ContentIdeaRequest, ContentReviewRequest, ContactCreate, InboundSubmission, OutreachTaskRequest, ResearchRequest, ReviewRequest
from .linkedin_import import router as linkedin_import_router


def _thread_config() -> dict[str, Any]:
    return {"configurable": {"thread_id": str(uuid.uuid4())}}


def _contact_identifiers(contact: Contact) -> set[str]:
    result = set()
    if contact.email:
        result.add(contact.email.strip().casefold())
    if contact.phone:
        digits = "".join(c for c in contact.phone if c.isdigit())
        if digits:
            result.add(digits)
    if contact.linkedin_url:
        result.add(contact.linkedin_url.strip().rstrip("/").casefold())
    return result


def _suppress(session, contact: Contact, reason: str) -> None:
    for identifier in _contact_identifiers(contact):
        if session.scalar(select(Suppression.id).where(Suppression.identifier_normalized == identifier)) is None:
            session.add(Suppression(identifier_normalized=identifier, reason=reason))


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = Settings.from_env()
        database = Database(settings.database_url)
        database.create_tables()
        checkpointer_context = None
        entered = False
        checkpointer = None
        try:
            if settings.checkpoint_backend == "postgres":
                from langgraph.checkpoint.postgres import PostgresSaver
                checkpointer_context = PostgresSaver.from_conn_string(settings.checkpoint_database_url)
                checkpointer = checkpointer_context.__enter__()
                entered = True
                checkpointer.setup()
            app.state.database = database
            app.state.settings = settings
            app.state.graphs = build_graphs(database.session_factory, settings, checkpointer)
            yield
        finally:
            if checkpointer_context is not None and entered:
                checkpointer_context.__exit__(None, None, None)
            database.dispose()

    app = FastAPI(title="GTM Delta Lap API", version="0.1.0", lifespan=lifespan)
    extension_origin = os.getenv("CHROME_EXTENSION_ORIGIN", "").strip()
    if extension_origin:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[extension_origin],
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "Idempotency-Key"],
            allow_credentials=False,
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/inbound")
    def inbound(payload: InboundSubmission, request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=160)):
        data = payload.model_dump(mode="json")
        data["idempotency_key"] = idempotency_key or str(uuid.uuid4())
        result = request.app.state.graphs["inbound"].invoke({"submission": data}, config=_thread_config())
        return {key: result.get(key) for key in ("outcome", "lead_id", "account_id", "contact_id", "activity_id", "qualification_score", "qualification_reason")}

    @app.post("/v1/research/accounts")
    def research(payload: ResearchRequest, request: Request):
        result = request.app.state.graphs["research"].invoke({"account": payload.model_dump(mode="json")}, config=_thread_config())
        return {"outcome": result.get("outcome"), "account_id": result.get("account_id"), "review_activity_id": result.get("activity_id"), "score": result.get("score")}

    @app.get("/v1/accounts/{account_id}")
    def get_account(account_id: str, request: Request):
        with request.app.state.database.session_factory() as db:
            account = db.get(Account, account_id)
            if account is None:
                raise HTTPException(404, "Account not found")
            signals = db.scalars(select(Signal).where(Signal.account_id == account_id).order_by(Signal.observed_at.desc())).all()
            return {"id": account.id, "company_name": account.company_name, "domain": account.domain, "industry": account.industry, "employee_count": account.employee_count, "icp_score": account.icp_score, "score_breakdown": account.score_breakdown, "review_status": account.review_status, "signals": [{"id": s.id, "type": s.signal_type, "summary": s.summary, "url": s.evidence_url, "classification": s.classification, "confidence": s.confidence, "observed_at": s.observed_at.isoformat()} for s in signals]}

    @app.post("/v1/accounts/{account_id}/contacts")
    def add_contact(account_id: str, payload: ContactCreate, request: Request):
        data = payload.model_dump()
        with request.app.state.database.session_factory() as db:
            account = db.get(Account, account_id)
            if account is None:
                raise HTTPException(404, "Account not found")
            contact = None
            if data.get("email"):
                contact = db.scalar(select(Contact).where(Contact.account_id == account_id, Contact.email_normalized == data["email"]))
            if contact is None:
                contact = Contact(account_id=account_id, name=data["name"], role=data.get("role"), profile_location=data.get("profile_location"), email=data.get("email"), email_normalized=data.get("email"), phone=data.get("phone"), linkedin_url=data.get("linkedin_url"), source_url=data["source_url"], source_type=data["source_type"], last_verified_at=datetime.now(timezone.utc))
                db.add(contact)
            else:
                contact.name = data["name"]
                contact.role = data.get("role") or contact.role
                contact.profile_location = data.get("profile_location") or contact.profile_location
                contact.phone = data.get("phone") or contact.phone
                contact.linkedin_url = data.get("linkedin_url") or contact.linkedin_url
                contact.source_url = data["source_url"]
                contact.source_type = data["source_type"]
                contact.last_verified_at = datetime.now(timezone.utc)
            db.flush()
            db.add(AuditEvent(event_type="contact_added", entity_type="contact", entity_id=contact.id, payload={"source_type": contact.source_type, "has_email": bool(contact.email)}))
            db.commit()
            return {"contact_id": contact.id, "account_id": contact.account_id, "source_url": contact.source_url}

    @app.post("/v1/outreach/tasks")
    def outreach(payload: OutreachTaskRequest, request: Request):
        result = request.app.state.graphs["outreach"].invoke({"request": payload.model_dump(mode="json")}, config=_thread_config())
        return {"outcome": result.get("outcome"), "activity_id": result.get("activity_id"), "policy": result.get("gate")}

    @app.post("/v1/contacts/{contact_id}/suppress")
    def suppress_contact(contact_id: str, request: Request, reason: str = Query(default="user_opt_out", max_length=200)):
        with request.app.state.database.session_factory() as db:
            contact = db.get(Contact, contact_id)
            if contact is None:
                raise HTTPException(404, "Contact not found")
            _suppress(db, contact, reason)
            db.add(AuditEvent(event_type="contact_suppressed", entity_type="contact", entity_id=contact.id, payload={"reason": reason}))
            db.commit()
            return {"contact_id": contact.id, "status": "suppressed"}

    @app.post("/v1/contacts/{contact_id}/email-consent/revoke")
    def revoke_consent(contact_id: str, request: Request):
        with request.app.state.database.session_factory() as db:
            contact = db.get(Contact, contact_id)
            if contact is None:
                raise HTTPException(404, "Contact not found")
            permissions = db.scalars(select(Permission).where(Permission.contact_id == contact_id, Permission.channel == "email", Permission.purpose == "marketing", Permission.status == "granted", Permission.revoked_at.is_(None))).all()
            for permission in permissions:
                permission.status = "revoked"
                permission.revoked_at = datetime.now(timezone.utc)
            db.add(AuditEvent(event_type="email_marketing_consent_revoked", entity_type="contact", entity_id=contact_id, payload={"records": len(permissions)}))
            db.commit()
            return {"contact_id": contact_id, "status": "email_consent_revoked"}

    @app.get("/v1/review")
    def review_queue(request: Request, status: str = Query(default="pending_review", max_length=32), limit: int = Query(default=100, ge=1, le=500)):
        with request.app.state.database.session_factory() as db:
            items = db.scalars(select(Activity).where(Activity.status == status).order_by(Activity.created_at.asc()).limit(limit)).all()
            return {"items": [{"id": x.id, "account_id": x.account_id, "contact_id": x.contact_id, "lead_id": x.lead_id, "action_type": x.action_type, "channel": x.channel, "task_summary": x.task_summary, "suggested_text": x.suggested_text, "policy_metadata": x.policy_metadata, "requires_legal_review": x.requires_legal_review, "status": x.status, "due_at": x.due_at.isoformat() if x.due_at else None} for x in items]}

    @app.post("/v1/review/{activity_id}")
    def review_activity(activity_id: str, payload: ReviewRequest, request: Request):
        with request.app.state.database.session_factory() as db:
            activity = db.get(Activity, activity_id)
            if activity is None:
                raise HTTPException(404, "Activity not found")
            if activity.status != "pending_review":
                raise HTTPException(409, "Activity is no longer pending review")
            if payload.decision == "do_not_contact" and activity.contact_id is None:
                raise HTTPException(400, "Activity is not associated with a contact")
            activity.status = {"approve": "approved", "edit": "edited", "defer": "deferred", "do_not_contact": "blocked"}[payload.decision]
            if payload.edited_text:
                activity.suggested_text = payload.edited_text
            activity.review_note = payload.note
            if payload.decision == "do_not_contact":
                contact = db.get(Contact, activity.contact_id)
                if contact:
                    _suppress(db, contact, "reviewer_do_not_contact")
            db.add(AuditEvent(event_type="activity_reviewed", entity_type="activity", entity_id=activity.id, payload={"decision": payload.decision}))
            db.commit()
            return {"activity_id": activity.id, "status": activity.status}

    @app.post("/v1/content/ideas")
    def create_content(payload: ContentIdeaRequest, request: Request):
        result = request.app.state.graphs["content"].invoke({"request": payload.model_dump(mode="json")}, config=_thread_config())
        return {"content_id": result["content_id"], "status": "pending_review"}

    @app.get("/v1/content/ideas")
    def content_queue(request: Request, status: str = Query(default="pending_review", max_length=32), limit: int = Query(default=100, ge=1, le=500)):
        with request.app.state.database.session_factory() as db:
            ideas = db.scalars(select(ContentIdea).where(ContentIdea.review_status == status).order_by(ContentIdea.created_at.desc()).limit(limit)).all()
            return {"items": [{"id": x.id, "topic": x.topic, "audience": x.audience, "draft_text": x.draft_text, "source_urls": x.source_urls, "fact_check_status": x.fact_check_status, "review_status": x.review_status} for x in ideas]}

    @app.post("/v1/content/ideas/{content_id}/review")
    def review_content(content_id: str, payload: ContentReviewRequest, request: Request):
        with request.app.state.database.session_factory() as db:
            idea = db.get(ContentIdea, content_id)
            if idea is None:
                raise HTTPException(404, "Content idea not found")
            if idea.review_status != "pending_review":
                raise HTTPException(409, "Content idea is no longer pending review")
            idea.review_status = {"approve": "approved", "edit": "edited", "reject": "rejected"}[payload.decision]
            if payload.edited_text:
                idea.draft_text = payload.edited_text
            if payload.decision == "approve":
                idea.fact_check_status = "human_reviewed"
            idea.review_note = payload.note
            db.add(AuditEvent(event_type="content_reviewed", entity_type="content_idea", entity_id=idea.id, payload={"decision": payload.decision, "published": False}))
            db.commit()
            return {"content_id": idea.id, "status": idea.review_status, "published": False}

    return app


app = create_app()
app.include_router(linkedin_import_router)
