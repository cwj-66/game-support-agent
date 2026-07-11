#!/usr/bin/env python3
"""快速查看 MySQL mock 数据（需 docker compose up -d mysql）"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv

load_dotenv()

from app.core.mysql_db import get_mysql_conn, ping_mysql


def main() -> None:
    if not ping_mysql():
        print("MySQL 未连接。请先运行: docker compose up -d mysql")
        sys.exit(1)

    with get_mysql_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT uid, nickname, status, recharge_total FROM game_players LIMIT 10")
            players = cur.fetchall()
            cur.execute(
                "SELECT ticket_id, player_uid, title, status FROM support_tickets LIMIT 10"
            )
            tickets = cur.fetchall()

    print("=== game_players (前10条) ===")
    for p in players:
        print(p)

    print("\n=== support_tickets (前10条) ===")
    for t in tickets:
        print(t)


if __name__ == "__main__":
    main()
