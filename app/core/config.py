"""
环境变量配置管理
使用pydantic-settings统一管理配置
"""

import os
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """
    应用配置类
    
    优先级：环境变量 > .env文件 > 默认值
    
    Attributes:
        APP_NAME: 应用名称
        APP_VERSION: 应用版本
        DEBUG: 调试模式
        
        API_V1_PREFIX: API版本前缀
        
        RAG_SERVICE_URL: RAG服务地址
        MCP_SERVER_URL: MCP服务器地址
        
        OPENAI_API_KEY: LLM API Key
        MODEL_NAME: 使用的模型名称
        
        HIL_ENABLED: 是否启用Human-in-loop
        HIL_CONFIDENCE_THRESHOLD: 置信度阈值
    """
    
    # 基础配置
    APP_NAME: str = Field(default="game-support-agent", description="应用名称")
    APP_VERSION: str = Field(default="1.0.0", description="应用版本")
    DEBUG: bool = Field(default=False, description="调试模式")
    
    # API配置
    API_V1_PREFIX: str = "/api/v1"
    HOST: str = "0.0.0.0"
    PORT: int = 8002
    
    # 外部服务配置
    RAG_SERVICE_URL: str = Field(
        default="http://localhost:8000",
        description="enterprise-rag服务地址"
    )
    MCP_SERVER_URL: str = Field(
        default="http://localhost:8001",
        description="MCP SSE服务器地址"
    )
    
    # LLM配置
    OPENAI_API_KEY: Optional[str] = Field(
        default=None,
        description="OpenAI API Key（或其他LLM提供商）"
    )
    MODEL_NAME: str = Field(
        default="gpt-3.5-turbo",
        description="使用的LLM模型"
    )
    LLM_BASE_URL: Optional[str] = Field(
        default=None,
        description="LLM API基础URL（用于兼容第三方API）"
    )
    
    # Human-in-loop配置
    HIL_ENABLED: bool = Field(
        default=True,
        description="是否启用人工审核"
    )
    HIL_CONFIDENCE_THRESHOLD: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="置信度阈值，低于此值触发人工审核"
    )
    SENSITIVE_WORDS: List[str] = Field(
        default=["封号", "退款", "投诉", "举报", "盗号"],
        description="敏感词列表"
    )
    
    # 安全配置
    MCP_API_KEY: Optional[str] = Field(
        default=None,
        description="MCP层API Key"
    )
    API_KEY: Optional[str] = Field(
        default=None,
        description="FastAPI层API Key"
    )
    
    # 日志配置
    LOG_LEVEL: str = Field(default="INFO", description="日志级别")
    LOG_DIR: str = Field(default="./logs", description="日志目录")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# 全局配置实例
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """获取配置单例"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings():
    """重新加载配置（用于配置热更新）"""
    global _settings
    _settings = Settings()
