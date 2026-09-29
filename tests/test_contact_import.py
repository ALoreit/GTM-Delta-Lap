from dach_gtm_agent.schemas import ContactCreate


def test_contact_create_accepts_imported_profile_location():
    payload = ContactCreate(
        name="Ada Lovelace",
        role="Chief Technology Officer",
        profile_location="Berlin, Germany",
        linkedin_url="https://www.linkedin.com/in/ada-lovelace/",
        source_url="https://www.linkedin.com/in/ada-lovelace/",
        source_type="linkedin_visible_profile",
    )

    assert payload.profile_location == "Berlin, Germany"
    assert payload.source_type == "linkedin_visible_profile"
    assert payload.email is None
    assert payload.phone is None


def test_contact_import_still_requires_profile_provenance():
    try:
        ContactCreate(
            name="Ada Lovelace",
            linkedin_url="https://www.linkedin.com/in/ada-lovelace/",
            source_type="linkedin_visible_profile",
        )
    except Exception as error:
        assert "source_url" in str(error)
    else:
        raise AssertionError("source_url must remain required")
