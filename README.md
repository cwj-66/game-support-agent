# Game Support Agent

基于 MCP 协议 + LangGraph 的游戏客服 Agent，核心亮点是完整的 human-in-loop 机制。

## 项目架构

```
game-support-agent/
├── mcp_servers/knowledge_server/  # SSE MCP Server
├── agent/                         # LangGraph 核心
│   ├── graph.py                   # 主图、路由与 generate/detector 等
│   ├── nodes/                     # 推理、工具执行、人工审核节点
│   └── tools/                     # MCP 工具适配
├── app/                           # FastAPI 服务
│   ├── api/v1/                    # 对话和审核 API
│   ├── core/                      # 配置、LLM 工厂、异常
│   └── models/                    # 数据模型
├── human_in_loop/                 # 重点模块
│   ├── detector.py                # 中断检测（敏感词+置信度）
│   ├── reviewer.py                # 三种审核操作
│   ├── auditor.py                 # 审计日志
│   └── schema.py                  # 数据结构
├── client/                        # 客户端工具
│   ├── cli.py                     # 终端工具
│   └── web_ui.py                  # Streamlit 审核界面
├── tests/                         # 测试
└── data/                          # 示例原神 FAQ
```

## 核心特性

### 1. Human-in-loop 机制

- **中断检测**：`InterruptDetector` 结合敏感词 + 置信度；列表与阈值来自 `app.core.config`（`.env` 中 `SENSITIVE_WORDS`、`HIL_CONFIDENCE_THRESHOLD`）
- **三种操作**：APPROVE / MODIFY / OVERRIDE
- **审计链**：操作记录，支持事后追溯

### 2. MCP 协议集成

- SSE（默认端点路径 `/sse`，可配置 `ping` 保持长连）
- 工具：`query_knowledge`（查 RAG）、`check_knowledge_health`
- 请求头 `X-MCP-API-Key` 与 `MCP_API_KEY` 对应；知识服中间件未通过时返回 401
- Agent 侧 `create_knowledge_tool()` 通过 SSE 调用并自动带 Key

### 3. LangGraph 编排

- 流程：`reasoning` →（按需）`tool_exec` → `detector` → 分支 `human` / `generate` → `finish` → `END`
- `generate`：`MODIFY` / `OVERRIDE` 时**直接用人工内容**；否则若有知识结果则走 `get_chat_model()` 以原神客服口吻润色
- 提供 `run_agent` / `stream_agent`（`astream` 按节点更新，便于对接 SSE）

## 快速开始

### 1. 环境配置

```bash
python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
# 至少配置：LLM（DASHSCOPE_API_KEY 或 OPENAI_API_KEY）；
# 联调 MCP 时：MCP_API_KEY、MCP_SERVER_URL、RAG_SERVICE_URL
```

常用变量（与 `app.core.config` 一致，见 `.env.example`）：

| 变量 | 说明 |
|------|------|
| `DASHSCOPE_API_KEY` / `OPENAI_API_KEY` | LLM（有 DashScope 时优先） |
| `MCP_SERVER_URL` | MCP 基址，默认 `http://localhost:8001` |
| `MCP_API_KEY` | 请求头 `X-MCP-API-Key`，须与知识服侧一致 |
| `RAG_SERVICE_URL` | enterprise-rag 地址，默认 `http://localhost:8000` |
| `HIL_CONFIDENCE_THRESHOLD` / `SENSITIVE_WORDS` | 人工审核与中断检测参数 |

### 2. 启动服务

1. 启动 **RAG**（需先部署 enterprise-rag，默认 `8000`）
2. 启动 **MCP 知识服**（默认 `8001`，SSE：`/sse`）：

```bash
python -c "import asyncio; from mcp_servers.knowledge_server.server import run_server; asyncio.run(run_server())"
```

说明：包内 `mcp_servers.knowledge_server.server` 的 `__main__` 目前偏向本地单测，联调/生产请用上面方式调用 `run_server()`。

3. 启动 **FastAPI**：

```bash
python -m app.main
```

可选：`docker-compose up -d`（需镜像与依赖已配好）

### 3. 导入 FAQ 数据

```bash
python scripts/ingest_faq.py --rag-url http://localhost:8000
```

### 4. 测试

```bash
python client/cli.py --session test_001 "如何获得原石？"
python client/cli.py
streamlit run client/web_ui.py
```

## API 接口

### 对话接口

```http
POST /api/v1/chat/send
Content-Type: application/json

{
  "session_id": "sess_123",
  "message": "如何获得原石？"
}
```

### 人工审核接口

```http
POST /api/v1/human/review/{session_id}
Content-Type: application/json

{
  "session_id": "sess_123",
  "action": "MODIFY",
  "reviewer_id": "admin_001",
  "modified_content": "修改后的回复...",
  "notes": "优化表述"
}
```

## Human-in-loop 详解

### 中断触发条件

| 触发类型 | 说明 | 风险等级 |
|---------|------|---------|
| 敏感词 | 内容匹配 `SENSITIVE_WORDS` | high |
| 低置信度 | 推理置信度 &lt; `HIL_CONFIDENCE_THRESHOLD` | medium |
| 工具失败 | `tool_calls` 中含失败记录 | 见 detector 逻辑 |

### 三种审核操作

| 操作 | 说明 | 最终回复 |
|-----|------|---------|
| APPROVE | 直接通过 | 原 Agent 回复 |
| MODIFY | 修改后通过 | 人工编辑版 |
| OVERRIDE | 完全覆盖 | 人工全新编写 |

### 审计日志

保存在 `logs/audit/`，JSON 示例如下：

```json
{
  "audit_id": "audit_abc123",
  "session_id": "sess_123",
  "user_query": "如何退款？",
  "agent_raw_response": "...",
  "interrupt_triggered": true,
  "review_action": "MODIFY",
  "reviewer_id": "admin_001",
  "final_response": "...",
  "timestamps": {}
}
```

## 自动化测试

```bash
pytest
pytest tests/test_human_in_loop.py -v
pytest --cov=agent --cov=human_in_loop --cov-report=html
```

## 技术栈

- **LangGraph** / **langchain_openai**: 编排与 LLM
- **FastAPI**: RESTful API
- **MCP (Python SDK)**: SSE 客户端与知识服
- **httpx**: 异步 HTTP
- **Streamlit**: 审核界面
- **Pydantic / pydantic-settings**: 配置与校验
- **pytest**

## 项目结构说明

### mcp_servers/knowledge_server/

```text
server.py   # FastMCP、SSE、API Key 中间件、run_server（uvicorn）
client.py   # 调用 RAG 的 httpx 客户端
auth.py     # X-MCP-API-Key 与 MCP_API_KEY
models.py
```

### agent/

```text
graph.py         # 主图、generate_response_node（LLM 润色）、detector、finish
state.py
nodes/           # reasoning, tool_exec（create_knowledge_tool）, human 等
tools/
  mcp_adapter.py # create_knowledge_tool、SSE 调用
checkpointer.py
prompts/
```

### human_in_loop/

```text
detector.py    # 敏感词 + 置信度 + 工具失败等
reviewer.py / auditor.py / schema.py
```

## 待办事项

### 高优先级

- [ ] 将知识服 `run_server` 与 `python -m mcp_servers.knowledge_server.server` 的入口对齐，减少 `python -c` 联调成本
- [ ] 在 `app` 生命周期中补齐 RAG / MCP 健康检查与可观测性（当前 main 中仍有占位 TODO）
- [ ] 按需接入 LangGraph 官方 `interrupt()` 与多轮人工审核/恢复全链路

### 中优先级

- [ ] Redis / Postgres 持久化状态与审核队列
- [ ] 用户与会话管理、审核任务分配
- [ ] 提高单测与集成测覆盖率（含 SSE MCP 端到端）

### 低优先级

- [ ] 多语言回复
- [ ] Prometheus 指标、Sentry 等
- [ ] 性能与成本优化

## 许可证

MIT License
