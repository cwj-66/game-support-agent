import json
import time
from langchain_core.tools import tool


@tool
def create_ticket(user_id: str, issue_type: str, description: str) -> str:
    """为玩家创建客服工单，适用于需要后台人工处理的问题。

    issue_type 枚举值：
    - account_ban：账号封禁申诉
    - payment：充值/退款问题
    - bug：游戏 bug 反馈
    - other：其他问题

    当问题无法当场解决、用户需要留存凭证、或需要后台核查时调用此工具。

    Args:
        user_id: 玩家 UID
        issue_type: 问题类型，见上方枚举值
        description: 问题描述
    """
    ticket_id = f"TK{int(time.time())}"

    estimated = {
        "account_ban": "3-5 个工作日",
        "payment": "1-3 个工作日",
        "bug": "5-7 个工作日",
        "other": "3-5 个工作日",
    }.get(issue_type, "3-5 个工作日")

    result = {
        "ticket_id": ticket_id,
        "user_id": user_id,
        "issue_type": issue_type,
        "status": "submitted",
        "estimated_response": estimated,
    }

    return json.dumps(result, ensure_ascii=False)
