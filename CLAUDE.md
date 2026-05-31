# CLAUDE.md — Game Support Agent

## 项目概述

这是一个面向游戏客服场景的 AI Agent，基于 **LangGraph** 构建。核心目标是通过 LLM 自动处理玩家游戏客服请求（查询攻略、账号状态、创建工单等），同时通过 **Human-in-loop 机制** 确保安全合规——LLM 无法处理或触犯安全规则时转人工审核。

## 技术栈

| 层面 | 选型 |
|---|---|
| AI 编排 | LangGraph / langchain-core / langchain-openai |
| LLM | 阿里云 DashScope (qwen-turbo) 优先，OpenAI 兜底 |
| API 服务 | FastAPI + Pydantic |
| 持久化 | LangGraph MemorySaver（内存，当前演示用） |
| 审核界面 | Streamlit |
| 终端工具 | rich 库 |
| 测试 | pytest |

## 项目结构

```
game-support-agent/
├── agent/                          # LangGraph 核心编排
│   ├── graph.py                    # 主图：6 个节点 + 3 条条件边 + 路由函数
│   ├── state.py                    # AgentState 定义（TypedDict）
│   ├── checkpointer.py             # MemorySaver 状态持久化（单例）
│   ├── nodes/
│   │   ├── reasoning.py            # LLM 推理节点（bind_tools 自主决策）
│   │   ├── tool_exec.py            # 通用工具分发器（按 tool_calls 执行）
│   │   └── human_node.py           # 人工审核节点（interrupt 挂起 + 恢复）
│   ├── tools/
│   │   ├── __init__.py             # get_all_tools() 工厂，暴露 4 个工具
│   │   ├── query_knowledge.py        # KnowledgeTool（HTTP 直接调用 RAG 知识库）
│   │   ├── rag_client.py            # RAG HTTP 客户端（直接调 enterprise-rag）
│   │   ├── escalate.py             # 转人工工具 + EscalateDetector 升等检测（两路触发）
│   │   ├── account.py              # lookup_account(fields=None)（查询账号状态，按需取字段）
│   │   └── ticket.py               # create_ticket（创建工单）
│   └── prompts/
│       └── system.py               # 系统提示词（决策 + 客服润色）
├── app/                            # FastAPI 服务层
│   ├── main.py                     # 入口（CORS、路由、生命周期）
│   ├── api/v1/
│   │   ├── chat.py                 # POST /chat/send、GET /chat/history、POST /chat/stream
│   │   └── human.py                # 审核接口（pending、review、history、status）
│   ├── core/
│   │   ├── config.py               # pydantic-settings 配置管理
│   │   ├── llm.py                  # LLM 工厂（阿里云 > OpenAI 回退）
│   │   └── exceptions.py           # 5 种业务异常 + 全局处理
│   └── models/
│       ├── chat.py                 # 对话请求/响应模型
│       └── review.py               # 审核请求/响应模型
├── human_in_loop/                  # Human-in-loop 底层模块
│   ├── detector.py                 # InterruptDetector 安全兜底（敏感词 + 置信度）
│   ├── reviewer.py                 # HumanReviewer（APPROVE / MODIFY / OVERRIDE）
│   ├── auditor.py                  # AuditLogger（JSON 文件审计链）
│   └── schema.py                   # 数据结构（dataclass + TypedDict）
├── client/
│   ├── cli.py                      # 终端 CLI（rich 库）
│   └── web_ui.py                   # Streamlit 审核界面
├── scripts/
│   └── ingest_faq.py               # FAQ 批量导入 RAG
├── tests/
│   ├── conftest.py                 # Fixtures
│   ├── test_agent.py               # Agent 状态/节点/图/集成测试
│   ├── test_human_in_loop.py       # HIL 核心测试
│   └── test_rag_client.py          # RAG 客户端测试
├── data/
│   └── faq.json                    # 30 条《原神》FAQ 示例数据
├── .env.example                    # 配置模板
├── .gitignore                      # 忽略 venv/ __pycache__/ .env
├── requirements.txt
└── docker-compose.yml              # 3 个服务：rag / agent-api / web-ui
```

## 架构说明

### LangGraph 图结构

```
                 ┌──────────┐
                 │ 入口      │
                 │ START     │
                 └────┬─────┘
                      │
                      ▼
              ┌───────────────┐
              │  reasoning    │  ←─ LLM 绑定工具，自主决策
              │  (推理节点)   │     调工具？调什么工具？
              └───┬───────┬───┘
                  │       │
         有工具调用│       │无工具调用
                  │       │
                  ▼       ▼
        ┌────────────┐  ┌──────────┐
        │ tool_exec  │  │ generate │  ←─ 客服润色最终回复
        │ (工具执行)  │  │ (生成回复)│
        └─────┬──────┘  └────┬─────┘
              │               │
              │     ┌─────────┘
              │     ▼
     ┌────────┐  ┌──────────┐
     │  human │  │ detector │  ←─ 最后一道安全兜底
     │(人工审核)│  │(中断检测) │     敏感词/置信度
     └────┬───┘  └────┬─────┘
          │           │
          │    ┌──────┴──────┐
          │    │             │
          │    ▼             ▼
          │  ┌────────┐ ┌────────┐
          │  │ finish │ │ human  │
          │  │ (结束)  │ │(人工审核)│
          │  └────────┘ └────┬───┘
          └─────────┬────────┘
                    │
                    ▼
              ┌──────────┐
              │ generate │  ←─ 人工审核完成后重新生成回复
              │ (重新生成)│
              └──────────┘
```

### 节点职责

| 节点 | 职责说明 |
|---|---|
| **reasoning** | LLM 绑定 4 个工具进行自主决策。返回 AIMessage 可有 tool_calls（调工具）或无（直接润色）。出错时降级为兜底消息 |
| **tool_exec** | 通用分发器。逐条执行 tool_calls，写回 ToolMessage。对 `escalate_to_human` 做二次检测（EscalateDetector）。记录调用审计 |
| **generate** | 结合工具结果和客服提示词生成最终回复。若有人工审核结果（OVERRIDE/MODIFY），直接用人工内容。评估回复置信度并存到 metadata |
| **detector** | 最后一道安全兜底。InterruptDetector 检查内容中是否有敏感词、置信度是否过低 |
| **human** | 调用 `interrupt()` 挂起图，等待人工操作。恢复后由 HumanReviewer 处理三种操作 + 写审计日志 |
| **finish** | 结束节点。记录结束时间，将本轮对话压缩为一句摘要存到 `session_summary`，供下一轮复用 |

### 条件路由

| 路由函数 | 来源 → 去向 | 判断逻辑 |
|---|---|---|
| `route_from_reasoning` | reasoning → tool_exec / generate | AIMessage 含 tool_calls → tool_exec，否则 generate |
| `route_from_tool_exec` | tool_exec → human / reasoning | `interrupt_info.source == "llm_escalate"` → human，否则回 reasoning（ReAct 循环） |
| `route_from_detector` | detector → human / finish | `should_interrupt == True` → human，否则 finish |

### Human-in-loop 机制（两层检测）

**第一层 — 业务升等检测（escalate.py）**：两路触发——LLM 主动调用 escalate_to_human 工具（内部跑 EscalateDetector 深度判断），同时 tool_exec_node 每次执行完所有工具后调用 check_escalation() 兜底检测（工具失败/知识库无结果/ReAct 超限）。

**第二层 — 安全兜底检测（InterruptDetector）**：在 generate 之后，检查最终回复是否含敏感词、置信度是否过低。这是最后防线。

**三种审核操作**：
- APPROVE：直接通过原 Agent 回复
- MODIFY：修改后通过（人工编辑版）
- OVERRIDE：覆盖，人工重写

### 状态定义（AgentState）

关键字段：`messages`（对话历史，add_messages 自动合并）、`user_query`、`session_id`、`interrupt_info`、`human_review`、`tool_calls`（审计用）、`final_response`、`session_summary`（多轮摘要）、`metadata`

## 关键约束

1. **不要修改 graph.py 的图结构**（节点注册、边定义、路由逻辑）。如有改动需求，先问。
2. **human_node.py 的 interrupt() 调用是核心**。不要移除或绕过，整个 HIL 机制依赖它。
3. **不要删除或重命名 human_in_loop/ 下的任何模块**，detector、reviewer、auditor 都有明确职责。
4. **所有工具必须通过 `agent/tools/__init__.py` 的 `get_all_tools()` 暴露**。新增工具请走这个工厂。
5. **LLM 配置优先走阿里云 DashScope**，OpenAI 只做兜底。Key 配在 .env，不上传 GitHub。
6. **知识工具必须做安全降级**。KnowledgeTool 已实现连接失败/超时的分层处理，新增类似工具也要遵循。
7. **Agent 状态持久化目前用 MemorySaver（内存）**，重启后状态丢失。生产环境需替换。
8. **代码注释和 Docstring 用中文**，便于团队理解。
9. `.claude/` 目录和 `.env` 不上传 GitHub（已在 `.gitignore` 中配置）。

## 常用命令

```bash
# 安装依赖
pip install -r requirements.txt

# 复制配置模板
cp .env.example .env
# 然后编辑 .env 填入 LLM API Key 等

# 启动 FastAPI 服务
python -m app.main

# 启动 Steamlit 审核界面
streamlit run client/web_ui.py

# 终端 CLI 单次查询
python client/cli.py --session test_001 "如何获得原石？"

# 终端 CLI 交互模式
python client/cli.py

# 运行测试
pytest
# 指定文件
pytest tests/test_human_in_loop.py -v
# 带覆盖率
pytest --cov=agent --cov=human_in_loop --cov-report=html

# 导入 FAQ 到 RAG
python scripts/ingest_faq.py --rag-url http://localhost:8000

# Docker 启动
docker-compose up -d
```

## 当前进度

### 已完成
- [x] LangGraph 图结构定义（6 个节点 + 条件边 + ReAct 循环）
- [x] 4 个客服工具（知识库查询、账号查询、创建工单、转人工）
- [x] RAG 知识库 HTTP 集成（直接调用 RAG 服务）
- [x] Human-in-loop 完整链路（两层检测 + interrupt + 三种操作 + 审计日志）
- [x] FastAPI 服务层（对话接口 + 审核接口 + SSE 流式）
- [x] Streamlit 审核界面
- [x] 终端 CLI
- [x] 测试套件（Agent + HIL + RAG）
- [x] 多轮对话摘要（session_summary 跨轮传递）
- [x] FAQ 数据和导入脚本

### 待开发
- [ ] RAG 健康检查接入应用生命周期
- [ ] 生产级状态持久化（Redis/Postgres）
- [ ] 审核队列管理和任务分配
- [ ] 测试覆盖率提升（尤其端到端和 SSE 集成测试）
- [ ] 多语言回复支持
- [ ] 监控指标（Prometheus）和错误追踪（Sentry）
- [ ] 性能优化和 token 成本控制

## 给 Claude Code 的提示

- 遇到不确定的架构决策先问我，不要自作主张修改 graph 结构，不要不经过同意就修改代码。
- 不确定某个模块职责时，先阅读该模块的文件头 docstring，里面有清晰说明。
- 新增工具记得在 `agent/tools/__init__.py` 注册，并在 `agent/prompts/system.py` 的 `GAME_SUPPORT_SYSTEM_PROMPT` 中添加说明。
- 这个文件不上传到 GitHub（已在 `.gitignore` 中配置）。
