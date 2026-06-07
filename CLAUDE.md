# CLAUDE.md — Game Support Agent

## 项目概述

这是一个面向游戏客服场景的 AI Agent，基于 **LangGraph** 构建。核心目标是通过 LLM 自动处理玩家游戏客服请求（查询攻略、账号状态、创建工单等），同时通过 **安全检测+人工审核** 机制确保安全合规。

## 技术栈

| 层面 | 选型 |
|---|---|
| AI 编排 | LangGraph / langchain-core / langchain-openai |
| LLM | 阿里云 DashScope (qwen-turbo) 优先，OpenAI 兜底 |
| API 服务 | FastAPI + Pydantic |
| 持久化 | LangGraph AsyncSqliteSaver (SQLite) + 工单 SQLite |
| 审核界面 | Streamlit |
| 终端工具 | rich 库 |
| 评估 | LLM-as-Judge via qwen-max |
| 测试 | pytest |

## 项目结构

```
game-support-agent/
├── agent/                          # LangGraph 核心编排
│   ├── graph.py                    # 主图：7 个节点 + 2 条条件边 + 路由函数
│   ├── state.py                    # AgentState 定义（TypedDict）
│   ├── checkpointer.py             # AsyncSqliteSaver 状态持久化（SQLite 文件）
│   ├── nodes/
│   │   ├── reasoning.py            # LLM 推理节点（bind_tools 自主决策）
│   │   ├── tool_exec.py            # 通用工具分发器（按 tool_calls 执行）
│   │   ├── generate.py             # 客服回复润色生成
│   │   ├── detector.py             # 安全检测节点（敏感词/工具失败替换内容）
│   │   ├── human_node.py           # 人工审核节点（interrupt 挂起 + 恢复）
│   │   ├── escalate_node.py        # 转人工 Handoff 节点（整理上下文后移交 human）
│   │   └── finish.py               # 结束节点（清理元数据、更新工单状态）
│   ├── tools/
│   │   ├── __init__.py             # get_all_tools() 工厂，暴露 5 个工具
│   │   ├── query_knowledge.py        # KnowledgeTool（HTTP 直接调用 RAG 知识库）
│   │   ├── rag_client.py            # RAG HTTP 客户端
│   │   ├── escalate.py             # EscalateDetector 升等检测器（保留供后续扩展）
│   │   ├── account.py              # lookup_account(fields)（查询账号状态，按需取字段）
│   │   ├── ticket.py               # create_ticket（创建工单）
│   │   ├── ticket_status.py         # check_ticket（查询工单进度）
│   │   └── human_escalation.py      # request_human_escalation（转人工升等工具）
│   └── prompts/
│       └── system.py               # 系统提示词（决策 + 客服润色）
├── app/                            # FastAPI 服务层
│   ├── main.py                     # 入口（CORS、路由、生命周期）
│   ├── api/v1/
│   │   ├── chat.py                 # POST /chat/send、GET /chat/history、POST /chat/stream
│   │   ├── human.py                # 审核接口（pending、review、status）
│   │   └── ticket.py               # 工单接口（创建、查询、更新、统计）
│   ├── core/
│   │   ├── database.py             # SQLite 工单 CRUD
│   │   ├── pending_store.py        # 待审核队列（内存，重启丢失）
│   │   ├── config.py               # pydantic-settings 配置管理
│   │   ├── llm.py                  # LLM 工厂（阿里云 > OpenAI 回退）
│   │   └── exceptions.py           # 5 种业务异常 + 全局处理
│   └── models/
│       ├── chat.py                 # 对话请求/响应模型
│       ├── review.py               # 审核请求/响应模型
│       └── ticket.py               # 工单数据模型
├── safety/                         # 安全检测模块
│   ├── detector.py                 # 敏感词匹配 + 工具失败检测
│   ├── schema.py                   # 数据结构（dataclass）
│   └── __init__.py
├── eval/                           # 评测框架
│   ├── evaluate.py                 # 三段式评测引擎（硬评分 + LLM-as-Judge）
│   ├── rag_01~07.json              # RAG 检索类别 7 题
│   ├── tool_01~08.json             # 工具调用类别 8 题
│   ├── hil_01~07.json              # HIL 类别 7 题
│   ├── mc_01~05.json               # 多轮上下文类别 5 题
│   └── report_*.{csv,md}           # 评估报告
├── client/
│   ├── cli.py                      # 终端 CLI（rich 库）
│   └── web_ui.py                   # Streamlit 审核界面
├── tests/
│   ├── conftest.py                 # Fixtures
│   ├── test_agent.py               # Agent 状态/节点/图/集成测试
│   ├── test_safety.py              # 安全检测模块测试
│   └── test_rag_client.py          # RAG 客户端测试
├── data/
│   ├── accounts.json               # 账号 mock 数据（账号查询工具使用）
│   ├── game_support.db             # LangGraph 状态持久化
│   └── tickets.db                  # 工单 SQLite
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
              │  reasoning    │  ←─ LLM 绑定 5 个工具，自主决策
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
         有升等│               │
         请求 │               ▼
              ▼         ┌──────────┐       ┌──────────────────┐
     ┌──────────────┐   │ detector │  ←─  │ 安全检测，命中则  │
     │human_handoff │   │ (安全检测)│      │ 直接替换回复内容  │
     │(转人工Handoff)│   └────┬─────┘      └──────────────────┘
     └──────┬───────┘        │
            │                ▼
            ▼          ┌──────────┐
     ┌──────────┐      │  finish  │
     │  human   │      │  (结束)  │
     │(人工审核) │      └──────────┘
     └────┬─────┘
          │
          ▼
    ┌──────────┐
    │  finish  │  ←─ 若有 human_reply，作为最终回复
    │  (结束)  │
    └──────────┘
```

### 节点职责

| 节点 | 职责说明 |
|---|---|
| **reasoning** | LLM 绑定 5 个工具进行自主决策。返回 AIMessage 可有 tool_calls（调工具）或无（直接润色）。出错时降级为兜底消息 |
| **tool_exec** | 通用分发器。逐条执行 tool_calls，写回 ToolMessage。对 `request_human_escalation` 提前拦截并直接设 interrupt_info。重复调用检测、工单上下文注入。记录调用审计 |
| **generate** | 结合工具结果和客服提示词生成最终回复。有关联工单时回写 agent_reply |
| **detector** | 安全兜底（不触发中断）。敏感词命中 → 替换回复为违规警告；工具调用失败 → 替换为道歉+询问转人工。拦截记录写入 metadata |
| **human_handoff** | 转人工 Handoff。整理工具执行记录和对话上下文，构建 interrupt_info，路由到 human 节点 |
| **human** | 调用 `interrupt()` 挂起图，等待人工输入。恢复后直接将人工回复字符串写入 state.human_reply |
| **finish** | 结束节点。若有 human_reply 则作为最终回复（标记 human_source）。关联工单自动标记 resolved。清理运行时元数据 |

### 条件路由

| 路由/边 | 来源 → 去向 | 判断逻辑 |
|---|---|---|
| `route_from_reasoning` | reasoning → tool_exec / generate | AIMessage 含 tool_calls → tool_exec，否则 generate |
| `route_from_tool_exec` | tool_exec → reasoning / human_handoff | `interrupt_info` 存在 → human_handoff，否则回 reasoning（ReAct 循环） |
| 固定边 | detector → finish | 直连（检测结果直接替换回复内容，不触发中断） |
| 固定边 | human → finish | 直连（human_reply 由 finish_node 处理为最终回复） |

### 人工审核流程

LLM 调用 `request_human_escalation` 工具 → tool_exec 检测到后设 `interrupt_info` → `human_handoff` 节点整理上下文 → `human` 节点挂起。

审核员通过 API 直接输入回复字符串 → `Command(resume=reply)` 恢复图执行 → `human_node` 把字符串写入 `state.human_reply` → `finish_node` 作为最终回复（标记 `human_source=True`）。

### 安全检测

`detector` 节点在 generate 之后执行，由 `safety.detector` 模块提供：
- 敏感词检测：~15 条内置敏感词正则匹配，命中后替换回复为违规警告
- 工具失败检测：检查 metadata 中的工具调用状态，失败后替换为道歉+询问是否转人工

检测器**不触发 interrupt**，直接替换回复内容 + 记录拦截日志到 metadata。

### 状态定义（AgentState）

关键字段：`messages`（对话历史，add_messages 自动合并）、`user_query`、`user_id`、`session_id`、`ticket_id`、`interrupt_info`、`human_review`、`human_reply`、`tool_calls`（审计用）、`final_response`、`node_trace`（节点执行路径追踪）、`metadata`

## 关键约束

1. **不要修改 graph.py 的图结构**（节点注册、边定义、路由逻辑）。如有改动需求，先问。
2. **human_node.py 的 interrupt() 调用是核心**。不要移除或绕过，整个审核机制依赖它。
3. **所有工具必须通过 `agent/tools/__init__.py` 的 `get_all_tools()` 暴露**。新增工具请走这个工厂。
4. **LLM 配置优先走阿里云 DashScope**，OpenAI 只做兜底。Key 配在 .env，不上传 GitHub。
5. **知识工具必须做安全降级**。KnowledgeTool 已实现连接失败/超时的分层处理，新增类似工具也要遵循。
6. **Agent 状态持久化目前用 AsyncSqliteSaver（SQLite 文件）**，重启后状态保留。生产环境可替换为 RedisSaver 或 PostgresSaver。
7. **代码注释和 Docstring 用中文**，便于团队理解。
8. `.claude/` 目录和 `.env` 不上传 GitHub（已在 `.gitignore` 中配置）。

## 常用命令

```bash
# 安装依赖
pip install -r requirements.txt

# 复制配置模板
cp .env.example .env
# 然后编辑 .env 填入 LLM API Key 等

# 启动 FastAPI 服务
python -m app.main

# 启动 Streamlit 审核界面
streamlit run client/web_ui.py

# 终端 CLI 单次查询
python client/cli.py --session test_001 "如何获得原石？"

# 终端 CLI 交互模式
python client/cli.py

# 运行评测
python eval/evaluate.py
python eval/evaluate.py --category tool
python eval/evaluate.py --skip-llm

# 运行测试
pytest
pytest tests/test_safety.py -v
pytest --cov=agent --cov=safety --cov-report=html

# Docker 启动
docker-compose up -d
```

## 当前进度

### 已完成
- [x] LangGraph 图结构定义（7 个节点 + 条件边 + ReAct 循环）
- [x] 5 个客服工具（知识库查询、账号查询、创建工单、查工单进度、转人工）
- [x] RAG 知识库 HTTP 集成（直接调用 RAG 服务）
- [x] 人工审核完整链路（升等触发 + handoff 整理 + interrupt 挂起 + 恢复）
- [x] 安全检测（敏感词 + 工具失败静默拦截）
- [x] FastAPI 服务层（对话接口 + 审核接口 + SSE 流式）
- [x] Streamlit 审核界面
- [x] 终端 CLI
- [x] 测试套件（Agent + 安全检测 + RAG）
- [x] 多轮对话摘要（session_summary 跨轮传递）
- [x] Eval 评测框架（~27 题，四类别，LLM-as-Judge）

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
