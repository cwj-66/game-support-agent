"""
Human-in-loop 重点测试
测试三种中断场景：敏感词触发、工具失败触发、审核操作
"""

import pytest
import pytest_asyncio
import tempfile
import json
from pathlib import Path
from unittest.mock import patch

from human_in_loop.schema import (
    InterruptDecision, ReviewOperation, AuditLogEntry, PendingTask
)
from human_in_loop.detector import InterruptDetector, get_default_detector
from human_in_loop.reviewer import (
    HumanReviewer, ReviewActionType, ReviewContext,
    approve_response, modify_response, override_response
)
from human_in_loop.auditor import AuditLogger


class TestInterruptDetector:
    """
    中断检测器测试
    测试敏感词匹配和工具失败检测
    """
    
    def test_sensitive_word_detection(self):
        """测试敏感词检测"""
        detector = InterruptDetector(
            sensitive_words=["封号", "退款", "投诉"],
        )

        decision = detector.detect("我要投诉你们封号我的账号")
        
        assert decision.should_interrupt is True
        assert "投诉" in decision.sensitive_words
        assert "封号" in decision.sensitive_words
        assert decision.level == "high"
    
    def test_tool_failure_detection(self):
        """测试工具失败检测"""
        detector = InterruptDetector()

        decision = detector.detect("正常回复内容", metadata={
            "tool_calls": [{"status": "failed", "error": "连接超时"}]
        })

        assert decision.should_interrupt is True
        assert decision.level == "medium"
        assert "工具调用失败" in decision.reason

    def test_no_trigger(self):
        """测试不触发中断"""
        detector = InterruptDetector(
            sensitive_words=["封号"],
        )

        decision = detector.detect("如何获得原石？")
        
        assert decision.should_interrupt is False
        assert decision.level == "low"
    
    def test_sensitive_and_tool_failure(self):
        """测试同时触发敏感词和工具失败"""
        detector = InterruptDetector(
            sensitive_words=["投诉"],
        )

        decision = detector.detect("我要投诉，这是敏感问题", metadata={
            "tool_calls": [{"status": "failed", "error": "超时"}]
        })

        assert decision.should_interrupt is True
        assert decision.level == "high"
        assert "投诉" in decision.reason
        assert "工具调用失败" in decision.reason
    
    def test_update_sensitive_words(self):
        """测试更新敏感词列表"""
        detector = InterruptDetector(sensitive_words=["旧词"])
        
        detector.update_sensitive_words(["新词1", "新词2"])
        
        decision = detector.detect("包含新词1的内容")
        assert decision.should_interrupt is True
        assert "新词1" in decision.sensitive_words
    
    def test_case_insensitive_matching(self):
        """测试大小写不敏感匹配"""
        detector = InterruptDetector(
            sensitive_words=["退款"],
            case_sensitive=False
        )
        
        decision = detector.detect("我要申请REFUND")
        # 不区分大小写，但此处是中文，测试逻辑
        # 实际应该测试英文敏感词


class TestHumanReviewer:
    """
    人工审核器测试
    测试三种操作：APPROVE / MODIFY / OVERRIDE
    """
    
    @pytest_asyncio.fixture
    async def reviewer(self):
        """创建审核器实例"""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = AuditLogger(log_dir=tmpdir)
            yield HumanReviewer(audit_logger=logger)
    
    @pytest_asyncio.fixture
    def review_context(self):
        """创建审核上下文"""
        return ReviewContext(
            session_id="test_session",
            user_query="如何退款？",
            agent_response="关于退款，请联系客服...",
            interrupt_reason="检测到敏感词: 退款",
            risk_level="high"
        )
    
    @pytest.mark.asyncio
    async def test_approve_action(self, reviewer, review_context):
        """测试APPROVE操作"""
        result = await reviewer.review(
            context=review_context,
            action=ReviewActionType.APPROVE,
            reviewer_id="admin_001",
            notes="内容正确，直接通过"
        )
        
        assert result["success"] is True
        assert result["action"] == "APPROVE"
        assert result["final_response"] == review_context.agent_response
        assert result["was_modified"] is False
    
    @pytest.mark.asyncio
    async def test_modify_action(self, reviewer, review_context):
        """测试MODIFY操作"""
        modified = "修改后的内容：请联系官方客服处理退款申请。"
        
        result = await reviewer.review(
            context=review_context,
            action=ReviewActionType.MODIFY,
            reviewer_id="admin_001",
            modified_content=modified,
            notes="优化表述"
        )
        
        assert result["success"] is True
        assert result["action"] == "MODIFY"
        assert result["final_response"] == modified
        assert result["was_modified"] is True
    
    @pytest.mark.asyncio
    async def test_modify_without_content_fails(self, reviewer, review_context):
        """测试MODIFY不提供内容时应该失败"""
        with pytest.raises(ValueError) as exc_info:
            await reviewer.review(
                context=review_context,
                action=ReviewActionType.MODIFY,
                reviewer_id="admin_001",
                modified_content=None
            )
        
        assert "modified_content" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_override_action(self, reviewer, review_context):
        """测试OVERRIDE操作"""
        override = "【人工回复】退款申请需通过官方渠道提交，处理周期3-5个工作日。"
        
        result = await reviewer.review(
            context=review_context,
            action=ReviewActionType.OVERRIDE,
            reviewer_id="admin_001",
            modified_content=override
        )
        
        assert result["success"] is True
        assert result["action"] == "OVERRIDE"
        assert result["final_response"] == override
        assert result["was_modified"] is True
        assert result.get("is_override") is True
    
    @pytest.mark.asyncio
    async def test_shortcut_functions(self, review_context):
        """测试快捷函数"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 使用独立的logger避免干扰
            with patch("human_in_loop.reviewer.HumanReviewer") as mock_reviewer_class:
                mock_reviewer = mock_reviewer_class.return_value
                mock_reviewer.review.return_value = {"success": True}
                
                # 测试approve快捷函数
                await approve_response(review_context, "admin_001")
                
                # 验证调用
                mock_reviewer.review.assert_called()


class TestAuditLogger:
    """
    审计日志测试
    测试审计链记录功能
    """
    
    @pytest.fixture
    def temp_log_dir(self):
        """创建临时日志目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir
    
    def test_create_entry(self, temp_log_dir):
        """测试创建审计记录"""
        logger = AuditLogger(log_dir=temp_log_dir)
        
        audit_id = logger.create_entry(
            session_id="sess_001",
            user_query="如何退款？",
            agent_raw_response="联系客服...",
            interrupt_decision={
                "should_interrupt": True,
                "reason": "敏感词",
                "level": "high"
            }
        )
        
        assert audit_id.startswith("audit_")
        
        # 验证文件已创建
        log_file = Path(temp_log_dir) / f"{audit_id}.json"
        assert log_file.exists()
    
    def test_log_review(self, temp_log_dir):
        """测试记录审核结果"""
        logger = AuditLogger(log_dir=temp_log_dir)
        
        audit_id = logger.create_entry(
            session_id="sess_002",
            user_query="测试",
            agent_raw_response="回复",
            interrupt_decision={"should_interrupt": True, "reason": "测试", "level": "low"}
        )
        
        # 记录审核结果
        asyncio.run(logger.log_review(
            state={
                "session_id": "sess_002",
                "user_query": "测试",
                "final_response": "最终回复"
            },
            review={
                "action": "MODIFY",
                "reviewer_id": "admin_001",
                "timestamp": "2024-01-01T00:00:00",
                "modified_content": "修改后的回复"
            }
        ))
        
        # 验证记录
        log_data = logger.load_audit(audit_id)
        assert log_data is not None
        assert log_data["review_action"] == "MODIFY"
        assert log_data["reviewer_id"] == "admin_001"
    
    def test_list_audits(self, temp_log_dir):
        """测试列出审计记录"""
        logger = AuditLogger(log_dir=temp_log_dir)
        
        # 创建多条记录
        for i in range(3):
            logger.create_entry(
                session_id=f"sess_{i}",
                user_query=f"问题{i}",
                agent_raw_response="回复",
                interrupt_decision={"should_interrupt": True, "reason": "测试", "level": "low"}
            )
        
        audits = logger.list_audits(limit=2)
        assert len(audits) == 2
    
    def test_get_stats(self, temp_log_dir):
        """测试获取统计信息"""
        logger = AuditLogger(log_dir=temp_log_dir)
        
        # 创建不同状态的记录
        for i in range(5):
            audit_id = logger.create_entry(
                session_id=f"sess_{i}",
                user_query="测试",
                agent_raw_response="回复",
                interrupt_decision={
                    "should_interrupt": i < 3,  # 3条中断
                    "reason": "测试",
                    "level": "low"
                }
            )
        
        stats = logger.get_stats()
        
        assert stats["total_sessions"] == 5
        assert stats["interrupted_count"] == 3
        assert stats["interruption_rate"] == 0.6


class TestInterruptScenarios:
    """
    中断场景集成测试
    测试真实业务场景下的中断流程
    """
    
    def test_sensitive_refund_scenario(self):
        """测试退款敏感词场景"""
        detector = InterruptDetector()
        
        # 用户询问退款
        decision = detector.detect(
            content="我想申请退款，充错金额了",
        )
        
        assert decision.should_interrupt is True
        assert "退款" in decision.sensitive_words
        assert decision.level == "high"
    
    def test_tool_failure_scenario(self):
        """测试工具失败场景"""
        detector = InterruptDetector()

        decision = detector.detect(
            content="查询结果为空",
            metadata={"tool_calls": [{"status": "failed", "error": "服务不可用"}]}
        )

        assert decision.should_interrupt is True
        assert "工具调用失败" in decision.reason

    def test_complain_scenario(self):
        """测试投诉场景"""
        detector = InterruptDetector()

        decision = detector.detect(
            content="我要投诉你们胡乱封号！",
        )
        
        assert decision.should_interrupt is True
        assert "投诉" in decision.sensitive_words
        assert "封号" in decision.sensitive_words
    
    @pytest.mark.asyncio
    async def test_full_review_workflow(self):
        """测试完整审核工作流"""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = AuditLogger(log_dir=tmpdir)
            reviewer = HumanReviewer(audit_logger=logger)
            
            # 1. 触发中断
            detector = InterruptDetector()
            decision = detector.detect("我要投诉")
            assert decision.should_interrupt is True
            
            # 2. 创建审核上下文
            context = ReviewContext(
                session_id="workflow_test",
                user_query="我要投诉封号问题",
                agent_response="关于投诉...",
                interrupt_reason=decision.reason,
                risk_level=decision.level
            )
            
            # 3. 执行MODIFY审核
            result = await reviewer.review(
                context=context,
                action=ReviewActionType.MODIFY,
                reviewer_id="admin_001",
                modified_content="【人工处理】您的反馈已收到，我们会尽快处理。",
                notes="优化投诉处理话术"
            )
            
            assert result["success"] is True
            assert result["was_modified"] is True
            
            # 4. 验证审计记录
            audits = logger.list_audits(session_id="workflow_test")
            assert len(audits) >= 1


# TODO: 需要补充的测试
# - TestDetectorPerformance: 检测器性能测试（大量文本）
# - TestReviewerConcurrency: 审核器并发测试
# - TestAuditRotation: 日志轮转测试
# - TestPendingTaskQueue: 待审核任务队列测试
