# Game Support Agent

基于 LangGraph 的游戏客服 Agent，实现 LLM 自主处理 + RAG 知识库 + Human-in-loop 审核的完整闭环；含 ~25 条评测用例、LLM-as-Judge 评估框架，streaming 响应延迟 ~3.9s。

## 项目架构

```
game-support-agent/
├── agent/                          # LangGraph 核心编排
│   ├── graph.py                    # 主图：7 个节点 + 2 条条件边
│   ├── state.py                    # AgentState 定义（TypedDict）
│   ├── checkpointer.py             # AsyncSqliteSaver 状态持久化
│   ├── nodes/
│   │   ├── reasoning.py            # LLM 推理节点（bind_tools 自主决策）
│   │   ├── tool_exec.py            # 通用工具分发器
│   │   ├── generate.py             # 客服回复润色生成
│   │   ├── detector.py             # 安全兜底检测（静默拦截）
│   │   ├── human_node.py           # 人工审核节点（interrupt 挂起）
│   │   ├── human_handoff.py        # 转人工 Handoff（整理上下文）
│   │   └── finish.py               # 结束节点
│   ├── tools/
│   │   ├── __init__.py             # get_all_tools()：MCP 优先，本地兜底
│   │   ├── query_knowledge.py      # KnowledgeTool（HTTP 调用 RAG 知识库）
│   │   ├── rag_client.py           # RAG HTTP 客户端
│   │   ├── account.py              # lookup_account（本地 LangChain 包装）
│   │   ├── ticket.py               # create_ticket（本地 LangChain 包装）
│   │   ├── ticket_status.py        # check_ticket（本地 LangChain 包装）
│   │   ├── human_escalation.py     # request_human_escalation（必须留在图内）
│   │   └── mcp_client.py           # MCP Client（连接 mcp_server.py）
│   └── prompts/
│       └── system.py               # 系统提示词（决策 + 客服润色模板）
├── app/                            # FastAPI 服务层
│   ├── main.py                     # 入口（CORS、路由、生命周期、MCP Client 初始化）
│   ├── api/v1/
│   │   ├── chat.py                 # POST /chat/send、GET /chat/history、POST /chat/stream
│   │   ├── human.py                # 审核接口（pending、review、status）
│   │   └── ticket.py               # 工单 CRUD 接口
│   ├── core/
│   │   ├── config.py               # pydantic-settings 配置管理
│   │   ├── llm.py                  # LLM 工厂（DashScope 优先，OpenAI 兜底）
│   │   ├── database.py             # SQLite 工单 CRUD（底层）
│   │   ├── ticket_service.py       # 工单业务逻辑（create/check，供 MCP 与本地工具共用）
│   │   ├── account_service.py      # 账号查询业务逻辑（供 MCP 与本地工具共用）
│   │   ├── pending_store.py        # 待审核队列（内存）
│   │   └── exceptions.py           # 5 种业务异常 + 全局处理器
│   └── models/
│       ├── chat.py                 # 对话请求/响应模型
│       ├── review.py               # 审核请求/响应模型
│       └── ticket.py               # 工单数据模型
├── safety/                          # 安全检测模块
│   ├── detector.py                 # 敏感词正则匹配 + 工具失败检测
│   ├── schema.py                   # InterruptDecision 数据结构
│   └── __init__.py
├── eval/                           # 评测框架
│   ├── evaluate.py                 # 三段式评测引擎
│   ├── rag_01~07.json              # RAG 检索类别（7 题）
│   ├── tool_01~08.json             # 工具调用类别（8 题）
│   ├── hil_01~07.json              # Human-in-loop 类别（7 题）
│   ├── mc_01~05.json               # 多轮上下文类别（5 题）
│   └── report_*.{csv,md}           # 评估报告
├── client/                         # 客户端
│   ├── cli.py                      # 终端 CLI（rich 库）
│   ├── web_ui.py                   # 客服审核界面（Streamlit）
│   └── user_ui.py                  # 用户聊天界面（Streamlit）
├── tests/
│   ├── test_agent.py
│   ├── test_safety.py
│   └── test_rag_client.py
├── data/
│   ├── accounts.json               # 账号 mock 数据（账号查询工具使用）
│   ├── game_support.db             # LangGraph 状态持久化
│   └── tickets.db                  # 工单 SQLite
├── mcp_server.py                   # MCP Server（独立进程，暴露 4 个客服工具）
├── .env.example
├── requirements.txt
└── docker-compose.yml              # rag / agent-api / web-ui
```

## 架构设计决策

### 为什么用确定性条件边控制 human escalation（而非 LLM 自主判断）

典型的 Agent 框架让 LLM 自行决定"是否需要转人工"，但游戏客服场景中 LLM 的判断不可靠——它可能在敏感话题上过度自信直接回复，也可能对常规问题误判为高风险。因此本项目采用**双层兜底**：

1. **业务升等（LLM 触发）**：LLM 可调用 `request_human_escalation` 工具主动请求转人工，适用于 LLM 明确知道"这事我处理不了"的场景（如投诉、账号封禁申诉）。
2. **安全兜底（图结构强制）**：无论 LLM 如何回复，`detector` 节点在 `generate` 之后强制执行敏感词检测和工具失败检查。命中规则时不触发 interrupt，而是**静默替换**回复内容为预设文案。这个节点是 Graph 的固定边，不由 LLM 控制，不可跳过。

### detector 节点的静默拦截设计

`detector` 节点不调用 `interrupt()`，而是直接修改 `state.final_response` 并记录拦截日志到 `state.metadata`。这样设计的原因是：
- 敏感词命中或工具失败通常不需要人工介入（只是需要换一种说法回复用户）
- 避免不必要的审核开销，只有 LLM 主动要求转人工时才走完整 HIL 路径
- 拦截记录写入 metadata，可在后续审计中追溯

### Human-in-loop 机制

- **中断触发路径**：LLM 调用 `request_human_escalation` → `tool_exec` 设 `interrupt_info` → `human_handoff` 整理上下文 → `human` 节点 `interrupt()` 挂起
- **审核操作**：审核员通过 API 提交回复字符串，`Command(resume=reply)` 恢复图执行，`human_reply` 作为最终回复（标记 `human_source=True`）

### MCP 集成

工具层采用 **MCP Server + MCP Client** 架构，业务逻辑与暴露层分离：

```
app/core/ticket_service.py   ─┐
app/core/account_service.py  ─┤  业务逻辑（只写一次）
app/core/database.py         ─┘
         ↑              ↑
mcp_server.py      agent/tools/*.py
（@mcp.tool 注册）  （@tool 本地兜底）
         ↑
agent/tools/mcp_client.py → LangGraph reasoning / tool_exec
```

**MCP Server**（`mcp_server.py`，独立进程，端口 8001）暴露 4 个工具：
- `create_ticket` / `check_ticket` / `lookup_account` / `query_knowledge`

**MCP Client**（`agent/tools/mcp_client.py`）在 FastAPI 启动时连接 `http://localhost:8001/mcp`（streamable_http），发现并缓存工具。

**工具选用策略**（`get_all_tools()`）：
- MCP Server 已连接 → 使用 MCP 工具 + 本地 `request_human_escalation`（触发 interrupt，不能外置）
- MCP Server 未连接 → 全部使用本地 LangChain 工具兜底

**Graph 不感知 MCP**：`reasoning` 节点 `bind_tools()`，`tool_exec` 节点统一 `tool.ainvoke()`；MCP 工具由 `langchain-mcp-adapters` 转成 LangChain BaseTool，与本地工具调用方式相同。

**启动 MCP（可选但推荐）**：

```bash
# 终端 1：MCP Server
python mcp_server.py

# 终端 2：FastAPI 主服务（启动时会自动连接 MCP）
python -m app.main
```

连接成功时日志示例：`[MCP] MCP Server connected, discovered 4 tool(s)`

### 工具层分层说明

| 层级 | 文件 | 职责 |
|------|------|------|
| 核心逻辑 | `app/core/ticket_service.py`、`account_service.py` | 映射规则、读库写库、返回 dict |
| MCP 暴露 | `mcp_server.py` | `@mcp.tool()` + Docstring（给 LLM 看）+ 调 service |
| 本地兜底 | `agent/tools/ticket.py` 等 | `@tool` + Docstring + 调 service |
| 图内专用 | `agent/tools/human_escalation.py` | 触发 LangGraph interrupt，不放入 MCP |

Docstring 在 MCP 与本地各维护一份（参数签名可能不同，如 MCP 版 `check_ticket` 需显式传 `user_id`）；业务逻辑修改只需改 service 层。

### 工单生命周期

```
玩家提交 / Agent 创建 → pending
    ↓ 客服开始处理
processing
    ↓ 客服填写处理结果
resolved
    ↓ 玩家查询
Agent 读取 agent_reply 返回给玩家
```

## 性能

| 模式 | 响应时间 | 说明 |
|------|----------|------|
| Thinking mode（关闭前） | ~70s | LLM 思考过程占用大量时间 |
| Streaming 模式 | ~3.9s | 关闭 thinking mode 后流式输出逐节点推送 |

## 快速开始

### 1. 环境配置

```bash
python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
# 配置 LLM Key（DASHSCOPE_API_KEY 或 OPENAI_API_KEY）
```

### 2. 启动服务

**推荐：先启动 MCP Server，再启动主服务**

```bash
# 终端 1：MCP Server（工具服务）
python mcp_server.py

# 终端 2：FastAPI 后端
python -m app.main
```

仅启动主服务也可运行（自动降级为本地工具，不影响核心功能）。

默认监听 `http://127.0.0.1:8002`，API 文档见 `http://127.0.0.1:8002/docs`

### 3. 启动前端界面

**用户界面**（玩家端 — 对话、提工单、查进度）：

```bash
streamlit run client/user_ui.py
```

**客服界面**（客服端 — HIL 审核、工单处理）：

```bash
streamlit run client/web_ui.py
```

两个界面可同时运行，共用同一个后端。

### 4. 运行评测

```bash
# 跑全部用例
python eval/evaluate.py

# 只跑特定类别
python eval/evaluate.py --category tool
python eval/evaluate.py --category rag
python eval/evaluate.py --category hil
python eval/evaluate.py --category mc

# 跳过 LLM Judge（只做硬评分）
python eval/evaluate.py --skip-llm

# 调试：只跑前 3 题
python eval/evaluate.py --max-cases 3
```

### 5. 测试

```bash
pytest
pytest tests/test_safety.py -v
pytest --cov=agent --cov=safety --cov-report=html
```

## 启动流程速查

| 组件 | 命令 | 端口 |
|------|------|------|
| MCP Server（工具服务） | `python mcp_server.py` | 8001 |
| FastAPI 后端 | `python -m app.main` | 8002 |
| 用户界面 | `streamlit run client/user_ui.py` | 8501 |
| 客服界面 | `streamlit run client/web_ui.py` | 8502 |
| 终端 CLI | `python client/cli.py --session test_001 "问题"` | — |

## API 接口

### 对话

```http
POST /api/v1/chat/send
Content-Type: application/json

{
  "session_id": "sess_123",
  "user_id": "UID001",
  "message": "如何获得原石？"
}
```

### 工单

```http
POST   /api/v1/ticket/create          # 创建工单
GET    /api/v1/ticket/{ticket_id}     # 查询工单
GET    /api/v1/ticket/list            # 工单列表（支持 status/player_uid 筛选）
PATCH  /api/v1/ticket/{ticket_id}     # 更新工单（客服处理）
GET    /api/v1/ticket/stats           # 工单统计
```

### 人工审核

```http
GET   /api/v1/human/pending               # 待审核列表
POST  /api/v1/human/review/{session_id}   # 提交审核结果（reply + reviewer_id）
GET   /api/v1/human/status/{session_id}   # 查询审核状态
```

## Eval Framework

### 评测类别

| 类别 | 题数 | 说明 |
|------|------|------|
| RAG 检索 | 7 | 知识库查询准确性、置信度阈值、降级行为 |
| 工具调用 | 8 | 账号查询、工单创建/查询、工具选择合规性 |
| 审核 | 7 | 转人工触发、禁止操作拦截、安全兜底 |
| 多轮上下文 | 5 | 跨轮对话摘要、上下文连贯性 |
| **合计** | **27** | |

### 三段式评分

1. **硬评分（程序逻辑）**：
   - `tool_score`：预期工具调用召回率
   - `escalation_score`：`must_escalate` 标记的 case 是否正确触发转人工
   - `forbidden_score`：`forbidden_actions` 是否被触发（触发则整题 0 分）

2. **内容 LLM-as-Judge**：
   - 调用 `qwen-max`（DashScope 优先）评估回复对标准答案信息点的覆盖程度
   - 关键数值（如次数、金额、UID）必须精确匹配
   - 无 LLM 可用时降级为关键词匹配

3. **综合评分**：
   - 正常场景：工具 30% + 升等 15% + 禁止 25% + 内容 30%
   - 升等中断场景（内容评分无区分度）：工具 45% + 升等 35% + 禁止 20%

### 报告输出

- CSV（utf-8-sig，Excel 可直接打开）
- Markdown（含逐题明细、汇总统计、低分题分析）
- 单题详情：执行路径、信息点覆盖/遗漏、失分原因

## 技术栈

| 层面 | 选型 |
|------|------|
| AI 编排 | LangGraph / langchain-core / langchain-openai |
| LLM | 阿里云 DashScope (qwen-turbo) 优先，OpenAI 兜底 |
| 评测 | LLM-as-Judge via qwen-max |
| API 服务 | FastAPI + Pydantic |
| 客户端 | Streamlit + rich CLI |
| 持久化 | SQLite（LangGraph 状态 + 工单双库） |
| 外部集成 | MCP Server（streamable_http）+ RAG HTTP |
| 测试 | pytest |

## 已知限制与设计取舍

1. **pending_store 为内存实现**：待审核任务存储在进程内 dict 中，服务重启后丢失。这是当前简化实现的主动取舍——避免引入 Redis 增加部署复杂度。生产环境建议替换为 Redis/数据库持久化。

2. **双 SQLite 数据库无跨库事务**：LangGraph checkpointer（`game_support.db`）和工单 CRUD（`tickets.db`）是独立的两个 SQLite 文件，没有跨库一致性保证。在生产规模下，checkpointer 建议替换为 RedisSaver/PostgresSaver。

3. **工具层通过 service 层访问数据**：`ticket_service.py` / `account_service.py` 封装业务逻辑，MCP Server 与本地 LangChain 工具共用；底层仍依赖 `app.core.database`。`request_human_escalation` 因需触发 LangGraph interrupt，仅保留在 agent 进程内。
