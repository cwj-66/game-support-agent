"""账号状态规则（根据 UID 末位数字决定）：
  - 1 → normal（正常状态）
  - 2 → banned（封禁状态）
  - 3 → recharge_abnormal（充值出现异常）
"""

import json
from langchain_core.tools import tool


@tool
def lookup_account(user_id: str) -> str:
    """查询玩家账号状态，包括封禁情况和充值记录。

    当用户询问自己的账号状态、是否被封禁、充值记录时调用此工具。

    Args:
        user_id: 玩家 UID（用户提供的数字即为UID，如"221"、"id12345"）
    """
    try:
        last_digit = int(user_id[-1])
    except (ValueError, IndexError):
        last_digit = 9

    if last_digit == 1:
        result = {
            "_health": {"ok": True, "confidence": 0.9, "message": None},
            "uid": user_id,
            "status": "normal",
            "ban_reason": None,
            "recharge_total": 1280.0,
            "last_login": "2026-05-08T20:15:00Z",
        }
    elif last_digit == 2:
        result = {
            "_health": {"ok": True, "confidence": 0.9, "message": None},
            "uid": user_id,
            "status": "banned",
            "ban_reason": "违反用户协议第3.2条：使用外挂程序",
            "recharge_total": 328.0,
            "last_login": "2026-04-10T18:23:00Z",
        }
    elif last_digit == 3:
        result = {
            "_health": {"ok": True, "confidence": 0.9, "message": None},
            "uid": user_id,
            "status": "recharge_abnormal",
            "ban_reason": None,
            "recharge_total": 5000.0,
            "last_login": "2026-05-20T14:30:00Z",
            "abnormal_detail": "近期充值出现异常,充值未到账",
        }
    else:
        result = {
            "_health": {"ok": True, "confidence": 0.9, "message": None},
            "uid": user_id,
            "status": "normal",
            "ban_reason": None,
            "recharge_total": 1280.0,
            "last_login": "2026-05-08T20:15:00Z",
        }

    return json.dumps(result, ensure_ascii=False)
