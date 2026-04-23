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
    - 查看待审核任务
    - 执行人工审核操作
    - 查看对话历史
    """
    
    def __init__(self, api_url: str = DEFAULT_API_URL):
        self.api_url = api_url.rstrip("/")
        self.session_id: Optional[str] = None
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def chat(self, message: str, session_id: Optional[str] = None):
        """发送对话消息"""
        sid = session_id or self.session_id or f"cli_{id(message)}"
        
        console.print(f"[dim]发送消息到会话 {sid}...[/dim]")
        
        try:
            response = await self.client.post(
                f"{self.api_url}/chat/send",
                json={
                    "session_id": sid,
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
            
            # 检查是否需要审核
            if data.get("requires_review"):
                console.print(
                    f"[yellow]⚠️ 此回复需要人工审核 (Review ID: {data.get('review_id')})[/yellow]"
                )
            
            # 显示元数据
            metadata = data.get("metadata", {})
            if metadata:
                console.print(f"[dim]置信度: {metadata.get('confidence', 'N/A')} | 耗时: {metadata.get('execution_time_ms', 'N/A')}ms[/dim]")
                
        except httpx.HTTPError as e:
            console.print(f"[red]请求失败: {e}[/red]")
    
    async def list_pending(self):
        """列出待审核任务"""
        console.print("[dim]获取待审核任务...[/dim]")
        
        try:
            response = await self.client.get(
                f"{self.api_url}/human/pending"
            )
            response.raise_for_status()
            data = response.json()
            
            items = data.get("items", [])
            total = data.get("total", 0)
            
            if not items:
                console.print("[yellow]暂无待审核任务[/yellow]")
                return
            
            # 创建表格
            table = Table(
                title=f"待审核任务列表 (共 {total} 个)",
                box=box.ROUNDED
            )
            table.add_column("Review ID", style="cyan")
            table.add_column("Session", style="magenta")
            table.add_column("用户问题", style="green", max_width=30)
            table.add_column("风险等级", style="red")
            table.add_column("等待时间", style="yellow")
            
            for item in items:
                table.add_row(
                    item.get("review_id", "")[:8],
                    item.get("session_id", "")[:8],
                    item.get("user_query", "")[:30] + "...",
                    item.get("risk_level", "unknown"),
                    f"{item.get('wait_time_seconds', 0)}s"
                )
            
            console.print(table)
            
        except httpx.HTTPError as e:
            console.print(f"[red]请求失败: {e}[/red]")
    
    async def review(self, session_id: str, action: str, modified: Optional[str] = None, reviewer: str = "cli_user"):
        """执行人工审核"""
        console.print(f"[dim]提交审核操作: {action}...[/dim]")
        
        payload = {
            "session_id": session_id,
            "action": action.upper(),
            "reviewer_id": reviewer
        }
        
        if modified:
            payload["modified_content"] = modified
        
        try:
            response = await self.client.post(
                f"{self.api_url}/human/review/{session_id}",
                json=payload
            )
            response.raise_for_status()
            data = response.json()
            
            if data.get("success"):
                console.print(f"[green]✓ 审核成功[/green]")
                console.print(f"操作: {data.get('action')}")
                console.print(f"最终回复: {data.get('final_response')[:100]}...")
            else:
                console.print(f"[red]✗ 审核失败[/red]")
                
        except httpx.HTTPError as e:
            console.print(f"[red]请求失败: {e}[/red]")
    
    async def interactive(self):
        """交互式对话模式"""
        console.print(Panel.fit(
            "[bold blue]游戏客服Agent CLI[/bold blue]\n"
            "输入消息与Agent对话，或输入命令:\n"
            "  [yellow]/pending[/yellow] - 查看待审核任务\n"
            "  [yellow]/review <session_id> <action>[/yellow] - 审核操作\n"
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
                    parts = user_input[1:].split(maxsplit=2)
                    cmd = parts[0].lower()
                    
                    if cmd == "quit" or cmd == "exit":
                        console.print("[dim]再见![/dim]")
                        break
                    
                    elif cmd == "pending":
                        await self.list_pending()
                    
                    elif cmd == "review":
                        if len(parts) < 3:
                            console.print("[red]用法: /review <session_id> <APPROVE|MODIFY|OVERRIDE> [content][/red]")
                            continue
                        _, session_id, action = parts[:3]
                        modified = parts[3] if len(parts) > 3 else None
                        await self.review(session_id, action, modified)
                    
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
        "message",
        nargs="?",
        help="发送的消息（非交互模式）"
    )
    
    args = parser.parse_args()
    
    cli = GameSupportCLI(api_url=args.api_url)
    
    try:
        if args.message:
            # 非交互模式：发送单条消息
            asyncio.run(cli.chat(args.message, args.session))
        else:
            # 交互模式
            asyncio.run(cli.interactive())
    except KeyboardInterrupt:
        pass
    finally:
        asyncio.run(cli.close())


if __name__ == "__main__":
    main()
