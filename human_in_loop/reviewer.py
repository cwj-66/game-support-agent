"""
人工审核操作模块
实现三种操作枚举：APPROVE / MODIFY / OVERRIDE
每种操作对应不同的状态转移逻辑
"""

from typing import Optional, Dict, Any, Callable
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime

from .schema import ReviewAction, ReviewOperation
from .auditor import AuditLogger


class ReviewActionType(Enum):
    """
    人工审核操作类型枚举
    
    三种核心操作：
    - APPROVE: 通过，原样使用Agent回复
    - MODIFY: 修改后通过，使用人工编辑的版本
    - OVERRIDE: 覆盖，人工完全重写回复
    """
    APPROVE = "APPROVE"
    MODIFY = "MODIFY"
    OVERRIDE = "OVERRIDE"


@dataclass
class ReviewContext:
    """
    审核上下文
    
    包含审核所需的所有信息
    """
    session_id: str
    user_query: str
    agent_response: str
    interrupt_reason: str
    risk_level: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class HumanReviewer:
    """
    人工审核处理器
    
    职责：
    1. 处理三种审核操作
    2. 应用不同操作的状态转移逻辑
    3. 记录操作到审计日志
    
    操作差异：
    - APPROVE:  final_response = agent_response
    - MODIFY:   final_response = modified_content（人工编辑版）
    - OVERRIDE: final_response = modified_content（人工全新编写）
    """
    
    def __init__(self, audit_logger: Optional[AuditLogger] = None):
        self.audit_logger = audit_logger or AuditLogger()
        self._action_handlers: Dict[ReviewActionType, Callable] = {
            ReviewActionType.APPROVE: self._handle_approve,
            ReviewActionType.MODIFY: self._handle_modify,
            ReviewActionType.OVERRIDE: self._handle_override,
        }
    
    async def review(
        self,
        context: ReviewContext,
        action: ReviewActionType,
        reviewer_id: str,
        modified_content: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        执行人工审核
        
        Args:
            context: 审核上下文
            action: 操作类型
            reviewer_id: 审核员ID
            modified_content: 修改后的内容（MODIFY/OVERRIDE时使用）
            notes: 审核备注
            
        Returns:
            处理结果，包含final_response等
        """
        # 获取操作处理器
        handler = self._action_handlers.get(action)
        if not handler:
            raise ValueError(f"未知的操作类型: {action}")
        
        # 执行操作处理
        result = handler(context, modified_content)
        
        # 创建操作记录
        operation = ReviewOperation(
            action=action.value,
            reviewer_id=reviewer_id,
            timestamp=datetime.utcnow().isoformat(),
            modified_content=result.get("modified_content"),
            notes=notes,
            approved=result.get("approved", False)
        )
        
        # 记录审计日志
        await self._log_audit(context, operation, result)
        
        return {
            "success": True,
            "action": action.value,
            "final_response": result["final_response"],
            "was_modified": result.get("was_modified", False),
            "reviewer_id": reviewer_id,
            "timestamp": operation.timestamp
        }
    
    def _handle_approve(
        self, 
        context: ReviewContext, 
        modified_content: Optional[str]
    ) -> Dict[str, Any]:
        """
        处理APPROVE操作
        
        直接通过，不做任何修改
        """
        return {
            "final_response": context.agent_response,
            "approved": True,
            "was_modified": False,
            "modified_content": None
        }
    
    def _handle_modify(
        self, 
        context: ReviewContext, 
        modified_content: Optional[str]
    ) -> Dict[str, Any]:
        """
        处理MODIFY操作
        
        使用人工修改后的版本
        """
        if not modified_content:
            raise ValueError("MODIFY操作必须提供modified_content")
        
        return {
            "final_response": modified_content,
            "approved": True,
            "was_modified": True,
            "modified_content": modified_content
        }
    
    def _handle_override(
        self, 
        context: ReviewContext, 
        modified_content: Optional[str]
    ) -> Dict[str, Any]:
        """
        处理OVERRIDE操作
        
        人工完全重写回复
        """
        if not modified_content:
            raise ValueError("OVERRIDE操作必须提供modified_content")
        
        return {
            "final_response": modified_content,
            "approved": True,
            "was_modified": True,
            "modified_content": modified_content,
            "is_override": True  # 标记为覆盖操作
        }
    
    async def _log_audit(
        self,
        context: ReviewContext,
        operation: ReviewOperation,
        result: Dict[str, Any]
    ):
        """记录审计日志"""
        try:
            await self.audit_logger.log_review_operation(
                session_id=context.session_id,
                user_query=context.user_query,
                agent_raw_response=context.agent_response,
                operation=operation,
                final_response=result["final_response"],
                interrupt_reason=context.interrupt_reason,
                interrupt_level=context.risk_level
            )
        except Exception as e:
            # 审计失败不应中断主流程
            print(f"[Warning] 审计日志记录失败: {e}")


# 快捷函数

async def approve_response(
    context: ReviewContext,
    reviewer_id: str,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """快捷函数：通过Agent回复"""
    reviewer = HumanReviewer()
    return await reviewer.review(
        context=context,
        action=ReviewActionType.APPROVE,
        reviewer_id=reviewer_id,
        notes=notes
    )


async def modify_response(
    context: ReviewContext,
    reviewer_id: str,
    modified_content: str,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """快捷函数：修改后通过"""
    reviewer = HumanReviewer()
    return await reviewer.review(
        context=context,
        action=ReviewActionType.MODIFY,
        reviewer_id=reviewer_id,
        modified_content=modified_content,
        notes=notes
    )


async def override_response(
    context: ReviewContext,
    reviewer_id: str,
    override_content: str,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """快捷函数：完全覆盖回复"""
    reviewer = HumanReviewer()
    return await reviewer.review(
        context=context,
        action=ReviewActionType.OVERRIDE,
        reviewer_id=reviewer_id,
        modified_content=override_content,
        notes=notes
    )


# TODO: 未来扩展
# - 实现批量审核支持
# - 添加审核员权限控制
# - 实现审核质量评分机制
