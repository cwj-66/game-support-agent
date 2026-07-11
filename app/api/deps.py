"""
路由层公共依赖：玩家 JWT 鉴权、会话归属校验。

游戏客户端请求头：
    Authorization: Bearer <游戏服签发的 JWT>
"""

from dataclasses import dataclass
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings

_bearer = HTTPBearer(auto_error=False)


@dataclass
class CurrentPlayer:
    """JWT 验证通过后得到的玩家身份（可信 user_id）"""

    user_id: str
    server_id: Optional[str] = None
    nickname: Optional[str] = None


def decode_game_token(token: str, settings: Settings) -> dict:
    """解码并校验游戏 JWT，失败则抛 HTTPException。"""
    if not settings.GAME_JWT_SECRET:
        raise HTTPException(status_code=500, detail="服务端未配置 GAME_JWT_SECRET")

    try:
        return jwt.decode(
            token,
            settings.GAME_JWT_SECRET,
            algorithms=[settings.GAME_JWT_ALGORITHM],
            options={"require": ["sub", "exp"]},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="登录已过期，请重新进入游戏")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="无效的登录凭证")


async def get_current_player(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> CurrentPlayer:
    """
    校验游戏服签发的 JWT，提取真实玩家 UID。

    开发模式：DEBUG=true 且未配置 GAME_JWT_SECRET 时，返回 mock 玩家 10001。
    """
    if settings.game_auth_disabled:
        return CurrentPlayer(user_id="10001", server_id="s1", nickname="开发测试号")

    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="缺少 Authorization: Bearer token")

    payload = decode_game_token(credentials.credentials, settings)

    user_id = payload.get("sub") or payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="token 中缺少用户标识 (sub)")

    return CurrentPlayer(
        user_id=str(user_id),
        server_id=payload.get("server_id"),
        nickname=payload.get("nickname"),
    )


def require_session_owner(session_id: str, player: CurrentPlayer) -> None:
    """
    校验会话是否属于当前玩家。

    约定 session_id 格式：{user_id}_{随机串}，例如 10001_a1b2c3d4
    """
    expected_prefix = f"{player.user_id}_"
    if not session_id.startswith(expected_prefix):
        raise HTTPException(status_code=403, detail="无权访问该会话")


def require_ticket_owner(ticket_player_uid: str, player: CurrentPlayer) -> None:
    """校验工单是否属于当前玩家"""
    if ticket_player_uid != player.user_id:
        raise HTTPException(status_code=403, detail="无权访问该工单")


async def require_reviewer_token(
    x_reviewer_token: str = Header(..., alias="X-Reviewer-Token"),
    settings: Settings = Depends(get_settings),
) -> str:
    """客服审核/后台接口鉴权"""
    if not settings.REVIEWER_API_KEY:
        return "dev_reviewer"
    if x_reviewer_token != settings.REVIEWER_API_KEY:
        raise HTTPException(status_code=403, detail="审核员 token 无效")
    return x_reviewer_token
