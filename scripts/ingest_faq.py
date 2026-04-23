"""
FAQ数据导入脚本
把faq.json灌进RAG项目

用法：
    python scripts/ingest_faq.py --rag-url http://localhost:8000
"""

import argparse
import json
import asyncio
import sys
from pathlib import Path
from typing import List, Dict, Any

import httpx
from rich.console import Console
from rich.progress import Progress, TaskID
from rich.table import Table


console = Console()


def load_faq_data(filepath: str) -> List[Dict[str, Any]]:
    """
    加载FAQ数据文件
    
    Args:
        filepath: faq.json文件路径
        
    Returns:
        FAQ条目列表
    """
    path = Path(filepath)
    if not path.exists():
        console.print(f"[red]错误：文件不存在 {filepath}[/red]")
        sys.exit(1)
    
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    console.print(f"[green]已加载 {len(data)} 条FAQ数据[/green]")
    return data


def prepare_documents(faq_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    将FAQ条目转换为RAG文档格式
    
    RAG服务期望的文档格式：
    {
        "id": "唯一标识",
        "content": "文档内容",
        "metadata": {...}
    }
    """
    documents = []
    
    for item in faq_items:
        # 组合问题和答案作为文档内容
        content = f"问题：{item['question']}\n\n答案：{item['answer']}"
        
        doc = {
            "id": item.get("id", f"faq_{len(documents)}"),
            "content": content,
            "metadata": {
                "category": item.get("category", "general"),
                "keywords": item.get("keywords", []),
                "question": item["question"],
                "source": "faq.json",
                "type": "faq"
            }
        }
        documents.append(doc)
    
    return documents


async def ingest_to_rag(
    documents: List[Dict[str, Any]],
    rag_url: str,
    batch_size: int = 10
) -> Dict[str, Any]:
    """
    批量导入文档到RAG服务
    
    Args:
        documents: 文档列表
        rag_url: RAG服务地址
        batch_size: 每批导入数量
        
    Returns:
        导入结果统计
    """
    stats = {
        "total": len(documents),
        "success": 0,
        "failed": 0,
        "errors": []
    }
    
    async with httpx.AsyncClient() as client:
        with Progress() as progress:
            task = progress.add_task("[cyan]导入文档...", total=len(documents))
            
            # 分批导入
            for i in range(0, len(documents), batch_size):
                batch = documents[i:i + batch_size]
                
                try:
                    response = await client.post(
                        f"{rag_url}/api/v1/documents/batch",
                        json={"documents": batch},
                        timeout=30.0
                    )
                    response.raise_for_status()
                    
                    result = response.json()
                    stats["success"] += result.get("inserted", len(batch))
                    
                    progress.update(task, advance=len(batch))
                    
                except Exception as e:
                    stats["failed"] += len(batch)
                    stats["errors"].append(str(e))
                    console.print(f"[red]批次 {i//batch_size + 1} 导入失败: {e}[/red]")
                    progress.update(task, advance=len(batch))
    
    return stats


async def check_rag_health(rag_url: str) -> bool:
    """检查RAG服务健康状态"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{rag_url}/health",
                timeout=5.0
            )
            return response.status_code == 200
    except Exception:
        return False


def print_results(stats: Dict[str, Any]):
    """打印导入结果"""
    table = Table(title="导入结果")
    table.add_column("指标", style="cyan")
    table.add_column("数值", style="green")
    
    table.add_row("总计文档", str(stats["total"]))
    table.add_row("成功导入", str(stats["success"]))
    table.add_row("失败数量", str(stats["failed"]))
    table.add_row("成功率", f"{stats['success']/stats['total']*100:.1f}%")
    
    console.print(table)
    
    if stats["errors"]:
        console.print("\n[red]错误详情：[/red]")
        for error in stats["errors"][:5]:  # 只显示前5个错误
            console.print(f"  - {error}")


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="FAQ数据导入RAG服务")
    parser.add_argument(
        "--faq-file",
        default="./data/faq.json",
        help="FAQ数据文件路径 (默认: ./data/faq.json)"
    )
    parser.add_argument(
        "--rag-url",
        default="http://localhost:8000",
        help="RAG服务地址 (默认: http://localhost:8000)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="批量导入大小 (默认: 10)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅预览，不实际导入"
    )
    
    args = parser.parse_args()
    
    console.print(f"[bold blue]FAQ数据导入工具[/bold blue]")
    console.print(f"RAG服务: {args.rag_url}")
    console.print(f"FAQ文件: {args.faq_file}\n")
    
    # 检查RAG服务
    console.print("[dim]检查RAG服务状态...[/dim]")
    if not await check_rag_health(args.rag_url):
        console.print(f"[red]警告：无法连接到RAG服务 {args.rag_url}[/red]")
        console.print("[yellow]请确保RAG服务已启动[/yellow]")
        # 不退出，允许用户继续
    else:
        console.print("[green]RAG服务连接正常[/green]")
    
    # 加载数据
    faq_data = load_faq_data(args.faq_file)
    documents = prepare_documents(faq_data)
    
    console.print(f"\n准备导入 {len(documents)} 条文档")
    
    # 预览模式
    if args.dry_run:
        console.print("\n[yellow]预览模式 - 预览前3条文档：[/yellow]")
        for doc in documents[:3]:
            console.print(f"\nID: {doc['id']}")
            console.print(f"Category: {doc['metadata']['category']}")
            console.print(f"Content: {doc['content'][:100]}...")
        return
    
    # 确认导入
    confirm = console.input("\n确认开始导入? [y/N]: ")
    if confirm.lower() != 'y':
        console.print("[yellow]已取消[/yellow]")
        return
    
    # 执行导入
    console.print("\n开始导入...")
    stats = await ingest_to_rag(documents, args.rag_url, args.batch_size)
    
    # 打印结果
    print_results(stats)
    
    # 返回码
    if stats["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
