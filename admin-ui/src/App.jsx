import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Table,
  Button,
  Input,
  Empty,
  message,
  Typography,
  Spin,
  Drawer,
  Tag,
  Alert,
} from 'antd'
import './App.css'
import { API_BASE } from './config'

const REVIEWER_ID = 'admin_001'
const AUTH_HEADERS = { 'X-Reviewer-Token': 'dev' }
const HISTORY_POLL_INTERVAL = 3000
const IDLE_LIMIT_SECONDS = 300  // 与后端 HUMAN_USER_IDLE_SECONDS 保持一致

const RISK_COLOR = {
  low: 'green',
  medium: 'orange',
  high: 'red',
}

/** 计算距现在多少秒（isoStr 为 null 时返回 null） */
function secondsAgo(isoStr) {
  if (!isoStr) return null
  try {
    return Math.floor((Date.now() - new Date(isoStr).getTime()) / 1000)
  } catch {
    return null
  }
}

/** 格式化秒数为「X分X秒」 */
function fmtSecs(s) {
  if (s === null || s === undefined) return '—'
  if (s < 60) return `${s}秒`
  return `${Math.floor(s / 60)}分${s % 60}秒`
}

function App() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [currentTask, setCurrentTask] = useState(null)
  const [history, setHistory] = useState([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [reply, setReply] = useState('')
  const [submitting, setSubmitting] = useState(false)
  // 用于每秒刷新计时的 tick
  const [tick, setTick] = useState(0)
  const historyEndRef = useRef(null)
  const currentTaskRef = useRef(null)

  // 同步 ref，方便定时器里访问最新 currentTask
  useEffect(() => {
    currentTaskRef.current = currentTask
  }, [currentTask])

  // 每秒 tick，驱动计时更新
  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [])

  const fetchPending = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/human/pending`, {
        headers: AUTH_HEADERS,
      })
      if (!res.ok) throw new Error('fetch failed')
      const data = await res.json()
      setItems(data.items || [])

      // 若当前打开的会话已被后端清除（超时），自动关闭抽屉
      const task = currentTaskRef.current
      if (task && drawerOpen) {
        const still = (data.items || []).find((i) => i.session_id === task.session_id)
        if (!still) {
          message.info('用户长时间未回复，接待已自动结束')
          closeDrawer()
        } else {
          // 更新 currentTask 的 last_user_at / last_agent_at
          setCurrentTask(still)
        }
      }
    } catch {
      if (!silent) message.error('获取待接待列表失败')
    } finally {
      if (!silent) setLoading(false)
    }
  }, [drawerOpen])

  const fetchHistory = useCallback(async (sessionId, silent = false) => {
    if (!silent) setHistoryLoading(true)
    try {
      // 使用客服专用历史接口（含 human_agent 角色，过滤 ToolMessage）
      const res = await fetch(`${API_BASE}/human/history/${sessionId}`, {
        headers: AUTH_HEADERS,
      })
      if (!res.ok) throw new Error('history failed')
      const data = await res.json()
      // 展示完整对话：user（玩家）/ agent（AI客服）/ human_agent（人工客服）
      setHistory(data.messages || [])
    } catch {
      if (!silent) {
        message.error('获取对话历史失败')
        setHistory([])
      }
    } finally {
      if (!silent) setHistoryLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchPending()
    const timer = setInterval(() => fetchPending(true), 5000)
    return () => clearInterval(timer)
  }, [fetchPending])

  // 会话抽屉打开时，轮询对话历史
  useEffect(() => {
    if (!drawerOpen || !currentTask) return undefined
    fetchHistory(currentTask.session_id, true)
    const timer = setInterval(() => {
      fetchHistory(currentTask.session_id, true)
    }, HISTORY_POLL_INTERVAL)
    return () => clearInterval(timer)
  }, [drawerOpen, currentTask?.session_id, fetchHistory])

  // 新消息时滚动到底部
  useEffect(() => {
    historyEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [history])

  const openSession = async (record) => {
    setCurrentTask(record)
    setReply('')
    setHistory([])
    setDrawerOpen(true)

    try {
      await fetch(`${API_BASE}/human/join/${record.session_id}`, {
        method: 'POST',
        headers: AUTH_HEADERS,
      })
    } catch (e) {
      console.error('Join failed', e)
    }

    fetchHistory(record.session_id)
  }

  const closeDrawer = () => {
    setDrawerOpen(false)
    setCurrentTask(null)
    setReply('')
    setHistory([])
  }

  /** 发送消息（继续接待） */
  const sendMessage = async () => {
    const text = reply.trim()
    if (!text) {
      message.warning('请填写回复内容')
      return
    }
    setSubmitting(true)
    try {
      const res = await fetch(`${API_BASE}/human/review/${currentTask.session_id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...AUTH_HEADERS },
        body: JSON.stringify({ reply: text, reviewer_id: REVIEWER_ID, action: 'continue' }),
      })
      if (!res.ok) throw new Error('submit failed')
      message.success('消息已发送')
      setReply('')
      fetchHistory(currentTask.session_id, true)
    } catch {
      message.error('发送失败')
    } finally {
      setSubmitting(false)
    }
  }

  /** 结束接待（可携带最后一条消息，也可为空） */
  const endSession = async () => {
    setSubmitting(true)
    try {
      const text = reply.trim()
      const res = await fetch(`${API_BASE}/human/review/${currentTask.session_id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...AUTH_HEADERS },
        body: JSON.stringify({
          reply: text || null,
          reviewer_id: REVIEWER_ID,
          action: 'close',
        }),
      })
      if (!res.ok) throw new Error('close failed')
      message.success('接待已结束')
      closeDrawer()
      fetchPending()
    } catch {
      message.error('结束接待失败')
    } finally {
      setSubmitting(false)
    }
  }

  // 计时展示（依赖 tick 每秒刷新）
  const userIdleSecs = currentTask ? secondsAgo(currentTask.last_user_at) : null
  const agentIdleSecs = currentTask ? secondsAgo(currentTask.last_agent_at) : null
  const userIdleWarning = userIdleSecs !== null && userIdleSecs > IDLE_LIMIT_SECONDS * 0.6

  const highRiskCount = items.filter((i) => i.risk_level === 'high').length
  const avgWait = items.length
    ? Math.round(items.reduce((s, i) => s + (i.wait_time_seconds || 0), 0) / items.length)
    : 0

  const columns = [
    {
      title: '会话ID',
      dataIndex: 'session_id',
      key: 'session_id',
      width: 130,
      ellipsis: true,
      render: (id) => <Typography.Text code>{id}</Typography.Text>,
    },
    {
      title: '用户问题',
      dataIndex: 'user_query',
      key: 'user_query',
      ellipsis: true,
    },
    {
      title: 'Agent 摘要',
      dataIndex: 'agent_response',
      key: 'agent_response',
      ellipsis: true,
    },
    {
      title: '触发原因',
      dataIndex: 'interrupt_reason',
      key: 'interrupt_reason',
      ellipsis: true,
    },
    {
      title: '风险',
      dataIndex: 'risk_level',
      key: 'risk_level',
      width: 80,
      render: (level) => (
        <Tag color={RISK_COLOR[level] || 'default'}>{level || '—'}</Tag>
      ),
    },
    {
      title: '等待',
      dataIndex: 'wait_time_seconds',
      key: 'wait_time_seconds',
      width: 80,
      render: (s) => `${s ?? 0}s`,
    },
    {
      title: '操作',
      key: 'action',
      width: 110,
      render: (_, record) => (
        <Button type="primary" size="small" className="enter-btn" onClick={() => openSession(record)}>
          进入会话
        </Button>
      ),
    },
  ]

  return (
    <div className="admin-layout">
      <aside className="admin-sidebar">
        <div className="admin-sidebar-brand">
          <h2>客服工作台</h2>
          <p>Game Support Agent</p>
        </div>
        <nav className="admin-sidebar-nav">
          <div className="admin-nav-item">
            <span className="nav-icon">💬</span>
            待接待会话
          </div>
        </nav>
        <div className="admin-sidebar-footer">
          客服 ID: {REVIEWER_ID}
        </div>
      </aside>

      <div className="admin-main">
        <header className="admin-topbar">
          <h1>待接待会话</h1>
          <span className="admin-topbar-meta">每 5 秒自动刷新</span>
        </header>

        <div className="admin-content">
          <div className="stats-row">
            <div className="stat-card">
              <div className="stat-icon pending">📋</div>
              <div className="stat-info">
                <div className="stat-value">{items.length}</div>
                <div className="stat-label">待接待</div>
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-icon waiting">⏱️</div>
              <div className="stat-info">
                <div className="stat-value">{avgWait}s</div>
                <div className="stat-label">平均等待</div>
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-icon risk">⚠️</div>
              <div className="stat-info">
                <div className="stat-value">{highRiskCount}</div>
                <div className="stat-label">高风险</div>
              </div>
            </div>
          </div>

          <div className="table-card">
            <div className="table-card-header">
              <h3>会话队列</h3>
              <Typography.Text type="secondary">共 {items.length} 条</Typography.Text>
            </div>
            <Spin spinning={loading}>
              {items.length === 0 && !loading ? (
                <Empty description="暂无待接待会话，喝杯咖啡等等 ☕" />
              ) : (
                <Table
                  rowKey="session_id"
                  columns={columns}
                  dataSource={items}
                  pagination={false}
                />
              )}
            </Spin>
          </div>
        </div>
      </div>

      <Drawer
        className="session-drawer"
        title={currentTask ? `会话 ${currentTask.session_id}` : '会话详情'}
        open={drawerOpen}
        onClose={closeDrawer}
        width={720}
        destroyOnHidden
        extra={
          <Button
            danger
            onClick={endSession}
            loading={submitting}
            disabled={submitting}
          >
            结束接待
          </Button>
        }
      >
        {currentTask && (
          <div className="drawer-body">
            <div className="task-summary">
              <div className="task-summary-title">任务摘要</div>
              <div className="task-summary-row">
                <span className="task-summary-label">触发原因</span>
                <span className="task-summary-value">
                  {currentTask.interrupt_reason || '未知'}
                </span>
              </div>
              <div className="task-summary-row">
                <span className="task-summary-label">风险等级</span>
                <span className="task-summary-value">
                  <Tag color={RISK_COLOR[currentTask.risk_level] || 'default'}>
                    {currentTask.risk_level || 'unknown'}
                  </Tag>
                </span>
              </div>
              <div className="task-summary-row">
                <span className="task-summary-label">用户问题</span>
                <span className="task-summary-value">{currentTask.user_query}</span>
              </div>
            </div>

            <div className="idle-timers" key={tick}>
              <span className={userIdleWarning ? 'idle-warn' : ''}>
                👤 用户 {fmtSecs(userIdleSecs)} 未回复
                {userIdleWarning && `（超 ${Math.floor(IDLE_LIMIT_SECONDS / 60)} 分钟将自动结束）`}
              </span>
              <span>🧑‍💼 客服 {fmtSecs(agentIdleSecs)} 未回复</span>
            </div>

            {userIdleWarning && (
              <Alert
                type="warning"
                message={`用户已 ${fmtSecs(userIdleSecs)} 未回复，即将自动结束接待`}
                showIcon
              />
            )}

            <span className="chat-section-label">对话记录 · 自动刷新</span>
            <Spin spinning={historyLoading}>
              <div className="chat-history">
                {history.length === 0 && !historyLoading ? (
                  <Empty
                    description="暂无对话记录"
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                  />
                ) : (
                  history.map((msg, idx) => {
                    const isUser = msg.role === 'user'
                    const isHumanAgent = msg.role === 'human_agent'
                    const isAi = !isUser && !isHumanAgent
                    const senderLabel = isUser ? '玩家' : isHumanAgent ? '人工客服' : 'AI 客服'
                    const avatar = isUser ? '👤' : isHumanAgent ? '🧑‍💼' : '🤖'
                    return (
                      <div
                        key={`${msg.timestamp}-${idx}`}
                        className={`chat-bubble-row ${isUser ? 'user' : 'agent'}`}
                      >
                        <div className={`chat-avatar ${isAi ? 'ai' : ''}`}>{avatar}</div>
                        <div className={`chat-bubble ${isAi ? 'ai-agent' : ''}`}>
                          <span className="bubble-sender">{senderLabel}</span>
                          {msg.content}
                        </div>
                      </div>
                    )
                  })
                )}
                <div ref={historyEndRef} />
              </div>
            </Spin>

            <div className="reply-area">
              <Input.TextArea
                rows={3}
                value={reply}
                placeholder="输入回复，Enter 发送（Shift+Enter 换行）"
                onChange={(e) => setReply(e.target.value)}
                onPressEnter={(e) => {
                  if (!e.shiftKey) {
                    e.preventDefault()
                    sendMessage()
                  }
                }}
              />
              <div className="reply-actions">
                <Button
                  type="primary"
                  onClick={sendMessage}
                  loading={submitting}
                  disabled={submitting}
                >
                  发送
                </Button>
              </div>
            </div>
          </div>
        )}
      </Drawer>
    </div>
  )
}

export default App
