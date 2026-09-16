"""
API v1 路由汇总
"""

from fastapi import APIRouter

from app.core.config import get_settings
from . import chat, demo, human, ticket

settings = get_settings()

router = APIRouter(prefix=settings.API_V1_PREFIX)
router.include_router(chat.router)
router.include_router(human.router)
router.include_router(ticket.router)
router.include_router(demo.router)
