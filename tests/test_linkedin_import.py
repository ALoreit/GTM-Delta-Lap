from dach_gtm_agent.linkedin_import import LinkedInVisibleProfileImport


def test_linkedin_company_url_is_accepted_as_domain_key():
    payload = LinkedInVisibleProfileImport(
        user_confirmed=True,
        company_name="Example GmbH",
        domain="https://www.linkedin.com/company/example/",
        name="Ada Lovelace",
        linkedin_url="https://www.linkedin.com/in/ada-lovelace/",
    )

    assert payload.domain == "linkedin.com/company/example"
