#!/usr/bin/env python3
"""
修复 MySQL 中 UTF-8 中文被误存为乱码的问题。

原因：init.sql 首次导入时客户端字符集不正确，导致中文以 mojibake 形式写入。
用法：python scripts/mysql/fix_encoding.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from dotenv import load_dotenv

load_dotenv()

from app.core.mysql_db import get_mysql_conn, ping_mysql

# 与 scripts/mysql/init.sql 保持一致的正确中文
TICKET_FIXES = [
    {
        "ticket_id": "TK-20260501-1001",
        "title": "充值未到账",
        "description": "昨天充了648元原石没到账",
        "agent_reply": "已补发，请查收邮件",
    },
    {
        "ticket_id": "TK-20260510-1002",
        "title": "账号异地登录提醒",
        "description": "收到异地登录短信是否正常",
        "agent_reply": "建议修改密码并开启二次验证",
    },
    {
        "ticket_id": "TK-20260410-2001",
        "title": "申请解封",
        "description": "我没有使用外挂，请核实",
        "agent_reply": None,
    },
    {
        "ticket_id": "TK-20260520-3001",
        "title": "充值异常核实",
        "description": "5000元充值显示异常",
        "agent_reply": "正在与支付渠道核实",
    },
    {
        "ticket_id": "TK-20260528-6001",
        "title": "活动奖励未发放",
        "description": "完成活动未收到奖励",
        "agent_reply": None,
    },
    {
        "ticket_id": "TK-20260529-9001",
        "title": "大额充值风控",
        "description": "9999元充值被拦截",
        "agent_reply": None,
    },
    {
        "ticket_id": "TK-20260515-1501",
        "title": "如何获得角色",
        "description": "新手不知道如何抽卡",
        "agent_reply": "可在祈愿界面使用原石抽取",
    },
]

PLAYER_FIXES = [
    ("10001", "风行者"),
    ("10002", "暗夜猎手"),
    ("10003", "星辰法师"),
    ("10004", "铁壁骑士"),
    ("10005", "流浪剑客"),
    ("10006", "圣光牧师"),
    ("10007", "新手小白"),
    ("10008", "烈焰战士"),
    ("10009", "土豪玩家"),
    ("10010", "休闲达人"),
    ("10011", "弓箭手"),
    ("10012", "迷途者"),
    ("10013", "龙吟"),
    ("10014", "充值困惑"),
    ("10015", "老玩家"),
    ("10016", "举报狂魔"),
    ("10017", "月影"),
    ("10018", "萌新求带"),
    ("10019", "代充嫌疑"),
    ("10020", "至尊VIP"),
]


def main() -> None:
    if not ping_mysql():
        print("MySQL 未连接。请先运行: docker compose up -d mysql")
        sys.exit(1)

    with get_mysql_conn() as conn:
        with conn.cursor() as cur:
            for item in TICKET_FIXES:
                cur.execute(
                    """
                    UPDATE support_tickets
                    SET title = %s, description = %s, agent_reply = %s
                    WHERE ticket_id = %s
                    """,
                    (
                        item["title"],
                        item["description"],
                        item["agent_reply"],
                        item["ticket_id"],
                    ),
                )
            for uid, nickname in PLAYER_FIXES:
                cur.execute(
                    "UPDATE game_players SET nickname = %s WHERE uid = %s",
                    (nickname, uid),
                )

    print(f"已修复 {len(TICKET_FIXES)} 条工单、{len(PLAYER_FIXES)} 条玩家昵称。")


if __name__ == "__main__":
    main()
