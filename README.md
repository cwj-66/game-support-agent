# Game Support Agent

基于 LangGraph 的游戏客服 Agent，实现 LLM 自主处理 + RAG 知识库 + 人工接待的完整闭环；含 27 条评测用例、LLM-as-Judge 评估框架。

## 项目架构

```
game-support-agent/
├── agent/                          # LangGraph 核心编排
│   ├── graph.py                    # 主图：4 个节点 + 1 条条件边（ReAct 循环）
│   ├── state.py                    # AgentState 定义（TypedDict）
│   ├── checkpointer.py             # AsyncRedisSaver 状态持久化
│   ├── nodes/
│   │   ├── reasoning.py            # LLM 推理节点（bind_tools 自主决策）
│   │   ├── tool_exec.py            # 通用工具分发器
│   │   ├── generate.py             # 客服回复润色生成
│   │   └── finish.py               # 结束节点
│   ├── tools/
│   │   ├── __init__.py             # get_all_tools()：MCP 工具 + 本地提议工具
│   │   ├── mcp_client.py           # MCP Client（连接 mcp_server.py）
│   │   ├── rag_client.py           # RAG HTTP 客户端
│   │   ├── propose_ticket.py       # 提议创建工单（前端确认后落库）
│   │   └── propose_human_escalation.py  # 提议转人工（前端确认后进入接待）
│   └── prompts/
│       └── system.py               # 系统提示词
├── app/                            # FastAPI 服务层
│   ├── main.py                     # 入口（CORS、路由、生命周期、MCP/Redis/MySQL 初始化）
│   ├── api/
│   │   ├── deps.py                 # JWT 鉴权、会话归属校验
│   │   └── v1/
│   │       ├── chat.py             # 对话 / 流式 / 工单&人工确认
│   │       ├── human.py            # 人工接待接口
│   │       └── ticket.py           # 工单 CRUD
│   ├── core/
│   │   ├── config.py               # pydantic-settings 配置
│   │   ├── llm.py                  # LLM 工厂（DashScope 优先，OpenAI 兜底）
│   │   ├── mysql_db.py             # MySQL 连接池
│   │   ├── checkpoint_helper.py    # checkpoint 读写辅助
│   │   └── exceptions.py           # 业务异常 + 全局处理器
│   ├── repositories/
│   │   └── database.py             # MySQL 工单/账号 CRUD
│   ├── services/
│   │   ├── ticket_service.py       # 工单业务逻辑（MCP 与 API 共用）
│   │   ├── account_service.py      # 账号查询业务逻辑
│   │   ├── pending_store.py        # 待接待队列（Redis，降级内存）
│   │   ├── human_chat.py           # 人工接待消息写入 checkpoint
│   │   ├── session_store.py        # 会话 TTL 管理
│   │   ├── session_summary.py      # 多轮对话摘要
│   │   └── long_term_memory.py     # 长期记忆
│   └── models/
│       ├── chat.py
│       ├── human_session.py
│       └── ticket.py
├── eval/                           # 评测框架（27 题，四类别）
├── player-chat/                    # 玩家端（React + Vite + Ant Design）
├── admin-ui/                       # 客服端（React + Vite + Ant Design）
├── client/                         # 终端 CLI（rich）
│   ├── cli.py
│   ├── web_ui.py                   # 旧版 Streamlit（可选）
│   └── user_ui.py
├── scripts/
│   ├── generate_game_token.py      # 本地测试 JWT 生成
│   ├── view_mysql_data.py          # 查看 MySQL 数据
│   └── mysql/init.sql              # Docker MySQL 初始化脚本
├── tests/
├── data/                           # 运行时数据目录
├── mcp_server.py                   # MCP Server（3 个工具：query_knowledge / lookup_account / check_ticket）
├── .env.example
├── requirements.txt
└── docker-compose.yml              # mysql + redis + rag + agent-api + web-ui
```

### LangGraph 流程（简图）

```
START → reasoning ─┬─ 有 tool_calls → tool_exec → reasoning（ReAct 循环）
                   └─ 无 tool_calls  → generate → finish → END
```

- **工单创建**：Agent 调用 `propose_ticket` → 前端弹窗确认 → `POST /chat/ticket-confirm` 落库
- **转人工**：Agent 调用 `propose_human_escalation` → 前端确认 → `POST /chat/human-confirm` → 客服在 admin-ui 接待

## 快速开始

### 1. 环境配置

```bash
python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

`.env` 至少配置：

- `DASHSCOPE_API_KEY`（或 `OPENAI_API_KEY` 兜底）
- `REASONING_MODEL_NAME` / `GENERATE_MODEL_NAME`
- `GAME_JWT_SECRET`（本地可用 `python scripts/generate_game_token.py --user-id 10001` 测 JWT）

### 2. 启动基础依赖

```bash
# MySQL（工单/账号）+ Redis（Agent 状态 + 待接待队列）
docker compose up -d mysql redis
```

### 3. 启动后端

```bash
# 终端 1：MCP Server（必须，主服务启动时会连接）
python mcp_server.py

# 终端 2：FastAPI 后端
python -m app.main
```

默认 `http://127.0.0.1:8002`，API 文档 `http://127.0.0.1:8002/docs`

### 4. 启动前端

```bash
# 玩家端
cd player-chat && npm install && npm run dev   # http://localhost:5173

# 客服端
cd admin-ui && npm install && npm run dev      # http://localhost:5174
```

两个前端通过 Vite proxy 转发到 `http://localhost:8002`。

### 5. 运行评测 / 测试

```bash
python eval/evaluate.py
python eval/evaluate.py --category tool
python eval/evaluate.py --skip-llm

pytest
pytest tests/test_safety.py -v
```

## 启动流程速查

| 组件 | 命令 | 端口 |
|------|------|------|
| MySQL | `docker compose up -d mysql` | 3307（映射） |
| Redis | `docker compose up -d redis` | 6379 |
| RAG 服务（可选） | `docker compose up -d rag-service` | 8000 |
| MCP Server | `python mcp_server.py` | 8001 |
| FastAPI 后端 | `python -m app.main` | 8002 |
| 玩家端 | `cd player-chat && npm run dev` | 5173 |
| 客服端 | `cd admin-ui && npm run dev` | 5174 |
| 终端 CLI | `python client/cli.py --session test_001 "问题"` | — |

## API 接口

### 对话（玩家 JWT：`Authorization: Bearer <token>`）

```http
POST /api/v1/chat/send              # 发送消息
POST /api/v1/chat/stream            # SSE 流式回复
GET  /api/v1/chat/history/{session_id}
GET  /api/v1/chat/reply/{session_id}   # 轮询 Agent 回复
POST /api/v1/chat/ticket-confirm    # 确认创建工单
POST /api/v1/chat/human-confirm     # 确认转人工
```

### 工单

```http
POST   /api/v1/ticket/create
POST   /api/v1/ticket/submit        # 提交工单并触发 Agent
GET    /api/v1/ticket/list
GET    /api/v1/ticket/{ticket_id}
PATCH  /api/v1/ticket/{ticket_id}
GET    /api/v1/ticket/stats
```

### 人工接待（客服 Token：`X-Reviewer-Token`）

```http
GET   /api/v1/human/pending
POST  /api/v1/human/join/{session_id}
POST  /api/v1/human/review/{session_id}   # reply + action: continue|close
GET   /api/v1/human/status/{session_id}
GET   /api/v1/human/history/{session_id}
```

客服通过 `continue` 多轮对话，`close` 结束接待。消息直接写入 LangGraph checkpoint。

## Eval Framework

### 评测类别

| 类别 | 题数 | 说明 |
|------|------|------|
| RAG 检索 | 7 | 知识库查询准确性、置信度阈值、降级行为 |
| 工具调用 | 8 | 账号查询、工单创建/查询、工具选择合规性 |
| 人工接待 | 7 | 转人工触发、禁止操作拦截 |
| 多轮上下文 | 5 | 跨轮对话摘要、上下文连贯性 |
| **合计** | **27** | |

### 三段式评分

1. **硬评分**：`tool_score` / `escalation_score` / `forbidden_score`
2. **内容 LLM-as-Judge**：`qwen-max` 评估信息点覆盖（无 LLM 时降级关键词匹配）
3. **综合评分**：正常场景 工具30% + 升等15% + 禁止25% + 内容30%；升等场景 工具45% + 升等35% + 禁止20%

报告输出 CSV + Markdown，含逐题明细和低分分析。

## Docker 一键部署

```bash
# 需先在 .env 配置 DASHSCOPE_API_KEY 等
docker compose up -d
```

服务：mysql、redis、rag-service、agent-api（8002）、web-ui（8501，旧版 Streamlit）。

## 技术栈

| 层面 | 选型 |
|------|------|
| AI 编排 | LangGraph / langchain-core / langchain-openai |
| LLM | DashScope（qwen3.5-plus 推理 + qwen-turbo 润色），OpenAI 兜底 |
| 评测 | LLM-as-Judge via qwen-max |
| API 服务 | FastAPI + Pydantic |
| 客户端 | React + Vite + Ant Design + rich CLI |
| 持久化 | Redis（Agent 状态 + 待接待队列）+ MySQL（工单/账号） |
| 外部集成 | MCP Server（streamable_http）+ RAG HTTP |
| 鉴权 | 游戏 JWT（玩家）+ Reviewer Token（客服） |
| 测试 | pytest |
