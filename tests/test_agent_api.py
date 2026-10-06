from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from dach_gtm_agent.api import create_app
from dach_gtm_agent.models import Account, Contact


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("GRAPH_CHECKPOINT_BACKEND", "memory")
    app = create_app()
    with TestClient(app) as test_client:
        database = app.state.database
        with database.session_factory() as db:
            account = Account(company_name="Acme GmbH", domain="acme.example")
            db.add(account)
            db.flush()
            db.add_all(
                [
                    Contact(
                        account_id=account.id,
                        name="Anna Beispiel",
                        role="CEO",
                        email="anna@acme.example",
                        phone="+491234",
                        linkedin_connected=True,
                    ),
                    Contact(
                        account_id=account.id,
                        name="Ben Beispiel",
                        role="CTO",
                        email="ben@acme.example",
                        phone="+495678",
                        linkedin_connected=False,
                    ),
                ]
            )
            db.commit()
        yield test_client


def test_agent_contact_list_supports_linkedin_filter(client: TestClient):
    response = client.get("/v1/agent/contacts", params={"linkedin_connected": True})

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "id": response.json()["items"][0]["id"],
            "name": "Anna Beispiel",
            "company_name": "Acme GmbH",
            "linkedin_connected": True,
        }
    ]


def test_agent_contact_details_exclude_email_and_phone(client: TestClient):
    response = client.get("/v1/agent/contacts/anna%20beispiel")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Anna Beispiel"
    assert body["company"]["name"] == "Acme GmbH"
    assert "email" not in body
    assert "phone" not in body


def test_agent_contact_requires_unique_name(client: TestClient):
    database = client.app.state.database
    with database.session_factory() as db:
        account = db.scalar(select(Account))
        db.add(Contact(account_id=account.id, name="Anna Beispiel"))
        db.commit()

    response = client.get("/v1/agent/contacts/Anna%20Beispiel")

    assert response.status_code == 409
