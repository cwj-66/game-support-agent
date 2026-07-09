"""
工单提议工具
LLM 调用此工具时，不会立即创建工单，而是向前端返回「是/否」确认按钮。
tool_exec 会拦截此工具调用，写入 state.ticket_offer，不走普通工具执行流程。
"""

from langchain_core.tools import tool


@tool
async def propose_ticket(issue_type: str, summary: str) -> str:
    """向用户提出创建工单的建议，展示「是/否」确认按钮，用户确认后才真正创建工单。

    以下场景需调用此工具：
    1. 游戏相关问题，工具查完后无法完全解决，需要后台专员跟进处理
    2. 用户明确表示想要创建工单（"帮我创建工单"、"提交一个反馈"等）

    issue_type 枚举值：
    - account_ban：账号封禁申诉
    - payment：充值/退款问题
    - bug：游戏 bug 反馈
    - other：其他问题

    Args:
        issue_type: 问题类型，见上方枚举值
        summary: 用户问题的简短总结（≤50字，会展示给用户确认）
    """
    # 此工具永远不会真正执行，tool_exec 会在执行前拦截
    return "工单确认请求已提出"
