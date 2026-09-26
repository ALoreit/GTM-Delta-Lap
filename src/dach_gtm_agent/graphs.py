from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, TypedDict
from urllib.parse import urlsplit

from langgraph.graph import END, START, StateGraph
try:
    from langgraph.checkpoint.memory import InMemorySaver
except ImportError:  # LangGraph versions before the InMemorySaver alias
    from langgraph.checkpoint.memory import MemorySaver as InMemorySaver
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from .config import Settings
from .models import Account, Activity, AuditEvent, Contact, ContentIdea, Lead, Permission, Signal, Suppression, utcnow
from .policy import evaluate_outreach_policy
from .scoring import score_account


class InboundState(TypedDict, total=False):
    submission: dict[str, Any]
    lead_id: str
    contact_id: str
    account_id: str
    activity_id: str
    outcome: str
    qualification_score: int
    qualification_reason: str


class ResearchState(TypedDict, total=False):
    account: dict[str, Any]
    score: dict[str, Any]
    account_id: str
    activity_id: str
    outcome: str


class OutreachState(TypedDict, total=False):
    request: dict[str, Any]
    gate: dict[str, Any]
    activity_id: str
    outcome: str


class ContentState(TypedDict, total=False):
    request: dict[str, Any]
    draft_text: str
    content_id: str


def _domain(value: str) -> str:
    value = value.strip()
    parsed = urlsplit(value if "://" in value else f"//{value}")
    host = (parsed.hostname or "").casefold().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result


def _ids(contact: Contact) -> set[str]:
    values = set()
    if contact.email:
        values.add(contact.email.strip().casefold())
    if contact.phone:
        digits = re.sub(r"\D", "", contact.phone)
        if digits:
            values.add(digits)
    if contact.linkedin_url:
        values.add(contact.linkedin_url.strip().rstrip("/").casefold())
    return values


def _audit(session, event: str, kind: str, entity_id: str, payload: dict[str, Any]) -> None:
    session.add(AuditEvent(event_type=event, entity_type=kind, entity_id=entity_id, payload=payload))


def build_graphs(session_factory: sessionmaker, settings: Settings, checkpointer: Any | None = None) -> dict[str, Any]:
    saver = checkpointer if checkpointer is not None else InMemorySaver()

    def inbound_prepare(state: InboundState) -> dict[str, Any]:
        data = dict(state["submission"])
        data["company_domain"] = _domain(data["company_domain"])
        data["contact_email"] = data["contact_email"].strip().casefold()
        text = data["request_text"].casefold()
        intent = any(word in text for word in ("demo", "angebot", "pricing", "preis", "beratung", "pilot", "trial"))
        urgent = any(word in text for word in ("dringend", "sofort", "diese woche"))
        score = 25 + (40 if intent else 0) + (20 if urgent else 0) + (15 if len(text.split()) >= 25 else 0)
        reasons = ["Konkrete Anfrage eingegangen."]
        if intent:
            reasons.append("Explizites Produkt- oder Kaufsignal.")
        if urgent:
            reasons.append("Dringlichkeit im Anfragewortlaut.")
        if len(text.split()) >= 25:
            reasons.append("Ausreichend Kontext für eine Qualifizierung.")
        return {
            "submission": data,
            "qualification_score": min(100, score),
            "qualification_reason": " ".join(reasons),
        }

    def inbound_persist(state: InboundState) -> dict[str, Any]:
        data = state["submission"]
        key = data.get("idempotency_key") or str(uuid.uuid4())
        with session_factory() as db:
            existing = db.scalar(select(Lead).where(Lead.idempotency_key == key))
            if existing:
                return {"outcome": "duplicate", "lead_id": existing.id, "account_id": existing.account_id, "contact_id": existing.contact_id}
            account = db.scalar(select(Account).where(Account.domain == data["company_domain"]))
            if account is None:
                account = Account(company_name=data["company_name"], domain=data["company_domain"], country=data.get("country", "DACH"), industry=data.get("industry"))
                db.add(account)
                db.flush()
            else:
                account.company_name = data["company_name"]
                account.industry = data.get("industry") or account.industry
            contact = db.scalar(select(Contact).where(Contact.account_id == account.id, Contact.email_normalized == data["contact_email"]))
            if contact is None:
                contact = Contact(account_id=account.id, name=data["contact_name"], role=data.get("contact_role"), email=data["contact_email"], email_normalized=data["contact_email"], source_type="inbound_form")
                db.add(contact)
                db.flush()
            if data.get("marketing_consent"):
                db.add(Permission(contact_id=contact.id, channel="email", purpose="marketing", status="granted", consent_source=data.get("form_source", "website_form"), consent_text_version=data["consent_wording_version"], consent_text=data["consent_text"], granted_at=_dt(data["consent_captured_at"])))
            lead = Lead(idempotency_key=key, account_id=account.id, contact_id=contact.id, request_summary=data["request_text"], qualification_score=state["qualification_score"], qualification_reason=state["qualification_reason"], status="needs_review")
            db.add(lead)
            db.flush()
            activity = Activity(account_id=account.id, contact_id=contact.id, lead_id=lead.id, action_type="inbound_follow_up", channel="internal", task_summary="Review inbound request and route to the appropriate owner.", policy_metadata={"qualification_score": state["qualification_score"], "marketing_consent": bool(data.get("marketing_consent")), "external_communication_sent": False}, status="pending_review")
            db.add(activity)
            db.flush()
            _audit(db, "inbound_qualified", "lead", lead.id, {"qualification_score": state["qualification_score"], "activity_id": activity.id})
            result = {"lead_id": lead.id, "account_id": account.id, "contact_id": contact.id, "activity_id": activity.id, "outcome": "needs_review"}
            db.commit()
            return result

    def research_score(state: ResearchState) -> dict[str, Any]:
        account = state["account"]
        account["domain"] = _domain(account["domain"])
        return {"account": account, "score": score_account(industry=account.get("industry"), employee_count=account.get("employee_count"), signals=account.get("signals", []), target_industries=settings.target_industries, min_employees=settings.min_employees, max_employees=settings.max_employees, signal_max_age_days=settings.signal_max_age_days)}

    def research_persist(state: ResearchState) -> dict[str, Any]:
        data, score = state["account"], state["score"]
        with session_factory() as db:
            account = db.scalar(select(Account).where(Account.domain == data["domain"]))
            if account is None:
                account = Account(company_name=data["company_name"], domain=data["domain"])
                db.add(account)
                db.flush()
            account.company_name = data["company_name"]
            account.country = data.get("country", "DACH")
            account.industry = data.get("industry")
            account.employee_count = data.get("employee_count")
            account.icp_score = score["score"]
            account.score_breakdown = score
            account.review_status = score["review_status"]
            for signal in data.get("signals", []):
                found = db.scalar(select(Signal).where(Signal.account_id == account.id, Signal.signal_type == signal["signal_type"], Signal.summary == signal["summary"]))
                if found is None:
                    db.add(Signal(account_id=account.id, signal_type=signal["signal_type"], summary=signal["summary"], evidence_url=signal.get("evidence_url"), source_type=signal.get("source_type", "team_provided"), classification=signal.get("classification", "fact"), confidence=signal.get("confidence", 0.5), observed_at=_dt(signal.get("observed_at", utcnow()))))
            activity = db.scalar(select(Activity).where(Activity.account_id == account.id, Activity.action_type == "account_research_review", Activity.status == "pending_review"))
            if activity is None:
                activity = Activity(account_id=account.id, action_type="account_research_review", channel="internal", task_summary="Review account evidence, source freshness, and ICP score before any contact action.", policy_metadata={"score": score["score"], "score_breakdown": score}, status="pending_review")
                db.add(activity)
            db.flush()
            _audit(db, "account_researched", "account", account.id, {"score": score["score"], "signals_received": len(data.get("signals", []))})
            result = {"account_id": account.id, "activity_id": activity.id, "outcome": "needs_review", "score": score}
            db.commit()
            return result

    def outreach_run(state: OutreachState) -> dict[str, Any]:
        data = state["request"]
        with session_factory() as db:
            contact = db.get(Contact, data["contact_id"])
            if contact is None:
                return {"outcome": "blocked", "gate": {"allowed": False, "status": "blocked", "reason": "Contact not found."}}
            identifiers = _ids(contact)
            suppressed = bool(identifiers and db.scalar(select(Suppression.id).where(Suppression.identifier_normalized.in_(identifiers)).limit(1)))
            consent = bool(contact.email_normalized and db.scalar(select(Permission.id).where(Permission.contact_id == contact.id, Permission.channel == "email", Permission.purpose == "marketing", Permission.status == "granted", Permission.revoked_at.is_(None)).limit(1)))
            decision = evaluate_outreach_policy(channel=data["channel"], suppressed=suppressed, has_email=bool(contact.email), has_phone=bool(contact.phone), has_linkedin_profile=bool(contact.linkedin_url), has_marketing_email_consent=consent)
            gate = {"allowed": decision.allowed_to_create_task, "status": decision.status, "reason": decision.reason, "requires_legal_review": decision.requires_legal_review, "contact_id": contact.id, "account_id": contact.account_id}
            if not decision.allowed_to_create_task:
                _audit(db, "outreach_task_blocked", "contact", contact.id, {"channel": data["channel"], "reason": decision.reason})
                db.commit()
                return {"outcome": "blocked", "gate": gate}
            task = Activity(account_id=contact.account_id, contact_id=contact.id, action_type="manual_outreach_task", channel=data["channel"], task_summary=data["reason"], suggested_text=data.get("suggested_text"), policy_metadata={"policy_reason": decision.reason, "evidence_url": data["evidence_url"], "manual_execution_only": True, "external_action_executed": False}, status="pending_review", due_at=_dt(data["due_at"]) if data.get("due_at") else None, requires_legal_review=decision.requires_legal_review)
            db.add(task)
            db.flush()
            _audit(db, "outreach_task_created", "activity", task.id, {"channel": task.channel, "contact_id": contact.id})
            db.commit()
            return {"outcome": "task_created", "activity_id": task.id, "gate": gate}

    def content_draft(state: ContentState) -> dict[str, Any]:
        data = state["request"]
        draft = f"Ein Gedanke zu {data['topic']}\n\nFür {data['audience']}: {data['takeaway']}\n\nFrage an die Community: {data['discussion_question']}\n\nQuellen zur Faktenprüfung: " + " | ".join(data["source_urls"])
        return {"draft_text": draft}

    def content_save(state: ContentState) -> dict[str, Any]:
        data = state["request"]
        with session_factory() as db:
            idea = ContentIdea(topic=data["topic"], audience=data["audience"], takeaway=data["takeaway"], discussion_question=data["discussion_question"], source_urls=data["source_urls"], draft_text=state["draft_text"], fact_check_status="pending", review_status="pending_review")
            db.add(idea)
            db.flush()
            _audit(db, "content_draft_created", "content_idea", idea.id, {"source_count": len(data["source_urls"]), "published": False})
            db.commit()
            return {"content_id": idea.id}

    def compile_graph(state_type, nodes, edges):
        builder = StateGraph(state_type)
        for name, node in nodes:
            builder.add_node(name, node)
        builder.add_edge(START, edges[0][0])
        for source, target in edges:
            if source != "START":
                builder.add_edge(source, target)
        return builder.compile(checkpointer=saver)

    inbound = compile_graph(InboundState, [("prepare", inbound_prepare), ("persist", inbound_persist)], [("START", "prepare"), ("prepare", "persist"), ("persist", END)])
    research = compile_graph(ResearchState, [("score", research_score), ("persist", research_persist)], [("START", "score"), ("score", "persist"), ("persist", END)])
    outreach = compile_graph(OutreachState, [("policy_and_task", outreach_run)], [("START", "policy_and_task"), ("policy_and_task", END)])
    content = compile_graph(ContentState, [("draft", content_draft), ("persist", content_save)], [("START", "draft"), ("draft", "persist"), ("persist", END)])
    return {"inbound": inbound, "research": research, "outreach": outreach, "content": content}
