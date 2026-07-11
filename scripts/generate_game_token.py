#!/usr/bin/env python3
"""
生成游戏 JWT，供本地联调客服 API。

用法：
    python scripts/generate_game_token.py --user-id 10001
    python scripts/generate_game_token.py --user-id 10003 --server-id s2 --nickname 星辰法师
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

# 把项目根目录加入 path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import jwt
from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    parser = argparse.ArgumentParser(description="生成游戏玩家 JWT")
    parser.add_argument("--user-id", required=True, help="玩家 UID，对应 game_players.uid")
    parser.add_argument("--server-id", default="s1", help="区服 ID")
    parser.add_argument("--nickname", default=None, help="昵称（可选，写入 token）")
    parser.add_argument("--hours", type=int, default=24, help="有效小时数")
    args = parser.parse_args()

    secret = os.getenv("GAME_JWT_SECRET")
    if not secret:
        print("错误：请先在 .env 中配置 GAME_JWT_SECRET", file=sys.stderr)
        sys.exit(1)

    algorithm = os.getenv("GAME_JWT_ALGORITHM", "HS256")
    now = datetime.now(timezone.utc)
    payload = {
        "sub": args.user_id,
        "server_id": args.server_id,
        "iat": now,
        "exp": now + timedelta(hours=args.hours),
    }
    if args.nickname:
        payload["nickname"] = args.nickname

    token = jwt.encode(payload, secret, algorithm=algorithm)
    print(token)
    print()
    print("请求示例：")
    print(f'  curl -H "Authorization: Bearer {token}" http://127.0.0.1:8002/api/v1/chat/history/10001_test')


if __name__ == "__main__":
    main()
