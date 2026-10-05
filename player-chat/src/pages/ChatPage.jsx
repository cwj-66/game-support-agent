import { demoFetch } from '../access'
import { useState, useRef, useEffect } from 'react'
import { Input, Button, Card, Drawer, Spin, Tag, message } from 'antd'
import { UserOutlined, PoweroffOutlined } from '@ant-design/icons'
import { API_BASE } from '../config'
import { apiFetch, newRequestId, readError } from '../api'
import { consumeEvents } from '../sse'
import { useAuth } from '../auth'
import { PlayerProfileDesc, scenarioOf } from '../PlayerProfile'
import { ExamplePanel, TracePanel } from '../components/DemoPanels'
import './ChatPage.css'

const POLL_INTERVAL = 3000
// 兜底超时：服务端排队上限 60s + 执行上限 90s，之外再留余量；正常情况由服务端先给出明确结果
const SEND_TIMEOUT = 180 * 1000

/** 根据 HTTP 状态码返回可读错误信息 */
const getHttpErrorMessage = (status) => {
  if (status === 401) return '登录已过期，请到「测试账号」页重新选择账号'
  if (status === 403) return '无权访问该会话，请刷新页面重试'
  if (status === 409) return '上一条消息仍在处理，请等待完成后再操作。'
  if (status === 429) return '提问太频繁，请稍后再试。'
  if (status === 503) return '服务繁忙，请稍后再试。'
  if (status >= 500) return '服务端错误，请稍后重试'
  return '请求失败，请检查后端是否启动'
}

/** 失败后右侧状态：区分服务繁忙、排队超时、频率限制等真实原因 */
const traceErrorFor = (code, status) => {
  if (code === 'quota_exhausted') return '对话体验额度已用完。'
  if (code === 'server_busy' || code === 'capacity_unavailable') return '服务繁忙，本轮未进入处理。'
  if (code === 'queue_timeout') return '排队等待超时，本轮未开始处理。'
  if (code === 'rate_limited' || status === 429) return '提问太频繁，本轮未提交。'
  if (code === 'session_busy' || status === 409) return '上一条消息仍在处理。'
  if (code === 'agent_timeout') return '本轮处理超时，已停止。'
  if (code === 'turn_cancelled') return '本轮已停止。'
  if (code === 'stream_interrupted') return '回复中断，未收到完整执行记录。'
  return '本轮未完成。'
}

const newSessionId = (uid) => `${uid}_${newRequestId()}`

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

// Render the model's emphasis as React text nodes, never as raw HTML.
function ReplyText({ text }) {
  return String(text).split(/(\*\*[^*]+\*\*)/g).map((part, index) =>
    part.startsWith('**') && part.endsWith('**')
      ? <strong key={index}>{part.slice(2, -2)}</strong>
      : part,
  )
}

function readConversation(uid) {
  try { return JSON.parse(sessionStorage.getItem(`demo-chat:${uid}`)) || {} }
  catch { return {} }
}

function ChatPage() {
  const { player, logout } = useAuth()
  const [saved] = useState(() => readConversation(player.uid))
  const [sessionId, setSessionId] = useState(() => saved.sessionId || newSessionId(player.uid))
  const [messages, setMessages] = useState(() => saved.messages?.length ? saved.messages.map((m) => m.loading ? { ...m, loading: false, content: m.content || '页面刷新中断了这次回复，请重新发送问题。' } : m) : INITIAL_MESSAGES)
  const [input, setInput] = useState(saved.input || '')
  const [sending, setSending] = useState(false)
  const [ending, setEnding] = useState(false)
  const [trace, setTrace] = useState(saved.trace || null)
  const [traceError, setTraceError] = useState('')
  const [startedAt, setStartedAt] = useState(0)
  // idle / connecting / queued / running：只有服务端确认入场后才进入 running
  const [phase, setPhase] = useState('idle')
  const [queuePosition, setQueuePosition] = useState(null)
  const [humanMode, setHumanMode] = useState(saved.humanMode || false)
  const [ticketOffer, setTicketOffer] = useState(saved.ticketOffer || null)
  const [humanOffer, setHumanOffer] = useState(saved.humanOffer || null)
  const [ticketConfirming, setTicketConfirming] = useState(false)
  const [humanConfirming, setHumanConfirming] = useState(false)
  const [profileOpen, setProfileOpen] = useState(false)
  const [profile, setProfile] = useState(player)
  const [profileLoading, setProfileLoading] = useState(false)

  // 已消费的历史消息总数，用于增量拉取（包含 user + assistant 全量）
  const seenHistoryCountRef = useRef(saved.seenHistoryCount || 0)
  // 当前等待中的"思考气泡" ID，轮询到回复后用来替换
  const loadingMsgIdRef = useRef(null)
  const listEndRef = useRef(null)
  const controllerRef = useRef(null)
  // 上一次未完成的提交：玩家原样重发时沿用同一个请求 ID，服务端若已完成会直接返回原结果
  const lastFailedRef = useRef(null)

  useEffect(() => () => controllerRef.current?.abort(), [])

  useEffect(() => {
    try {
      sessionStorage.setItem(`demo-chat:${player.uid}`, JSON.stringify({
        sessionId, messages, input, trace, humanMode, ticketOffer, humanOffer,
        seenHistoryCount: seenHistoryCountRef.current,
      }))
    } catch { /* Conversation remains usable if browser storage is unavailable. */ }
  }, [player.uid, sessionId, messages, input, trace, humanMode, ticketOffer, humanOffer])

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
    let cancelled = false

    const poll = async () => {
      try {
        const res = await apiFetch(`/chat/history/${sessionId}`)
        if (!res.ok) return
        const data = await res.json()
        if (cancelled) return
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
          if (cancelled) return
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
    return () => { cancelled = true; clearInterval(timer) }
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
        const res = await demoFetch(`${API_BASE}/demo/players`)
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

    const requestId = lastFailedRef.current?.text === text && lastFailedRef.current.sessionId === sessionId
      ? lastFailedRef.current.requestId
      : newRequestId()
    lastFailedRef.current = null
    const userMsg = { id: Date.now(), role: 'user', content: text }
    const thinkingId = Date.now() + 1
    const waitingText = humanMode ? '等待客服回复...' : '正在提交...'
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
    setPhase('connecting')
    setQueuePosition(null)
    setStartedAt(Date.now())
    setTrace(null)
    setTraceError('')
    const controller = new AbortController()
    controllerRef.current = controller
    let timedOut = false
    const timeoutId = setTimeout(() => { timedOut = true; controller.abort() }, SEND_TIMEOUT)
    let streamedText = ''
    // 失败且尚未输出任何回复时，把问题放回输入框，方便玩家原样重试
    const allowRetry = () => {
      if (streamedText) return
      lastFailedRef.current = { text, requestId, sessionId }
      setInput((current) => current || text)
    }

    try {
      const res = await apiFetch('/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          message: text,
          client_request_id: requestId,
        }),
        signal: controller.signal,
      })
      if (!res.ok) {
        if (res.status === 401) logout()
        const err = await readError(res, getHttpErrorMessage(res.status))
        setTraceError(traceErrorFor(err.code, res.status))
        updateAgentMsg(thinkingId, err.message, false)
        if (res.status !== 401 && res.status !== 403) allowRetry()
        return
      }

      let data = null
      await consumeEvents(res, (event) => {
        if (event.type === 'queue') {
          if (event.status === 'queued') {
            setPhase('queued')
            setQueuePosition(Number.isInteger(event.position) ? event.position : null)
            updateAgentMsg(thinkingId, Number.isInteger(event.position) ? `排队中，前面还有 ${event.position - 1} 个问题...` : '排队中...', true)
          } else if (event.status === 'admitted') {
            setPhase('running')
            setQueuePosition(null)
            updateAgentMsg(thinkingId, '正在处理...', true)
          }
        } else if (event.type === 'delta') {
          streamedText += event.text
          updateAgentMsg(thinkingId, streamedText, false)
        } else if (event.type === 'stage') {
          setTrace((prev) => {
            const detail = prev?.execution_trace || { stages: [], tools: [], source_count: 0 }
            const stages = [...detail.stages]
            if (event.status === 'running') stages.push({ ...event })
            else {
              const index = stages.findLastIndex((step) => step.name === event.name && step.status === 'running')
              if (index !== -1) stages[index] = { ...event }
            }
            return { ...prev, execution_trace: { ...detail, stages } }
          })
        } else if (event.type === 'tool') {
          setTrace((prev) => {
            const detail = prev?.execution_trace || { stages: [], tools: [], source_count: 0 }
            const tools = [...detail.tools]
            const index = tools.findIndex((tool) => tool.id === event.id)
            if (index === -1) tools.push({ ...event })
            else tools[index] = { ...event }
            return { ...prev, execution_trace: { ...detail, tools } }
          })
        } else if (event.type === 'done') data = event
      })
      if (!data) throw new Error('未收到完整回复')
      setTrace(data.metadata || null)

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
      const aborted = err?.name === 'AbortError'
      if (aborted && !timedOut) {
        setTraceError('本轮已停止。')
        updateAgentMsg(thinkingId, streamedText || '已停止本次回复。', false)
      } else if (aborted) {
        setTraceError('等待时间过长，本轮未完成。')
        updateAgentMsg(thinkingId, '等待时间过长，请稍后重试。', false)
        allowRetry()
      } else {
        setTraceError(traceErrorFor(err?.code))
        updateAgentMsg(
          thinkingId,
          err?.partial ? `${streamedText}\n\n（${err.message}）` : err?.message || '网络异常，请稍后重试',
          false,
        )
        if (err?.code !== 'turn_cancelled') allowRetry()
      }
    } finally {
      clearTimeout(timeoutId)
      if (controllerRef.current === controller) controllerRef.current = null
      setSending(false)
      setPhase('idle')
      setQueuePosition(null)
    }
  }

  /** 停止当前提交：断开连接后服务端会取消执行并释放排队/执行名额 */
  const stopSending = () => controllerRef.current?.abort()

  const endConversation = async () => {
    if (ending || ticketConfirming || humanConfirming) return
    setEnding(true)
    controllerRef.current?.abort()
    try {
      const response = await apiFetch('/chat/end', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId }),
      })
      if (!response.ok) throw new Error((await readError(response, getHttpErrorMessage(response.status))).message)
      lastFailedRef.current = null
      setSessionId(newSessionId(player.uid))
      setMessages(INITIAL_MESSAGES); setInput(''); setTrace(null); setTraceError('')
      setStartedAt(0); setHumanMode(false); setTicketOffer(null); setHumanOffer(null)
      seenHistoryCountRef.current = 0; loadingMsgIdRef.current = null
      message.success('已结束上一段对话，新的对话已开启。工单继续保留。')
    } catch (error) { message.error(error.message || '结束对话失败，请重试。') }
    finally { setEnding(false) }
  }

  // 同一个确认卡片的重试沿用同一请求 ID，服务端据此返回首次结果，不会重复建单或重复转人工
  const confirmIdsRef = useRef({})
  const confirmRequestId = (kind, offer, confirmed) => {
    const key = `${kind}:${sessionId}:${offer?.summary || ''}:${confirmed}`
    confirmIdsRef.current[key] ||= newRequestId()
    return confirmIdsRef.current[key]
  }

  const handleTicketConfirm = async (confirmed) => {
    if (ticketConfirming) return
    setTicketConfirming(true)
    try {
      const res = await apiFetch('/chat/ticket-confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, confirmed, client_request_id: confirmRequestId('ticket', ticketOffer, confirmed) }),
      })
      if (!res.ok) {
        const err = await readError(res, '操作失败，请稍后重试')
        if (res.status === 409 || res.status === 429 || res.status === 503) {
          message.warning(err.message)
          return
        }
        const detail = err.message
        setTicketOffer(null)
        setMessages((prev) => [
          ...prev,
          { id: Date.now(), role: 'agent', content: detail },
        ])
        return
      }
      const data = await res.json()
      // 建单失败时服务端已恢复待确认状态，保留按钮供玩家重试
      if (data.status !== 'failed') setTicketOffer(null)

      const resultMsg = confirmed
        ? data.status === 'created'
          ? `✅ 工单已创建！工单号：${data.ticket_id}，预计处理时间：${data.estimated_response || '3-5个工作日'}`
          : '工单创建失败，可再次点击「是」重试'
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
    if (humanConfirming) return
    setHumanConfirming(true)
    try {
      const res = await apiFetch('/chat/human-confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, confirmed, client_request_id: confirmRequestId('human', humanOffer, confirmed) }),
      })
      if (!res.ok) {
        const err = await readError(res, '操作失败，请稍后重试')
        if (res.status === 409 || res.status === 429 || res.status === 503) {
          message.warning(err.message)
          return
        }
        const detail = err.message
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
    if (msg.role === 'user') return '我'
    if (msg.isHuman) return '人工'
    return '✳'
  }

  const getSenderLabel = (msg) => {
    if (msg.role === 'user') return '我'
    if (msg.isHuman) return '人工客服'
    return 'AI 助手'
  }

  return (
    <div className="chat-page">
      <ExamplePanel uid={player.uid} onUse={setInput} />
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
          <div className="chat-header-actions">
            <Button className="profile-button" icon={<UserOutlined aria-hidden="true" />} size="small" onClick={() => setProfileOpen(true)}>查看账号</Button>
            <Button className="end-conversation-button" icon={<PoweroffOutlined aria-hidden="true" />} size="small" onClick={endConversation} loading={ending}
              disabled={ticketConfirming || humanConfirming}>结束对话</Button>
          </div>
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
                    <ReplyText text={msg.content} />
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
          <Input.TextArea
            autoSize={{ minRows: 1, maxRows: 4 }}
            value={input}
            placeholder={
              humanMode ? '继续向人工客服描述问题...' : '请输入问题，按 Enter 发送'
            }
            onChange={(e) => setInput(e.target.value)}
            onPressEnter={(e) => { if (!e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); handleSend() } }}
          />
          {sending ? (
            <Button danger onClick={stopSending} disabled={ending}>停止</Button>
          ) : (
            <Button type="primary" onClick={handleSend} disabled={ending}>发送</Button>
          )}
        </div>
      </Card>
      <TracePanel trace={trace} sending={sending} phase={phase} queuePosition={queuePosition}
        startedAt={startedAt} error={traceError} humanMode={humanMode} />
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
