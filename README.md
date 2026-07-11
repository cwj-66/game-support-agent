# Game Support Agent

基于 LangGraph 的游戏客服 Agent，实现 LLM 自主处理 + RAG 知识库 + 人工接待的完整闭环；含 ~25 条评测用例、LLM-as-Judge 评估框架，streaming 响应延迟 ~3.9s。

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
│   │   ├── human.py                # 人工接待接口（pending、reply、status）
│   │   └── ticket.py               # 工单 CRUD 接口
│   ├── core/
│   │   ├── config.py               # pydantic-settings 配置管理
│   │   ├── llm.py                  # LLM 工厂（DashScope 优先，OpenAI 兜底）
│   │   ├── database.py             # SQLite 工单 CRUD（底层）
│   │   ├── ticket_service.py       # 工单业务逻辑（create/check，供 MCP 与本地工具共用）
│   │   ├── account_service.py      # 账号查询业务逻辑（供 MCP 与本地工具共用）
│   │   ├── pending_store.py        # 待接待队列（Redis）
│   │   └── exceptions.py           # 5 种业务异常 + 全局处理器
│   └── models/
│       ├── chat.py                 # 对话请求/响应模型
│       ├── human_session.py        # 人工接待请求/响应模型
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
├── player-chat/                    # 玩家端（React + Vite + Ant Design）
├── admin-ui/                       # 客服端（React + Vite + Ant Design）
├── client/                         # 终端 CLI
│   ├── cli.py                      # 终端 CLI（rich 库）
│   ├── web_ui.py                   # 旧版 Streamlit 客服界面（可选）
│   └── user_ui.py                  # 旧版 Streamlit 玩家界面（可选）
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

前端为 **React + Vite + Ant Design**

**玩家端**

```bash
cd player-chat
npm run dev
```
默认访问 `http://localhost:5173`

**客服端**：

```bash
cd admin-ui
npm run dev
```
默认访问 `http://localhost:5174`


两个界面可同时运行，共用 FastAPI 后端（`http://localhost:8002`）。

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
| 玩家端（React） | `cd player-chat && npm run dev` | 5173 |
| 客服端（React） | `cd admin-ui && npm run dev` | 5174 |
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

### 人工接待

```http
GET   /api/v1/human/pending               # 待接待会话列表
POST  /api/v1/human/review/{session_id}   # 客服发消息（reply + action: continue|close）
POST  /api/v1/human/join/{session_id}     # 客服接入会话
GET   /api/v1/human/status/{session_id}   # 查询是否在人工接待中
GET   /api/v1/human/history/{session_id}  # 客服查看对话历史
```

客服通过 `continue` 继续多轮对话，通过 `close` 结束接待。消息写入 LangGraph checkpoint，不经过 interrupt 挂起。

## Eval Framework

### 评测类别

| 类别 | 题数 | 说明 |
|------|------|------|
| RAG 检索 | 7 | 知识库查询准确性、置信度阈值、降级行为 |
| 工具调用 | 8 | 账号查询、工单创建/查询、工具选择合规性 |
| 人工接待 | 7 | 转人工触发、禁止操作拦截、安全兜底 |
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
| 客户端 | React + Vite + Ant Design（player-chat / admin-ui）+ rich CLI |
| 持久化 | SQLite（LangGraph 状态 + 工单双库） |
| 外部集成 | MCP Server（streamable_http）+ RAG HTTP |
| 测试 | pytest |

## 已知限制与设计取舍

1. **pending_store 为内存实现**：待审核任务存储在进程内 dict 中，服务重启后丢失。这是当前简化实现的主动取舍——避免引入 Redis 增加部署复杂度。生产环境建议替换为 Redis/数据库持久化。

2. **双 SQLite 数据库无跨库事务**：LangGraph checkpointer（`game_support.db`）和工单 CRUD（`tickets.db`）是独立的两个 SQLite 文件，没有跨库一致性保证。在生产规模下，checkpointer 建议替换为 RedisSaver/PostgresSaver。

3. **工具层通过 service 层访问数据**：`ticket_service.py` / `account_service.py` 封装业务逻辑，MCP Server 与本地 LangChain 工具共用；底层仍依赖 `app.core.database`。`request_human_escalation` 因需触发 LangGraph interrupt，仅保留在 agent 进程内。
