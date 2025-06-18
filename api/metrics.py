from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Any

from services import metrics
from .deps import get_db, get_current_user

try:  # Optional import since SQLAlchemy may not be installed
    from sqlalchemy.orm import Session
except Exception:  # pragma: no cover - SQLAlchemy optional
    Session = Any  # type: ignore


class MetricsDashboard(BaseModel):
    students: int
    matches: int
    hires_30d: int
    avg_score: float

    class Config:
        orm_mode = True


router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/summary", response_model=MetricsDashboard)
def get_summary(
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> MetricsDashboard:
    """Return metrics for the authenticated user's school."""
    data = metrics.summary(db, getattr(current_user, "school_id"))
    return MetricsDashboard(**data)
