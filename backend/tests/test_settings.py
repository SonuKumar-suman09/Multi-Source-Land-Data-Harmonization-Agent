"""Settings compatibility with PostgreSQL URLs supplied by managed providers."""

from app.core.config import Settings


def test_normalizes_postgres_scheme_to_installed_psycopg_driver() -> None:
    assert Settings(database_url="postgres://user:pass@db.example:5432/app").database_url == (
        "postgresql+psycopg://user:pass@db.example:5432/app"
    )
    assert Settings(database_url="postgresql://user:pass@db.example:5432/app").database_url == (
        "postgresql+psycopg://user:pass@db.example:5432/app"
    )


def test_keeps_explicit_psycopg_url_unchanged() -> None:
    url = "postgresql+psycopg://user:pass@localhost:5432/app"
    assert Settings(database_url=url).database_url == url
