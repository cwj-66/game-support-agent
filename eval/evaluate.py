"""
批量评估 Agent 性能

三段式评估：
  1. 跑 Agent：graph.invoke() 收集 node_trace + messages + final_response
  2. 硬评分（程序逻辑）：
     - tool_score: 预期工具调用召回率
     - escalation_score: must_escalate 是否满足
     - forbidden_score: forbidden_actions 是否触发（触发整题 0 分）
  3. 内容 LLM Judge：
     - 调 LLM（DashScope 优先）评估回复对信息点的覆盖程度
     - 输出 CSV 报告

用法:
    python eval/evaluate.py
    python eval/evaluate.py --category tool
    python eval/evaluate.py --category rag
    python eval/evaluate.py --skip-llm          # 跳过 LLM Judge
    python eval/evaluate.py --max-cases 3       # 调试用
    python eval/evaluate.py --output my_report.csv

    python eval/evaluate.py --category tool --output eval/report_tool
    python eval/evaluate.py --category rag  --output eval/report_rag
    python eval/evaluate.py --category hil  --output eval/report_hil
    python eval/evaluate.py --category mc   --output eval/report_mc
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

# 将项目根目录加入 sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(str(PROJECT_ROOT / ".env"))

from agent.graph import get_graph
from agent.state import create_initial_state


# ======================================================================
# 配置
# ======================================================================

EVAL_DIR = Path(__file__).parent
REPORT_PATH = EVAL_DIR / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
# LLM Judge 模型
JUDGE_FALLBACK_MODEL = os.getenv("JUDGE_FALLBACK_MODEL", "qwen3.6-plus")
JUDGE_TIMEOUT = 30  # 秒


# ======================================================================
# 1. 加载测试用例
# ======================================================================

def load_test_cases(category: Optional[str] = None) -> List[Dict]:
    """加载 eval/ 下所有 JSON 测试用例，category 按 case 的 category 字段过滤"""
    all_cases = []
    for fpath in sorted(glob(str(EVAL_DIR / "*.json"))):
        fname = Path(fpath).name
        if fname == "report.csv":
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


# ======================================================================
# 2. 运行 Agent
# ======================================================================

async def run_single(graph, case: Dict) -> Dict:
    """对单个测试用例执行 graph.invoke()，返回执行结果"""
    case_id = case["id"]
    question = case["question"]
    run_id = f"eval_{case_id}_{datetime.now().strftime('%H%M%S%f')}"

    initial_state = create_initial_state(
        session_id=run_id,
        user_id=case.get("user_id", "10001"),
        user_query=question,
    )

    config = {
        "configurable": {
            "thread_id": run_id,
            "checkpoint_ns": "game_support_eval",
        }
    }

    try:
        result = await graph.ainvoke(initial_state, config)
    except Exception as e:
        tb = traceback.format_exc()
        return {
            "case_id": case_id,
            "error": f"{type(e).__name__}: {e}",
            "traceback": tb,
            "node_trace": [],
            "messages": [],
            "final_response": "",
            "actual_tools": [],
            "interrupt_info": None,
            "has_interrupt": False,
        }

    # 从 messages 中提取实际工具调用
    actual_tools = []
    for msg in result.get("messages", []):
        tc = getattr(msg, "tool_calls", None)
        if tc:
            for t in tc:
                actual_tools.append({
                    "name": t.get("name", ""),
                    "args": t.get("args", {}),
                })

    return {
        "case_id": case_id,
        "node_trace": result.get("node_trace", []),
        "messages": result.get("messages", []),
        "final_response": result.get("final_response") or "",
        "interrupt_info": result.get("interrupt_info"),
        "actual_tools": actual_tools,
        "has_interrupt": result.get("__interrupt__") is not None,
        "error": None,
    }


# ======================================================================
# 3. 硬评分
# ======================================================================

def score_tool_usage(case: Dict, result: Dict) -> Tuple[float, str]:
    """
    工具调用评分：expected_tool_sequence 的召回率
    - expected_no_tools = true 时，实际调用了工具则得 0 分
    - 核心公式：|实际 ∩ 预期| / |预期|
    """
    actual_tools = result.get("actual_tools", [])
    actual_names = {t["name"] for t in actual_tools}

    # 预期不应调用任何工具
    if case.get("expected_no_tools"):
        if actual_tools:
            names = [t["name"] for t in actual_tools]
            return 0.0, f"不应调用工具，实际调用了: {names}"
        return 1.0, ""

    expected = case.get("expected_tool_sequence", [])
    if not expected:
        return 1.0, ""

    expected_names = {e["name"] for e in expected}
    correct = len(expected_names & actual_names)
    score = correct / len(expected_names)

    reasons = []
    if missing := expected_names - actual_names:
        reasons.append(f"缺少: {sorted(missing)}")
    if extra := actual_names - expected_names:
        reasons.append(f"多余: {sorted(extra)}")

    return score, "; ".join(reasons)


def score_escalation(case: Dict, result: Dict) -> Tuple[float, str]:
    """升等评分：must_escalate 为 true 时，human 节点被访问或有 interrupt 即满分"""
    if not case.get("must_escalate"):
        return 1.0, ""
    if "human" in result.get("node_trace", []) or result.get("has_interrupt", False):
        return 1.0, ""
    return 0.0, "应转人工但未触发 human 节点也未产生 interrupt"


def score_forbidden(case: Dict, result: Dict) -> Tuple[float, str, bool]:
    """
    禁止操作评分
    Returns: (score, reason, is_blocked)
    is_blocked=True 时整题总分强制归零
    """
    forbidden = case.get("forbidden_actions", [])
    if not forbidden:
        return 1.0, "", False

    actual_tools = result.get("actual_tools", [])
    violated = [t for t in actual_tools if t["name"] in forbidden]
    if not violated:
        return 1.0, "", False

    names = [v["name"] for v in violated]
    return 0.0, f"触发了禁止操作: {names}", True


# ======================================================================
# 4. LLM-as-Judge（内容评分）
# ======================================================================

def _build_judge_messages(actual_reply: str, ground_truth: str, scenario_context: Optional[str] = None) -> List[Dict]:
    """构造 LLM Judge 的 messages"""
    context_block = ""
    if scenario_context:
        context_block = f"""场景背景（仅供参考，不计入评分）:
{scenario_context}

"""
    prompt = f"""你是一个专业的游戏客服回复质量评估员。你的任务是将实际回复与标准答案对比，评估覆盖程度。

实际回复:
{actual_reply}

{context_block}标准答案（应包含的信息点）:
{ground_truth}

请仔细对比，判断实际回复覆盖了标准答案中的哪些信息点，遗漏了哪些。
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


async def llm_judge(actual_reply: str, ground_truth_text: str, scenario_context: Optional[str] = None) -> Dict:
    """
    调用 LLM 进行内容评估
    链路：DashScope/OpenAI 兼容接口 → 关键词兜底
    """
    if not actual_reply.strip():
        return {"covered": [], "missing": ["无回复内容可评估"], "score": 0.0}

    messages = _build_judge_messages(actual_reply, ground_truth_text, scenario_context)

    result = await _try_llm_judge(messages)
    if result is not None:
        return result

    return _keyword_fallback(actual_reply, ground_truth_text)


# ======================================================================
# 5. 输出
# ======================================================================

def write_csv(results: List[Dict], path: str):
    """输出 CSV 报告（utf-8-sig 供 Excel 直接打开）"""
    fieldnames = [
        "id", "category", "subcategory", "scenario", "question",
        "tool_score", "escalation_score", "forbidden_score", "content_score",
        "total_score",
        "covered_info", "missing_info",
        "failure_reason",
        "node_trace", "error",
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

        # 汇总
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

        # 逐题表格
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

        # 低分题详情
        low_score = [r for r in results if (r.get("total_score") or 1.0) < 0.5]
        if low_score:
            f.write("\n## 低分题\n\n")
            for r in low_score:
                f.write(f"- **{r['id']}** (总分 {r['total_score']:.2f}): ")
                f.write(f"{r.get('failure_reason', '')}\n")
                if r.get("missing_info"):
                    f.write(f"  - 遗漏: {r['missing_info']}\n")

        # 每个 case 的详情（折叠式）
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
            f.write("</details>\n\n")

    print(f"MD:  {path}")


def print_summary(results: List[Dict]):
    """终端打印 Markdown 表格 + 汇总"""
    total = len(results)
    if total == 0:
        print("没有测试结果")
        return

    # ---- 逐题 Markdown 表格 ----
    print(f"\n## 评估报告（共 {total} 题）\n")
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

    # ---- 汇总 ----
    avg_tool = sum(r.get("tool_score", 0) or 0 for r in results) / total
    avg_esc = sum(r.get("escalation_score", 0) or 0 for r in results) / total
    avg_forbid = sum(r.get("forbidden_score", 0) or 0 for r in results) / total
    avg_content = sum(r.get("content_score", 0) or 0 for r in results) / total
    avg_total = sum(r.get("total_score", 0) or 0 for r in results) / total

    print(f"\n### 汇总")
    print(f"| 指标 | 工具调用 | 升等检测 | 禁止操作 | 内容质量 | **综合** |")
    print(f"|------|----------|----------|----------|----------|----------|")
    print(f"| 均分 | {avg_tool:.2f} | {avg_esc:.2f} | {avg_forbid:.2f} | {avg_content:.2f} | **{avg_total:.2f}** |")

    # 按类别聚合
    by_cat = defaultdict(list)
    for r in results:
        by_cat[r.get("category", "unknown")].append(r)
    if by_cat:
        print(f"\n### 按类别")
        for cat, items in sorted(by_cat.items()):
            cat_avg = sum(r.get("total_score", 0) or 0 for r in items) / len(items)
            print(f"- **{cat}**: {len(items)} 题, 均分 {cat_avg:.2f}")

    # 低分题
    low_score = [r for r in results if (r.get("total_score") or 1.0) < 0.5]
    if low_score:
        print(f"\n### ⚠ 低分题 (总分 < 0.5)")
        for r in low_score:
            reason = r.get("failure_reason", "") or r.get("missing_info", "")
            print(f"- **{r['id']}**: {reason[:120]}")


# ======================================================================
# 6. 主流程
# ======================================================================

async def main():
    parser = argparse.ArgumentParser(description="游戏客服 Agent 批量评估")
    parser.add_argument("--category", choices=["tool", "rag", "hil", "mc"], help="只跑特定类别（按 id 前缀匹配）")
    parser.add_argument("--output", default=str(REPORT_PATH), help="CSV/MD 输出路径（不含扩展名）")
    parser.add_argument("--skip-llm", action="store_true", help="跳过 LLM Judge（仅硬评分）")
    parser.add_argument("--max-cases", type=int, default=0, help="最多跑 N 题（调试用）")
    parser.add_argument("--report-format", choices=["csv", "md", "both"], default="both",
                        help="报告格式: csv=Excel用, md=Cursor预览, both=都生成")
    args = parser.parse_args()

    # 加载用例
    cases = load_test_cases(args.category)
    if args.max_cases:
        cases = cases[:args.max_cases]

    print(f"加载了 {len(cases)} 个测试用例")
    if not cases:
        print("没有找到测试用例，退出")
        return

    # 初始化 graph
    print("初始化 LangGraph...")
    graph = await get_graph()

    # 批量运行
    results = []
    for i, case in enumerate(cases):
        cid = case["id"]
        q_short = case.get("question", "")[:50]
        print(f"\n[{i + 1}/{len(cases)}] 运行 {cid}: {q_short}...")

        result = await run_single(graph, case)

        # 运行异常处理
        if result.get("error"):
            print(f"  ❌ 错误: {result['error'][:80]}")
            results.append({
                "id": cid,
                "category": case.get("category", ""),
                "subcategory": case.get("subcategory", ""),
                "scenario": case.get("scenario", ""),
                "question": case.get("question", ""),
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
            continue

        # --- 硬评分 ---
        tool_score, tool_reason = score_tool_usage(case, result)
        esc_score, esc_reason = score_escalation(case, result)
        forbid_score, forbid_reason, is_blocked = score_forbidden(case, result)

        # --- 内容 LLM Judge ---
        if args.skip_llm:
            content_result = {"covered": [], "missing": ["已跳过 LLM Judge"], "score": 0.0}
        else:
            actual_reply = result.get("final_response", "")
            if not actual_reply.strip():
                # 兜底：取最后一条 AI 消息
                from langchain_core.messages import AIMessage
                for msg in reversed(result.get("messages", [])):
                    if isinstance(msg, AIMessage) and msg.content:
                        actual_reply = msg.content
                        break
            content_result = await llm_judge(actual_reply or "", _format_ground_truth(case.get("ground_truth", "")), case.get("llm_judge_context"))

        content_score = content_result.get("score", 0.0)
        covered = content_result.get("covered", [])
        missing = content_result.get("missing", [])

        # --- 综合总分 ---
        # 权重：工具 30% + 升等 15% + 禁止 25% + 内容 30%
        total_score = (
            tool_score * 0.30
            + esc_score * 0.15
            + forbid_score * 0.25
            + content_score * 0.30
        )
        if is_blocked:
            total_score = 0.0

        # --- 失分原因 ---
        reasons = []
        if tool_reason:
            reasons.append(f"[工具] {tool_reason}")
        if esc_reason:
            reasons.append(f"[升等] {esc_reason}")
        if forbid_reason:
            reasons.append(f"[禁止] {forbid_reason}")
        if missing:
            reasons.append(f"[内容] 遗漏: {'; '.join(missing)}")
        if is_blocked:
            reasons.append("触发了禁止操作，整题 0 分")

        print(f"  工具={tool_score:.2f} 升等={esc_score:.2f} 禁止={forbid_score:.2f} "
              f"内容={content_score:.2f} 总分={total_score:.2f}")
        if reasons:
            print(f"  原因: {'; '.join(reasons)[:120]}")

        results.append({
            "id": cid,
            "category": case.get("category", ""),
            "subcategory": case.get("subcategory", ""),
            "scenario": case.get("scenario", ""),
            "question": case.get("question", ""),
            "tool_score": tool_score,
            "escalation_score": esc_score,
            "forbidden_score": forbid_score,
            "content_score": content_score,
            "total_score": total_score,
            "covered_info": "; ".join(covered),
            "missing_info": "; ".join(missing),
            "failure_reason": "; ".join(reasons),
            "node_trace": " -> ".join(result.get("node_trace", [])),
            "error": "",
        })

    # 输出
    output_base = args.output.replace(".csv", "").replace(".md", "")
    fmt = args.report_format
    if fmt in ("csv", "both"):
        write_csv(results, output_base + ".csv")
    if fmt in ("md", "both"):
        write_markdown(results, output_base + ".md")
    print(f"共 {len(results)} 题")
    print_summary(results)


if __name__ == "__main__":
    asyncio.run(main())
