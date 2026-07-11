"""
终端测试工具
命令行界面，用于快速测试Agent和API
"""

import asyncio
import argparse
import json
import sys
from typing import Optional

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich import box


console = Console()

# API基础URL
DEFAULT_API_URL = "http://localhost:8002/api/v1"


class GameSupportCLI:
    """
    游戏客服Agent命令行客户端
    
    功能：
    - 发送对话消息
    - 查看待接待会话
    - 客服发送人工接待消息
    - 查看对话历史
    """
    
    def __init__(self, api_url: str = DEFAULT_API_URL):
        self.api_url = api_url.rstrip("/")
        self.session_id: Optional[str] = None
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def chat(self, message: str, session_id: Optional[str] = None, user_id: str = "cli_user"):
        """发送对话消息"""
        sid = session_id or self.session_id or f"cli_{id(message)}"

        console.print(f"[dim]发送消息到会话 {sid} (UID: {user_id})...[/dim]")

        try:
            response = await self.client.post(
                f"{self.api_url}/chat/send",
                json={
                    "session_id": sid,
                    "user_id": user_id,
                    "message": message
                }
            )
            response.raise_for_status()
            data = response.json()
            
            # 保存session_id
            self.session_id = data.get("session_id")
            
            # 显示回复
            console.print(Panel(
                Markdown(data.get("response", "无回复")),
                title="[green]Agent回复[/green]",
                border_style="green"
            ))
            
            # 人工接待中
            if data.get("status") == "human_chat":
                console.print(
                    f"[yellow]⏳ 已进入人工接待，等待客服回复 (Session: {data.get('session_id')})[/yellow]"
                )
            
            # 显示元数据
            metadata = data.get("metadata", {})
            if metadata:
                console.print(f"[dim]耗时: {metadata.get('execution_time_ms', 'N/A')}ms[/dim]")
                
        except httpx.HTTPError as e:
            console.print(f"[red]请求失败: {e}[/red]")
    
    async def list_pending(self):
        """列出待接待会话"""
        console.print("[dim]获取待接待会话...[/dim]")
        
        try:
            response = await self.client.get(
                f"{self.api_url}/human/pending"
            )
            response.raise_for_status()
            data = response.json()
            
            items = data.get("items", [])
            total = data.get("total", 0)
            
            if not items:
                console.print("[yellow]暂无待接待会话[/yellow]")
                return

            table = Table(
                title=f"待接待会话列表 (共 {total} 个)",
                box=box.ROUNDED
            )
            table.add_column("Session", style="cyan")
            table.add_column("用户问题", style="green", max_width=30)
            table.add_column("风险等级", style="red")
            table.add_column("等待时间", style="yellow")
            
            for item in items:
                table.add_row(
                    item.get("session_id", "")[:12],
                    item.get("user_query", "")[:30] + "...",
                    item.get("risk_level", "unknown"),
                    f"{item.get('wait_time_seconds', 0)}s"
                )
            
            console.print(table)
            
        except httpx.HTTPError as e:
            console.print(f"[red]请求失败: {e}[/red]")
    
    async def send_human_reply(
        self,
        session_id: str,
        reply: str,
        action: str = "continue",
        reviewer: str = "cli_user",
    ):
        """客服发送人工接待消息"""
        console.print(f"[dim]提交接待操作: {action}...[/dim]")

        payload = {
            "reply": reply,
            "reviewer_id": reviewer,
            "action": action.lower(),
        }

        try:
            response = await self.client.post(
                f"{self.api_url}/human/review/{session_id}",
                json=payload
            )
            response.raise_for_status()
            data = response.json()

            if data.get("success"):
                console.print("[green]✓ 发送成功[/green]")
                console.print(f"操作: {data.get('action')}")
                console.print(f"消息: {data.get('final_response')[:100]}...")
            else:
                console.print("[red]✗ 发送失败[/red]")

        except httpx.HTTPError as e:
            console.print(f"[red]请求失败: {e}[/red]")
    
    async def interactive(self):
        """交互式对话模式"""
        console.print(Panel.fit(
            "[bold blue]游戏客服Agent CLI[/bold blue]\n"
            "输入消息与Agent对话，或输入命令:\n"
            "  [yellow]/pending[/yellow] - 查看待接待会话\n"
            "  [yellow]/reply <session_id> <continue|close> <消息>[/yellow] - 客服回复\n"
            "  [yellow]/quit[/yellow] - 退出",
            title="欢迎使用",
            border_style="blue"
        ))
        
        while True:
            try:
                user_input = Prompt.ask("[bold]>[/bold]", console=console)
                user_input = user_input.strip()
                
                if not user_input:
                    continue
                
                # 命令处理
                if user_input.startswith("/"):
                    parts = user_input[1:].split(maxsplit=3)
                    cmd = parts[0].lower()
                    
                    if cmd == "quit" or cmd == "exit":
                        console.print("[dim]再见![/dim]")
                        break
                    
                    elif cmd == "pending":
                        await self.list_pending()
                    
                    elif cmd == "reply":
                        if len(parts) < 4:
                            console.print("[red]用法: /reply <session_id> <continue|close> <消息内容>[/red]")
                            continue
                        session_id, action, reply_text = parts[1], parts[2], parts[3]
                        await self.send_human_reply(session_id, reply_text, action)
                    
                    else:
                        console.print(f"[red]未知命令: {cmd}[/red]")
                
                else:
                    # 普通对话
                    await self.chat(user_input)
                    
            except KeyboardInterrupt:
                console.print("\n[dim]再见![/dim]")
                break
            except Exception as e:
                console.print(f"[red]错误: {e}[/red]")
    
    async def close(self):
        """关闭客户端"""
        await self.client.aclose()


def main():
    """CLI入口"""
    parser = argparse.ArgumentParser(description="游戏客服Agent CLI工具")
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"API基础URL (默认: {DEFAULT_API_URL})"
    )
    parser.add_argument(
        "--session",
        help="指定会话ID"
    )
    parser.add_argument(
        "--user-id",
        default="cli_user",
        help="玩家游戏UID (默认: cli_user)"
    )
    parser.add_argument(
        "message",
        nargs="?",
        help="发送的消息（非交互模式）"
    )
    
    args = parser.parse_args()
    
    cli = GameSupportCLI(api_url=args.api_url)
    
    try:
        if args.message:
            # 非交互模式：发送单条消息
            asyncio.run(cli.chat(args.message, args.session, args.user_id))
        else:
            # 交互模式
            asyncio.run(cli.interactive())
    except KeyboardInterrupt:
        pass
    finally:
        asyncio.run(cli.close())


if __name__ == "__main__":
    main()
