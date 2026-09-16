import { useState, useRef, useEffect } from 'react'
import { Input, Button, Card, Drawer, Spin, Tag } from 'antd'
import { API_BASE } from '../config'
import { apiFetch } from '../api'
import { useAuth } from '../auth'
import { PlayerProfileDesc, scenarioOf } from '../PlayerProfile'
import './ChatPage.css'

const POLL_INTERVAL = 3000
const SEND_TIMEOUT = 90 * 1000

/** 根据 HTTP 状态码返回可读错误信息 */
const getHttpErrorMessage = (status) => {
  if (status === 401) return '登录已过期，请到「测试账号」页重新选择账号'
  if (status === 403) return '无权访问该会话，请刷新页面重试'
  if (status >= 500) return '服务端错误，请稍后重试'
  return '请求失败，请检查后端是否启动'
}

const DEFAULT_REPLY = '很抱歉没能为您解决问题，您可以继续向我求助。'
const HUMAN_OFFER_REPLY =
  '很抱歉没能为您解决问题。您可通过下方按钮确认是否转接人工客服，也可以继续向我求助。'
const TICKET_OFFER_REPLY =
  '很抱歉没能为您解决问题。您可通过下方按钮确认是否创建工单，也可以继续向我求助。'

const resolveDisplayReply = (data) => {
  if (data.response?.trim()) return data.response
  if (data.human_offer) return HUMAN_OFFER_REPLY
  if (data.ticket_offer) return TICKET_OFFER_REPLY
  return DEFAULT_REPLY
}

/** 进入聊天时的客服开场白 */
const INITIAL_MESSAGES = [
  {
    id: 1,
    role: 'agent',
    content: '您好！我是游戏客服助手，可以帮您查询攻略、账号状态、工单进度等。请问有什么可以帮您？',
  },
]

function ChatPage() {
  const { player, logout } = useAuth()
  const [sessionId] = useState(() => `${player.uid}_${Date.now()}`)
  const [messages, setMessages] = useState(INITIAL_MESSAGES)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [humanMode, setHumanMode] = useState(false)
  const [ticketOffer, setTicketOffer] = useState(null)
  const [humanOffer, setHumanOffer] = useState(null)
  const [ticketConfirming, setTicketConfirming] = useState(false)
  const [humanConfirming, setHumanConfirming] = useState(false)
  const [profileOpen, setProfileOpen] = useState(false)
  const [profile, setProfile] = useState(player)
  const [profileLoading, setProfileLoading] = useState(false)

  // 已消费的历史消息总数，用于增量拉取（包含 user + assistant 全量）
  const seenHistoryCountRef = useRef(0)
  // 当前等待中的"思考气泡" ID，轮询到回复后用来替换
  const loadingMsgIdRef = useRef(null)
  const listEndRef = useRef(null)

  /** 进入人工模式前，先拉一次当前历史作为基线，再设 humanMode */
  const enterHumanMode = async () => {
    try {
      const res = await apiFetch(`/chat/history/${sessionId}`)
      if (res.ok) {
        const data = await res.json()
        seenHistoryCountRef.current = data.total || 0
      }
    } catch {
      // 静默忽略，从 0 开始也无妨（最多重复展示历史）
    }
    setHumanMode(true)
  }

  /**
   * 人工模式轮询历史（增量）
   * 每 3s 拉 /chat/history，找出 seenHistoryCountRef 之后的 is_human 新消息
   * 同时用 /chat/reply 检测 human_active 是否已变 false
   */
  useEffect(() => {
    if (!humanMode) return undefined

    const poll = async () => {
      try {
        const res = await apiFetch(`/chat/history/${sessionId}`)
        if (!res.ok) return
        const data = await res.json()
        const allMsgs = data.messages || []

        const newHumanMsgs = allMsgs
          .slice(seenHistoryCountRef.current)
          .filter((m) => m.role === 'assistant' && m.is_human)

        seenHistoryCountRef.current = allMsgs.length

        if (newHumanMsgs.length > 0) {
          setMessages((prev) => {
            let updated = [...prev]
            for (const m of newHumanMsgs) {
              const loadingIdx = loadingMsgIdRef.current
                ? updated.findIndex((msg) => msg.id === loadingMsgIdRef.current)
                : -1
              if (loadingIdx !== -1) {
                updated[loadingIdx] = {
                  ...updated[loadingIdx],
                  content: m.content,
                  loading: false,
                  isHuman: true,
                }
                loadingMsgIdRef.current = null
              } else {
                updated.push({
                  id: Date.now() + Math.random(),
                  role: 'agent',
                  content: m.content,
                  isHuman: true,
                })
              }
            }
            return updated
          })
        }

        const replyRes = await apiFetch(`/chat/reply/${sessionId}`)
        if (replyRes.ok) {
          const replyData = await replyRes.json()
          if (replyData.human_active === false) {
            setHumanMode(false)
            if (loadingMsgIdRef.current) {
              setMessages((prev) =>
                prev.filter((m) => !(m.id === loadingMsgIdRef.current && m.loading)),
              )
              loadingMsgIdRef.current = null
            }
          }
        }
      } catch {
        // 静默忽略
      }
    }

    poll()
    const timer = setInterval(poll, POLL_INTERVAL)
    return () => clearInterval(timer)
  }, [humanMode, sessionId])

  useEffect(() => {
    listEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    if (!profileOpen || !player?.uid) return undefined
    let cancelled = false
    const load = async () => {
      setProfileLoading(true)
      try {
        const res = await fetch(`${API_BASE}/demo/players`)
        if (!res.ok) return
        const data = await res.json()
        const fresh = Array.isArray(data)
          ? data.find((p) => p.uid === player.uid)
          : null
        if (!cancelled && fresh) setProfile(fresh)
      } catch {
        // 接口失败时沿用登录时缓存的档案
      } finally {
        if (!cancelled) setProfileLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [profileOpen, player?.uid])

  const updateAgentMsg = (thinkingId, content, loading, isHuman = false) => {
    setMessages((prev) =>
      prev.map((msg) =>
        msg.id === thinkingId
          ? { ...msg, content, loading, isHuman }
          : msg,
      ),
    )
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
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), SEND_TIMEOUT)

      const res = await apiFetch('/chat/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          message: text,
        }),
        signal: controller.signal,
      })
      clearTimeout(timeoutId)

      if (!res.ok) {
        if (res.status === 401) logout()
        updateAgentMsg(thinkingId, getHttpErrorMessage(res.status), false)
        return
      }

      const data = await res.json()

      if (data.status === 'human_chat' || humanMode) {
        loadingMsgIdRef.current = thinkingId
        updateAgentMsg(thinkingId, '消息已发送，等待客服回复...', true, true)
        if (!humanMode) {
          // 首次进入人工模式：重置基线后再 setHumanMode
          enterHumanMode()
        }
        return
      }

      setHumanMode(false)
      updateAgentMsg(thinkingId, resolveDisplayReply(data), false, false)

      if (data.ticket_offer) {
        setTicketOffer(data.ticket_offer)
      }
      if (data.human_offer) {
        setHumanOffer(data.human_offer)
      }
    } catch (err) {
      const isTimeout = err?.name === 'AbortError'
      updateAgentMsg(
        thinkingId,
        isTimeout
          ? '响应超时，请确认后端已重启后重试'
          : '网络异常，请检查后端是否启动',
        false,
      )
    } finally {
      setSending(false)
    }
  }

  const handleTicketConfirm = async (confirmed) => {
    setTicketConfirming(true)
    try {
      const res = await apiFetch('/chat/ticket-confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, confirmed }),
      })
      if (!res.ok) {
        let detail = '操作失败，请稍后重试'
        try {
          const err = await res.json()
          detail = err.detail || err.message || detail
        } catch {}
        setTicketOffer(null)
        setMessages((prev) => [
          ...prev,
          { id: Date.now(), role: 'agent', content: detail },
        ])
        return
      }
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

  const handleHumanConfirm = async (confirmed) => {
    setHumanConfirming(true)
    try {
      const res = await apiFetch('/chat/human-confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, confirmed }),
      })
      if (!res.ok) {
        let detail = '操作失败，请稍后重试'
        try {
          const err = await res.json()
          detail = err.detail || err.message || detail
        } catch {}
        setHumanOffer(null)
        setMessages((prev) => [
          ...prev,
          { id: Date.now(), role: 'agent', content: detail },
        ])
        return
      }
      const data = await res.json()
      setHumanOffer(null)

      if (confirmed && data.status === 'entered') {
        const enterMsg = '已为您转接人工客服，请稍候，客服将尽快回复您。'
        setMessages((prev) => [
          ...prev,
          { id: Date.now(), role: 'agent', content: enterMsg, isHuman: true },
        ])
        // 设置基线后进入人工模式，防止把已有历史当新消息重复展示
        await enterHumanMode()
        return
      }

      const resultMsg =
        confirmed
          ? '转人工失败，请稍后重试'
          : '好的，已取消转人工。如需帮助随时告知。'

      setMessages((prev) => [
        ...prev,
        { id: Date.now(), role: 'agent', content: resultMsg },
      ])
    } catch {
      setHumanOffer(null)
      setMessages((prev) => [
        ...prev,
        { id: Date.now(), role: 'agent', content: '操作失败，请稍后重试' },
      ])
    } finally {
      setHumanConfirming(false)
    }
  }

  const getAvatar = (msg) => {
    if (msg.role === 'user') return '👤'
    if (msg.isHuman) return '🧑‍💼'
    return '🤖'
  }

  const getSenderLabel = (msg) => {
    if (msg.role === 'user') return '我'
    if (msg.isHuman) return '人工客服'
    return 'AI 助手'
  }

  return (
    <div className="chat-page">
      <Card
        className="chat-card"
        title={
          <span>
            游戏客服助手
            {player?.nickname && (
              <span className="chat-player-label">
                {player.nickname} · {player.uid}
              </span>
            )}
            {humanMode && (
              <Tag color="orange" className="chat-status-tag">
                人工客服接待中
              </Tag>
            )}
          </span>
        }
        extra={
          <Button size="small" onClick={() => setProfileOpen(true)}>
            查看账号
          </Button>
        }
      >
        <div className="message-list">
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`message-item ${msg.role === 'user' ? 'user' : 'agent'}`}
            >
              <div
                className={`message-avatar ${msg.isHuman ? 'human' : ''}`}
              >
                {getAvatar(msg)}
              </div>
              <div className="message-bubble-wrap">
                <span className="message-sender">{getSenderLabel(msg)}</span>
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
            </div>
          ))}
          {humanOffer && (
            <div className="message-item agent">
              <div className="message-avatar">🤖</div>
              <div className="message-bubble-wrap">
                <span className="message-sender">AI 助手</span>
                <div className="message-bubble ticket-offer">
                  <div style={{ marginBottom: 8 }}>
                    <strong>{humanOffer.display_text || '是否为你转人工？'}</strong>
                  </div>
                  <div className="offer-actions">
                    <Button
                      type="primary"
                      size="small"
                      loading={humanConfirming}
                      onClick={() => handleHumanConfirm(true)}
                    >
                      是
                    </Button>
                    <Button
                      size="small"
                      disabled={humanConfirming}
                      onClick={() => handleHumanConfirm(false)}
                    >
                      否
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          )}
          {ticketOffer && (
            <div className="message-item agent">
              <div className="message-avatar">🤖</div>
              <div className="message-bubble-wrap">
                <span className="message-sender">AI 助手</span>
                <div className="message-bubble ticket-offer">
                  <div style={{ marginBottom: 8 }}>
                    <strong>{ticketOffer.display_text || '是否为您生成工单？'}</strong>
                  </div>
                  <div className="offer-actions">
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
            </div>
          )}
          <div ref={listEndRef} />
        </div>

        <div className="input-area">
          <Input
            value={input}
            placeholder={
              humanMode ? '继续向人工客服描述问题...' : '请输入问题，按 Enter 发送'
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
      <Drawer
        title="当前账号"
        placement="right"
        width={360}
        open={profileOpen}
        onClose={() => setProfileOpen(false)}
      >
        <Spin spinning={profileLoading}>
          <PlayerProfileDesc player={profile || player} />
          {(profile || player) && (
            <p className="chat-profile-hint">{scenarioOf(profile || player)}</p>
          )}
        </Spin>
      </Drawer>
    </div>
  )
}

export default ChatPage
