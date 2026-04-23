"""
Human-in-loop 核心节点
使用LangGraph的interrupt()实现真正的断点暂停
保存完整状态到checkpointer，支持人工操作后恢复
"""

from typing import Dict, Any, Optional
from langgraph.types import interrupt

from ..state import AgentState, HumanReviewResult
from human_in_loop.detector import InterruptDetector, InterruptDecision
from human_in_loop.reviewer import ReviewAction
from human_in_loop.auditor import AuditLogger


async def human_node(state: AgentState) -> Dict[str, Any]:
    """
    人工审核节点：触发中断并等待人工介入
    
    这是Human-in-loop机制的核心实现：
    1. 使用LangGraph的interrupt()暂停图执行
    2. 保存完整AgentState到checkpointer
    3. 等待人工操作（APPROVE/MODIFY/OVERRIDE）
    4. 恢复执行并应用审核结果
    
    节点流程：
    - 进入 → 触发interrupt → 状态持久化 → 等待人工操作
    - 人工操作 → 读取状态 → 应用审核结果 → 继续执行
    
    Args:
        state: 当前Agent状态（包含final_response等待审核）
        
    Returns:
        应用人工审核结果后的状态更新
        
    TODO:
    - 接入真实interrupt机制
    - 实现状态恢复时的校验逻辑
    - 添加超时处理（人工长时间未响应）
    """
    session_id = state["session_id"]
    final_response = state.get("final_response")
    interrupt_info = state.get("interrupt_info")
    
    # 准备中断参数
    interrupt_payload = {
        "session_id": session_id,
        "content": final_response,
        "interrupt_reason": interrupt_info.get("reason") if interrupt_info else None,
        "interrupt_level": interrupt_info.get("level") if interrupt_info else None,
        "waiting_for": "human_review",
        "options": ["APPROVE", "MODIFY", "OVERRIDE"],
        "timestamp": "2024-01-01T00:00:00"  # TODO: 真实时间
    }
    
    # 触发LangGraph中断
    # 这会暂停图执行，保存状态到checkpointer
    # 返回值为人工操作后的结果
    print(f"[Human Node] 触发中断，等待人工审核: {session_id}")
    
    # 使用LangGraph的interrupt函数
    # 真实实现时使用: human_result = interrupt(interrupt_payload)
    
    # TODO: 接入真实interrupt机制
    # human_result = interrupt(interrupt_payload)
    
    # 模拟人工审核结果（开发占位）
    human_result: HumanReviewResult = {
        "action": "APPROVE",
        "reviewer_id": "admin_001",
        "timestamp": "2024-01-01T00:01:00",
        "modified_content": None,
        "notes": "内容符合规范，通过",
        "approved": True
    }
    
    # 处理审核结果
    result = _apply_human_review(state, human_result)
    
    # 记录审计日志
    await _log_audit(state, human_result)
    
    return result


def _apply_human_review(
    state: AgentState, 
    review: HumanReviewResult
) -> Dict[str, Any]:
    """
    应用人工审核结果到状态
    
    三种操作的差异：
    - APPROVE: 原样通过，不修改内容
    - MODIFY: 使用人工修改后的内容替换
    - OVERRIDE: 人工直接给出最终答案（跳过Agent生成）
    
    Args:
        state: 当前状态
        review: 人工审核结果
        
    Returns:
        更新后的状态
    """
    action = review.get("action")
    final_response = state.get("final_response", "")
    
    if action == "APPROVE":
        # 直接通过，无需修改
        processed_response = final_response
        
    elif action == "MODIFY":
        # 使用人工修改的内容
        modified = review.get("modified_content")
        if modified:
            processed_response = modified
        else:
            # 人工没提供修改内容，保持原样
            processed_response = final_response
            
    elif action == "OVERRIDE":
        # 人工完全覆盖
        override_content = review.get("modified_content", "[人工接管回复]")
        processed_response = override_content
        
    else:
        # 未知操作，保持原样
        processed_response = final_response
    
    return {
        "human_review": review,
        "final_response": processed_response,
        "messages": [],  # 可以添加审核完成的系统消息
        "metadata": {
            **state.get("metadata", {}),
            "human_review_applied": True,
            "review_action": action,
            "processed_at": review.get("timestamp")
        }
    }


async def _log_audit(state: AgentState, review: HumanReviewResult):
    """记录人工审核审计日志"""
    try:
        logger = AuditLogger()
        await logger.log_review(state, review)
    except Exception as e:
        # 审计日志失败不应中断主流程
        print(f"[Warning] 审计日志记录失败: {e}")


def check_resume_state(state: AgentState) -> Optional[Dict[str, Any]]:
    """
    检查是否需要从断点恢复
    
    在图重新启动时调用，检查是否存在待恢复的中断状态
    
    Args:
        state: 当前传入的状态
        
    Returns:
        如果是恢复状态，返回恢复数据；否则None
        
    TODO:
    - 实现与checkpointer的集成
    - 添加状态完整性校验
    """
    # 检查状态是否包含恢复标记
    metadata = state.get("metadata", {})
    if metadata.get("resuming_from_interrupt"):
        return {
            "resumed": True,
            "previous_checkpoint": metadata.get("checkpoint_id")
        }
    return None


# TODO: 未来扩展
# - 实现超时自动拒绝机制
# - 添加多轮人工审核支持
# - 实现审核结果的事后分析
