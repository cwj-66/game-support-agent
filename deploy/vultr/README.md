# Vultr 独立部署（当前使用）

网站：https://chenwj.click/。服务器 IP：45.77.24.56。

访问路径：浏览器 → 服务器 Nginx HTTPS → 独立作品集服务（15176）/ Docker 前端（15177）→ Agent、MCP、RAG → MySQL、Qdrant、Redis。
网站不再依赖本机 Docker 或反向 SSH 隧道。原隧道脚本仅保留作历史方案。

## 服务器文件

- `/opt/game-support-deploy/game-support-agent/compose.yml`：来自本目录 `compose.server.yml`。
- `/opt/game-support-deploy/game-support-agent/.env`：聊天模型、访问校验配置；仅服务端使用。
- `/opt/game-support-deploy/enterprise-rag/.env`：硅基流动密钥和云端模型配置。
- `/opt/game-support-deploy/game-support-agent/data/`：持久化会话 SQLite。
- MySQL、Qdrant、Redis 使用独立的 Docker 数据卷，数据库端口不发布到公网。
- `/opt/chenwj-portfolio/`：保留已有作品集页面和密码验证。
- `/etc/nginx/sites-available/game-support-demo`：保留已有域名及 HTTPS 证书。

向量化使用 `BAAI/bge-m3` 云端 API，重排使用 `BAAI/bge-reranker-v2-m3` 云端 API。
RAG 镜像使用 `Dockerfile.cloud` / `requirements-cloud.txt`，不安装本地 PyTorch、向量模型、重排模型或 PDF 解析模型。
线上知识库只读。已有 MySQL 数据与 2932 条 Qdrant 向量通过快照迁移，不重新入库。

## 常用维护

在服务器执行：

```sh
cd /opt/game-support-deploy/game-support-agent
docker compose ps
docker compose logs --tail=80 agent-api rag-api mcp-server
docker stats --no-stream
docker compose up -d
```

所有运行服务设为 `restart: unless-stopped`，Docker 服务开机自启。不要执行 `docker compose down -v`，否则会删除数据卷。
修改代码后重新构建对应服务；修改 `.env` 后用 `docker compose up -d` 重建服务使配置生效。

## 并发、排队与故障保护

参数都在 `compose.server.yml` 的 `x-agent-limits` 中，修改后执行 `docker compose up -d agent-api mcp-server` 生效。

| 参数 | 默认 | 含义 |
|------|------|------|
| `AGENT_MAX_CONCURRENCY` | 3 | 全站同时执行的完整问答（含工具调用与回复生成） |
| `AGENT_MAX_QUEUE` | 10 | 最多排队数；队列满返回 503 `server_busy` + `Retry-After` |
| `AGENT_QUEUE_TIMEOUT_SECONDS` | 60 | 排队上限；超时返回 `queue_timeout`，等待记录同时删除 |
| `AGENT_EXEC_TIMEOUT_SECONDS` | 90 | 单个问答执行上限（不含排队），超时取消并返回 `agent_timeout` |
| `AGENT_LEASE_SECONDS` | 30 | 名额租约；执行中每 10 秒续租，进程崩溃后最多 30 秒自动回收 |
| `SSE_HEARTBEAT_SECONDS` | 15 | 排队与执行期间的 SSE 心跳 |
| `CHAT_RATE_LIMIT_PER_MINUTE` | 10 | 每个访客（HttpOnly cookie `gsa_visitor`）每分钟提交次数，超限 429 |
| `CHAT_RATE_LIMIT_PER_IP_PER_MINUTE` | 30 | 每个真实 IP 的上限，防止清 cookie 绕过 |
| `LLM_READ_TIMEOUT_SECONDS` / `UPSTREAM_MAX_RETRIES` | 30 / 1 | Qwen 单次读取超时；只对 429/5xx/网络错误重试 1 次 |
| `MCP_TOOL_TIMEOUT_SECONDS` / `MCP_KNOWLEDGE_TIMEOUT_SECONDS` | 15 / 60 | 账号与工单工具、知识查询工具超时，MCP 层不重试 |
| `RAG_TIMEOUT_SECONDS` | 30 | Agent 调检索服务超时；云端向量化与重排在 RAG 内各自最多重试 1 次 |
| `BREAKER_*` | 5 次 / 60s / 30s | 连续失败 5 次熔断 30 秒，之后只放行 1 个探测请求 |
| `MYSQL_POOL_SIZE` / `BLOCKING_POOL_SIZE` | 5 / 4 | 每进程 MySQL 连接上限与同步查询线程数（agent-api、mcp-server 各一份） |

RAG 侧（`rag-api` 的 `environment`）：`CLOUD_MODEL_TIMEOUT=15`、`CLOUD_MAX_RETRIES=1`、`DB_POOL_SIZE=5`、`DB_MAX_OVERFLOW=2`、`DB_POOL_TIMEOUT=5`。MySQL 设 `--max-connections=60`，三个进程的连接池合计最多 17 条。

请求处理顺序：鉴权与会话归属 → 访客频率限制（429）→ 会话锁（409）→ 幂等结果 → 全站容量排队（503）→ 执行。人工接待中的玩家消息不占问答名额。

**Redis 故障时**新问答和会话状态修改返回 503 `capacity_unavailable`，不会退化为无限放行；频率限制退回进程内计数；人工队列沿用原有的内存降级。可用 `curl -s 127.0.0.1:15177/health` 查看 `checks.capacity`（执行中/排队数）与 `checks.circuits`（熔断状态）。

**真实 IP**：边缘 Nginx 必须用 `$remote_addr` 覆盖 `X-Forwarded-For`；容器内 Nginx 只追加本跳。后端只在直连对端位于 `TRUSTED_PROXY_CIDRS` 时读取该头，并从右向左取第一个非代理地址；uvicorn 以 `--no-proxy-headers` 启动。作品集站点的 Nginx 若与本目录 `nginx.conf` 不同，需要手动确认这一点（本次未登录服务器修改）。

**超时链路**：边缘与容器 Nginx 的 `proxy_read_timeout` 均为 300 秒，大于「排队 60 秒 + 执行 90 秒」；心跳每 15 秒一次，代理不会因空闲断开。

## 日志与资源预算

所有容器使用 json-file 日志，单文件 10MB、保留 3 个。内存上限合计约 2.9GB：MySQL 640m、Redis 192m（`maxmemory 128mb`，`noeviction`）、Qdrant 512m、RAG 640m、Agent 640m、MCP 256m、前端 64m。协调用的 Redis 键都带过期时间（容量键空闲 10 分钟、幂等结果 10 分钟、频率窗口 60 秒）。

`docker stats --no-stream` 中某个容器接近上限时，先看日志定位，不要直接调大 worker 数。

## 扩容前提（多 worker / 多实例）

当前固定 `agent-api --workers 1`、`rag-api --workers 1`。增加 worker 或实例前必须满足：

1. **检查点迁出 SQLite**：`AsyncSqliteSaver` 是单进程单连接，多进程写同一文件只能靠 `busy_timeout` 排队，并且不同进程的读缓存不一致。需要换成共享数据库检查点（例如 Postgres 或 Redis checkpointer），并迁移现有会话。
2. **协调后端保持 Redis**：`COORDINATION_BACKEND=redis` 时全站名额、排队、会话锁、频率与幂等都已跨进程生效；`memory` 只能单进程使用。
3. **熔断状态是进程内的**：每个进程独立统计，扩容后每个进程都会各自探测一次，下游压力按进程数放大。
4. **连接池按进程计算**：MySQL 总连接 = 进程数 × (池大小 + 溢出)，需同步调整 `--max-connections`。
5. **人工队列与会话 TTL 的内存降级**：Redis 不可用时这两项会退回进程内存，多进程下互不可见；扩容前应改为 Redis 不可用即拒绝。
6. 单机 2 核 4GB 下 Agent 的瓶颈是云端模型延迟而不是 CPU，增加 worker 不会提高 3 个并发名额的吞吐；需要先确认云端限额后再调 `AGENT_MAX_CONCURRENCY`。

并发实现与测试数据见 [`concurrency-report.md`](concurrency-report.md)。

## 登录与回滚

作品集密码校验通过后同时签发游戏演示访问 cookie，不需要再次输入密码。
游戏 API 自身仍保留访问验证；客服完整演示权限不变。
切换前配置备份位于服务器 `/opt/game-support-deploy/backup-时间戳/`，包含原作品集服务代码、环境配置、Nginx 和首页内容。
`connect-portfolio.py` 为本次一次性迁移脚本，不能重复执行。

---

以下是历史隧道方案，当前无需使用：

# Vultr 入口 + 本地 Docker 演示

访问路径：浏览器 → Vultr Nginx :80 → 服务器回环端口 :15175 → SSH 隧道 → 本地前端 :5175。

服务器只承载转发；本地 Docker 和隧道都必须运行，电脑不能休眠。当前先使用 HTTP IP 入口，尚未配置 HTTPS。

## 文件

- `nginx.conf`：复制为 `/etc/nginx/sites-available/game-support-demo`，在 `sites-enabled` 中建立同名链接。
- `demo-offline.html`：复制为 `/var/www/game-support-demo/demo-offline.html`。
- `../../scripts/start-demo-tunnel.ps1`：在本机保持 SSH 反向隧道，掉线后自动重连，不会启动 Docker。

服务器身份必须先在 Vultr 控制台核对，并保存到专用 known_hosts。私钥仅留在本机，不上传、不提交仓库。

```powershell
.\scripts\start-demo-tunnel.ps1
```

默认读取当前 Windows 用户的 `~/.ssh/game-support-demo_ed25519` 和 `~/.ssh/game-support-demo_known_hosts`。私钥应属于实际运行 PowerShell 的用户；工具沙箱账户生成的私钥不可直接当作用户密钥使用。也可用 `-IdentityFile` / `-KnownHostsFile` 指定其他已验证文件。

本机 RAG 在 `enterprise-rag` 目录执行 `.\scripts\start-local.ps1`，无需激活环境。脚本使用该项目 `.venv`，并在导入应用前加载 `.env`。本机共享数据库地址应使用 `127.0.0.1:3307`，模型路径应指向实际存在的本地目录。

## 启用步骤

1. 检查本机可用内存和 Docker 资源上限，由用户启动 Docker，再分批启动项目。
2. 验证本地 `http://127.0.0.1:5175` 的真实知识问答、演示账号隔离、独立密钥及客服权限；不可把开发密钥直接公开。
3. 启动隧道，在服务器访问 `http://127.0.0.1:15175` 验证转发。
4. 上述验证完成后，在服务器执行 `touch /var/www/game-support-demo/live.enabled` 开放演示。删除该标记即可关闭，无需重启 Nginx。
5. 从外网检查页面和流式聊天。`nginx -t` 成功后才能 reload 新配置。

默认没有 `live.enabled`，因此公网仅显示“演示暂未启动”，返回 503。隧道掉线时同样显示该页面。

仅需开放 80/tcp，15175 保持服务器回环监听，数据库和 RAG 端口不暴露公网。后续可配置域名和 HTTPS。
