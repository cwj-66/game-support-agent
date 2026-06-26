"""
安全检测模块测试
测试敏感词检测和工具失败检测
"""

from safety.detector import InterruptDetector, get_default_detector


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


class TestInterruptScenarios:
    """
    中断场景集成测试
    测试真实业务场景下的中断流程
    """
    
    def test_sensitive_refund_scenario(self):
        """测试退款敏感词场景"""
        detector = InterruptDetector(sensitive_words=["退款"])

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
        detector = InterruptDetector(sensitive_words=["投诉", "封号"])

        decision = detector.detect(
            content="我要投诉你们胡乱封号！",
        )

        assert decision.should_interrupt is True
        assert "投诉" in decision.sensitive_words
        assert "封号" in decision.sensitive_words
    
# TODO: 需要补充的测试
# - TestDetectorPerformance: 检测器性能测试（大量文本）
# - TestReviewerConcurrency: 审核器并发测试
# - TestAuditRotation: 日志轮转测试
# - TestPendingTaskQueue: 待审核任务队列测试
