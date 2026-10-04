"""pydantic-settings 环境变量配置。"""

from typing import List, Literal, Optional
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
        default="qwen3.8-max-0902",
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

    SQLITE_BUSY_TIMEOUT_MS: int = Field(default=5000, description="SQLite 写锁等待上限（毫秒）")

    LOG_LEVEL: str = Field(default="INFO", description="日志级别")

    # --- 跨进程协调：容量、会话锁、频率限制、幂等 ---
    COORDINATION_BACKEND: Literal["redis", "memory"] = Field(
        default="redis",
        description="redis=生产（跨进程）；memory=仅单进程开发/测试，不能用于多 worker",
    )
    AGENT_MAX_CONCURRENCY: int = Field(default=3, ge=1, description="全站同时执行的完整问答数")
    AGENT_MAX_QUEUE: int = Field(default=10, ge=0, description="全站最多排队问答数")
    AGENT_QUEUE_TIMEOUT_SECONDS: float = Field(default=60, gt=0, description="排队最长等待秒数")
    AGENT_LEASE_SECONDS: float = Field(default=30, gt=0, description="执行名额租约时长，执行期间按 1/3 周期续租")
    AGENT_EXEC_TIMEOUT_SECONDS: float = Field(default=90, gt=0, description="单个问答执行上限（不含排队）")
    AGENT_QUEUE_POLL_SECONDS: float = Field(default=0.5, gt=0, description="排队轮询间隔")
    SSE_HEARTBEAT_SECONDS: float = Field(default=15, gt=0, description="SSE 心跳间隔")
    SESSION_LOCK_TTL_SECONDS: float = Field(default=30, gt=0, description="会话锁租约，持有期间续租")
    SESSION_LOCK_WAIT_SECONDS: float = Field(default=2, ge=0, description="短写入抢会话锁的等待秒数")
    IDEMPOTENCY_TTL_SECONDS: int = Field(default=600, gt=0, description="幂等结果保留秒数")
    CHAT_RATE_LIMIT_PER_MINUTE: int = Field(default=10, ge=1, description="每个访客每分钟聊天提交次数")
    CHAT_RATE_LIMIT_PER_IP_PER_MINUTE: int = Field(default=30, ge=1, description="每个客户端 IP 每分钟提交上限（防清 cookie 绕过）")
    TRUSTED_PROXY_CIDRS: str = Field(
        default="127.0.0.1/32,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16",
        description="可信反向代理网段；只有直连对端在此范围内才读取转发头",
    )

    # --- 云端调用超时、重试与熔断 ---
    LLM_CONNECT_TIMEOUT_SECONDS: float = Field(default=5, gt=0, description="Qwen 连接超时")
    LLM_READ_TIMEOUT_SECONDS: float = Field(default=30, gt=0, description="Qwen 单次读取超时")
    LLM_MAX_CONNECTIONS: int = Field(default=10, ge=1, description="Qwen HTTP 连接池上限")
    UPSTREAM_MAX_RETRIES: int = Field(default=1, ge=0, le=2, description="临时错误的最大重试次数")
    UPSTREAM_RETRY_MAX_WAIT_SECONDS: float = Field(default=2, ge=0, description="单次重试最长退避（含 Retry-After）")
    MCP_TOOL_TIMEOUT_SECONDS: float = Field(default=15, gt=0, description="账号/工单 MCP 工具超时")
    MCP_KNOWLEDGE_TIMEOUT_SECONDS: float = Field(default=60, gt=0, description="知识查询 MCP 工具超时（含检索与作答）")
    RAG_TIMEOUT_SECONDS: float = Field(default=30, gt=0, description="RAG 检索 HTTP 超时")
    BREAKER_FAILURE_THRESHOLD: int = Field(default=5, ge=1, description="窗口内连续失败多少次后熔断")
    BREAKER_WINDOW_SECONDS: float = Field(default=60, gt=0, description="熔断统计窗口")
    BREAKER_OPEN_SECONDS: float = Field(default=30, gt=0, description="熔断打开时长，之后放行一个探测请求")

    # --- MySQL 连接池与阻塞线程池 ---
    MYSQL_POOL_SIZE: int = Field(default=5, ge=1, description="每进程 MySQL 连接上限")
    MYSQL_POOL_TIMEOUT_SECONDS: float = Field(default=5, gt=0, description="等待空闲连接上限")
    MYSQL_CONNECT_TIMEOUT_SECONDS: int = Field(default=5, ge=1, description="MySQL 建连超时")
    MYSQL_READ_TIMEOUT_SECONDS: int = Field(default=10, ge=1, description="MySQL 读写超时")
    MYSQL_POOL_RECYCLE_SECONDS: int = Field(default=1800, ge=60, description="连接最长复用时间")
    BLOCKING_POOL_SIZE: int = Field(default=4, ge=1, description="同步数据库调用使用的线程上限")

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
