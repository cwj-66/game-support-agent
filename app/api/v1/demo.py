"""演示用接口：列出测试玩家并签发 JWT，供玩家端选号登录。"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import issue_game_token
from app.core.config import Settings, get_settings
from app.services.account_service import get_player, list_demo_players

router = APIRouter(prefix="/demo", tags=["演示登录"])


class DemoPlayer(BaseModel):
    """测试账号卡片展示字段"""

    uid: str
    nickname: Optional[str] = None
    server_id: Optional[str] = None
    level: Optional[int] = None
    vip_level: Optional[int] = None
    status: Optional[str] = None
    ban_reason: Optional[str] = None
    recharge_total: float = 0
    abnormal_detail: Optional[str] = None
    last_login: Optional[str] = None


class DemoLoginRequest(BaseModel):
    uid: str = Field(..., description="game_players.uid")


class DemoLoginResponse(BaseModel):
    token: str
    player: DemoPlayer


@router.get("/players", response_model=list[DemoPlayer], summary="列出测试账号")
async def get_demo_players() -> list[DemoPlayer]:
    """返回 MySQL 中全部 Mock 玩家，无需登录。"""
    try:
        rows = list_demo_players()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"账号数据库不可用: {e}") from e
    return [DemoPlayer(**row) for row in rows]


@router.post("/login", response_model=DemoLoginResponse, summary="选择测试账号登录")
async def demo_login(
    body: DemoLoginRequest,
    settings: Settings = Depends(get_settings),
) -> DemoLoginResponse:
    """按 UID 签发玩家 JWT，有效期 24 小时。"""
    try:
        record = get_player(body.uid)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"账号数据库不可用: {e}") from e

    if record is None:
        raise HTTPException(status_code=404, detail=f"测试账号 {body.uid} 不存在")

    token = issue_game_token(
        record["uid"],
        settings,
        server_id=record.get("server_id"),
        nickname=record.get("nickname"),
    )
    return DemoLoginResponse(token=token, player=DemoPlayer(**record))
