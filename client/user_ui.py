"""
Streamlit 用户界面
玩家端：与AI客服对话、创建工单、查询工单进度
"""

import streamlit as st
import httpx
import asyncio
import time
import uuid

st.set_page_config(
    page_title="游戏客服 - 用户端",
    page_icon="🎮",
    layout="centered",
)

API_BASE_URL = "http://localhost:8002/api/v1"


# ── API 客户端 ──

class APIClient:
    async def send_message(self, session_id: str, user_id: str, message: str) -> dict:
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.post(
                f"{API_BASE_URL}/chat/send",
                json={"session_id": session_id, "user_id": user_id, "message": message},
            )
            r.raise_for_status()
            return r.json()

    async def get_history(self, session_id: str) -> list:
        try:
            async with httpx.AsyncClient(timeout=15.0) as c:
                r = await c.get(f"{API_BASE_URL}/chat/history/{session_id}")
                r.raise_for_status()
                data = r.json()
                return data.get("messages", [])
        except Exception:
            return []

    async def create_ticket(self, player_uid: str, title: str, description: str, priority: str) -> dict:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(
                f"{API_BASE_URL}/ticket/create",
                json={
                    "player_uid": player_uid,
                    "title": title,
                    "description": description,
                    "priority": priority,
                },
            )
            r.raise_for_status()
            return r.json()

    async def check_ticket(self, ticket_id: str) -> dict | None:
        try:
            async with httpx.AsyncClient(timeout=15.0) as c:
                r = await c.get(f"{API_BASE_URL}/ticket/{ticket_id}")
                r.raise_for_status()
                return r.json()
        except Exception:
            return None

    async def get_human_reply(self, session_id: str) -> dict:
        """轮询人工客服回复"""
        try:
            async with httpx.AsyncClient(timeout=15.0) as c:
                r = await c.get(f"{API_BASE_URL}/chat/reply/{session_id}")
                r.raise_for_status()
                return r.json()
        except Exception:
            return {"status": "pending"}

    async def check_human_status(self, session_id: str) -> dict:
        """查询会话是否在人工接待中"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(f"{API_BASE_URL}/human/status/{session_id}")
                r.raise_for_status()
                return r.json()
        except Exception:
            return {"has_pending_human": True}


# ── 页面 ──

def chat_tab(client: APIClient):
    st.subheader("💬 AI 客服助手")
    st.caption("向我提问游戏攻略、账号问题、活动信息等")

    # 初始化会话
    if "session_id" not in st.session_state:
        st.session_state.session_id = f"user_{uuid.uuid4().hex[:8]}"
    if "user_id" not in st.session_state:
        st.session_state.user_id = f"UID{uuid.uuid4().hex[:6].upper()}"
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "waiting" not in st.session_state:
        st.session_state.waiting = False

    # 侧边用户信息
    with st.sidebar:
        st.header("👤 玩家信息")
        st.session_state.user_id = st.text_input("玩家 UID", value=st.session_state.user_id)
        st.session_state.session_id = st.text_input("会话 ID", value=st.session_state.session_id)
        st.markdown("---")
        if st.button("🔄 新会话", use_container_width=True):
            st.session_state.session_id = f"user_{uuid.uuid4().hex[:8]}"
            st.session_state.messages = []
            st.rerun()

    # 显示聊天记录
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # 输入
    if prompt := st.chat_input("请输入您的问题…", disabled=st.session_state.waiting):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        st.session_state.waiting = True
        with st.chat_message("assistant"):
            try:
                result = asyncio.run(
                    client.send_message(
                        st.session_state.session_id,
                        st.session_state.user_id,
                        prompt,
                    )
                )
                response = result.get("response", "抱歉，暂时无法处理，请稍后再试。")

                if result.get("status") == "human_chat":
                    st.info(response)
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": response + "\n\n⏳ *客服接待中，请稍候…*",
                    })

                    final_response = None
                    with st.spinner("客服接待中，等待回复…"):
                        sid = st.session_state.session_id
                        while True:
                            time.sleep(5)
                            poll = asyncio.run(client.get_human_reply(sid))
                            if poll.get("status") == "completed" and poll.get("reply"):
                                final_response = poll["reply"]
                                break
                            status = asyncio.run(client.check_human_status(sid))
                            if not status.get("has_pending_human"):
                                break

                    if not final_response:
                        history = asyncio.run(client.get_history(sid))
                        if history:
                            for msg in reversed(history):
                                if msg.get("role") == "assistant":
                                    final_response = msg["content"]
                                    break

                    if not final_response:
                        final_response = "客服已处理，请继续提问。"
                    st.success("✅ 收到客服回复")
                    st.markdown(final_response)
                    st.session_state.messages[-1] = {"role": "assistant", "content": final_response}
                else:
                    st.markdown(response)
                    st.session_state.messages.append({"role": "assistant", "content": response})

            except Exception as e:
                err_msg = f"请求失败：{e}"
                st.error(err_msg)
                st.session_state.messages.append({"role": "assistant", "content": err_msg})
            finally:
                st.session_state.waiting = False
        st.rerun()


def ticket_create_tab(client: APIClient):
    st.subheader("📝 提交工单")
    st.caption("需要人工处理的问题（账号申诉、充值问题、Bug反馈等），请提交工单")

    user_id = st.session_state.get("user_id", "UID001")

    with st.form("ticket_form"):
        issue_type = st.selectbox(
            "问题类型",
            options=[
                ("account_ban", "🔒 账号封禁申诉"),
                ("payment", "💳 充值/退款问题"),
                ("bug", "🐛 游戏 Bug 反馈"),
                ("other", "📋 其他问题"),
            ],
            format_func=lambda x: x[1],
        )
        title = st.text_input("标题", placeholder="简要描述您的问题")
        description = st.text_area("详细描述", placeholder="请详细描述您遇到的问题…", height=150)
        priority = st.selectbox(
            "优先级",
            options=[("P0", "P0 紧急（分钟级响应）"), ("P1", "P1 普通（小时级响应）"), ("P2", "P2 低（天级响应）")],
            format_func=lambda x: x[1],
        )

        if st.form_submit_button("📨 提交工单", use_container_width=True, type="primary"):
            if not title or not description:
                st.warning("请填写标题和描述")
            else:
                with st.spinner("提交中…"):
                    try:
                        result = asyncio.run(
                            client.create_ticket(
                                user_id, title, description, priority[0]
                            )
                        )
                        st.success(f"工单提交成功！")
                        st.info(f"工单号：**{result.get('ticket_id')}**")
                        st.info(f"预计处理时间：{result.get('estimated_response', '3-5个工作日')}")
                    except Exception as e:
                        st.error(f"提交失败：{e}")


def ticket_query_tab(client: APIClient):
    st.subheader("🔍 查询工单进度")
    st.caption("输入工单号查看处理进度和客服回复")

    ticket_id = st.text_input("工单号", placeholder="TK-20260526-xxxx")
    if st.button("查询", use_container_width=True, type="primary") and ticket_id:
        with st.spinner("查询中…"):
            ticket = asyncio.run(client.check_ticket(ticket_id.strip()))

        if ticket:
            status_map = {
                "pending": "🕐 等待处理",
                "processing": "⏳ 处理中",
                "resolved": "✅ 已解决",
                "escalated": "🔴 已升等",
            }
            status_str = status_map.get(ticket.get("status", ""), ticket.get("status", "未知"))

            st.markdown(f"**工单号**：{ticket.get('ticket_id')}")
            st.markdown(f"**标题**：{ticket.get('title', '')}")
            st.markdown(f"**状态**：{status_str}")
            st.markdown(f"**问题描述**：{ticket.get('description', '')}")
            if ticket.get("agent_reply"):
                st.success(f"**客服回复**：{ticket['agent_reply']}")
            if ticket.get("resolved_at"):
                st.caption(f"解决时间：{ticket['resolved_at']}")
            st.caption(f"创建时间：{ticket.get('created_at', '')}")
        else:
            st.warning(f"未找到工单：{ticket_id}")


def main():
    st.title("🎮 游戏客服助手")
    st.caption("原神玩家服务中心 — AI 智能客服 + 人工工单")

    client = APIClient()

    tab1, tab2, tab3 = st.tabs(["💬 对话客服", "📝 提交工单", "🔍 查询进度"])

    with tab1:
        chat_tab(client)
    with tab2:
        ticket_create_tab(client)
    with tab3:
        ticket_query_tab(client)


if __name__ == "__main__":
    main()
