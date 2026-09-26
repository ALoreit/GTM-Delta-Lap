from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyDecision:
    allowed_to_create_task: bool
    status: str
    reason: str
    requires_legal_review: bool = False


def evaluate_outreach_policy(
    *,
    channel: str,
    suppressed: bool,
    has_email: bool,
    has_phone: bool,
    has_linkedin_profile: bool,
    has_marketing_email_consent: bool,
) -> PolicyDecision:
    """Return permission to create a human-reviewed task, never to send anything."""
    if suppressed:
        return PolicyDecision(False, "blocked", "Contact is on the cross-channel suppression list.")

    if channel == "email":
        if not has_email:
            return PolicyDecision(False, "blocked", "No email address is available.")
        if not has_marketing_email_consent:
            return PolicyDecision(
                False,
                "blocked",
                "No active, documented marketing email consent is recorded.",
            )
        return PolicyDecision(
            True,
            "pending_review",
            "Consent exists; a human must review the content and scope. No email is sent.",
        )

    if channel == "phone":
        if not has_phone:
            return PolicyDecision(False, "blocked", "No phone number is available.")
        return PolicyDecision(
            True,
            "pending_review",
            "Manual call task only; case-specific legal review is required before calling.",
            requires_legal_review=True,
        )

    if channel == "linkedin":
        if not has_linkedin_profile:
            return PolicyDecision(False, "blocked", "No manually sourced LinkedIn profile URL is recorded.")
        return PolicyDecision(
            True,
            "pending_review",
            "Manual profile-review task only; no scraping, messaging, comments, or reactions.",
        )

    return PolicyDecision(False, "blocked", "Unsupported channel.")
