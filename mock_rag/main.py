"""
Mock RAG — 开源演示用知识库桩服务。

实现与本项目约定的 HTTP 契约，便于无企业 RAG 时一键跑通。
真实环境请将 RAG_SERVICE_URL 指向自有知识库服务。
"""

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="Mock RAG", version="1.0.0")

# 简单关键词命中，仅供本地演示
_KB = [
    {
        "keywords": ["原石", "祈愿", "抽卡"],
        "text": "原石可通过每日委托、活动奖励、深渊挑战和商店购买等方式获得，用于祈愿抽取角色与武器。",
        "score": 0.9,
        "source": "mock/faq_primogem.md",
    },
    {
        "keywords": ["封号", "解封", "申诉"],
        "text": "账号被封禁后可在客服渠道提交申诉，请提供 UID、大致封禁时间与相关说明，由人工核实处理。",
        "score": 0.88,
        "source": "mock/faq_ban_appeal.md",
    },
    {
        "keywords": ["充值", "到账", "退款"],
        "text": "充值未到账时请保留订单号与支付凭证，联系客服核实支付渠道状态；恶意退款可能导致账号限制。",
        "score": 0.86,
        "source": "mock/faq_payment.md",
    },
    {
        "keywords": ["换绑", "实名", "注销"],
        "text": "换绑与实名变更需通过官方账号安全流程办理；注销账号前请确认资产已处理完毕，注销后不可恢复。",
        "score": 0.85,
        "source": "mock/faq_account.md",
    },
]


class RetrieveRequest(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: int = Field(default=10, ge=1, le=20)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "mock-rag"}


@app.post("/api/v1/retrieve")
async def retrieve(req: RetrieveRequest):
    """约定契约：POST /api/v1/retrieve → {sources, max_score}（无 LLM 生成）"""
    q = req.question.strip()
    hits = []
    for item in _KB:
        if any(k in q for k in item["keywords"]):
            hits.append(
                {
                    "text": item["text"],
                    "source": item["source"],
                    "page": None,
                    "score": item["score"],
                }
            )
    hits = hits[: req.top_k]
    return {
        "query": q,
        "sources": hits,
        "max_score": max((h["score"] for h in hits), default=0.0),
        "retrieve_mode": "mock",
        "elapsed_ms": 1,
        "timing": {"total_ms": 1.0},
    }
