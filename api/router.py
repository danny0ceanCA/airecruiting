from fastapi import APIRouter

from .metrics import router as metrics_router

router = APIRouter()
router.include_router(metrics_router)
