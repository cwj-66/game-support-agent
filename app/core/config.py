"""
环境变量配置管理
使用pydantic-settings统一管理配置
"""

from typing import List, Optional, Literal
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
        中断检测的敏感词在 human_in_loop.detector 中管理
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
        description="RAG知识库服务地址"
    )
    
    # LLM配置（双通道：阿里云优先，OpenAI兜底）
    DASHSCOPE_API_KEY: Optional[str] = Field(
        default=None,
        description="阿里云DashScope API Key"
    )
    OPENAI_API_KEY: Optional[str] = Field(
        default=None,
        description="OpenAI API Key（兜底通道）"
    )
    MODEL_NAME: str = Field(
        default="qwen-turbo",
        description="使用的LLM模型"
    )
    LLM_BASE_URL: Optional[str] = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        description="LLM API基础URL（用于兼容第三方API）"
    )
    
    # Human-in-loop配置
    HIL_ENABLED: bool = Field(
        default=True,
        description="是否启用人工审核"
    )
    # 已迁移至 detector.py 管理
    
    # 安全配置
    API_KEY: Optional[str] = Field(
        default=None,
        description="FastAPI层API Key"
    )
    
    # LangSmith 可观测性配置
    LANGCHAIN_TRACING_V2: bool = Field(
        default=False,
        description="是否启用LangSmith追踪"
    )
    LANGCHAIN_API_KEY: Optional[str] = Field(
        default=None,
        description="LangSmith API Key"
    )
    LANGCHAIN_PROJECT: str = Field(
        default="game-support-agent",
        description="LangSmith项目名称"
    )

    # 日志配置
    LOG_LEVEL: str = Field(default="INFO", description="日志级别")
    LOG_DIR: str = Field(default="./logs", description="日志目录")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"  # 忽略 .env 中的未知字段（如旧版 MCP 配置）


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


def get_llm_provider(settings: Optional[Settings] = None) -> Literal["dashscope", "openai"]:
    """
    获取当前可用的LLM提供商

    优先级：
    1. DASHSCOPE_API_KEY
    2. OPENAI_API_KEY
    """
    cfg = settings or get_settings()
    if cfg.DASHSCOPE_API_KEY:
        return "dashscope"
    if cfg.OPENAI_API_KEY:
        return "openai"
    raise ValueError("未配置LLM密钥：请设置 DASHSCOPE_API_KEY 或 OPENAI_API_KEY")
