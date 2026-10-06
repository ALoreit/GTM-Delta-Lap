from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from .models import Base


class Database:
    def __init__(self, url: str):
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
        )

    def create_tables(self) -> None:
        Base.metadata.create_all(self.engine)
        # Additive compatibility migration for databases created before profile import.
        columns = {column["name"] for column in inspect(self.engine).get_columns("contacts")}
        if "profile_location" not in columns:
            with self.engine.begin() as connection:
                connection.execute(text("ALTER TABLE contacts ADD COLUMN profile_location VARCHAR(200)"))
        if "linkedin_connected" not in columns:
            with self.engine.begin() as connection:
                connection.execute(text("ALTER TABLE contacts ADD COLUMN linkedin_connected BOOLEAN NOT NULL DEFAULT 0"))

    def dispose(self) -> None:
        self.engine.dispose()
