# Game Support Agent

基于 MCP 协议 + LangGraph 的游戏客服 Agent，核心亮点是完整的 human-in-loop 机制。

## 项目架构

```
game-support-agent/
├── mcp_servers/knowledge_server/  # SSE MCP Server
├── agent/                         # LangGraph 核心
│   ├── graph.py                   # 主图定义
│   ├── nodes/                     # 推理、工具执行、人工审核节点
│   └── tools/                     # MCP 工具适配
├── app/                           # FastAPI 服务
│   ├── api/v1/                    # 对话和审核API
│   ├── core/                      # 配置和异常处理
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
└── data/                          # 30条原神FAQ
```

## 核心特性

### 1. Human-in-loop 机制

- **中断检测**：敏感词列表 + 置信度阈值双重过滤
- **三种操作**：APPROVE（通过）/ MODIFY（修改）/ OVERRIDE（覆盖）
- **审计链**：完整的操作记录，支持事后追溯

### 2. MCP 协议集成

- SSE 模式 MCP Server
- 暴露 `query_knowledge` 工具查询RAG
- 独立API Key认证层

### 3. LangGraph 编排

节点顺序：`reasoning` → `tool_exec` → `detector` → [条件分支] → `human_node` / `generate`

## 快速开始

### 1. 环境配置

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API Key 等配置
```

### 2. 启动服务

```bash
# 方式1：手动启动各服务
# 1. 启动RAG服务（需先部署 enterprise-rag）
# 2. 启动MCP Server
python -m mcp_servers.knowledge_server.server

# 3. 启动FastAPI服务
python -m app.main

# 方式2：Docker Compose一键启动（需配置RAG镜像）
docker-compose up -d
```

### 3. 导入FAQ数据

```bash
# 将示例FAQ导入RAG服务
python scripts/ingest_faq.py --rag-url http://localhost:8000
```

### 4. 测试

```bash
# CLI 测试
python client/cli.py --session test_001 "如何获得原石？"

# 进入交互模式
python client/cli.py

# Web 审核界面
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
| 敏感词 | 内容匹配敏感词列表 | high |
| 低置信度 | LLM置信度 < 阈值 | medium |

### 三种审核操作

| 操作 | 说明 | 最终回复 |
|-----|------|---------|
| APPROVE | 直接通过 | 原Agent回复 |
| MODIFY | 修改后通过 | 人工编辑版 |
| OVERRIDE | 完全覆盖 | 人工全新编写 |

### 审计日志

保存在 `logs/audit/` 目录，JSON格式：

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
  "timestamps": {...}
}
```

## 测试

```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/test_human_in_loop.py -v

# 覆盖率报告
pytest --cov=agent --cov=human_in_loop --cov-report=html
```

## 技术栈

- **LangGraph**: Agent 编排和状态管理
- **FastAPI**: RESTful API
- **MCP (fastmcp)**: 协议层实现
- **httpx**: 异步HTTP客户端
- **Streamlit**: 审核可视化界面
- **Pydantic**: 数据验证
- **pytest**: 测试框架

## 项目结构说明

### mcp_servers/knowledge_server/

```python
server.py   # SSE MCP Server，暴露 query_knowledge 工具
client.py   # RAG HTTP 客户端封装
auth.py     # MCP层API Key校验
models.py   # 请求/响应Pydantic模型
```

### agent/

```python
graph.py    # LangGraph主图，节点编排
state.py    # AgentState定义（消息、中断标记、审核结果）
nodes/      # 三个核心节点
  reasoning.py   # LLM自主决策
  tool_exec.py   # 执行MCP工具
  human_node.py  # 断点暂停/恢复
tools/
  mcp_adapter.py # MCP工具转LangGraph工具
checkpointer.py  # MemorySaver配置
prompts/
  system.py      # 系统提示词
```

### human_in_loop/ （重点模块）

```python
detector.py    # InterruptDetector：敏感词+置信度检测
reviewer.py    # HumanReviewer：三种操作处理
auditor.py     # AuditLogger：审计链记录
schema.py      # 中断决策、审核操作、审计日志数据结构
```

## 待办事项

### 高优先级

- [ ] 接入真实LLM（OpenAI/Azure）
- [ ] 实现真实MCP SSE连接
- [ ] 完善LangGraph interrupt()集成
- [ ] 接入真实的RAG服务

### 中优先级

- [ ] 实现Redis/Postgres持久化
- [ ] 添加用户会话管理
- [ ] 实现审核任务队列分配
- [ ] 添加更多测试覆盖

### 低优先级

- [ ] 多语言支持
- [ ] 监控指标（Prometheus）
- [ ] 日志聚合（Sentry）
- [ ] 性能优化

## 许可证

MIT License
