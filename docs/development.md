# 开发与部署指南

[返回项目首页](../README.md)。本文保留目录结构、API、RAG 契约及完整部署参考。除特别注明外，命令均在仓库根目录执行。首次克隆和最短演示步骤见首页“快速开始”。

## 项目架构

```
game-support-agent/
├── agent/                          # LangGraph 核心编排
│   ├── graph.py                    # 主图：4 个节点 + 1 条条件边（ReAct 循环）
│   ├── state.py                    # AgentState 定义（TypedDict）
│   ├── checkpointer.py             # AsyncSqliteSaver 状态持久化
│   ├── nodes/
│   │   ├── reasoning.py            # LLM 推理节点（bind_tools 自主决策）
│   │   ├── tool_exec.py            # 通用工具分发器
│   │   ├── generate.py             # 客服回复润色生成
│   │   └── finish.py               # 结束节点
│   ├── tools/
│   │   ├── __init__.py             # get_all_tools()：MCP 工具 + 本地提议工具
│   │   ├── mcp_client.py           # MCP Client（连接 mcp_server.py）
│   │   ├── rag_client.py           # RAG HTTP 客户端（仅检索）
│   │   ├── knowledge_answer.py     # 基于检索片段生成本侧答案
│   │   ├── propose_ticket.py       # 提议创建工单（前端确认后落库）
│   │   └── propose_human_escalation.py  # 提议转人工（前端确认后进入接待）
│   └── prompts/
│       └── system.py               # 系统提示词
├── app/                            # FastAPI 服务层
│   ├── main.py                     # 入口（CORS、路由、生命周期）
│   ├── api/
│   │   ├── deps.py                 # JWT / Reviewer Token 鉴权
│   │   └── v1/
│   │       ├── chat.py             # 对话 / 流式 / 工单&人工确认
│   │       ├── human.py            # 人工接待接口
│   │       └── ticket.py           # 工单 CRUD
│   ├── core/                       # 配置、LLM、MySQL、异常
│   ├── repositories/               # MySQL CRUD
│   ├── services/                   # 工单、账号、接待队列、会话摘要等
│   └── models/
├── eval/                           # 评测框架（27 题，四类别）
├── player-chat/                    # 统一前端：玩家端 + 客服工作台 /admin
├── admin-ui/                       # 已并入 player-chat，勿单独启动
├── client/
│   └── cli.py                      # 终端 CLI（rich）
├── mock_rag/                       # 本地演示用 RAG 桩服务（可选）
├── scripts/
│   ├── generate_game_token.py      # 本地测试 JWT 生成
│   └── mysql/                      # Docker MySQL：客服库 + 共享的 rag_database
├── tests/
├── data/                           # 运行时数据目录（*.db 不入库）
├── mcp_server.py                   # MCP Server（query_knowledge / lookup_account / check_ticket）
├── .env.example
├── requirements.txt
└── docker-compose.yml              # mysql + redis + qdrant + rag-api + mcp + agent-api + player-chat
```

### LangGraph 流程（简图）

```
START → reasoning ─┬─ 有 tool_calls → tool_exec → reasoning（ReAct 循环）
                   └─ 无 tool_calls  → generate → finish → END
```

- **工单创建**：Agent 调用 `propose_ticket` → 前端弹窗确认 → `POST /chat/ticket-confirm` 落库
- **转人工**：Agent 调用 `propose_human_escalation` → 前端确认 → `POST /chat/human-confirm` → 客服在 `/admin` 接待

## 快速开始

前置环境：Python 3.11、Node.js 22.12+（22.x）及 Docker Compose。以下步骤采用本机 Python 服务与前端，Docker 仅提供基础依赖。

### 1. 环境配置

```bash
python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

`.env` 至少配置：

- `DASHSCOPE_API_KEY`（Agent 模型调用使用）
- `REASONING_MODEL_NAME` / `GENERATE_MODEL_NAME`
- `GAME_JWT_SECRET`（本地可用 `python scripts/generate_game_token.py --user-id 10001` 测 JWT）

`.env.example` 默认使用 `qwen3.8-max-0902`（推理）、`qwen3.8-flash`（润色）和 `deepseek-v4.1-flash`（评测裁判）；实际运行以本机 `.env` 或容器环境变量为准。当前 `get_chat_model()` 使用 DashScope 兼容接口及 `DASHSCOPE_API_KEY`，只填写 `OPENAI_API_KEY` 并不会自动切换模型提供方。

### 2. 启动基础依赖

```bash
# MySQL（工单/账号）+ Redis（待接待队列）
docker compose up -d mysql redis
```

本地联调知识查询时，还需启动 RAG 服务：可在另一终端运行 `python -m uvicorn mock_rag.main:app --port 8000` 使用桩数据。真实检索使用同级目录的 `enterprise-rag`，并启动 Qdrant；不能把桩数据测评分数算作真实知识库成绩。

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
cd player-chat
npm ci
npm run dev   # http://localhost:5173
```

| 路径 | 说明 |
|------|------|
| http://localhost:5173 | 玩家端 |
| http://localhost:5173/admin | 客服工作台 |

前端通过 Vite proxy 转发到 `http://localhost:8002`。在 `/accounts` 选择测试账号后，页面自动获取玩家 JWT。客服端默认使用 Token `dev`；更改后端 `REVIEWER_API_KEY` 时，需同步设置前端 `VITE_REVIEWER_TOKEN` 并重启 Vite。

### 5. 运行评测 / 测试

```bash
python eval/evaluate.py
python eval/evaluate.py --category tool
python eval/evaluate.py --skip-llm

pytest
pytest tests/test_rag_client.py -v
```

`pytest` 是离线单元测试，无需启动服务或消耗模型额度。27 道 Agent 评测题在 `eval/tool_*.json`、`rag_*.json`、`hil_*.json` 和 `mc_*.json` 中；多轮题按同一会话逐轮执行。账号/工单题依据 `scripts/mysql/init.sql`，知识题依据已入库的 `enterprise-rag` 文档，因此正式运行前需启动 MySQL、真实 RAG 和 MCP Server。`eval/evaluate.py` 会调用真实 Agent 和模型；`--skip-llm` 只跳过裁判模型，不跳过被测 Agent 的模型调用。评测报告写入指定路径的 `.csv`、`.md` 和 `.json`（含逐轮详情）。

## 启动流程速查（本地开发）

| 组件 | 命令 | 端口 |
|------|------|------|
| 全栈（含真实 RAG） | 两仓库同级，按下方“Docker 联合部署”准备后执行 `docker compose up -d --build` | 5175 / 8000 / 8002 |
| MySQL / Redis / Qdrant | 已包含在全栈中；也可 `up -d mysql redis qdrant` | 3307 / 6380 / 6333（仅 127.0.0.1） |
| RAG 桩（不跑 Docker RAG） | `python -m uvicorn mock_rag.main:app --port 8000` | 8000 |
| MCP Server | `python mcp_server.py` | 8001 |
| FastAPI 后端 | `python -m app.main` | 8002 |
| 前端 | `cd player-chat && npm run dev` | 5173（`/admin` 为客服工作台） |
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

### 并发与幂等约定

- 修改会话状态的入口（`send`、`stream`、`ticket-confirm`、`human-confirm`、`end`、客服 `review`/`join`、空闲自动关闭）都先取 Redis 会话锁 `gsa:session-lock:{session_id}`。锁按会话号加，不按 UID；前端会话号为 `{uid}_{uuid}`。
- 同一会话已有问答在执行时，新提交返回 409 `session_busy`；`end` 会发出取消标记，等待最多 8 秒让进行中的问答退出后再关闭。
- 聊天与确认请求可带 `client_request_id`（8–64 位字母数字、`-`、`_`），`/ticket/create`、`/ticket/submit` 使用 `Idempotency-Key` 头；相同 ID 在 10 分钟内重试会直接返回首次结果。
- 只有调用模型的路径（`send`/`stream` 正常模式、`/ticket/submit`）占全站名额；SSE 事件新增 `queue`（`queued` 带真实排队位置 / `admitted`）、心跳注释 `: ping` 和带 `code` 的 `error`。
- 错误码：429 `rate_limited`、409 `session_busy` / `turn_cancelled`、503 `server_busy` / `queue_timeout` / `capacity_unavailable` / `upstream_unavailable`、504 `agent_timeout`，均带 `Retry-After`（`turn_cancelled` 除外）。
- 本机没有 Redis 时可在 `.env` 设 `COORDINATION_BACKEND=memory`（仅单进程）。测试默认使用 memory，并通过 `fakeredis[lua]` 执行真实 Lua 脚本（`pip install -r requirements-dev.txt`）。
- 模拟云端压测：`python scripts/load_test_mock.py`（不消耗真实 token，结果写入 `deploy/vultr/concurrency-results.json`）。

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
2. **内容 LLM-as-Judge**：默认 `deepseek-v4.1-flash`（可用 `JUDGE_FALLBACK_MODEL` 覆盖）评估信息点覆盖；调用失败时降级关键词匹配
3. **综合评分**：正常场景 工具30% + 升等15% + 禁止25% + 内容30%；升等场景 工具45% + 升等35% + 禁止20%

报告输出 CSV + Markdown + JSON，含逐题明细和低分分析；生成报告保留在本机，默认不提交到仓库。评分基于测试账号的数据库记录和已入库的内部知识文档，不使用网上答案补齐参考答案。分数仅代表这 27 道题及当次服务、模型和知识库状态，不等于生产环境准确率。最近一次实测摘要见 [评测记录](evaluation.md)。

## Docker 联合部署（本地开发）

一条 compose 拉起客服 + 知识库：**一份 MySQL（两个库）+ Redis + Qdrant**。
两个 Git 仓库需同级目录；配套仓库：[enterprise-rag](https://github.com/cwj-66/enterprise-rag)。

```
PythonProject/game-support-agent   ← 在此执行 compose
PythonProject/enterprise-rag
```

需要 Docker Engine、同级的 `enterprise-rag` 仓库及足够的模型运行内存。首次构建会下载镜像与 Python 依赖，可能耗时较长；本机曾因依赖下载与内存限制未能验证完整的一键构建，因此建议先确认基础组件与 RAG 健康检查。不要同时 `up` `enterprise-rag/docker-compose.yml`。

### 1. 准备环境变量

```bash
cp .env.example .env
# 至少填写：DASHSCOPE_API_KEY、GAME_JWT_SECRET、REVIEWER_API_KEY
# RAG_API_KEY 与知识库 API_KEY 一致；示例密钥只用于本地开发
```

RAG 不在 `../enterprise-rag` 时，在 `.env` 设置 `ENTERPRISE_RAG_DIR`（正斜杠路径）。

### 2. 启动全部服务

```bash
docker compose up -d --build
```

修改 `.env` 中的模型名后，需重新创建 `agent-api` 和 `mcp-server` 容器；仅修改文件不会更新正在运行的容器。Docker API 使用独立的 `data/game_support_docker.db` 保存会话，避免与本机评测进程共用 SQLite 文件。

查看状态：

```bash
docker compose ps
```

停止：

```bash
docker compose down
```

### 3. 访问地址

| 入口 | 地址 | 说明 |
|------|------|------|
| 前端 | http://localhost:5175 | 玩家聊天；`/admin` 为客服工作台 |
| Agent API | http://localhost:8002/docs | FastAPI Swagger |
| RAG UI | http://localhost:8000/ui | 上传/检索知识库（`X-API-Key` = `RAG_API_KEY`） |
| MySQL | `127.0.0.1:3307` | 仅本机；库 `game_support` + `rag_database` |
| Redis | `127.0.0.1:6380` | 仅本机；待接待队列 |
| Qdrant | `127.0.0.1:6333` | 仅本机；向量 |

Compose 默认将前端及两个 API 绑定在 `127.0.0.1`，使用示例数据库密码与开发密钥，只适合本地开发。真实对外部署须先更换 MySQL、JWT、RAG 与客服密钥，并通过受控反向代理提供访问；需要监听外部网卡时再显式设置 `BIND_HOST`。

本地生成玩家 JWT：

```bash
python scripts/generate_game_token.py --user-id 10001
```

### 4. 常用命令

```bash
# 只重启后端
docker compose up -d --build agent-api mcp-server

# 查看后端 / RAG 日志
docker compose logs -f agent-api rag-api

# 若 player-chat 未起来
docker compose up -d player-chat
```

## 可选：宿主机 RAG + 容器后端

这是独立的混合运行方案。先启动 MySQL 与 Redis，再启动宿主机 RAG 和容器后端；不要同时运行上面的本机 MCP / FastAPI 服务，以免占用相同端口。

若真实 `enterprise-rag` 在宿主机运行，再于本仓库执行 `docker compose up -d qdrant db-init`，然后在 `enterprise-rag` 目录配置其虚拟环境、API 密钥、MySQL 与 Qdrant 地址以及 BGE-M3 模型路径。以下为 Windows PowerShell 示例，模型目录须按实际位置修改：

```powershell
$env:DATABASE_URL='mysql+pymysql://rag_user:rag_password@127.0.0.1:3307/rag_database'
$env:QDRANT_HOST='127.0.0.1'
$env:EMBED_MODEL='C:/path/to/bge-m3'
$env:PYTHONIOENCODING='utf-8'
$env:OMP_NUM_THREADS='4'
$env:MKL_NUM_THREADS='4'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

确认 `http://127.0.0.1:8000/health` 的 `index_ready=true` 后，在本仓库 `.env` 设置 `RAG_API_KEY` 与 `enterprise-rag/.env` 的 `API_KEY` 一致，并将 `MCP_RAG_SERVICE_URL`、`AGENT_RAG_SERVICE_URL` 设置为 `http://host.docker.internal:8000`；再运行 `docker compose up -d --no-deps mcp-server agent-api`。`index_ready=true` 只说明索引已加载；正式评测前仍需确认所需文档已入库。若沿用既有测试索引，请记录文档版本和实际解析方式。

## RAG 知识库

`docker compose up` 会构建并启动同级仓库 `enterprise-rag` 的 `rag-api`。Agent 通过 MCP 工具 `query_knowledge`：

1. HTTP 调用知识库 **`POST /api/v1/retrieve`** 只取片段
2. 在本仓库用 LLM（`agent/tools/knowledge_answer.py`）依据片段作答
3. 再经图中 `generate` 节点润色成客服话术

不跑 Docker、只测 Agent 时可用内置桩：

```bash
python -m uvicorn mock_rag.main:app --port 8000
```

### 外部 RAG HTTP 契约

自有知识库需实现**仅检索**接口（不要依赖 RAG 侧生成答案）：

```http
GET /health
→ 200 {"status": "ok"}

POST /api/v1/retrieve
Content-Type: application/json
X-API-Key: <optional>

{"question": "如何获得原石？", "top_k": 10}

→ 200
{
  "query": "如何获得原石？",
  "sources": [
    {"text": "片段全文", "source": "faq.md", "page": null, "score": 0.92}
  ],
  "max_score": 0.92,
  "retrieve_mode": "vector",
  "elapsed_ms": 120
}
```

客户端见 `agent/tools/rag_client.py`；不可用时会安全降级（建议转人工），不阻断主服务启动。

## 技术栈

| 层面 | 选型 |
|------|------|
| AI 编排 | LangGraph / langchain-core / langchain-openai |
| LLM | DashScope 兼容接口；模型由 `REASONING_MODEL_NAME` / `GENERATE_MODEL_NAME` 配置 |
| 评测 | LLM-as-Judge 默认 `deepseek-v4.1-flash` |
| API 服务 | FastAPI + Pydantic |
| 客户端 | React + Vite + Ant Design + rich CLI |
| 持久化 | SQLite（Agent 状态）+ Redis（待接待队列）+ MySQL（工单/账号 + 知识库元数据）+ Qdrant（向量） |
| 外部集成 | MCP Server（streamable_http）+ enterprise-rag HTTP（/api/v1/retrieve） |
| 鉴权 | 游戏 JWT（玩家）+ Reviewer Token（客服） |
| 测试 | pytest |
