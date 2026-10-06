from __future__ import annotations

import os
from dataclasses import dataclass


def _optional_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    return int(value) if value else None


@dataclass(frozen=True)
class Settings:
    database_url: str
    chrome_extension_origin: str | None
    target_industries: tuple[str, ...]
    min_employees: int | None
    max_employees: int | None
    signal_max_age_days: int

    @classmethod
    def from_env(cls) -> "Settings":
        industries = tuple(
            item.strip().casefold()
            for item in os.getenv(
                "ICP_TARGET_INDUSTRIES",
                "b2b saas,saas,software,technology,tech",
            ).split(",")
            if item.strip()
        )
        extension_origin = os.getenv("CHROME_EXTENSION_ORIGIN", "").strip() or None
        return cls(
            database_url=os.getenv("DATABASE_URL", "sqlite:///./gtm.db"),
            chrome_extension_origin=extension_origin,
            target_industries=industries,
            min_employees=_optional_int("ICP_MIN_EMPLOYEES"),
            max_employees=_optional_int("ICP_MAX_EMPLOYEES"),
            signal_max_age_days=int(os.getenv("ICP_SIGNAL_MAX_AGE_DAYS", "180")),
        )
