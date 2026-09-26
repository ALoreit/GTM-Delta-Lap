from __future__ import annotations

import os
from dataclasses import dataclass


def _optional_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    return int(value) if value else None


@dataclass(frozen=True)
class Settings:
    database_url: str
    checkpoint_backend: str
    checkpoint_database_url: str | None
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
        backend = os.getenv("GRAPH_CHECKPOINT_BACKEND", "memory").strip().casefold()
        if backend not in {"memory", "postgres"}:
            raise ValueError("GRAPH_CHECKPOINT_BACKEND must be 'memory' or 'postgres'")
        checkpoint_url = os.getenv("CHECKPOINT_DATABASE_URL", "").strip() or None
        if backend == "postgres" and not checkpoint_url:
            raise ValueError(
                "CHECKPOINT_DATABASE_URL is required when GRAPH_CHECKPOINT_BACKEND=postgres"
            )
        return cls(
            database_url=os.getenv("DATABASE_URL", "sqlite:///./gtm.db"),
            checkpoint_backend=backend,
            checkpoint_database_url=checkpoint_url,
            target_industries=industries,
            min_employees=_optional_int("ICP_MIN_EMPLOYEES"),
            max_employees=_optional_int("ICP_MAX_EMPLOYEES"),
            signal_max_age_days=int(os.getenv("ICP_SIGNAL_MAX_AGE_DAYS", "180")),
        )
