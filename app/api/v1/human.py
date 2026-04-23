"""
人工审核操作API
审核员对Agent输出进行APPROVE/MODIFY/OVERRIDE操作
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, Path

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    HumanReviewNotPendingException,
    SessionNotFoundException,
    ValidationException
)
from app.models.review import (
    ReviewAction,
    ReviewResponse,
    PendingReviewsResponse,
    ReviewTask,
    ReviewHistoryResponse,
    ReviewHistoryItem
)


router = APIRouter(prefix="/human", tags=["人工审核"])


@router.get("/pending", response_model=PendingReviewsResponse)
async def list_pending_reviews(
    settings: Settings = Depends(get_settings)
) -> PendingReviewsResponse:
    """
    获取待审核任务列表
    
    返回所有等待人工审核的对话任务
    """
    # TODO: 从内存/Redis/数据库查询待审核任务
    # TODO: 实现任务排序（优先级、等待时间）
    
    # 模拟数据
    mock_tasks = [
        ReviewTask(
            review_id="rev_001",
            session_id="sess_123",
            user_query="如何申请退款？",
            agent_response="关于退款...",
            interrupt_reason="检测到敏感词: 退款",
            risk_level="high",
            created_at="2024-01-01T10:00:00",
            wait_time_seconds=300
        )
    ]
    
    return PendingReviewsResponse(
        total=len(mock_tasks),
        items=mock_tasks
    )


@router.post("/review/{session_id}", response_model=ReviewResponse)
async def submit_review(
    session_id: str,
    action: ReviewAction,
    settings: Settings = Depends(get_settings)
) -> ReviewResponse:
    """
    提交人工审核操作
    
    三种操作类型：
    - APPROVE: 原样通过Agent的回复
    - MODIFY: 修改后通过
    - OVERRIDE: 人工完全重写回复
    
    流程：
    1. 验证session_id存在且有待审核内容
    2. 验证操作参数
    3. 应用审核结果到Agent状态
    4. 继续执行Agent图
    5. 记录审计日志
    6. 返回结果
    """
    # 参数校验
    if action.action in ["MODIFY", "OVERRIDE"] and not action.modified_content:
        raise ValidationException(
            "MODIFY和OVERRIDE操作必须提供modified_content",
            field="modified_content"
        )
    
    # TODO: 检查session是否有待审核内容
    # TODO: 调用human_node继续执行
    # TODO: 记录审计日志
    
    # 确定最终回复内容
    if action.action == "APPROVE":
        final_response = "[原Agent回复内容]"
    else:
        final_response = action.modified_content or "[人工处理]"
    
    return ReviewResponse(
        success=True,
        review_id=f"rev_{session_id}",
        session_id=session_id,
        action=action.action,
        final_response=final_response,
        processed_at="2024-01-01T00:00:00"  # TODO: 真实时间
    )


@router.get("/history", response_model=ReviewHistoryResponse)
async def get_review_history(
    reviewer_id: str = None,
    limit: int = 50,
    settings: Settings = Depends(get_settings)
) -> ReviewHistoryResponse:
    """
    获取审核历史
    
    可按审核员筛选，支持分页
    """
    # TODO: 从审计日志查询历史
    # TODO: 实现分页
    
    return ReviewHistoryResponse(
        total=0,
        items=[]
    )


@router.get("/status/{session_id}")
async def get_review_status(
    session_id: str = Path(..., description="会话ID"),
    settings: Settings = Depends(get_settings)
):
    """
    查询会话的审核状态
    
    返回：
    - 是否需要审核
    - 当前审核进度
    - 审核历史
    """
    # TODO: 查询会话的审核状态
    
    return {
        "session_id": session_id,
        "has_pending_review": False,
        "pending_review_id": None,
        "review_history": []
    }


# TODO: 未来扩展
# - 添加批量审核API
# - 添加审核任务分配API（分配给特定审核员）
# - 添加审核统计API
