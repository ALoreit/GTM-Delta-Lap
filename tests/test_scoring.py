from datetime import datetime, timedelta, timezone

from dach_gtm_agent.scoring import score_account

NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)


def test_scoring_is_explainable_and_caps_at_100():
    signals = [
        {"classification": "fact", "confidence": 0.9, "evidence_url": "https://example.com/jobs", "observed_at": NOW.isoformat()},
        {"classification": "fact", "confidence": 0.8, "evidence_url": "https://example.com/news", "observed_at": NOW.isoformat()},
    ]
    result = score_account(industry="B2B SaaS", employee_count=80, signals=signals,
        target_industries=("b2b saas", "software"), min_employees=10, max_employees=500,
        signal_max_age_days=180, now=NOW)
    assert result["score"] == 100
    assert sum(result["parts"].values()) == 100
    assert result["signals_with_sources"] == 2
    assert result["explanations"]


def test_inference_or_missing_sources_force_review():
    result = score_account(industry="B2B SaaS", employee_count=None,
        signals=[{"classification": "inference", "confidence": 0.5, "evidence_url": None, "observed_at": NOW.isoformat()}],
        target_industries=("b2b saas",), min_employees=None, max_employees=None,
        signal_max_age_days=180, now=NOW)
    assert result["review_status"] == "needs_review"
    assert result["signals_with_sources"] == 0


def test_old_signal_is_discounted():
    result = score_account(industry="software", employee_count=50,
        signals=[{"classification": "fact", "confidence": 0.9, "evidence_url": "https://example.com/old", "observed_at": (NOW - timedelta(days=400)).isoformat()}],
        target_industries=("software",), min_employees=None, max_employees=None,
        signal_max_age_days=180, now=NOW)
    assert result["parts"]["intent_signal"] == 8
