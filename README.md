# DACH GTM Agent — LangGraph MVP

FastAPI/LangGraph backend und Chrome-Erweiterung für manuell gestartete GTM-Workflows: Inbound-Qualifizierung, Account-Research/Scoring, manuelle Outreach-Aufgaben und Content-Entwürfe.

## LinkedIn-Profilimport

Nach einem ausdrücklichen Klick auf **„Sichtbares LinkedIn-Profil übernehmen“** liest die Erweiterung ausgewählte, aktuell sichtbare Basisangaben aus dem aktiven einzelnen Profil: Profil-URL, Name, Profilheadline, Standort und – sofern das aktuelle Layout sie in den ausgewählten sichtbaren Bereichen enthält – den Firmennamen. Die Werte werden erst nach Prüfung und Bestätigung des Formulars ans Backend gesendet.

Die DOM-Auswahl hängt von LinkedIns veränderlicher Seitendarstellung ab. Angaben können leer bleiben oder nach UI-Änderungen angepasst werden müssen. Es werden keine nicht sichtbaren Profilbereiche geöffnet, keine Hintergrundnavigation ausgeführt und keine privaten Endpunkte oder LinkedIn-Cookies verwendet.

Firmendomain, Branche, Mitarbeiterzahl, geschäftliche E-Mail und Telefon werden nicht automatisch angereichert. Sie müssen ergänzt oder über einen separat konfigurierten und zugelassenen Datenprovider beschafft werden. Diese Version enthält noch keinen Enrichment-Provider-Adapter.

Der Backend-Endpunkt `POST /v1/import/linkedin-visible-profile` validiert die Profil-URL, verlangt `user_confirmed: true`, führt das vorhandene Account-Scoring aus, erstellt bzw. aktualisiert den Kontakt und protokolliert Profil-URL, Importquelle und Bestätigung im Audit-Log. Der Kontakt wird anhand der Profil-URL, ersatzweise geschäftlicher E-Mail, innerhalb des Accounts dedupliziert.

Es gibt keinen Versand und keine automatisierten LinkedIn-Aktionen. Die Implementierung ist keine Rechtsberatung und prüft oder erzeugt keine Freigaben; der Betreiber ist für die Freigaben und den Einsatz verantwortlich.

### Chrome-Erweiterung einrichten

1. Backend lokal unter `http://127.0.0.1:8000` starten.
2. `chrome://extensions` öffnen, Entwicklermodus aktivieren und den Ordner `extension/` entpackt laden.
3. Die Erweiterungs-ID als `CHROME_EXTENSION_ORIGIN=chrome-extension://<extension-id>` in `.env` setzen und die API neu starten.
4. Ein einzelnes LinkedIn-Profil öffnen, Erweiterung starten und **„Sichtbares LinkedIn-Profil übernehmen“** klicken.
5. Werte prüfen und fehlende Firmenfelder ergänzen; danach **„Prüfen & speichern“** klicken.

Die Chrome-Berechtigungen sind `activeTab` und `scripting`, plus Zugriff auf das lokale Backend. Das Skript wird erst auf Nutzerklick in den aktiven Tab injiziert.

## Weitere API-Funktionen

- `POST /v1/inbound`: Formularanfrage deduplizieren, heuristisch qualifizieren und interne Review-Aufgabe erzeugen.
- `POST /v1/research/accounts`: Account und belegte Signale erfassen/scoren.
- `GET /v1/accounts/{account_id}`: Accountscore und Belege lesen.
- `POST /v1/accounts/{account_id}/contacts`: Kontakt manuell bzw. aus einer zugelassenen Quelle erfassen.
- `POST /v1/outreach/tasks`: kanalgeprüfte manuelle Review-Aufgabe erstellen; kein Versand.
- `GET /v1/review` und `POST /v1/review/{activity_id}`: Review-Queue und manuelle Entscheidung.
- Weitere Endpunkte: Suppression, Einwilligungswiderruf und Content-Review; siehe `/docs`.

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

Die API ist im MVP nicht authentifiziert; CORS ist kein Authentifizierungsmechanismus. Backend nicht ungeschützt im Internet bereitstellen. Vor einem Produktivbetrieb sind mindestens Authentifizierung/Rollen, HTTPS, Rate-Limits, Datenminimierung, Löschfristen, versionierte Migrationen, Datenschutzprüfung und End-to-End-Tests erforderlich. `Database.create_tables()` enthält eine additive Migration für die neue Standortspalte in lokalen Bestandsdatenbanken.

Tests: `pytest`.
