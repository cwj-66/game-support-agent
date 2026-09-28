"""pydantic-settings 环境变量配置。"""

from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """应用配置（环境变量 > .env > 默认值）。"""

    APP_NAME: str = Field(default="game-support-agent", description="应用名称")
    APP_VERSION: str = Field(default="1.0.0", description="应用版本")
    DEBUG: bool = Field(default=False, description="调试模式")

    API_V1_PREFIX: str = "/api/v1"
    HOST: str = "127.0.0.1"
    PORT: int = 8002

    RAG_SERVICE_URL: str = Field(
        default="http://localhost:8000",
        description="RAG知识库服务地址",
    )
    RAG_API_KEY: Optional[str] = Field(
        default=None,
        description="调用外部 RAG 时的 X-API-Key",
    )
    MCP_SERVER_URL: str = Field(
        default="http://localhost:8001",
        description="MCP Server 地址",
    )

    DASHSCOPE_API_KEY: Optional[str] = Field(
        default=None,
        description="阿里云 DashScope API Key",
    )
    OPENAI_API_KEY: Optional[str] = Field(
        default=None,
        description="可选 OpenAI API Key；当前 LLM 调用仍使用 DashScope 兼容接口",
    )
    REASONING_MODEL_NAME: str = Field(
        default="qwen3.8-max",
        description="reasoning 推理节点使用的 LLM 模型",
    )
    GENERATE_MODEL_NAME: str = Field(
        default="qwen3.8-flash",
        description="generate 润色节点使用的轻量模型",
    )
    LLM_BASE_URL: Optional[str] = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        description="LLM API 基础 URL",
    )

    ENABLE_THINKING: bool = Field(
        default=False,
        description="是否启用思考模式",
    )

    REVIEWER_API_KEY: Optional[str] = Field(
        default=None,
        description="审核员 API Key（请求头 X-Reviewer-Token）",
    )
    GAME_JWT_SECRET: Optional[str] = Field(
        default=None,
        description="游戏服签发 JWT 的密钥",
    )
    GAME_JWT_ALGORITHM: str = Field(
        default="HS256",
        description="游戏 JWT 签名算法",
    )

    MYSQL_HOST: str = Field(default="127.0.0.1", description="MySQL 主机")
    MYSQL_PORT: int = Field(default=3307, description="MySQL 端口")
    MYSQL_USER: str = Field(default="game_support", description="MySQL 用户名")
    MYSQL_PASSWORD: str = Field(default="game_support_pass", description="MySQL 密码")
    MYSQL_DATABASE: str = Field(default="game_support", description="MySQL 数据库名")

    LANGCHAIN_TRACING_V2: bool = Field(
        default=False,
        description="是否启用 LangSmith 追踪",
    )
    LANGCHAIN_API_KEY: Optional[str] = Field(
        default=None,
        description="LangSmith API Key",
    )
    LANGCHAIN_PROJECT: str = Field(
        default="game-support-agent",
        description="LangSmith 项目名称",
    )

    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis 连接地址（pending_store；不可用时降级为内存）",
    )
    REDIS_PASSWORD: Optional[str] = Field(
        default=None,
        description="Redis 密码",
    )
    SESSION_TTL_SECONDS: int = Field(
        default=7200,
        description="客服会话 TTL（秒）",
    )
    HUMAN_USER_IDLE_SECONDS: int = Field(
        default=300,
        description="人工接待中用户空闲超时（秒）",
    )

    DB_PATH: str = Field(
        default="./data/game_support.db",
        description="SQLite 检查点数据库路径（LangGraph Agent 状态）",
    )

    LOG_LEVEL: str = Field(default="INFO", description="日志级别")

    @property
    def mysql_url(self) -> str:
        """SQLAlchemy / PyMySQL 连接串"""
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"
            f"?charset=utf8mb4"
        )

    @property
    def game_auth_disabled(self) -> bool:
        """本地开发：DEBUG 且未配置 JWT 密钥时跳过玩家鉴权"""
        return self.DEBUG and not self.GAME_JWT_SECRET

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """获取配置单例"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
