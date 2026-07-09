"""
环境变量配置管理
使用pydantic-settings统一管理配置
"""

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
        MODEL_NAME: (已弃用，请用 REASONING_MODEL_NAME)
        REASONING_MODEL_NAME: reasoning 节点的模型
        GENERATE_MODEL_NAME: generate 节点的模型
        
        HIL_ENABLED: 是否启用Human-in-loop
        中断检测的敏感词在 safety.detector 中管理
    """
    
    # 基础配置
    APP_NAME: str = Field(default="game-support-agent", description="应用名称")
    APP_VERSION: str = Field(default="1.0.0", description="应用版本")
    DEBUG: bool = Field(default=False, description="调试模式")
    
    # API配置
    API_V1_PREFIX: str = "/api/v1"
    HOST: str = "127.0.0.1"
    PORT: int = 8002
    
    # 外部服务配置
    RAG_SERVICE_URL: str = Field(
        default="http://localhost:8000",
        description="RAG知识库服务地址"
    )
    MCP_SERVER_URL: str = Field(
        default="http://localhost:8001",
        description="MCP Server SSE 地址"
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
        description="推理节点使用的LLM模型（已弃用，请用 REASONING_MODEL_NAME）"
    )
    REASONING_MODEL_NAME: str = Field(
        default="qwen-turbo",
        description="reasoning 推理节点使用的LLM模型"
    )
    GENERATE_MODEL_NAME: str = Field(
        default="qwen-turbo",
        description="generate 润色节点使用的轻量模型（可改为 qwen-turbo/qwen3.6-flash 等低成本模型）"
    )
    LLM_BASE_URL: Optional[str] = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        description="LLM API基础URL（用于兼容第三方API）"
    )
    
    # LLM 思考模式配置
    ENABLE_THINKING: bool = Field(
        default=False,
        description="是否启用思考模式（True=推理更深但更慢，False=快速响应）",
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
        description="FastAPI层通用API Key"
    )
    REVIEWER_API_KEY: Optional[str] = Field(
        default=None,
        description="审核员 API Key，用于人工审核接口鉴权（简化版，生产应替换为 JWT + RBAC）"
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

    # Redis 配置（生产环境：pending_store 持久化 + 可选缓存）
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis 连接地址（pending_store 使用，不可用时自动降级为内存）",
    )
    REDIS_PASSWORD: Optional[str] = Field(
        default=None,
        description="Redis 密码",
    )
    SESSION_TTL_SECONDS: int = Field(
        default=7200,
        description="客服会话 TTL（秒），默认 2 小时无活动后会话过期，下次消息开新线程",
    )

    # 数据库配置
    DB_PATH: str = Field(
        default="./data/game_support.db",
        description="SQLite 检查点数据库文件路径（LangGraph Agent 状态持久化）",
    )
    TICKET_DB_PATH: str = Field(
        default="./data/tickets.db",
        description="SQLite 工单数据库文件路径",
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


