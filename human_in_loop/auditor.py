"""
审计链记录模块
记录完整的Human-in-loop流程，支持事后追溯
"""

import json
import os
import uuid
from typing import Optional, Dict, Any, List
from datetime import datetime
from pathlib import Path

from .schema import AuditLogEntry, ReviewOperation, AuditLogEntryDict


class AuditLogger:
    """
    审计日志记录器
    
    职责：
    1. 记录中断触发事件
    2. 记录人工审核操作
    3. 保存完整审计链（JSON格式）
    
    审计日志包含：
    - 用户原始问题
    - Agent原始输出
    - 中断原因
    - 人工审核操作
    - 最终回复
    - 完整时间戳链
    
    TODO:
    - 生产环境改用数据库存储
    - 实现审计日志压缩归档
    """
    
    def __init__(self, log_dir: str = "./logs/audit"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # 内存中的临时缓存（未完成的审计记录）
        self._pending: Dict[str, AuditLogEntry] = {}
    
    def create_entry(
        self,
        session_id: str,
        user_query: str,
        agent_raw_response: str,
        interrupt_decision: Dict[str, Any]
    ) -> str:
        """
        创建新的审计记录
        
        在触发中断时调用，初始化审计记录
        
        Args:
            session_id: 会话ID
            user_query: 用户问题
            agent_raw_response: Agent原始输出
            interrupt_decision: 中断决策结果
            
        Returns:
            audit_id: 审计记录ID
        """
        audit_id = f"audit_{uuid.uuid4().hex[:12]}"
        
        entry = AuditLogEntry(
            audit_id=audit_id,
            session_id=session_id,
            user_query=user_query,
            agent_raw_response=agent_raw_response,
            interrupt_triggered=interrupt_decision.get("should_interrupt", False),
            interrupt_reason=interrupt_decision.get("reason", ""),
            interrupt_level=interrupt_decision.get("level", "low"),
            final_response="",  # 待填充
            metadata={
                "raw_decision": interrupt_decision
            }
        )
        
        self._pending[audit_id] = entry
        
        # 立即保存初始记录
        self._save_to_file(entry)
        
        return audit_id
    
    async def log_review(
        self,
        state: Dict[str, Any],
        review: Dict[str, Any]
    ) -> str:
        """
        记录人工审核结果
        
        Args:
            state: Agent状态（包含session_id等）
            review: 人工审核结果
            
        Returns:
            audit_id: 审计记录ID
        """
        session_id = state.get("session_id", "unknown")
        
        # 查找或创建审计记录
        audit_id = self._find_by_session(session_id)
        
        if audit_id and audit_id in self._pending:
            entry = self._pending[audit_id]
        else:
            # 创建新记录
            audit_id = f"audit_{uuid.uuid4().hex[:12]}"
            entry = AuditLogEntry(
                audit_id=audit_id,
                session_id=session_id,
                user_query=state.get("user_query", ""),
                agent_raw_response=state.get("final_response", ""),
                interrupt_triggered=True,
                interrupt_reason="human_review",
                interrupt_level="unknown"
            )
            self._pending[audit_id] = entry
        
        # 填充审核信息
        entry.review_action = review.get("action")
        entry.reviewer_id = review.get("reviewer_id")
        entry.review_timestamp = review.get("timestamp")
        entry.was_modified = review.get("action") in ["MODIFY", "OVERRIDE"]
        entry.final_response = review.get("modified_content") or state.get("final_response", "")
        entry.mark_completed()
        
        # 更新文件
        self._save_to_file(entry)
        
        # 从待处理列表移除
        if audit_id in self._pending:
            del self._pending[audit_id]
        
        return audit_id
    
    async def log_review_operation(
        self,
        session_id: str,
        user_query: str,
        agent_raw_response: str,
        operation: ReviewOperation,
        final_response: str,
        interrupt_reason: str,
        interrupt_level: str
    ) -> str:
        """
        记录完整的审核操作
        
        由HumanReviewer调用
        """
        audit_id = f"audit_{uuid.uuid4().hex[:12]}"
        
        entry = AuditLogEntry(
            audit_id=audit_id,
            session_id=session_id,
            user_query=user_query,
            agent_raw_response=agent_raw_response,
            interrupt_triggered=True,
            interrupt_reason=interrupt_reason,
            interrupt_level=interrupt_level,
            review_action=operation.action,
            reviewer_id=operation.reviewer_id,
            review_timestamp=operation.timestamp,
            was_modified=operation.action in ["MODIFY", "OVERRIDE"],
            final_response=final_response
        )
        entry.mark_completed()
        
        self._save_to_file(entry)
        
        return audit_id
    
    def _save_to_file(self, entry: AuditLogEntry):
        """保存审计记录到JSON文件"""
        filename = f"{entry.audit_id}.json"
        filepath = self.log_dir / filename
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(entry.to_dict(), f, ensure_ascii=False, indent=2)
    
    def _find_by_session(self, session_id: str) -> Optional[str]:
        """根据session_id查找待处理的audit_id"""
        for audit_id, entry in self._pending.items():
            if entry.session_id == session_id:
                return audit_id
        return None
    
    def load_audit(self, audit_id: str) -> Optional[AuditLogEntryDict]:
        """加载指定审计记录"""
        filepath = self.log_dir / f"{audit_id}.json"
        
        if not filepath.exists():
            return None
        
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data
    
    def list_audits(
        self,
        session_id: Optional[str] = None,
        reviewer_id: Optional[str] = None,
        limit: int = 100
    ) -> List[AuditLogEntryDict]:
        """
        列出审计记录
        
        Args:
            session_id: 按会话筛选
            reviewer_id: 按审核员筛选
            limit: 返回数量限制
        """
        results = []
        
        for filepath in sorted(self.log_dir.glob("audit_*.json"), reverse=True):
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                
                # 应用筛选条件
                if session_id and data.get("session_id") != session_id:
                    continue
                if reviewer_id and data.get("reviewer_id") != reviewer_id:
                    continue
                
                results.append(data)
                
                if len(results) >= limit:
                    break
        
        return results
    
    def get_stats(self) -> Dict[str, Any]:
        """获取审计统计信息"""
        all_audits = self.list_audits(limit=10000)
        
        total = len(all_audits)
        interrupted = sum(1 for a in all_audits if a.get("interrupt_triggered"))
        modified = sum(1 for a in all_audits if a.get("was_modified"))
        
        action_counts = {}
        for a in all_audits:
            action = a.get("review_action", "none")
            action_counts[action] = action_counts.get(action, 0) + 1
        
        return {
            "total_sessions": total,
            "interrupted_count": interrupted,
            "modified_count": modified,
            "interruption_rate": interrupted / total if total > 0 else 0,
            "modification_rate": modified / interrupted if interrupted > 0 else 0,
            "action_distribution": action_counts
        }


# 全局审计日志实例
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """获取审计日志实例"""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


# TODO: 未来扩展
# - 实现数据库存储后端
# - 添加审计日志加密
# - 实现日志自动归档
# - 添加实时监控指标输出
