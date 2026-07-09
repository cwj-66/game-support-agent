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
  Descriptions,
} from 'antd'
import './App.css'

const API_BASE = 'http://localhost:8002/api/v1'
const REVIEWER_ID = 'admin_001'
const AUTH_HEADERS = { 'X-Reviewer-Token': 'dev' }
const HISTORY_POLL_INTERVAL = 3000

const RISK_COLOR = {
  low: 'green',
  medium: 'orange',
  high: 'red',
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
  const historyEndRef = useRef(null)

  const fetchPending = useCallback(async (silent = false) => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/human/pending`, {
        headers: AUTH_HEADERS,
      })
      if (!res.ok) throw new Error('fetch failed')
      const data = await res.json()
      setItems(data.items || [])
    } catch {
      if (!silent) message.error('获取待接待列表失败')
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchHistory = useCallback(async (sessionId, silent = false) => {
    if (!silent) setHistoryLoading(true)
    try {
      const res = await fetch(`${API_BASE}/chat/history/${sessionId}`)
      if (!res.ok) throw new Error('history failed')
      const data = await res.json()
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
    const timer = setInterval(() => fetchPending(true), 10000)
    return () => clearInterval(timer)
  }, [fetchPending])

  // 会话抽屉打开时，轮询对话历史以接收玩家新消息
  useEffect(() => {
    if (!drawerOpen || !currentTask) return undefined

    fetchHistory(currentTask.session_id, true)
    const timer = setInterval(() => {
      fetchHistory(currentTask.session_id, true)
    }, HISTORY_POLL_INTERVAL)

    return () => clearInterval(timer)
  }, [drawerOpen, currentTask, fetchHistory])

  // 新消息时滚动到底部
  useEffect(() => {
    historyEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [history])

  const openSession = async (record) => {
    setCurrentTask(record)
    setReply('')
    setHistory([])
    setDrawerOpen(true)

    // 调用接入接口，发送「客服已接入」系统提示
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

  const sendToPlayer = async (action) => {
    const text = reply.trim()
    if (!text) {
      message.warning('请填写回复内容')
      return
    }

    setSubmitting(true)
    try {
      const res = await fetch(
        `${API_BASE}/human/review/${currentTask.session_id}`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...AUTH_HEADERS,
          },
          body: JSON.stringify({
            reply: text,
            reviewer_id: REVIEWER_ID,
            action,
          }),
        },
      )
      if (!res.ok) throw new Error('submit failed')

      if (action === 'close') {
        message.success('接待已结束')
        closeDrawer()
        fetchPending()
      } else {
        message.success('消息已发送')
        setReply('')
        fetchHistory(currentTask.session_id, true)
      }
    } catch {
      message.error(action === 'close' ? '结束接待失败' : '发送失败')
    } finally {
      setSubmitting(false)
    }
  }

  const columns = [
    {
      title: '会话ID',
      dataIndex: 'session_id',
      key: 'session_id',
      width: 130,
      ellipsis: true,
    },
    {
      title: '用户问题',
      dataIndex: 'user_query',
      key: 'user_query',
      ellipsis: true,
    },
    {
      title: 'Agent 回复',
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
      title: '等待(秒)',
      dataIndex: 'wait_time_seconds',
      key: 'wait_time_seconds',
      width: 90,
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_, record) => (
        <Button type="link" onClick={() => openSession(record)}>
          进入会话
        </Button>
      ),
    },
  ]

  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: '0 auto' }}>
      <Typography.Title level={4} style={{ marginBottom: 16 }}>
        客服工作台 — 待接待会话
      </Typography.Title>

      <Spin spinning={loading}>
        {items.length === 0 && !loading ? (
          <Empty description="暂无待接待会话" />
        ) : (
          <Table
            rowKey="session_id"
            columns={columns}
            dataSource={items}
            pagination={false}
          />
        )}
      </Spin>

      <Drawer
        title={currentTask ? `会话：${currentTask.session_id}` : '会话详情'}
        open={drawerOpen}
        onClose={closeDrawer}
        width={720}
        destroyOnHidden
      >
        {currentTask && (
          <div className="drawer-body">
            <Descriptions column={1} size="small" bordered title="任务摘要">
              <Descriptions.Item label="触发原因">
                {currentTask.interrupt_reason || '未知'}
              </Descriptions.Item>
              <Descriptions.Item label="风险等级">
                <Tag color={RISK_COLOR[currentTask.risk_level] || 'default'}>
                  {currentTask.risk_level || 'unknown'}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="用户问题">
                {currentTask.user_query}
              </Descriptions.Item>
            </Descriptions>

            <Typography.Text type="secondary">对话记录（自动刷新）</Typography.Text>
            <Spin spinning={historyLoading}>
              <div className="chat-history">
                {history.length === 0 && !historyLoading ? (
                  <Empty
                    description="暂无对话记录"
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                  />
                ) : (
                  history.map((msg, idx) => (
                    <div
                      key={`${msg.timestamp}-${idx}`}
                      className={`chat-bubble-row ${msg.role === 'user' ? 'user' : 'assistant'}`}
                    >
                      <div className="chat-bubble">{msg.content}</div>
                    </div>
                  ))
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
                    sendToPlayer('continue')
                  }
                }}
              />
              <div className="reply-actions">
                <Button
                  danger
                  onClick={() => sendToPlayer('close')}
                  loading={submitting}
                  disabled={submitting}
                >
                  结束接待
                </Button>
                <Button
                  type="primary"
                  onClick={() => sendToPlayer('continue')}
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
