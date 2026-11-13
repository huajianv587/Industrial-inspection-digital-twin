from __future__ import annotations

from collections.abc import Iterator
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool
from .settings import Settings


class Base(DeclarativeBase):
    pass


def create_database(database_url: str, *, environment: str = "production"
                    ) -> tuple[Engine, sessionmaker[Session]]:
    kwargs: dict[str, object] = {"pool_pre_ping": True}
    if database_url.startswith("sqlite:"):
        if environment not in {"test", "local_demo"}:
            raise ValueError("SQLite is disabled outside isolated tests and local demos.")
        kwargs["connect_args"] = {"check_same_thread": False}
        if database_url in {"sqlite://", "sqlite:///:memory:"} or database_url.endswith(":memory:"):
            kwargs["poolclass"] = StaticPool
    settings = Settings(database_url=database_url, environment=environment)
    normalized_url = settings.sqlalchemy_database_url()
    engine = create_engine(normalized_url, **kwargs)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def get_session(factory: sessionmaker[Session]) -> Iterator[Session]:
    with factory() as session:
        yield session
