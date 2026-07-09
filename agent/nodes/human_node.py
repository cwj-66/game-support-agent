"""
Human-in-loop 核心节点（多轮接待版）
使用 LangGraph 的 interrupt() 实现断点暂停，支持客服与玩家多轮对话。

每次 interrupt 恢复时，接收统一的载荷字典：
  {
    "source":  "agent" | "user",   # 谁发的消息
    "message": "...",               # 消息内容
    "action":  "continue" | "close" # 仅 agent 端需要；close 表示结束接待
  }

节点本身不判断是否结束，路由函数 route_from_human 负责判断 human_action。
"""

from datetime import datetime, timezone
from typing import Dict, Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import interrupt

from ..state import AgentState


async def human_node(state: AgentState) -> Dict[str, Any]:
    """
    人工接待节点：触发中断，等待外部唤醒，恢复后追加消息到历史并更新接待状态。

    流程：
    1. 构建中断载荷推送给客服端（首次进入时附带转人工原因等上下文）
    2. interrupt() 挂起图，等待 Command(resume=...) 唤醒
    3. 恢复后解析 resume 载荷，区分「客服回复」和「玩家追问」
    4. 将消息追加到 messages，返回 human_action 供路由判断
    """
    session_id = state["session_id"]
    interrupt_info = state.get("interrupt_info") or {}
    human_mode = state.get("human_mode", False)

    # --- 构建中断载荷 ---
    # 首次进入附带完整上下文；后续循环只带 human_mode 标记
    if not human_mode:
        agent_content = state.get("final_response", "")
        if not agent_content:
            agent_content = f"[Agent未生成回复] 中断原因：{interrupt_info.get('reason', '未知')}"
        interrupt_payload = {
            "session_id": session_id,
            "user_query": state.get("user_query", ""),
            "content": agent_content,
            "pending_content": interrupt_info.get("pending_content"),
            "interrupt_reason": interrupt_info.get("reason"),
            "interrupt_level": interrupt_info.get("level"),
            "source": interrupt_info.get("source"),
            "waiting_for": "human_chat",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    else:
        # 后续循环：人工接待持续中，客服或玩家可发消息
        interrupt_payload = {
            "session_id": session_id,
            "waiting_for": "human_chat",
            "human_mode": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    print(f"[Human Node] 挂起等待人工接待: {session_id} (human_mode={human_mode})")
    # interrupt() 返回 Command(resume=payload) 里的 payload
    resume_data: dict = interrupt(interrupt_payload)

    # --- 解析唤醒载荷 ---
    # 兼容旧版字符串格式（原 review 接口直接传字符串）
    if isinstance(resume_data, str):
        resume_data = {"source": "agent", "message": resume_data, "action": "close"}

    source = resume_data.get("source", "agent")
    message_text = resume_data.get("message", "")
    action = resume_data.get("action", "continue")  # 仅 agent 端有意义

    # --- 追加消息到对话历史 ---
    new_messages = []
    now_iso = datetime.now(timezone.utc).isoformat()
    if source == "user" and message_text:
        # 玩家追问 → 作为 HumanMessage 追加
        new_messages.append(HumanMessage(
            content=message_text,
            additional_kwargs={"timestamp": now_iso}
        ))
    elif source == "agent" and message_text:
        # 客服回复 → 作为带 human_source 标记的 AIMessage 追加
        new_messages.append(AIMessage(
            content=message_text,
            additional_kwargs={"human_source": True, "timestamp": now_iso},
        ))

    print(f"[Human Node] 收到 source={source} action={action} message={message_text[:50]!r}")

    return {
        "messages": new_messages,
        # 首次进入后设为 True，接待循环中保持 True，关闭后由 finish_node 清理
        "human_mode": True,
        # 传给路由函数：close → finish，continue → 再次挂起
        "human_action": action if source == "agent" else "continue",
        # human_reply 只在客服关闭时写最后一条，供 finish_node 记录 final_response
        "human_reply": message_text if (source == "agent" and action == "close") else None,
        "node_trace": ["human"],
    }
