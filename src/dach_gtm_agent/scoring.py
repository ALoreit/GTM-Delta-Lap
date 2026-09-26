from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def score_account(
    *,
    industry: str | None,
    employee_count: int | None,
    signals: list[dict[str, Any]],
    target_industries: tuple[str, ...],
    min_employees: int | None,
    max_employees: int | None,
    signal_max_age_days: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Transparent heuristic score; it is a review aid, not an autonomous decision."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    parts: dict[str, int] = {}
    explanations: list[str] = []

    normalized_industry = (industry or "").casefold()
    if not normalized_industry:
        parts["segment_fit"] = 10
        explanations.append("Segment unbekannt: neutraler Teilwert, manuell prüfen.")
    elif any(term in normalized_industry for term in target_industries):
        parts["segment_fit"] = 30
        explanations.append(f"Segment passt zum konfigurierten Zielmarkt ({industry}).")
    else:
        parts["segment_fit"] = 0
        explanations.append(f"Segment '{industry}' passt nicht zu den konfigurierten Zielbegriffen.")

    if employee_count is None:
        parts["size_fit"] = 10
        explanations.append("Mitarbeiterzahl fehlt; Größen-Fit ist unbestimmt.")
    else:
        lower_ok = min_employees is None or employee_count >= min_employees
        upper_ok = max_employees is None or employee_count <= max_employees
        if lower_ok and upper_ok:
            parts["size_fit"] = 20
            if min_employees is None and max_employees is None:
                explanations.append("Größe nicht begrenzt: Mitarbeiterzahl erfasst, keine harte ICP-Grenze konfiguriert.")
            else:
                explanations.append("Mitarbeiterzahl liegt im konfigurierten ICP-Band.")
        else:
            parts["size_fit"] = 0
            explanations.append("Mitarbeiterzahl liegt außerhalb des konfigurierten ICP-Bands.")

    current_facts = []
    stale_facts = []
    inferences = []
    for signal in signals:
        classification = signal.get("classification", "fact")
        if classification == "inference":
            inferences.append(signal)
            continue
        age_days = max(0, (now - _as_datetime(signal.get("observed_at", now))).days)
        (current_facts if age_days <= signal_max_age_days else stale_facts).append(signal)

    if any(float(s.get("confidence", 0.0)) >= 0.6 and s.get("evidence_url") for s in current_facts):
        parts["intent_signal"] = 25
        explanations.append("Mindestens ein aktuelles, belegtes Fakt-Signal mit ausreichender Sicherheit liegt vor.")
    elif current_facts:
        parts["intent_signal"] = 15
        explanations.append("Aktuelle Fakten liegen vor, aber Beleg oder Sicherheit ist begrenzt.")
    elif stale_facts:
        parts["intent_signal"] = 8
        explanations.append("Nur ältere Fakt-Signale vorhanden; Aktualität prüfen.")
    elif inferences:
        parts["intent_signal"] = 5
        explanations.append("Es liegen nur Schlussfolgerungen vor; nicht als gesicherte Fakten verwenden.")
    else:
        parts["intent_signal"] = 0
        explanations.append("Kein Kaufsignal erfasst.")

    evidenced_count = sum(bool(s.get("evidence_url")) for s in signals)
    if evidenced_count >= 2:
        parts["data_quality"] = 25
        explanations.append("Mindestens zwei Signale haben Quell-URLs.")
    elif evidenced_count == 1:
        parts["data_quality"] = 15
        explanations.append("Ein Signal hat eine Quell-URL; Stichprobenprüfung empfohlen.")
    else:
        parts["data_quality"] = 0
        explanations.append("Keine Quell-URLs vorhanden; zwingend manuell prüfen.")

    total = min(100, sum(parts.values()))
    needs_review = not signals or evidenced_count == 0 or bool(inferences)
    return {
        "score": total,
        "parts": parts,
        "explanations": explanations,
        "review_status": "needs_review" if needs_review else "scored_needs_human_review",
        "signals_with_sources": evidenced_count,
    }
