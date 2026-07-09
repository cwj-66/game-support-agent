import { useState, useRef, useEffect } from 'react'
import { Input, Button, Card, Spin, Tag } from 'antd'
import './ChatPage.css'

const POLL_INTERVAL = 3000
const POLL_TIMEOUT = 5 * 60 * 1000

/** 每次刷新页面生成新会话 ID，避免复用旧 pending/人工状态 */
const createSessionId = () => `test_${Date.now()}`

const INITIAL_MESSAGES = [
  { id: 1, role: 'user', content: '你好，我想查一下账号状态' },
  { id: 2, role: 'agent', content: '您好！请提供您的游戏 UID，我帮您查询。' },
]

function ChatPage() {
  const [sessionId] = useState(createSessionId)
  const [messages, setMessages] = useState(INITIAL_MESSAGES)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [humanMode, setHumanMode] = useState(false)
  const [ticketOffer, setTicketOffer] = useState(null)  // { summary, issue_type, display_text }
  const [ticketConfirming, setTicketConfirming] = useState(false)

  const pollTimerRef = useRef(null)
  const pollStartRef = useRef(null)
  const lastHumanReplyRef = useRef('')
  const listEndRef = useRef(null)
  const messagesRef = useRef(messages)

  useEffect(() => {
    messagesRef.current = messages
  }, [messages])

  const clearPolling = () => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current)
      pollTimerRef.current = null
    }
    pollStartRef.current = null
  }

  useEffect(() => () => clearPolling(), [])

  // 人工接待期间后台轮询，接收客服主动发来的新消息
  useEffect(() => {
    if (!humanMode) return undefined

    const timer = setInterval(async () => {
      const hasLoading = messagesRef.current.some((m) => m.loading)
      if (hasLoading) return

      try {
        const res = await fetch(
          `http://localhost:8002/api/v1/chat/reply/${sessionId}`,
        )
        if (!res.ok) return
        const data = await res.json()
        if (
          data.status === 'completed' &&
          data.reply &&
          data.reply !== lastHumanReplyRef.current
        ) {
          lastHumanReplyRef.current = data.reply
          setMessages((prev) => {
            const last = prev[prev.length - 1]
            if (last?.role === 'agent' && last.content === data.reply) {
              return prev
            }
            return [
              ...prev,
              {
                id: Date.now(),
                role: 'agent',
                content: data.reply,
                isHuman: true,
              },
            ]
          })
          if (data.human_active === false) {
            setHumanMode(false)
          }
        }
      } catch {
        // 静默忽略
      }
    }, POLL_INTERVAL)

    return () => clearInterval(timer)
  }, [humanMode])

  useEffect(() => {
    listEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const updateAgentMsg = (thinkingId, content, loading, isHuman = false) => {
    setMessages((prev) =>
      prev.map((msg) =>
        msg.id === thinkingId
          ? { ...msg, content, loading, isHuman }
          : msg,
      ),
    )
  }

  const startPolling = (thinkingId, lastSeen = '') => {
    clearPolling()
    pollStartRef.current = Date.now()

    const poll = async () => {
      if (Date.now() - pollStartRef.current > POLL_TIMEOUT) {
        clearPolling()
        updateAgentMsg(thinkingId, '等待超时，请稍后重试', false, humanMode)
        return
      }

      try {
        const res = await fetch(
          `http://localhost:8002/api/v1/chat/reply/${sessionId}`,
        )
        if (!res.ok) return

        const data = await res.json()
        // 多轮人工：只有收到「新」回复才结束等待
        if (data.status === 'completed' && data.reply !== lastSeen) {
          clearPolling()
          lastHumanReplyRef.current = data.reply
          updateAgentMsg(thinkingId, data.reply, false, true)
          if (data.human_active === false) {
            setHumanMode(false)
          }
        }
      } catch {
        // 单次轮询失败静默忽略
      }
    }

    poll()
    pollTimerRef.current = setInterval(poll, POLL_INTERVAL)
  }

  const handleSend = async () => {
    const text = input.trim()
    if (!text || sending) return

    const userMsg = { id: Date.now(), role: 'user', content: text }
    const thinkingId = Date.now() + 1
    const waitingText = humanMode ? '等待客服回复...' : '思考中...'
    const thinkingMsg = {
      id: thinkingId,
      role: 'agent',
      content: waitingText,
      loading: true,
      isHuman: humanMode,
    }

    setMessages((prev) => [...prev, userMsg, thinkingMsg])
    setInput('')
    setSending(true)

    try {
      const res = await fetch('http://localhost:8002/api/v1/chat/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          user_id: 'user_001',
          message: text,
        }),
      })

      if (!res.ok) throw new Error('request failed')

      const data = await res.json()

      if (data.status === 'under_review') {
        setHumanMode(true)
        const waitMsg = humanMode
          ? '消息已发送，等待客服回复...'
          : '已转人工客服，请稍候...'
        updateAgentMsg(thinkingId, waitMsg, true, true)
        startPolling(thinkingId, lastHumanReplyRef.current)
        return
      }

      // 人工模式下不应收到 AI 回复，兜底继续等待客服
      if (humanMode) {
        updateAgentMsg(thinkingId, '消息已发送，等待客服回复...', true, true)
        startPolling(thinkingId, lastHumanReplyRef.current)
        return
      }

      // 人工接待结束后，回到 AI 模式
      setHumanMode(false)
      lastHumanReplyRef.current = ''
      updateAgentMsg(thinkingId, data.response, false, false)

      // 有工单 offer → 展示确认按钮
      if (data.ticket_offer) {
        setTicketOffer(data.ticket_offer)
      }
    } catch {
      updateAgentMsg(thinkingId, '请求失败，请检查后端是否启动', false)
    } finally {
      setSending(false)
    }
  }

  const handleTicketConfirm = async (confirmed) => {
    setTicketConfirming(true)
    try {
      const res = await fetch('http://localhost:8002/api/v1/chat/ticket-confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, confirmed }),
      })
      const data = await res.json()
      setTicketOffer(null)

      const resultMsg = confirmed
        ? data.status === 'created'
          ? `✅ 工单已创建！工单号：${data.ticket_id}，预计处理时间：${data.estimated_response || '3-5个工作日'}`
          : '工单创建失败，请稍后重试'
        : '好的，已取消工单创建。如需帮助随时告知。'

      setMessages((prev) => [
        ...prev,
        { id: Date.now(), role: 'agent', content: resultMsg },
      ])
    } catch {
      setTicketOffer(null)
      setMessages((prev) => [
        ...prev,
        { id: Date.now(), role: 'agent', content: '操作失败，请稍后重试' },
      ])
    } finally {
      setTicketConfirming(false)
    }
  }

  return (
    <div className="chat-page">
      <Card
        className="chat-card"
        title={
          <span>
            游戏客服 Agent
            {humanMode && (
              <Tag color="orange" style={{ marginLeft: 8 }}>
                人工客服接待中
              </Tag>
            )}
          </span>
        }
      >
        <div className="message-list">
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`message-item ${msg.role === 'user' ? 'user' : 'agent'}`}
            >
              <div
                className={`message-bubble ${msg.isHuman ? 'human-agent' : ''}`}
              >
                {msg.loading ? (
                  <span className="thinking">
                    <Spin size="small" />
                    {msg.content}
                  </span>
                ) : (
                  msg.content
                )}
              </div>
            </div>
          ))}
          {ticketOffer && (
            <div className="message-item agent">
              <div className="message-bubble ticket-offer">
                <div style={{ marginBottom: 8 }}>
                  <strong>{ticketOffer.display_text || '是否为您生成工单？'}</strong>
                </div>
                {ticketOffer.summary && (
                  <div style={{ fontSize: 13, color: '#555', marginBottom: 10 }}>
                    问题摘要：{ticketOffer.summary}
                  </div>
                )}
                <div style={{ display: 'flex', gap: 8 }}>
                  <Button
                    type="primary"
                    size="small"
                    loading={ticketConfirming}
                    onClick={() => handleTicketConfirm(true)}
                  >
                    是
                  </Button>
                  <Button
                    size="small"
                    disabled={ticketConfirming}
                    onClick={() => handleTicketConfirm(false)}
                  >
                    否
                  </Button>
                </div>
              </div>
            </div>
          )}
          <div ref={listEndRef} />
        </div>

        <div className="input-area">
          <Input
            value={input}
            placeholder={
              humanMode ? '继续向人工客服描述问题...' : '请输入问题...'
            }
            onChange={(e) => setInput(e.target.value)}
            onPressEnter={handleSend}
          />
          <Button
            type="primary"
            onClick={handleSend}
            disabled={sending}
            loading={sending}
          >
            发送
          </Button>
        </div>
      </Card>
    </div>
  )
}

export default ChatPage
