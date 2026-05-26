"""
Streamlit 客服工作台
整合人工审核（Human-in-loop）+ 工单管理两个核心功能
"""

import streamlit as st
import httpx
import asyncio
from typing import Optional, Dict, Any


# 页面配置
st.set_page_config(
    page_title="游戏客服Agent工作台",
    page_icon="🎮",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_BASE_URL = "http://localhost:8002/api/v1"

# ── 常量 ──

STATUS_STYLE = {
    "pending": ("🕐", "等待处理", "#f0ad4e"),
    "processing": ("⏳", "处理中", "#5bc0de"),
    "resolved": ("✅", "已解决", "#5cb85c"),
    "escalated": ("🔴", "已升等", "#d9534f"),
}
PRIORITY_ORDER = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
PRIORITY_LABEL = {"urgent": "紧急", "high": "高", "medium": "中", "low": "低"}


# ============ API 客户端 ============

class ReviewAPIClient:
    """审核API客户端封装"""

    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url.rstrip("/")

    async def get_pending_reviews(self) -> list:
        try:
            async with httpx.AsyncClient(timeout=15.0) as c:
                r = await c.get(f"{self.base_url}/human/pending")
                r.raise_for_status()
                return r.json().get("items", [])
        except Exception as e:
            st.error(f"获取待审核任务失败: {e}")
            return []

    async def submit_review(
        self, session_id: str, action: str, reviewer_id: str, modified_content: str | None = None
    ) -> bool:
        try:
            payload = {
                "session_id": session_id,
                "action": action,
                "reviewer_id": reviewer_id,
            }
            if modified_content:
                payload["modified_content"] = modified_content
            async with httpx.AsyncClient(timeout=15.0) as c:
                r = await c.post(f"{self.base_url}/human/review/{session_id}", json=payload)
                r.raise_for_status()
            return True
        except Exception as e:
            st.error(f"提交审核失败: {e}")
            return False


class TicketClient:
    """工单API客户端封装"""

    async def _get(self, path: str, params: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(f"{API_BASE_URL}{path}", params=params)
            r.raise_for_status()
            return r.json()

    async def _patch(self, path: str, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.patch(f"{API_BASE_URL}{path}", json=payload)
            r.raise_for_status()
            return r.json()

    async def list_tickets(
        self, status: str | None = None, player_uid: str | None = None, page: int = 1
    ) -> dict:
        params = {"page": page, "page_size": 20}
        if status:
            params["status"] = status
        if player_uid:
            params["player_uid"] = player_uid
        return await self._get("/ticket/list", params)

    async def get_ticket(self, ticket_id: str) -> dict | None:
        try:
            return await self._get(f"/ticket/{ticket_id}")
        except Exception:
            return None

    async def update_ticket(
        self,
        ticket_id: str,
        status: str | None = None,
        agent_reply: str | None = None,
        reviewer_id: str | None = None,
    ) -> bool:
        payload: dict = {}
        if status is not None:
            payload["status"] = status
        if agent_reply is not None and agent_reply.strip():
            payload["agent_reply"] = agent_reply
        if reviewer_id is not None:
            payload["reviewer_id"] = reviewer_id
        if not payload:
            return False
        try:
            await self._patch(f"/ticket/{ticket_id}", payload)
            return True
        except Exception as e:
            st.error(f"更新工单失败: {e}")
            return False

    async def stats(self) -> dict:
        try:
            return await self._get("/ticket/stats")
        except Exception:
            return {}


# ============ Tab 1：待审核任务（Human-in-loop）============

def render_risk_badge(level: str) -> str:
    colors = {"high": "🔴 高风险", "medium": "🟡 中风险", "low": "🟢 低风险"}
    return colors.get(level, "⚪ 未知")


def render_pending_tasks(client: ReviewAPIClient):
    st.header("📋 待审核任务")

    with st.spinner("加载中..."):
        tasks = asyncio.run(client.get_pending_reviews())

    st.session_state["pending_count"] = len(tasks)

    if not tasks:
        st.info("暂无待审核任务 🎉")
        return

    for task in tasks:
        with st.expander(
            f"[{render_risk_badge(task.get('risk_level'))}] "
            f"{task.get('user_query', '无问题')[:50]}...",
            expanded=False,
        ):
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

                modified_content = st.text_area(
                    "修改后的内容（如需修改）",
                    value=task.get("agent_response", ""),
                    height=150,
                    key=f"modify_{session_id}",
                )

                btn_col1, btn_col2, btn_col3 = st.columns(3)
                with btn_col1:
                    if st.button("✅ 通过", key=f"approve_{session_id}", use_container_width=True):
                        asyncio.run(client.submit_review(session_id, "APPROVE", reviewer_id))
                        st.success("已通过")
                        st.rerun()
                with btn_col2:
                    if st.button("✏️ 修改", key=f"modify_{session_id}", use_container_width=True):
                        if not modified_content or modified_content == task.get("agent_response"):
                            st.error("请先修改内容")
                        else:
                            asyncio.run(
                                client.submit_review(session_id, "MODIFY", reviewer_id, modified_content)
                            )
                            st.success("已修改并通过")
                            st.rerun()
                with btn_col3:
                    if st.button("📝 覆盖", key=f"override_{session_id}", use_container_width=True):
                        if not modified_content:
                            st.error("覆盖操作需要填写新内容")
                        else:
                            asyncio.run(
                                client.submit_review(session_id, "OVERRIDE", reviewer_id, modified_content)
                            )
                            st.success("已覆盖")
                            st.rerun()


# ============ Tab 2：工单管理 ============

def _ticket_card(ticket: dict, client: TicketClient):
    """单个工单卡片"""
    tid = ticket["ticket_id"]
    status = ticket.get("status", "pending")
    priority = ticket.get("priority", "medium")
    emoji, label, color = STATUS_STYLE.get(status, ("⚪", "未知", "#ccc"))

    # 卡片头
    cols = st.columns([1.5, 2.5, 1.5, 1, 1, 1])
    with cols[0]:
        st.markdown(f"**{emoji} {tid}**")
    with cols[1]:
        title = ticket.get("title", "") or ""
        st.markdown(f"{title[:40]}{'…' if len(title) > 40 else ''}")
    with cols[2]:
        st.markdown(f"👤 {ticket.get('player_uid', '')}")
    with cols[3]:
        st.markdown(f"<span style='color:{color}'>{label}</span>", unsafe_allow_html=True)
    with cols[4]:
        st.markdown(f"**{PRIORITY_LABEL.get(priority, priority)}**")
    with cols[5]:
        created = (ticket.get("created_at", "") or "")[:10]
        st.caption(created)

    # 操作区
    if status in ("pending", "processing", "escalated"):
        with st.expander("✏️ 处理此工单", expanded=False):
            col_left, col_right = st.columns([1, 1])
            with col_left:
                new_status = st.selectbox(
                    "更新状态",
                    ["", "processing", "resolved"],
                    key=f"s_{tid}",
                )
                reviewer_id = st.text_input(
                    "处理人ID",
                    value=st.session_state.get("csr_id", "csr_001"),
                    key=f"r_{tid}",
                )
            with col_right:
                new_reply = st.text_area(
                    "处理结果 / 回复内容",
                    value=ticket.get("agent_reply", ""),
                    height=150,
                    key=f"rp_{tid}",
                    placeholder="请填写处理结果，该内容将返回给玩家…",
                )
                if st.button("✅ 提交处理", key=f"sb_{tid}", use_container_width=True, type="primary"):
                    if not new_status and not new_reply:
                        st.warning("请选择状态或填写处理结果")
                    else:
                        ok = asyncio.run(
                            client.update_ticket(
                                ticket["ticket_id"],
                                status=new_status or None,
                                agent_reply=new_reply or None,
                                reviewer_id=reviewer_id,
                            )
                        )
                        if ok:
                            st.success("工单已更新")
                            st.rerun()

        with st.expander("📋 查看完整信息", expanded=False):
            st.markdown(f"**问题描述**：{ticket.get('description', '无')}")
            if ticket.get("agent_reply"):
                st.markdown(f"**当前回复**：{ticket['agent_reply']}")
            st.caption(
                f"创建时间：{ticket.get('created_at', '')}　"
                f"解决时间：{ticket.get('resolved_at', '未解决')}　"
                f"人工审核：{'是' if ticket.get('human_reviewed') else '否'}"
            )
    else:
        with st.expander("📋 查看完整信息", expanded=False):
            st.markdown(f"**问题描述**：{ticket.get('description', '无')}")
            if ticket.get("agent_reply"):
                st.markdown(f"**客服回复**：{ticket['agent_reply']}")
            st.caption(
                f"创建时间：{ticket.get('created_at', '')}　"
                f"解决时间：{ticket.get('resolved_at', '未解决')}　"
                f"人工审核：{'是' if ticket.get('human_reviewed') else '否'}"
            )

    st.divider()


def render_ticket_management(client: TicketClient):
    st.header("📋 工单管理")

    reviewer_id = st.session_state.get("csr_id", "csr_001")

    # 快捷查询
    with st.container(border=True):
        col1, col2 = st.columns([3, 1])
        with col1:
            q = st.text_input(
                "按工单号查询",
                placeholder="输入工单号如 TK-20260526-xxxx",
                label_visibility="collapsed",
            )
        with col2:
            search_click = st.button("🔍 查询", use_container_width=True, type="primary")

        if (search_click or q) and q.strip():
            with st.spinner("查询中…"):
                ticket = asyncio.run(client.get_ticket(q.strip()))
            if ticket:
                _ticket_card(ticket, client)
            else:
                st.warning(f"未找到工单：{q.strip()}")
            st.markdown("---")

    # 统计看板
    with st.spinner("加载统计数据…"):
        stats = asyncio.run(client.stats())
    if stats:
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("全部工单", stats.get("total", 0))
        c2.metric("等待处理", stats.get("pending", 0))
        c3.metric("处理中", stats.get("processing", 0))
        c4.metric("已解决", stats.get("resolved", 0))
        c5.metric("已升等", stats.get("escalated", 0))
        c6.metric("人工审核", stats.get("human_reviewed", 0))

    st.markdown("---")

    # 筛选
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        status_filter = st.selectbox(
            "状态",
            ["全部", "pending", "processing", "resolved", "escalated"],
            index=0,
        )
    with col2:
        priority_filter = st.selectbox(
            "优先级",
            ["全部", "urgent", "high", "medium", "low"],
            index=0,
        )
    with col3:
        player_filter = st.text_input(
            "玩家 UID", placeholder="按玩家 UID 筛选", label_visibility="collapsed"
        )

    # 拆分待处理 / 已解决 Tab
    if status_filter == "全部":
        tab_a, tab_b = st.tabs(["📋 待处理工单", "✅ 已解决工单"])

        with tab_a:
            with st.spinner("加载待处理工单…"):
                data = asyncio.run(client.list_tickets(player_uid=player_filter or None))
            tickets = [t for t in data.get("tickets", [])
                       if t.get("status") in ("pending", "processing", "escalated")]
            if priority_filter != "全部":
                tickets = [t for t in tickets if t.get("priority") == priority_filter]
            tickets.sort(key=lambda t: PRIORITY_ORDER.get(t.get("priority", "medium"), 99))
            st.caption(f"待处理工单数：{len(tickets)}")
            if not tickets:
                st.info("暂无待处理工单")
            for t in tickets:
                _ticket_card(t, client)

        with tab_b:
            with st.spinner("加载已解决工单…"):
                data = asyncio.run(client.list_tickets(status="resolved",
                                                        player_uid=player_filter or None))
            tickets = data.get("tickets", [])
            if priority_filter != "全部":
                tickets = [t for t in tickets if t.get("priority") == priority_filter]
            st.caption(f"已解决工单数：{len(tickets)}")
            if not tickets:
                st.info("暂无已解决工单")
            for t in tickets[:30]:
                _ticket_card(t, client)
    else:
        with st.spinner(f"加载工单列表…"):
            data = asyncio.run(client.list_tickets(
                status=status_filter, player_uid=player_filter or None))
        tickets = data.get("tickets", [])
        if priority_filter != "全部":
            tickets = [t for t in tickets if t.get("priority") == priority_filter]
        st.caption(f"共 {len(tickets)} 条工单")
        if not tickets:
            st.info("暂无匹配的工单")
        for t in tickets:
            _ticket_card(t, client)


# ============ Tab 3：审核历史 ============

def render_audit_history():
    st.header("📜 审核历史")
    st.info("（该功能需要后端API支持）")


def render_help():
    """帮助信息"""
    with st.expander("❓ 使用帮助"):
        st.markdown("""
        ### 审核操作说明

        - **✅ 通过 (APPROVE)**: 直接通过Agent的回复，不做修改
        - **✏️ 修改 (MODIFY)**: 在Agent回复基础上修改后通过
        - **📝 覆盖 (OVERRIDE)**: 完全重写回复（使用新内容）

        ### 工单处理说明

        - 在「工单管理」Tab 中查看和处理玩家提交的工单
        - 选择状态 + 填写处理结果后提交
        - 玩家后续查询工单时，Agent 会自动读取处理结果

        ### 风险等级

        - 🔴 高风险：包含敏感词或严重问题，必须人工审核
        - 🟡 中风险：工具执行异常，建议人工确认
        - 🟢 低风险：一般性内容
        """)


# ============ 主页面 ============

def main():
    st.title("🎮 游戏客服Agent工作台")
    st.markdown("---")

    # 侧边栏
    with st.sidebar:
        st.header("⚙️ 设置")

        # 审核员ID（HIL用）
        reviewer_id = st.text_input(
            "审核员ID",
            value=st.session_state.get("reviewer_id", "admin_001"),
            help="用于标识审核操作人员",
        )
        st.session_state["reviewer_id"] = reviewer_id

        # 客服ID（工单管理用）
        csr_id = st.text_input(
            "客服处理人ID",
            value=st.session_state.get("csr_id", "csr_001"),
            help="用于标识工单处理人",
        )
        st.session_state["csr_id"] = csr_id

        st.markdown("---")

        # 统计
        st.header("📊 当前概览")
        with st.spinner(""):
            try:
                stats = asyncio.run(TicketClient().stats())
                st.metric("待处理工单", stats.get("pending", 0) + stats.get("processing", 0))
                st.metric("待审核任务", st.session_state.get("pending_count", 0))
            except Exception:
                pass

        st.markdown("---")
        if st.button("🔄 刷新数据", use_container_width=True):
            st.rerun()

    # 主Tab
    review_client = ReviewAPIClient()
    ticket_client = TicketClient()

    tab1, tab2, tab3, tab4 = st.tabs(["待审核任务", "工单管理", "审核历史", "帮助"])

    with tab1:
        render_pending_tasks(review_client)
    with tab2:
        render_ticket_management(ticket_client)
    with tab3:
        render_audit_history()
    with tab4:
        render_help()


if __name__ == "__main__":
    main()
