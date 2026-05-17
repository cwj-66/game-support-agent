"""
Streamlit 可视化审核界面
为人工审核员提供直观的任务队列和审核操作界面
"""

import streamlit as st
import httpx
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime


# 页面配置
st.set_page_config(
    page_title="游戏客服Agent审核台",
    page_icon="🎮",
    layout="wide",
    initial_sidebar_state="expanded"
)

# API配置
API_BASE_URL = "http://localhost:8002/api/v1"


class ReviewAPIClient:
    """审核API客户端封装"""
    
    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def get_pending_reviews(self) -> List[Dict[str, Any]]:
        """获取待审核任务列表"""
        try:
            response = await self.client.get(f"{self.base_url}/human/pending")
            response.raise_for_status()
            data = response.json()
            return data.get("items", [])
        except Exception as e:
            st.error(f"获取待审核任务失败: {e}")
            return []
    
    async def submit_review(
        self,
        session_id: str,
        action: str,
        reviewer_id: str,
        modified_content: Optional[str] = None
    ) -> bool:
        """提交审核操作"""
        try:
            payload = {
                "session_id": session_id,
                "action": action,
                "reviewer_id": reviewer_id
            }
            if modified_content:
                payload["modified_content"] = modified_content
            
            response = await self.client.post(
                f"{self.base_url}/human/review/{session_id}",
                json=payload
            )
            response.raise_for_status()
            return True
        except Exception as e:
            st.error(f"提交审核失败: {e}")
            return False
    
    async def close(self):
        await self.client.aclose()


# 初始化客户端
@st.cache_resource
def get_api_client():
    return ReviewAPIClient()


# ============ 页面组件 ============

def render_header():
    """渲染页面头部"""
    st.title("🎮 游戏客服Agent审核台")
    st.markdown("---")


def render_sidebar():
    """渲染侧边栏"""
    with st.sidebar:
        st.header("⚙️ 设置")
        
        # 审核员ID
        reviewer_id = st.text_input(
            "审核员ID",
            value=st.session_state.get("reviewer_id", "admin_001"),
            help="您的审核员标识"
        )
        st.session_state["reviewer_id"] = reviewer_id
        
        st.markdown("---")
        
        # 统计信息
        st.header("📊 统计")
        st.metric("待审核任务", st.session_state.get("pending_count", 0))
        st.metric("今日已审核", st.session_state.get("today_reviewed", 0))
        
        st.markdown("---")
        
        # 刷新按钮
        if st.button("🔄 刷新任务列表", use_container_width=True):
            st.rerun()


def render_risk_badge(level: str) -> str:
    """渲染风险等级标签"""
    colors = {
        "high": "🔴 高风险",
        "medium": "🟡 中风险",
        "low": "🟢 低风险"
    }
    return colors.get(level, "⚪ 未知")


def render_pending_tasks():
    """渲染待审核任务列表"""
    st.header("📋 待审核任务")
    
    client = get_api_client()
    
    # 异步获取任务
    with st.spinner("加载中..."):
        tasks = asyncio.run(client.get_pending_reviews())
    
    st.session_state["pending_count"] = len(tasks)
    
    if not tasks:
        st.info("暂无待审核任务 🎉")
        return
    
    # 显示任务列表
    for task in tasks:
        with st.expander(
            f"[{render_risk_badge(task.get('risk_level'))}] "
            f"{task.get('user_query', '无问题')[:50]}...",
            expanded=False
        ):
            render_task_detail(task)


def render_task_detail(task: Dict[str, Any]):
    """渲染单个任务详情"""
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("用户问题")
        st.info(task.get("user_query", "无"))
        
        st.subheader("Agent回复")
        st.warning(task.get("agent_response", "无"))
        
        st.subheader("触发原因")
        st.error(task.get("interrupt_reason", "未知"))
    
    with col2:
        st.subheader("审核操作")
        
        reviewer_id = st.session_state.get("reviewer_id", "admin_001")
        session_id = task.get("session_id")
        
        # 修改内容输入（MODIFY和OVERRIDE时使用）
        modified_content = st.text_area(
            "修改后的内容（如需修改）",
            value=task.get("agent_response", ""),
            height=150,
            key=f"modify_{session_id}"
        )
        
        # 操作按钮
        btn_col1, btn_col2, btn_col3 = st.columns(3)
        
        with btn_col1:
            if st.button("✅ 通过", key=f"approve_{session_id}", use_container_width=True):
                asyncio.run(client.submit_review(
                    session_id, "APPROVE", reviewer_id
                ))
                st.success("已通过")
                st.rerun()
        
        with btn_col2:
            if st.button("✏️ 修改", key=f"modify_{session_id}", use_container_width=True):
                if not modified_content or modified_content == task.get("agent_response"):
                    st.error("请先修改内容")
                else:
                    asyncio.run(client.submit_review(
                        session_id, "MODIFY", reviewer_id, modified_content
                    ))
                    st.success("已修改并通过")
                    st.rerun()
        
        with btn_col3:
            if st.button("📝 覆盖", key=f"override_{session_id}", use_container_width=True):
                if not modified_content:
                    st.error("覆盖操作需要填写新内容")
                else:
                    asyncio.run(client.submit_review(
                        session_id, "OVERRIDE", reviewer_id, modified_content
                    ))
                    st.success("已覆盖")
                    st.rerun()


def render_audit_history():
    """渲染审核历史"""
    st.header("📜 审核历史")
    st.info("（该功能需要后端API支持）")
    # TODO: 实现审核历史展示


def render_help():
    """渲染帮助信息"""
    with st.expander("❓ 使用帮助"):
        st.markdown("""
        ### 操作说明
        
        **三种审核操作：**
        - **✅ 通过 (APPROVE)**: 直接通过Agent的回复，不做修改
        - **✏️ 修改 (MODIFY)**: 在Agent回复基础上修改后通过
        - **📝 覆盖 (OVERRIDE)**: 完全重写回复（使用新内容）
        
        **风险等级：**
        - 🔴 高风险：包含敏感词或严重问题，必须人工审核
        - 🟡 中风险：工具执行异常，建议人工确认
        - 🟢 低风险：一般性内容
        
        **快捷操作：**
        - 点击任务展开查看详情
        - 使用左侧刷新按钮更新任务列表
        """)


# ============ 主页面 ============

def main():
    """主页面"""
    render_header()
    render_sidebar()
    
    # 选项卡
    tab1, tab2, tab3 = st.tabs(["待审核任务", "审核历史", "帮助"])
    
    with tab1:
        render_pending_tasks()
    
    with tab2:
        render_audit_history()
    
    with tab3:
        render_help()


if __name__ == "__main__":
    client = get_api_client()
    try:
        main()
    finally:
        asyncio.run(client.close())
