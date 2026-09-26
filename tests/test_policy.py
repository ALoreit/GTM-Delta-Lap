from dach_gtm_agent.policy import evaluate_outreach_policy


def test_email_without_explicit_marketing_consent_is_blocked():
    result = evaluate_outreach_policy(channel="email", suppressed=False, has_email=True,
        has_phone=False, has_linkedin_profile=False, has_marketing_email_consent=False)
    assert not result.allowed_to_create_task
    assert result.status == "blocked"


def test_phone_is_task_only_and_requires_legal_review():
    result = evaluate_outreach_policy(channel="phone", suppressed=False, has_email=False,
        has_phone=True, has_linkedin_profile=False, has_marketing_email_consent=False)
    assert result.allowed_to_create_task
    assert result.requires_legal_review
    assert result.status == "pending_review"


def test_suppression_blocks_every_channel():
    for channel in ("email", "phone", "linkedin"):
        result = evaluate_outreach_policy(channel=channel, suppressed=True, has_email=True,
            has_phone=True, has_linkedin_profile=True, has_marketing_email_consent=True)
        assert not result.allowed_to_create_task
        assert result.status == "blocked"


def test_linkedin_task_is_manual_only():
    result = evaluate_outreach_policy(channel="linkedin", suppressed=False, has_email=False,
        has_phone=False, has_linkedin_profile=True, has_marketing_email_consent=False)
    assert result.allowed_to_create_task
    assert "no scraping" in result.reason
