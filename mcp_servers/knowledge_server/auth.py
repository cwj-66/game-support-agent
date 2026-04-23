"""
MCP Server 层 API Key 校验
独立于FastAPI层的另一道防线
"""

import os
import hmac
import secrets
from typing import Optional
from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader


# API Key 请求头名称
API_KEY_HEADER = "X-MCP-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)


class MCPAuthManager:
    """
    MCP服务器认证管理器
    
    职责：
    1. 校验MCP连接请求的API Key
    2. 支持多Key轮换（未来）
    3. 常量时间比较防时序攻击
    
    TODO: 实现Key轮换机制
    TODO: 添加Key使用频率限制
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        初始化认证管理器
        
        Args:
            api_key: 从环境变量或参数获取，优先级：参数 > 环境变量
        """
        self._api_key = api_key or os.getenv("MCP_API_KEY", "")
        if not self._api_key:
            # 开发环境允许空Key，生产环境必须设置
            import warnings
            warnings.warn("MCP_API_KEY未设置，使用开发模式（无认证）")
    
    def verify(self, provided_key: Optional[str]) -> bool:
        """
        校验提供的API Key是否有效
        
        使用hmac.compare_digest进行常量时间比较，
        防止时序攻击泄露Key长度信息
        """
        if not self._api_key:
            # 未配置Key时，允许所有请求（仅开发环境）
            return True
        
        if not provided_key:
            return False
        
        # 常量时间比较，防时序攻击
        return hmac.compare_digest(
            self._api_key.encode(),
            provided_key.encode()
        )
    
    async def __call__(self, api_key: Optional[str] = Security(api_key_header)) -> str:
        """
        FastAPI依赖注入用
        
        Returns:
            校验通过的API Key值
            
        Raises:
            HTTPException: 401未授权
        """
        if not self.verify(api_key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的MCP API Key",
                headers={"WWW-Authenticate": API_KEY_HEADER},
            )
        return api_key or "dev-mode"


# 全局认证管理器实例
_auth_manager: Optional[MCPAuthManager] = None


def get_auth_manager() -> MCPAuthManager:
    """获取或创建认证管理器单例"""
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = MCPAuthManager()
    return _auth_manager


def require_mcp_auth(api_key: str = Security(api_key_header)) -> str:
    """
    FastAPI依赖：要求MCP层认证
    
    用法：
        @app.get("/protected")
        async def protected(auth: str = Depends(require_mcp_auth)):
            return {"message": "已认证"}
    """
    manager = get_auth_manager()
    if not manager.verify(api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="MCP认证失败",
        )
    return api_key or "dev-mode"


# TODO: 未来扩展
# - 添加 rate limiting 装饰器
# - 实现 API Key 黑白名单
# - 添加请求签名验证（防重放攻击）
