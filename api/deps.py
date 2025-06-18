from typing import Any, Generator

try:
    from sqlalchemy.orm import Session
except Exception:  # pragma: no cover - SQLAlchemy may not be installed
    Session = Any  # type: ignore


def get_db() -> Generator[Session, None, None]:
    """Dummy database dependency."""
    db = None
    try:
        yield db  # pragma: no cover - placeholder
    finally:
        pass


class User:
    """Simplified user model with a school_id attribute."""

    def __init__(self, school_id: int = 1):
        self.school_id = school_id


def get_current_user() -> User:
    """Return a dummy authenticated user."""
    return User()
