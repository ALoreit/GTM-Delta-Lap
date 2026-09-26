# DACH GTM Agent — LangGraph MVP

Backend und Chrome-Erweiterung für manuell gestartete GTM-Workflows: Inbound-Qualifizierung, Account-Research/Scoring, manuelle Outreach-Aufgaben und Content-Entwürfe.

## LinkedIn-Profilimport

Die Erweiterung kann nach einem ausdrücklichen Klick sichtbare Basisangaben des aktiven einzelnen LinkedIn-Profils übernehmen: Profil-URL, Name, Profilheadline, Standort und – sofern im sichtbaren Profil vorhanden – die aktuelle Firma. Die Werte erscheinen im Formular und werden erst nach Prüfung und Bestätigung an das Backend gesendet.

Nicht automatisch ermittelt werden E-Mail, Telefonnummer, Firmendomain, Branche oder Mitarbeiterzahl. Diese Felder können ergänzt werden; für echte Anreicherung kann später ein separat zugelassener Datenprovider angebunden werden. Die DOM-Auswahl beruht auf LinkedIns wechselnder Seitendarstellung; Felder können daher leer bleiben oder nach UI-Änderungen angepasst werden müssen.

Der Import speichert die Quellen-URL, markiert die Herkunft als `linkedin_visible_profile`, protokolliert die Bestätigung und führt das bestehende Account-Scoring aus. Kontakte werden anhand Profil-URL (und ersatzweise E-Mail) innerhalb des Accounts aktualisiert. Es gibt keinen Nachrichtversand und keine automatischen Aktionen auf LinkedIn.

**Voraussetzung:** Der Betreiber muss die erforderlichen internen und externen Freigaben für den konkreten Einsatz besitzen. Diese Implementierung ist keine Rechtsberatung und prüft oder erzeugt keine Freigaben.

### Chrome-Erweiterung einrichten

1. Backend lokal auf `http://127.0.0.1:8000` starten.
2. `chrome://extensions` öffnen, Entwicklermodus aktivieren und den Ordner `extension/` entpackt laden.
3. Die Erweiterungs-ID als `CHROME_EXTENSION_ORIGIN=chrome-extension://<extension-id>` in `.env` setzen und die API neu starten.
4. Ein einzelnes LinkedIn-Profil öffnen, Erweiterung starten, „Sichtbares LinkedIn-Profil übernehmen“ klicken.
5. Übernommene Werte und Firmenfelder prüfen, dann „Prüfen & speichern“ klicken.

Die Manifest-Berechtigungen sind `activeTab` und `scripting` plus Zugriff auf das lokale Backend. Das Skript wird erst durch den Import-Klick injiziert; es liest keine versteckten Felder oder Zusatzseiten aus und verwendet keine LinkedIn-Cookies oder privaten Schnittstellen.

## API

- `POST /v1/import/linkedin-visible-profile`: nimmt bestätigte Formularwerte entgegen, validiert die Profil-URL, führt Account-Scoring aus, erstellt/aktualisiert den Kontakt und legt ein Audit-Ereignis an.
- `POST /v1/research/accounts`: Account und belegte Signale erfassen/scoren.
- `GET /v1/accounts/{account_id}`: Accountscore und Belege lesen.
- `POST /v1/accounts/{account_id}/contacts`: Kontakt manuell bzw. aus einer zugelassenen Quelle erfassen.
- `POST /v1/outreach/tasks`: kanalgeprüfte manuelle Review-Aufgabe erstellen; kein Versand.
- `GET /v1/review` und `POST /v1/review/{activity_id}`: Review-Queue und manuelle Entscheidung.
- Weitere Endpunkte: Inbound-Qualifizierung, Suppression, Einwilligungswiderruf und Content-Review; Details siehe API-Dokumentation unter `/docs`.

## Backend starten

Voraussetzungen: Python 3.11+, Abhängigkeiten aus `pyproject.toml`; optional Docker Compose für PostgreSQL.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test]"
cp .env.example .env
uvicorn dach_gtm_agent.api:app --app-dir src --reload --env-file .env
```

Interaktive API-Dokumentation: `http://127.0.0.1:8000/docs`.

## Grenzen vor Produktivbetrieb

Die API ist im MVP nicht authentifiziert. CORS ist kein Authentifizierungsmechanismus. Vor Deployment außerhalb lokaler Entwicklung sind Authentifizierung/Rollen, HTTPS, Rate-Limits, Datenminimierung, Löschfristen, versionierte Migrationen, Datenschutzprüfung und End-to-End-Tests erforderlich. `Database.create_tables()` enthält für lokale Bestandsdaten eine additive Migration der neuen Standortspalte.

Tests: `pytest`.
