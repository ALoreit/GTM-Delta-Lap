from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from .config import Settings
from .db import Database
from .models import Account, Activity, AuditEvent, Contact, ContactNote, ContentIdea, Permission, PlannedAction, Signal, Suppression
from .schemas import ContentIdeaRequest, ContentReviewRequest, ContactCreate, ContactNoteCreate, ContactUpdate, InboundSubmission, OutreachTaskRequest, PlannedActionCreate, ResearchRequest, ReviewRequest
from .linkedin_import import router as linkedin_import_router
from .services import create_content_idea, create_outreach_task, qualify_inbound, research_account


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


def _agent_contact_details(contact: Contact, account: Account, notes: list[ContactNote], actions: list[PlannedAction]) -> dict[str, Any]:
    """Serialize contact context for agents without exposing direct contact data."""
    return {
        "id": contact.id,
        "name": contact.name,
        "role": contact.role,
        "location": contact.profile_location,
        "linkedin_url": contact.linkedin_url,
        "linkedin_connected": contact.linkedin_connected,
        "source_url": contact.source_url,
        "source_type": contact.source_type,
        "last_verified_at": contact.last_verified_at.isoformat() if contact.last_verified_at else None,
        "created_at": contact.created_at.isoformat(),
        "company": {
            "id": account.id,
            "name": account.company_name,
            "domain": account.domain,
            "industry": account.industry,
            "employee_count": account.employee_count,
            "country": account.country,
            "icp_score": account.icp_score,
            "review_status": account.review_status,
        },
        "notes": [{"id": note.id, "body": note.body, "created_at": note.created_at.isoformat()} for note in notes],
        "actions": [
            {
                "id": action.id,
                "title": action.title,
                "details": action.details,
                "due_at": action.due_at.isoformat() if action.due_at else None,
                "status": action.status,
            }
            for action in actions
        ],
    }


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = Settings.from_env()
        database = Database(settings.database_url)
        database.create_tables()
        try:
            app.state.database = database
            app.state.settings = settings
            yield
        finally:
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
        result = qualify_inbound(request.app.state.database.session_factory, data)
        return {key: result.get(key) for key in ("outcome", "lead_id", "account_id", "contact_id", "activity_id", "qualification_score", "qualification_reason")}

    @app.post("/v1/research/accounts")
    def research(payload: ResearchRequest, request: Request):
        result = research_account(request.app.state.database.session_factory, request.app.state.settings, payload.model_dump(mode="json"))
        return {"outcome": result.get("outcome"), "account_id": result.get("account_id"), "review_activity_id": result.get("activity_id"), "score": result.get("score")}

    @app.get("/v1/accounts/{account_id}")
    def get_account(account_id: str, request: Request):
        with request.app.state.database.session_factory() as db:
            account = db.get(Account, account_id)
            if account is None:
                raise HTTPException(404, "Account not found")
            signals = db.scalars(select(Signal).where(Signal.account_id == account_id).order_by(Signal.observed_at.desc())).all()
            return {"id": account.id, "company_name": account.company_name, "domain": account.domain, "industry": account.industry, "employee_count": account.employee_count, "icp_score": account.icp_score, "score_breakdown": account.score_breakdown, "review_status": account.review_status, "signals": [{"id": s.id, "type": s.signal_type, "summary": s.summary, "url": s.evidence_url, "classification": s.classification, "confidence": s.confidence, "observed_at": s.observed_at.isoformat()} for s in signals]}

    @app.get("/v1/contacts")
    def list_contacts(
        request: Request,
        search: str | None = Query(default=None, max_length=200),
        company_filter: str | None = Query(default=None, max_length=200),
        name_filter: str | None = Query(default=None, max_length=200),
        role_filter: str | None = Query(default=None, max_length=200),
        linkedin_connected: bool | None = Query(default=None),
        added_from: datetime | None = Query(default=None),
        added_to: datetime | None = Query(default=None),
        sort_by: str = Query(default="company", alias="sort"),
        direction: str = Query(default="asc"),
        limit: int = Query(default=500, ge=1, le=1000),
    ):
        sort_columns = {
            "company": Account.company_name,
            "name": Contact.name,
            "added": Contact.created_at,
        }
        if sort_by not in sort_columns:
            raise HTTPException(400, "sort must be one of: company, name, added")
        if direction not in {"asc", "desc"}:
            raise HTTPException(400, "direction must be 'asc' or 'desc'")
        with request.app.state.database.session_factory() as db:
            query = select(Contact, Account).join(Account, Contact.account_id == Account.id)
            if search:
                term = f"%{search.strip()}%"
                query = query.where(
                    Contact.name.ilike(term)
                    | Contact.role.ilike(term)
                    | Account.company_name.ilike(term)
                )
            if company_filter and company_filter.strip():
                query = query.where(Account.company_name.ilike(f"%{company_filter.strip()}%"))
            if name_filter and name_filter.strip():
                query = query.where(Contact.name.ilike(f"%{name_filter.strip()}%"))
            if role_filter and role_filter.strip():
                query = query.where(Contact.role.ilike(f"%{role_filter.strip()}%"))
            if linkedin_connected is not None:
                query = query.where(Contact.linkedin_connected == linkedin_connected)
            if added_from is not None:
                query = query.where(Contact.created_at >= added_from)
            if added_to is not None:
                query = query.where(Contact.created_at < added_to)
            sort_column = sort_columns[sort_by]
            order = sort_column.asc() if direction == "asc" else sort_column.desc()
            rows = db.execute(query.order_by(order, Contact.id.asc()).limit(limit)).all()
            return {"items": [{"id": contact.id, "name": contact.name, "company_name": account.company_name, "account_id": account.id, "role": contact.role, "linkedin_connected": contact.linkedin_connected, "created_at": contact.created_at.isoformat()} for contact, account in rows]}

    @app.get("/v1/contacts/{contact_id}")
    def get_contact(contact_id: str, request: Request):
        with request.app.state.database.session_factory() as db:
            row = db.execute(select(Contact, Account).join(Account, Contact.account_id == Account.id).where(Contact.id == contact_id)).first()
            if row is None:
                raise HTTPException(404, "Contact not found")
            contact, account = row
            notes = db.scalars(select(ContactNote).where(ContactNote.contact_id == contact_id).order_by(ContactNote.created_at.desc())).all()
            actions = db.scalars(select(PlannedAction).where(PlannedAction.contact_id == contact_id).order_by(PlannedAction.due_at.asc(), PlannedAction.created_at.desc())).all()
            return {
                "id": contact.id,
                "name": contact.name,
                "role": contact.role,
                "location": contact.profile_location,
                "email": contact.email,
                "phone": contact.phone,
                "linkedin_url": contact.linkedin_url,
                "linkedin_connected": contact.linkedin_connected,
                "source_url": contact.source_url,
                "source_type": contact.source_type,
                "last_verified_at": contact.last_verified_at.isoformat() if contact.last_verified_at else None,
                "created_at": contact.created_at.isoformat(),
                "company": {
                    "id": account.id,
                    "name": account.company_name,
                    "domain": account.domain,
                    "industry": account.industry,
                    "employee_count": account.employee_count,
                    "country": account.country,
                    "icp_score": account.icp_score,
                    "review_status": account.review_status,
                },
                "notes": [{"id": note.id, "body": note.body, "created_at": note.created_at.isoformat()} for note in notes],
                "actions": [{"id": action.id, "title": action.title, "details": action.details, "due_at": action.due_at.isoformat() if action.due_at else None, "status": action.status} for action in actions],
            }

    @app.get("/v1/agent/contacts")
    def agent_list_contacts(
        request: Request,
        linkedin_connected: bool | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
    ):
        """Return the minimal contact list contract intended for agent integrations."""
        with request.app.state.database.session_factory() as db:
            query = select(Contact, Account).join(Account, Contact.account_id == Account.id)
            if linkedin_connected is not None:
                query = query.where(Contact.linkedin_connected == linkedin_connected)
            rows = db.execute(
                query.order_by(Account.company_name.asc(), Contact.name.asc(), Contact.id.asc()).limit(limit)
            ).all()
            return {
                "items": [
                    {
                        "id": contact.id,
                        "name": contact.name,
                        "company_name": account.company_name,
                        "linkedin_connected": contact.linkedin_connected,
                    }
                    for contact, account in rows
                ]
            }

    @app.get("/v1/agent/contacts/{contact_name}")
    def agent_get_contact(contact_name: str, request: Request):
        """Return non-direct-contact context for one uniquely named contact."""
        normalized_name = contact_name.strip().casefold()
        if not normalized_name:
            raise HTTPException(400, "Contact name must not be empty")
        with request.app.state.database.session_factory() as db:
            rows = db.execute(
                select(Contact, Account)
                .join(Account, Contact.account_id == Account.id)
                .where(func.lower(Contact.name) == normalized_name)
            ).all()
            if not rows:
                raise HTTPException(404, "Contact not found")
            if len(rows) > 1:
                raise HTTPException(409, "Contact name is not unique; use the contact ID")
            contact, account = rows[0]
            notes = db.scalars(
                select(ContactNote)
                .where(ContactNote.contact_id == contact.id)
                .order_by(ContactNote.created_at.desc())
            ).all()
            actions = db.scalars(
                select(PlannedAction)
                .where(PlannedAction.contact_id == contact.id)
                .order_by(PlannedAction.due_at.asc(), PlannedAction.created_at.desc())
            ).all()
            return _agent_contact_details(contact, account, notes, actions)

    @app.patch("/v1/contacts/{contact_id}/linkedin-connected")
    def set_linkedin_connected(contact_id: str, request: Request, connected: bool = Query(...)):
        with request.app.state.database.session_factory() as db:
            contact = db.get(Contact, contact_id)
            if contact is None:
                raise HTTPException(404, "Contact not found")
            contact.linkedin_connected = connected
            db.add(AuditEvent(event_type="contact_linkedin_connection_updated", entity_type="contact", entity_id=contact.id, payload={"connected": connected}))
            db.commit()
            return {"contact_id": contact.id, "linkedin_connected": contact.linkedin_connected}

    @app.post("/v1/contacts/{contact_id}/notes")
    def add_contact_note(contact_id: str, payload: ContactNoteCreate, request: Request):
        with request.app.state.database.session_factory() as db:
            if db.get(Contact, contact_id) is None:
                raise HTTPException(404, "Contact not found")
            note = ContactNote(contact_id=contact_id, body=payload.body)
            db.add(note)
            db.commit()
            return {"id": note.id, "body": note.body, "created_at": note.created_at.isoformat()}

    @app.patch("/v1/contacts/{contact_id}")
    def update_contact(contact_id: str, payload: ContactUpdate, request: Request):
        data = payload.model_dump()
        with request.app.state.database.session_factory() as db:
            contact = db.get(Contact, contact_id)
            if contact is None:
                raise HTTPException(404, "Contact not found")
            account = db.get(Account, contact.account_id)
            if account is None:
                raise HTTPException(404, "Account not found")
            contact.name = data["name"]
            contact.role = data["role"]
            contact.profile_location = data["profile_location"]
            contact.email = data["email"]
            contact.email_normalized = data["email"]
            contact.phone = data["phone"]
            contact.linkedin_url = data["linkedin_url"]
            contact.linkedin_connected = data["linkedin_connected"]
            account_changed = any((
                account.company_name != data["company_name"],
                account.domain != data["domain"],
                account.industry != data["industry"],
                account.employee_count != data["employee_count"],
                account.country != data["country"],
            ))
            if account_changed:
                target_account = db.scalar(select(Account).where(Account.domain == data["domain"], Account.id != account.id))
                if target_account is None and account.domain == data["domain"]:
                    raise HTTPException(409, "Change the company domain or LinkedIn company URL to move only this contact to a separate account")
                if target_account is None:
                    target_account = Account(
                        company_name=data["company_name"],
                        domain=data["domain"],
                        country=data["country"],
                        industry=data["industry"],
                        employee_count=data["employee_count"],
                    )
                    db.add(target_account)
                    db.flush()
                contact.account_id = target_account.id
            db.add(AuditEvent(event_type="contact_updated", entity_type="contact", entity_id=contact.id, payload={"account_id": contact.account_id}))
            db.commit()
            return {"contact_id": contact.id, "account_id": contact.account_id}

    @app.post("/v1/contacts/{contact_id}/actions")
    def add_planned_action(contact_id: str, payload: PlannedActionCreate, request: Request):
        with request.app.state.database.session_factory() as db:
            if db.get(Contact, contact_id) is None:
                raise HTTPException(404, "Contact not found")
            action = PlannedAction(contact_id=contact_id, title=payload.title, details=payload.details, due_at=payload.due_at)
            db.add(action)
            db.commit()
            return {"id": action.id, "title": action.title, "details": action.details, "due_at": action.due_at.isoformat() if action.due_at else None, "status": action.status}

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
                contact = Contact(account_id=account_id, name=data["name"], role=data.get("role"), profile_location=data.get("profile_location"), email=data.get("email"), email_normalized=data.get("email"), phone=data.get("phone"), linkedin_url=data.get("linkedin_url"), linkedin_connected=data.get("linkedin_connected", False), source_url=data["source_url"], source_type=data["source_type"], last_verified_at=datetime.now(timezone.utc))
                db.add(contact)
            else:
                contact.name = data["name"]
                contact.role = data.get("role") or contact.role
                contact.profile_location = data.get("profile_location") or contact.profile_location
                contact.phone = data.get("phone") or contact.phone
                contact.linkedin_url = data.get("linkedin_url") or contact.linkedin_url
                contact.linkedin_connected = data.get("linkedin_connected", contact.linkedin_connected)
                contact.source_url = data["source_url"]
                contact.source_type = data["source_type"]
                contact.last_verified_at = datetime.now(timezone.utc)
            db.flush()
            db.add(AuditEvent(event_type="contact_added", entity_type="contact", entity_id=contact.id, payload={"source_type": contact.source_type, "has_email": bool(contact.email)}))
            db.commit()
            return {"contact_id": contact.id, "account_id": contact.account_id, "source_url": contact.source_url}

    @app.post("/v1/outreach/tasks")
    def outreach(payload: OutreachTaskRequest, request: Request):
        result = create_outreach_task(request.app.state.database.session_factory, payload.model_dump(mode="json"))
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
        result = create_content_idea(request.app.state.database.session_factory, payload.model_dump(mode="json"))
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

    web_dir = Path(__file__).with_name("web")

    @app.get("/", include_in_schema=False)
    def frontend() -> FileResponse:
        return FileResponse(web_dir / "index.html")

    app.mount("/static", StaticFiles(directory=web_dir), name="static")
    return app


app = create_app()
app.include_router(linkedin_import_router)
