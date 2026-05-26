# Game Support Agent

基于 LangGraph 的游戏客服 Agent，核心亮点是完整的 human-in-loop 机制 + 工单管理系统。

## 项目架构

```
game-support-agent/
├── agent/                          # LangGraph 核心编排
│   ├── graph.py                    # 主图：6 个节点 + 3 条条件边
│   ├── state.py                    # AgentState 定义
│   ├── checkpointer.py             # MemorySaver 状态持久化
│   ├── nodes/
│   │   ├── reasoning.py            # LLM 推理节点（bind_tools 自主决策）
│   │   ├── tool_exec.py            # 通用工具分发器
│   │   ├── generate.py             # 客服回复生成节点
│   │   ├── detector.py             # 安全兜底检测节点
│   │   ├── human_node.py           # 人工审核节点
│   │   └── finish.py               # 结束节点
│   ├── tools/
│   │   ├── __init__.py             # get_all_tools() 工厂
│   │   ├── query_knowledge.py      # 知识库查询工具
│   │   ├── rag_client.py           # RAG HTTP 客户端
│   │   ├── escalate.py             # 转人工工具
│   │   ├── account.py              # 账号查询工具
│   │   ├── ticket.py               # 创建工单工具
│   │   ├── ticket_status.py        # 查询工单进度工具
│   │   └── mcp_client.py           # MCP 客户端封装
│   └── prompts/
│       └── system.py               # 系统提示词
├── app/                            # FastAPI 服务层
│   ├── main.py                     # 入口（CORS、路由、生命周期）
│   ├── api/v1/
│   │   ├── chat.py                 # 对话接口
│   │   ├── human.py                # 人工审核接口
│   │   └── ticket.py               # 工单 CRUD 接口
│   ├── core/
│   │   ├── config.py               # pydantic-settings 配置
│   │   ├── llm.py                  # LLM 工厂
│   │   └── exceptions.py          # 业务异常
│   └── models/
│       ├── chat.py
│       ├── review.py
│       └── ticket.py
├── human_in_loop/                  # Human-in-loop 底层模块
│   ├── detector.py                 # 敏感词 + 置信度检测
│   ├── reviewer.py                 # APPROVE / MODIFY / OVERRIDE
│   ├── auditor.py                  # 审计日志
│   └── schema.py
├── client/                         # 客户端界面
│   ├── user_ui.py                  # 用户界面（聊天/提工单/查进度）
│   ├── web_ui.py                   # 客服界面（审核/工单管理）
│   └── cli.py                      # 终端 CLI
├── scripts/
│   └── ingest_faq.py               # FAQ 导入 RAG
├── tests/
│   ├── test_agent.py
│   ├── test_human_in_loop.py
│   └── test_rag_client.py
├── data/
│   ├── game_support.db             # SQLite 工单数据库
│   └── faq.json                    # 示例 FAQ 数据
├── mcp_server.py                   # MCP 工具服务
├── .env.example
├── requirements.txt
└── docker-compose.yml
```

## 核心特性

### 1. Human-in-loop 机制

- **两层检测**：业务升等（EscalateDetector）→ 安全兜底（InterruptDetector 敏感词 + 置信度）
- **三种操作**：APPROVE / MODIFY / OVERRIDE
- **审计链**：JSON 审计日志，支持事后追溯

### 2. 工单系统

- **SQLite 持久化**：工单创建、状态流转、处理结果
- **完整状态机**：pending → processing → resolved / escalated
- **REST API**：工单 CRUD、统计、分页查询

### 3. LangGraph 编排

- **ReAct 风格** 循环图：`reasoning` → `tool_exec` → `reasoning`，多轮工具调用
- **条件路由**：`route_from_reasoning`（调工具？）、`route_from_tool_exec`（升等？）、`route_from_detector`（中断？）
- **6 个节点**：reasoning → tool_exec → generate → detector → human → finish

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

### 2. 启动 FastAPI 后端

```bash
python -m app.main
```

默认监听 `http://localhost:8002`，API 文档见 `http://localhost:8002/docs`

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

### 4. 测试

```bash
pytest
pytest tests/test_human_in_loop.py -v
pytest --cov=agent --cov=human_in_loop --cov-report=html
```

## 启动流程速查

| 组件 | 命令 | 端口 |
|------|------|------|
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
POST  /api/v1/human/review/{session_id}   # 提交审核结果
GET   /api/v1/human/status/{session_id}   # 查询审核状态
```

## Human-in-loop 详解

### 中断触发路径

```
LLM 主动调用 escalate_to_human
  → tool_exec 设 interrupt_info
  → route_from_tool_exec → human

generate 之后 detector 兜底
  → 敏感词 / 低置信度命中
  → route_from_detector → human
```

### 三种审核操作

| 操作 | 说明 | 最终回复 |
|------|------|---------|
| APPROVE | 直接通过 | 原 Agent 回复 |
| MODIFY | 修改后通过 | 人工编辑版 |
| OVERRIDE | 完全覆盖 | 人工编写 |

## 工单生命周期

```
玩家提交 / Agent 创建 → pending
     ↓ 客服开始处理
processing
     ↓ 客服填写处理结果
resolved
     ↓ 玩家查询
Agent 读取 agent_reply 返回给玩家
```

审计日志保存在 `logs/audit/` 目录。

## 技术栈

- **LangGraph** / **langchain-core**: AI 编排
- **FastAPI**: RESTful API
- **Streamlit**: 用户界面 + 客服界面
- **SQLite**: 工单数据持久化
- **DashScope / OpenAI**: LLM 双通道
- **httpx**: 异步 HTTP
- **Pydantic**: 配置与校验
- **pytest**: 测试

## 待办事项

- [ ] Redis / Postgres 生产级状态持久化
- [ ] 用户与会话管理
- [ ] 审核任务分配
- [ ] 多语言回复支持
- [ ] 端到端测试覆盖
- [ ] Prometheus 监控 + Sentry 错误追踪
