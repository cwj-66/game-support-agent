"""
Streamlit 客服工作台
整合人工接待 + 工单管理两个核心功能
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
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2}
PRIORITY_LABEL = {"P0": "P0-紧急", "P1": "P1-普通", "P2": "P2-低"}


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

    async def get_session_history(self, session_id: str) -> list:
        """获取线程完整短期对话"""
        try:
            async with httpx.AsyncClient(timeout=15.0) as c:
                r = await c.get(f"{self.base_url}/human/history/{session_id}")
                r.raise_for_status()
                return r.json().get("messages", [])
        except Exception:
            return []

    async def join_session(self, session_id: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=15.0) as c:
                r = await c.post(f"{self.base_url}/human/join/{session_id}")
                return r.is_success
        except Exception:
            return False

    async def submit_review(
        self, session_id: str, reply: str, reviewer_id: str, action: str = "continue"
    ) -> bool:
        try:
            payload = {
                "reply": reply,
                "reviewer_id": reviewer_id,
                "action": action,
            }
            async with httpx.AsyncClient(timeout=30.0) as c:
                r = await c.post(f"{self.base_url}/human/review/{session_id}", json=payload)
                if not r.is_success:
                    detail = r.text
                    try:
                        detail = r.json().get("detail", r.text)
                    except Exception:
                        pass
                    st.error(f"提交审核失败 ({r.status_code}): {detail}")
                    return False
            return True
        except Exception as e:
            st.error(f"提交审核异常: {type(e).__name__}: {e}")
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


# ============ 合并工单看板（P0/P1/P2 分栏）============

def render_risk_badge(level: str) -> str:
    colors = {"high": "🔴 高风险", "medium": "🟡 中风险", "low": "🟢 低风险"}
    return colors.get(level, "⚪ 未知")


def _render_hil_mini(task: dict, client: ReviewAPIClient):
    """紧凑型审核卡片，嵌入 P0 栏"""
    session_id = task.get("session_id", "")
    risk = task.get("risk_level", "low")
    badge = render_risk_badge(risk)

    # 截取足够长的上下文预览
    preview = (task.get("user_query") or "")[:40]
    with st.popover(f"{badge} {preview}…", use_container_width=True):
        st.markdown(f"**用户问题**：{task.get('user_query', '无')}")
        st.markdown(f"**Agent回复**：{task.get('agent_response', '无')}")
        st.markdown(f"**触发原因**：{task.get('interrupt_reason', '未知')}")

        # 线程完整对话
        history = asyncio.run(client.get_session_history(session_id))
        if history:
            with st.expander("💬 查看完整对话", expanded=True):
                for msg in history:
                    role = msg.get("role", "")
                    label = {"user": "玩家", "agent": "AI", "human_agent": "客服"}.get(role, role)
                    st.markdown(f"**{label}**：{msg.get('content', '')}")

        pending_ctx = task.get("pending_content")
        if pending_ctx:
            with st.expander("📋 问题摘要", expanded=False):
                st.text(pending_ctx)

        if st.button("👋 接入会话", key=f"hil_join_{session_id}"):
            if asyncio.run(client.join_session(session_id)):
                st.success("已发送接入提示")
                st.rerun()

        reviewer_id = st.session_state.get("reviewer_id", "admin_001")
        reply = st.text_area(
            "人工回复内容",
            height=120,
            key=f"hil_reply_{session_id}",
            placeholder="请输入回复内容，将直接发送给用户…",
        )

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("💬 发送回复", key=f"hil_submit_{session_id}", use_container_width=True, type="primary"):
                if not reply.strip():
                    st.warning("请填写回复内容")
                else:
                    ok = asyncio.run(client.submit_review(session_id, reply, reviewer_id, "continue"))
                    if ok:
                        st.success("回复已发送")
                        st.rerun()
        with col_b:
            if st.button("🔚 结束接待", key=f"hil_close_{session_id}", use_container_width=True):
                if not reply.strip():
                    st.warning("结束接待时请填写最后一条回复")
                else:
                    ok = asyncio.run(client.submit_review(session_id, reply, reviewer_id, "close"))
                    if ok:
                        st.success("接待已结束")
                        st.rerun()


def _render_compact_ticket(ticket: dict, client: TicketClient):
    """紧凑型工单卡片，用于分栏展示"""
    tid = ticket["ticket_id"]
    status = ticket.get("status", "pending")
    emoji, label, color = STATUS_STYLE.get(status, ("⚪", "未知", "#ccc"))

    with st.container(border=True):
        cols = st.columns([3, 1])
        with cols[0]:
            st.markdown(f"**{emoji} {tid}**")
            st.caption(f"👤 {ticket.get('player_uid', '')} · {ticket.get('title', '')[:25]}")
        with cols[1]:
            st.markdown(f"<span style='color:{color}'>{label}</span>", unsafe_allow_html=True)
            st.caption((ticket.get("created_at", "") or "")[:10])

        if status in ("pending", "processing", "escalated"):
            with st.expander("✏️ 处理", expanded=False):
                new_status = st.selectbox(
                    "状态", ["", "processing", "resolved"], key=f"cst_{tid}"
                )
                new_reply = st.text_area(
                    "回复", height=80, key=f"crp_{tid}",
                    placeholder="处理结果将返回给玩家…",
                )
                reviewer = st.session_state.get("csr_id", "csr_001")
                if st.button("✅ 提交", key=f"csb_{tid}", use_container_width=True):
                    ok = asyncio.run(client.update_ticket(
                        tid, status=new_status or None,
                        agent_reply=new_reply or None,
                        reviewer_id=reviewer,
                    ))
                    if ok:
                        st.success("已更新")
                        st.rerun()


# ============ 工单管理 ============

def _ticket_card(ticket: dict, client: TicketClient):
    """单个工单卡片"""
    tid = ticket["ticket_id"]
    status = ticket.get("status", "pending")
    priority = ticket.get("priority", "P2")
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
                f"人工处理：{'是' if ticket.get('human_reviewed') else '否'}"
            )
    else:
        with st.expander("📋 查看完整信息", expanded=False):
            st.markdown(f"**问题描述**：{ticket.get('description', '无')}")
            if ticket.get("agent_reply"):
                st.markdown(f"**客服回复**：{ticket['agent_reply']}")
            st.caption(
                f"创建时间：{ticket.get('created_at', '')}　"
                f"解决时间：{ticket.get('resolved_at', '未解决')}　"
                f"人工处理：{'是' if ticket.get('human_reviewed') else '否'}"
            )

    st.divider()


def render_workspace(review_client: ReviewAPIClient, ticket_client: TicketClient):
    """合并工单看板：HIL 审核任务嵌入 P0 栏，按 P0/P1/P2 分栏展示"""

    # ── 加载数据 ──
    with st.spinner("加载数据…"):
        stats = asyncio.run(ticket_client.stats())
        pending_tasks = asyncio.run(review_client.get_pending_reviews())
    st.session_state["pending_count"] = len(pending_tasks)

    # ── 统计看板 ──
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("全部工单", stats.get("total", 0))
    c2.metric("等待处理", stats.get("pending", 0))
    c3.metric("处理中", stats.get("processing", 0))
    c4.metric("已解决", stats.get("resolved", 0))
    c5.metric("待接待", len(pending_tasks))
    c6.metric("人工处理", stats.get("human_reviewed", 0))

    st.markdown("---")

    # ── 快捷查询 ──
    col_q1, col_q2 = st.columns([3, 1])
    with col_q1:
        q = st.text_input("###", placeholder="按工单号查询 TK-20260526-xxxx", label_visibility="collapsed")
    with col_q2:
        search_click = st.button("🔍 查询", use_container_width=True, type="primary")
    if (search_click or q) and q.strip():
        with st.spinner(""):
            ticket = asyncio.run(ticket_client.get_ticket(q.strip()))
        if ticket:
            st.markdown("---")
            _ticket_card(ticket, ticket_client)
            st.markdown("---")
        else:
            st.warning(f"未找到工单：{q.strip()}")
            st.markdown("---")

    # ── 筛选 ──
    col_f1, col_f2 = st.columns([1, 1])
    with col_f1:
        status_filter = st.selectbox(
            "状态", ["全部待处理", "pending", "processing", "escalated"], index=0,
        )
    with col_f2:
        player_filter = st.text_input("玩家 UID", placeholder="按 UID 筛选", label_visibility="collapsed")

    # ── 获取工单 ──
    with st.spinner("加载工单…"):
        data = asyncio.run(ticket_client.list_tickets(player_uid=player_filter or None))
    all_tickets = data.get("tickets", [])

    # 状态筛选
    if status_filter == "全部待处理":
        active = [t for t in all_tickets if t.get("status") in ("pending", "processing", "escalated")]
    else:
        active = [t for t in all_tickets if t.get("status") == status_filter]

    # 按优先级分组
    p0_list = [t for t in active if t.get("priority") == "P0"]
    p1_list = [t for t in active if t.get("priority") == "P1"]
    p2_list = [t for t in active if t.get("priority") == "P2"]

    st.markdown("---")

    # ── P0 栏（置顶，视觉高亮，包含 HIL 审核任务）──
    with st.container(border=True):
        st.markdown("### 🔴 P0 — 紧急（分钟级响应）")

        # HIL 审核任务排在 P0 工单前面
        if pending_tasks:
            for task in pending_tasks:
                _render_hil_mini(task, review_client)

        if not p0_list and not pending_tasks:
            st.info("无待处理 P0 工单")
        else:
            for t in p0_list:
                _render_compact_ticket(t, ticket_client)

    st.markdown("---")

    # ── P1 / P2 两栏 ──
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        st.markdown("### 🟡 P1 — 普通（小时级响应）")
        if not p1_list:
            st.info("无待处理 P1 工单")
        else:
            for t in p1_list:
                _render_compact_ticket(t, ticket_client)
    with col_p2:
        st.markdown("### P2 — 低优（天级响应）")
        if not p2_list:
            st.info("无待处理 P2 工单")
        else:
            for t in p2_list:
                _render_compact_ticket(t, ticket_client)

    # ── 已解决工单（折叠） ──
    resolved = [t for t in all_tickets if t.get("status") == "resolved"]
    with st.expander(f"✅ 已解决工单（{len(resolved)} 条）"):
        if not resolved:
            st.info("暂无已解决工单")
        for t in resolved:
            _ticket_card(t, ticket_client)


# ============ Tab 3：审核历史 ============

def render_audit_history():
    st.header("📜 审核历史")
    st.info("（该功能需要后端API支持）")


def render_help():
    """帮助信息"""
    with st.expander("❓ 使用帮助"):
        st.markdown("""
        ### 工单看板说明

        - **🔴 P0 栏（置顶高亮）**：分钟级响应，包含 HIL 待审核任务和 P0 工单
        - **🟡 P1 栏**：小时级响应，普通问题
        - **P2 栏**：天级响应，低优问题
        - 在每张工单卡片可展开「处理」菜单快速更新状态和回复
        - 已解决工单折叠在底部，可展开查看

        ### 审核操作说明

        - **提交回复**：填写回复内容后提交，回复将直接发送给用户
        - **工具执行上下文**：可展开查看 Agent 查询了哪些工具和结果，辅助判断

        ### 工单处理说明

        - 在「工单看板」中按 P0→P1→P2 分栏查看和处理工单
        - 展开工单卡片中的「处理」菜单，选择状态 + 填写结果后提交
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

    tab1, tab2, tab3 = st.tabs(["📋 工单看板", "📜 审核历史", "❓ 帮助"])

    with tab1:
        render_workspace(review_client, ticket_client)
    with tab2:
        render_audit_history()
    with tab3:
        render_help()


if __name__ == "__main__":
    main()
