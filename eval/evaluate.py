"""批量评估 Agent：硬评分 + LLM-as-Judge。

用法: python eval/evaluate.py [--category tool|rag|hil|mc] [--skip-llm] [--output PATH]
"""

import argparse
import asyncio
import csv
import json
import logging
import os
import re
import sys
import traceback
from collections import defaultdict
from datetime import datetime
from glob import glob
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(str(PROJECT_ROOT / ".env"))

from agent.graph import get_graph
from agent.state import create_turn_input
from langchain_core.messages import ToolMessage


EVAL_DIR = Path(__file__).parent
REPORT_PATH = EVAL_DIR / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
JUDGE_FALLBACK_MODEL = os.getenv("JUDGE_FALLBACK_MODEL", "qwen3.8-max-0902")
JUDGE_TIMEOUT = 30


def load_test_cases(category: Optional[str] = None) -> List[Dict]:
    """加载 eval/ 下所有 JSON 测试用例，category 按 case 的 category 字段过滤"""
    all_cases = []
    for fpath in sorted(glob(str(EVAL_DIR / "*.json"))):
        fname = Path(fpath).name
        if not re.fullmatch(r"(?:tool|rag|hil|mc)_\d+\.json", fname):
            continue
        with open(fpath, encoding="utf-8") as f:
            data = json.load(f)
            items = data if isinstance(data, list) else [data]
            for item in items:
                item["_source_file"] = fname
            all_cases.extend(items)

    if category:
        all_cases = [c for c in all_cases if c.get("id", "").startswith(category + "_")]

    return all_cases


async def run_single(graph, case: Dict) -> Dict:
    """同一题的各轮共用 checkpoint，并分别记录每轮工具和回复。"""
    case_id = case["id"]
    user_id = case.get("user_id", "10001")
    run_id = f"{user_id}_eval_{case_id}_{datetime.now().strftime('%H%M%S%f')}"

    config = {
        "configurable": {
            "thread_id": run_id,
            "checkpoint_ns": "game_support_eval",
        }
    }

    turns = case.get("turns") or [case]
    turn_results = []
    message_count = trace_count = 0
    for turn in turns:
        try:
            result = await graph.ainvoke(
                create_turn_input(run_id, user_id, turn["question"]), config
            )
        except Exception as e:
            return {
                "case_id": case_id,
                "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc(),
                "turn_results": turn_results,
            }

        messages = result.get("messages", [])
        new_messages = messages[message_count:]
        message_count = len(messages)
        trace = result.get("node_trace", [])
        new_trace = trace[trace_count:]
        trace_count = len(trace)
        actual_tools = [
            {"name": tool.get("name", ""), "args": tool.get("args", {})}
            for msg in new_messages
            for tool in (getattr(msg, "tool_calls", None) or [])
        ]
        turn_results.append({
            "question": turn["question"],
            "messages": new_messages,
            "node_trace": new_trace,
            "final_response": result.get("final_response") or "",
            "human_offer": result.get("human_offer"),
            "actual_tools": actual_tools,
            "tool_results": [
                {"name": msg.name, "content": msg.content}
                for msg in new_messages if isinstance(msg, ToolMessage)
            ],
            "sources": result.get("metadata", {}).get("sources") or [],
        })

    return {"case_id": case_id, "turn_results": turn_results, "error": None}


def score_tool_usage(case: Dict, result: Dict) -> Tuple[float, str]:
    """按顺序匹配预期工具，并对多余调用扣分。"""
    actual_tools = result.get("actual_tools", [])
    actual_names = [t["name"] for t in actual_tools]

    if case.get("expected_no_tools"):
        if actual_tools:
            names = [t["name"] for t in actual_tools]
            return 0.0, f"不应调用工具，实际调用了: {names}"
        return 1.0, ""

    expected = case.get("expected_tool_sequence", [])
    if not expected:
        return 1.0, ""

    expected_names = [e["name"] for e in expected]
    matched = 0
    for name in actual_names:
        if matched < len(expected_names) and name == expected_names[matched]:
            matched += 1
    score = (matched / len(expected_names)) * (matched / max(len(actual_names), 1))

    reasons = []
    if matched < len(expected_names):
        reasons.append(f"预期顺序: {expected_names}，实际: {actual_names}")
    if len(actual_names) > matched:
        reasons.append(f"多余调用: {len(actual_names) - matched}")

    return score, "; ".join(reasons)


def score_escalation(case: Dict, result: Dict) -> Tuple[float, str]:
    """升等评分：must_escalate 为 true 时，调用了 propose_human_escalation 或产生 human_offer 即满分"""
    actual_tools = result.get("actual_tools", [])
    if not case.get("must_escalate"):
        if result.get("human_offer") or any(
            t["name"] == "propose_human_escalation" for t in actual_tools
        ):
            return 0.0, "普通问题不应主动转人工"
        return 1.0, ""
    if any(t["name"] == "propose_human_escalation" for t in actual_tools):
        return 1.0, ""
    if result.get("human_offer"):
        return 1.0, ""
    return 0.0, "应提议转人工但未调用 propose_human_escalation"


def score_forbidden(case: Dict, result: Dict) -> Tuple[float, str, bool]:
    """
    禁止操作评分
    Returns: (score, reason, is_blocked)
    is_blocked=True 时整题总分强制归零
    """
    forbidden = case.get("forbidden_actions", [])
    actual_tools = result.get("actual_tools", [])
    violated = [t for t in actual_tools if t["name"] in forbidden]
    phrases = [
        phrase for phrase in case.get("forbidden_phrases", [])
        if phrase.lower() in result.get("final_response", "").lower()
    ]
    if violated or phrases:
        names = [v["name"] for v in violated]
        return 0.0, f"触发禁止工具 {names} 或错误表述 {phrases}", True
    return 1.0, "", False


def _build_judge_messages(actual_reply: str, ground_truth: str, scenario_context: Optional[str] = None, evidence: Optional[str] = None) -> List[Dict]:
    """构造 LLM Judge 的 messages"""
    context_block = ""
    if scenario_context:
        context_block = f"""场景背景（仅供参考，不计入评分）:
{scenario_context}

"""
    evidence_block = (
        f"本轮内部工具实际返回的账号、工单或知识片段（事实依据）：\n{evidence}\n\n"
        if evidence is not None else ""
    )
    prompt = f"""你是游戏客服回复质量评估员。只使用本题提供的内部工具结果和知识库片段判断事实，不使用互联网或自身常识补充事实。

实际回复:
{actual_reply}

{context_block}{evidence_block}预设参考答案（仅当实际知识库片段支持时才要求覆盖）:
{ground_truth}

判断实际回复覆盖的信息。若内部工具结果没有某信息，回复承认无法确认应得到肯定，不得将该信息列为遗漏。回复添加工具结果没有支持的步骤、数值、规则或状态时必须扣分，并在 missing 写明“无依据内容”。
关键数值（如 10次、1280元、UID 10001）必须准确匹配，数值错误视为未覆盖。

以 JSON 格式输出，不要包含其他内容：
{{"covered": ["覆盖的信息点1", "覆盖的信息点2", ...], "missing": ["遗漏的信息点1", ...], "score": 0-1}}

score 规则：
- 1.0 = 完全覆盖所有信息点
- 0.7-0.9 = 覆盖大部分，遗漏少量次要信息
- 0.4-0.6 = 覆盖约一半
- 0.1-0.3 = 只覆盖了少量信息
- 0.0 = 完全没有覆盖或完全错误"""
    return [{"role": "user", "content": prompt}]


def _parse_judge_response(text: str) -> Dict:
    """从 LLM 输出中提取 JSON"""
    # 优先匹配最外层的完整 JSON 对象
    json_match = re.search(
        r'\{\s*"covered"\s*:\s*\[.*?\]\s*,\s*"missing"\s*:\s*\[.*?\]\s*,\s*"score"\s*:\s*[\d.]+\s*\}',
        text, re.DOTALL
    )
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # 直接尝试解析全文
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    return {"covered": [], "missing": ["LLM Judge 输出解析失败"], "score": 0.0}


def _format_ground_truth(ground_truth: Any) -> str:
    """将 ground_truth 转为可读文本字符串"""
    if isinstance(ground_truth, dict):
        key_info = ground_truth.get("key_information_required", [])
        if key_info:
            lines = ["应包含的信息点："]
            for item in key_info:
                lines.append(f"- {item}")
            return "\n".join(lines)
        # dict 格式但无 key_information_required，fallback 到 description 或全文
        return ground_truth.get("description", str(ground_truth))
    if isinstance(ground_truth, str):
        return ground_truth
    return str(ground_truth)


def _knowledge_evidence(result: Dict) -> Optional[str]:
    """只取本轮知识工具实际返回的片段，避免裁判补充外部常识。"""
    knowledge_results = []
    for item in result.get("tool_results", []):
        if item.get("name") != "query_knowledge":
            continue
        try:
            knowledge_results.append(json.loads(item.get("content") or "{}"))
        except (TypeError, ValueError):
            continue
    if not knowledge_results:
        return None
    texts = [
        str(source.get("text") or "")
        for knowledge in knowledge_results if isinstance(knowledge, dict)
        for source in knowledge.get("sources") or [] if isinstance(source, dict)
    ]
    return "\n".join(texts) if texts else "（没有命中的知识片段）"


def _tool_evidence(result: Dict) -> Optional[str]:
    """给裁判提供当前轮真实工具结果；知识工具只提供原始来源片段。"""
    parts = []
    knowledge = _knowledge_evidence(result)
    if knowledge is not None:
        parts.append(f"query_knowledge 来源:\n{knowledge}")
    for item in result.get("tool_results", []):
        name = item.get("name", "")
        if name and name != "query_knowledge":
            parts.append(f"{name}: {item.get('content', '')}")
    return "\n\n".join(parts) if parts else None


async def _try_llm_judge(messages: List[Dict]) -> Optional[Dict]:
    """用现有 DashScope / OpenAI 兼容接口做 Judge"""
    try:
        from openai import AsyncOpenAI
    except ImportError:
        logger.debug("openai 包未安装，无法使用 LLM Judge")
        return None

    api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    if not api_key:
        logger.debug("未配置 DASHSCOPE_API_KEY 或 OPENAI_API_KEY，LLM Judge 降级")
        return None

    try:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        resp = await client.chat.completions.create(
            model=JUDGE_FALLBACK_MODEL,
            messages=messages,
            max_tokens=1024,
            temperature=0,
        )
        return _parse_judge_response(resp.choices[0].message.content)
    except Exception as e:
        logger.debug("LLM Judge 调用失败: %s", e)
        return None


def _keyword_fallback(actual_reply: str, ground_truth: str) -> Dict:
    """兜底：关键词匹配评分（无 LLM 可用时）"""
    numbers = re.findall(r"\d+[,.]?\d*", ground_truth)
    covered = []
    missing = []

    for num in numbers[:10]:
        clean = num.replace(",", "").replace(".", "")
        if clean in actual_reply.replace(",", "").replace(".", ""):
            covered.append(f"数值 {num}")
        else:
            missing.append(f"数值 {num}")

    score = len(covered) / len(numbers) if numbers else 0.5
    return {"covered": covered, "missing": missing, "score": round(score, 2)}


async def llm_judge(actual_reply: str, ground_truth_text: str, scenario_context: Optional[str] = None, evidence: Optional[str] = None) -> Dict:
    """
    调用 LLM 进行内容评估
    链路：DashScope/OpenAI 兼容接口 → 关键词兜底
    """
    if not actual_reply.strip():
        return {"covered": [], "missing": ["无回复内容可评估"], "score": 0.0}

    messages = _build_judge_messages(actual_reply, ground_truth_text, scenario_context, evidence)

    result = await _try_llm_judge(messages)
    if result is not None:
        return result

    return _keyword_fallback(actual_reply, ground_truth_text)


def write_csv(results: List[Dict], path: str):
    """输出 CSV 报告（utf-8-sig 供 Excel 直接打开）"""
    fieldnames = [
        "id", "category", "subcategory", "scenario", "question",
        "tool_score", "escalation_score", "forbidden_score", "content_score",
        "total_score",
        "covered_info", "missing_info",
        "failure_reason",
        "node_trace", "error", "environment_error",
    ]

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            writer.writerow({k: row.get(k, "") for k in fieldnames})

    print(f"CSV: {path}")


def write_markdown(results: List[Dict], path: str):
    """输出 Markdown 报告（Cursor/VS Code 原生渲染）"""
    with open(path, "w", encoding="utf-8") as f:
        f.write("# 评估报告\n\n")

        affected = [r["id"] for r in results if r.get("environment_error")]
        if affected:
            f.write(f"**环境异常**: {', '.join(affected)} 的工具返回模型额度错误；"
                    "下方均分包含这些题，不能用于判断模型能力。\n\n")

        total = len(results)
        avg_tool = sum(r.get("tool_score", 0) or 0 for r in results) / total
        avg_esc = sum(r.get("escalation_score", 0) or 0 for r in results) / total
        avg_forbid = sum(r.get("forbidden_score", 0) or 0 for r in results) / total
        avg_content = sum(r.get("content_score", 0) or 0 for r in results) / total
        avg_total = sum(r.get("total_score", 0) or 0 for r in results) / total

        f.write(f"**总题数**: {total}  |  ")
        f.write(f"**工具均分**: {avg_tool:.2f}  |  ")
        f.write(f"**升等均分**: {avg_esc:.2f}  |  ")
        f.write(f"**禁止均分**: {avg_forbid:.2f}  |  ")
        f.write(f"**内容均分**: {avg_content:.2f}  |  ")
        f.write(f"**综合均分**: {avg_total:.2f}\n\n")

        f.write("## 逐题明细\n\n")
        f.write("| ID | 类别 | 工具分 | 升等分 | 禁止分 | 内容分 | 总分 | 失分原因 |\n")
        f.write("|----|------|--------|--------|--------|--------|------|----------|\n")
        for r in results:
            cid = r["id"]
            cat = r.get("category", "")[:16]
            ts = f"{r['tool_score']:.2f}"
            es = f"{r['escalation_score']:.2f}"
            fs = f"{r['forbidden_score']:.2f}"
            cs = f"{r['content_score']:.2f}"
            tot = f"{r['total_score']:.2f}"
            reason = (r.get("failure_reason") or "")[:60]
            f.write(f"| {cid} | {cat} | {ts} | {es} | {fs} | {cs} | {tot} | {reason} |\n")

        low_score = [r for r in results if (r.get("total_score") or 1.0) < 0.5]
        if low_score:
            f.write("\n## 低分题\n\n")
            for r in low_score:
                f.write(f"- **{r['id']}** (总分 {r['total_score']:.2f}): ")
                f.write(f"{r.get('failure_reason', '')}\n")
                if r.get("missing_info"):
                    f.write(f"  - 遗漏: {r['missing_info']}\n")

        f.write("\n## 详情\n\n")
        for r in results:
            f.write(f"<details>\n")
            f.write(f"<summary><b>{r['id']}</b> — 总分 {r['total_score']:.2f}</summary>\n\n")
            f.write(f"**问题**: {r.get('question', '')}\n\n")
            f.write(f"**执行路径**: `{r.get('node_trace', '')}`\n\n")
            if r.get("covered_info"):
                f.write(f"**已覆盖**: {r['covered_info']}\n\n")
            if r.get("missing_info"):
                f.write(f"**遗漏**: {r['missing_info']}\n\n")
            if r.get("failure_reason"):
                f.write(f"**失分原因**: {r['failure_reason']}\n\n")
            if r.get("environment_error"):
                f.write(f"**环境异常**: {r['environment_error']}\n\n")
            f.write("</details>\n\n")

    print(f"MD:  {path}")


def print_summary(results: List[Dict]):
    """终端打印 Markdown 表格 + 汇总"""
    total = len(results)
    if total == 0:
        print("没有测试结果")
        return

    print(f"\n## 评估报告（共 {total} 题）\n")
    affected = [r["id"] for r in results if r.get("environment_error")]
    if affected:
        print(f"环境异常: {', '.join(affected)}；均分包含受影响题，不宜用于能力判断。\n")
    header = "| ID | 类别 | 工具分 | 升等分 | 禁止分 | 内容分 | 总分 | 失分原因 |"
    sep = "|----|------|--------|--------|--------|--------|------|----------|"
    print(header)
    print(sep)
    for r in results:
        cid = r["id"]
        cat = r.get("category", "")[:12]
        ts = f"{r['tool_score']:.2f}"
        es = f"{r['escalation_score']:.2f}"
        fs = f"{r['forbidden_score']:.2f}"
        cs = f"{r['content_score']:.2f}"
        tot = f"{r['total_score']:.2f}"
        reason = (r.get("failure_reason") or "")[:40]
        print(f"| {cid} | {cat} | {ts} | {es} | {fs} | {cs} | {tot} | {reason} |")

    avg_tool = sum(r.get("tool_score", 0) or 0 for r in results) / total
    avg_esc = sum(r.get("escalation_score", 0) or 0 for r in results) / total
    avg_forbid = sum(r.get("forbidden_score", 0) or 0 for r in results) / total
    avg_content = sum(r.get("content_score", 0) or 0 for r in results) / total
    avg_total = sum(r.get("total_score", 0) or 0 for r in results) / total

    print(f"\n### 汇总")
    print(f"| 指标 | 工具调用 | 升等检测 | 禁止操作 | 内容质量 | **综合** |")
    print(f"|------|----------|----------|----------|----------|----------|")
    print(f"| 均分 | {avg_tool:.2f} | {avg_esc:.2f} | {avg_forbid:.2f} | {avg_content:.2f} | **{avg_total:.2f}** |")

    by_cat = defaultdict(list)
    for r in results:
        by_cat[r.get("category", "unknown")].append(r)
    if by_cat:
        print(f"\n### 按类别")
        for cat, items in sorted(by_cat.items()):
            cat_avg = sum(r.get("total_score", 0) or 0 for r in items) / len(items)
            print(f"- **{cat}**: {len(items)} 题, 均分 {cat_avg:.2f}")

    low_score = [r for r in results if (r.get("total_score") or 1.0) < 0.5]
    if low_score:
        print(f"\n### ⚠ 低分题 (总分 < 0.5)")
        for r in low_score:
            reason = r.get("failure_reason", "") or r.get("missing_info", "")
            print(f"- **{r['id']}**: {reason[:120]}")


async def score_turn(case: Dict, result: Dict, skip_llm: bool) -> Dict:
    """独立评分一轮，避免多轮题的工具调用相互抵消。"""
    tool_outputs = "\n".join(str(item.get("content", "")) for item in result.get("tool_results", []))
    environment_error = (
        "阿里云模型免费额度已用尽（AllocationQuota.FreeTierOnly）"
        if "AllocationQuota.FreeTierOnly" in tool_outputs else ""
    )
    tool_score, tool_reason = score_tool_usage(case, result)
    esc_score, esc_reason = score_escalation(case, result)
    forbid_score, forbid_reason, is_blocked = score_forbidden(case, result)

    if skip_llm:
        content_result = {"covered": [], "missing": ["已跳过 LLM Judge"], "score": 0.0}
    else:
        actual_reply = result.get("final_response", "")
        if not actual_reply.strip():
            from langchain_core.messages import AIMessage
            for msg in reversed(result.get("messages", [])):
                if isinstance(msg, AIMessage) and msg.content:
                    actual_reply = str(msg.content)
                    break
        content_result = await llm_judge(
            actual_reply, _format_ground_truth(case.get("ground_truth", "")),
            case.get("llm_judge_context"),
            _tool_evidence(result),
        )

    content_score = content_result.get("score", 0.0)
    is_human_offer_case = case.get("must_escalate") and (
        result.get("human_offer") or any(
            t["name"] == "propose_human_escalation"
            for t in result.get("actual_tools", [])
        )
    )
    if is_human_offer_case:
        total_score = tool_score * 0.45 + esc_score * 0.35 + forbid_score * 0.20
    else:
        total_score = (
            tool_score * 0.30 + esc_score * 0.15
            + forbid_score * 0.25 + content_score * 0.30
        )
    if is_blocked:
        total_score = 0.0

    reasons = [reason for reason in (tool_reason, esc_reason, forbid_reason) if reason]
    if not is_human_offer_case and not skip_llm:
        reasons.extend(content_result.get("missing", []))
    return {
        "question": case["question"],
        "tool_score": tool_score,
        "escalation_score": esc_score,
        "forbidden_score": forbid_score,
        "content_score": content_score,
        "total_score": total_score,
        "covered_info": "; ".join(content_result.get("covered", [])),
        "missing_info": "; ".join(content_result.get("missing", [])),
        "failure_reason": "; ".join(reasons),
        "actual_tools": result.get("actual_tools", []),
        "tool_results": result.get("tool_results", []),
        "environment_error": environment_error,
        "final_response": result.get("final_response", ""),
        "sources": result.get("sources", []),
        "node_trace": result.get("node_trace", []),
    }


async def main():
    parser = argparse.ArgumentParser(description="游戏客服 Agent 批量评估")
    parser.add_argument("--category", choices=["tool", "rag", "hil", "mc"], help="只跑特定类别（按 id 前缀匹配）")
    parser.add_argument("--output", default=str(REPORT_PATH), help="CSV/MD 输出路径（不含扩展名）")
    parser.add_argument("--skip-llm", action="store_true", help="跳过 LLM Judge（仅硬评分）")
    parser.add_argument("--max-cases", type=int, default=0, help="最多跑 N 题（调试用）")
    parser.add_argument("--report-format", choices=["csv", "md", "both"], default="both",
                        help="报告格式: csv=Excel用, md=Cursor预览, both=都生成")
    args = parser.parse_args()

    cases = load_test_cases(args.category)
    if args.max_cases:
        cases = cases[:args.max_cases]

    print(f"加载了 {len(cases)} 个测试用例")
    if not cases:
        print("没有找到测试用例，退出")
        return

    from app.core.config import get_settings
    from agent.tools.mcp_client import init_mcp_client, close_mcp_client
    from agent.checkpointer import close_checkpointer

    print("连接 MCP 并初始化 LangGraph...")
    await init_mcp_client(get_settings().MCP_SERVER_URL.rstrip("/") + "/mcp")
    graph = await get_graph()

    output_base = args.output.replace(".csv", "").replace(".md", "")

    def save_progress(rows: List[Dict]) -> None:
        with open(output_base + ".json", "w", encoding="utf-8") as file:
            json.dump(rows, file, ensure_ascii=False, indent=2)

    results = []
    for i, case in enumerate(cases):
        cid = case["id"]
        q_short = (case.get("question") or case.get("turns", [{}])[0].get("question", ""))[:50]
        print(f"\n[{i + 1}/{len(cases)}] 运行 {cid}: {q_short}...")

        result = await run_single(graph, case)

        if result.get("error"):
            print(f"  ❌ 错误: {result['error'][:80]}")
            results.append({
                "id": cid,
                "category": case.get("category", ""),
                "subcategory": case.get("subcategory", ""),
                "scenario": case.get("scenario", ""),
                "question": q_short,
                "tool_score": 0.0,
                "escalation_score": 0.0,
                "forbidden_score": 0.0,
                "content_score": 0.0,
                "total_score": 0.0,
                "covered_info": "",
                "missing_info": f"运行错误: {result['error']}",
                "failure_reason": f"运行异常: {result['error']}",
                "node_trace": "[]",
                "error": result["error"],
            })
            save_progress(results)
            continue

        turns = case.get("turns") or [case]
        details = [
            await score_turn(turn, turn_result, args.skip_llm)
            for turn, turn_result in zip(turns, result["turn_results"])
        ]
        count = len(details)
        averages = {
            key: sum(detail[key] for detail in details) / count
            for key in ("tool_score", "escalation_score", "forbidden_score",
                        "content_score", "total_score")
        }
        reasons = [
            f"第{index}轮: {detail['failure_reason']}"
            for index, detail in enumerate(details, 1) if detail["failure_reason"]
        ]
        print(f"  综合={averages['total_score']:.2f}，各轮={[round(d['total_score'], 2) for d in details]}")
        results.append({
            "id": cid,
            "category": case.get("category", ""),
            "subcategory": case.get("subcategory", ""),
            "scenario": case.get("fixture", ""),
            "question": " / ".join(turn["question"] for turn in turns),
            **averages,
            "covered_info": "; ".join(d["covered_info"] for d in details if d["covered_info"]),
            "missing_info": "; ".join(d["missing_info"] for d in details if d["missing_info"]),
            "failure_reason": "; ".join(reasons),
            "node_trace": " / ".join(" -> ".join(d["node_trace"]) for d in details),
            "error": "",
            "environment_error": "; ".join(
                sorted({d["environment_error"] for d in details if d["environment_error"]})
            ),
            "turn_details": details,
        })
        save_progress(results)

    fmt = args.report_format
    if fmt in ("csv", "both"):
        write_csv(results, output_base + ".csv")
    if fmt in ("md", "both"):
        write_markdown(results, output_base + ".md")
    await close_checkpointer()
    await close_mcp_client()
    print(f"共 {len(results)} 题")
    print_summary(results)


if __name__ == "__main__":
    asyncio.run(main())
