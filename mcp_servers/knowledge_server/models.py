"""
MCP Server 请求/响应 Pydantic 模型
定义与RAG服务交互的数据结构
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum


class KnowledgeSource(str, Enum):
    """知识来源类型"""
    FAQ = "faq"
    DOCUMENTATION = "documentation"
    POLICY = "policy"


class QueryRequest(BaseModel):
    """
    向RAG服务发起查询的请求模型
    
    Attributes:
        question: 用户问题
        top_k: 返回结果数量
        source_filter: 可选的知识来源过滤
    """
    question: str = Field(..., description="用户查询问题", min_length=1)
    top_k: int = Field(default=3, ge=1, le=10, description="返回最相关的K条结果")
    source_filter: Optional[List[KnowledgeSource]] = Field(
        default=None, 
        description="限定搜索的知识来源类型"
    )


class KnowledgeChunk(BaseModel):
    """
    RAG返回的单条知识片段
    
    Attributes:
        content: 知识内容
        source: 来源文档
        score: 相似度分数
        metadata: 额外元数据
    """
    content: str = Field(..., description="检索到的知识内容")
    source: str = Field(..., description="来源文档名称")
    score: float = Field(..., ge=0.0, le=1.0, description="相似度分数")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="额外元数据")


class QueryResponse(BaseModel):
    """
    RAG服务查询响应模型
    
    Attributes:
        query: 原始查询
        results: 知识片段列表
        total_found: 找到的结果总数
        has_answer: 是否有足够置信度的答案
    """
    query: str = Field(..., description="原始查询问题")
    results: List[KnowledgeChunk] = Field(default_factory=list, description="检索结果列表")
    total_found: int = Field(default=0, description="找到的结果总数")
    has_answer: bool = Field(default=False, description="是否有足够置信度的答案")
    
    def get_best_answer(self) -> Optional[str]:
        """获取最佳答案（分数最高的）"""
        if not self.results:
            return None
        best = max(self.results, key=lambda x: x.score)
        return best.content if best.score > 0.5 else None


class HealthResponse(BaseModel):
    """RAG服务健康检查响应"""
    status: str = Field(..., description="服务状态: healthy/degraded/down")
    version: Optional[str] = Field(default=None, description="RAG服务版本")
    latency_ms: Optional[float] = Field(default=None, description="响应延迟")


# TODO: 未来扩展模型
# - Add FeedbackRequest: 用户反馈模型（点赞/点踩）
# - Add ContextRequest: 多轮对话上下文模型
