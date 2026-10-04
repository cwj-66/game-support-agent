import { useEffect, useState } from 'react'
import { message } from 'antd'
import { DEMO_SCENARIOS } from '../demoScenarios'
import knowledgeQuestions from '../knowledgeExamples.json'
import multiTurnExamples from '../multiTurnExamples.json'
import handoffExamples from '../handoffExamples.json'

export function ExamplePanel({ uid, onUse }) {
  const scenario = DEMO_SCENARIOS[uid] || DEMO_SCENARIOS['10001']
  const copy = async (text) => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text)
      } else {
        const area = document.createElement('textarea')
        area.value = text
        area.style.cssText = 'position:fixed;opacity:0;top:0;left:0'
        document.body.appendChild(area)
        area.select()
        const copied = document.execCommand('copy')
        area.remove()
        if (!copied) throw new Error('copy unavailable')
      }
      message.success('已复制问题')
    } catch {
      onUse(text)
      message.info('问题已填入输入框，可直接发送或手动复制')
    }
  }
  const group = (title, questions) => <section className="example-group">
    <h3>{title}</h3>
    {questions.map((q) => <div className="example-item" key={q}>
      <button className="example-question" onClick={() => onUse(q)}>{q}<span aria-hidden="true">↗</span></button>
      <button className="copy-question" onClick={() => copy(q)} aria-label={`复制：${q}`}>复制</button>
    </div>)}
  </section>
  return <aside className="demo-panel example-panel">
    <div className="panel-eyebrow">开始探索 / EXPLORE</div>
    <h2>试着这样问</h2>
    <p className="panel-description">点击问题填入对话，或复制后自由编辑。</p>
    <div className="scenario-chip"><span className="status-dot" />{scenario.title}<small>UID {uid}</small></div>
    {group('当前账号', [...scenario.questions, '我上次那个问题解决没有？'])}
    {group('知识库问答', knowledgeQuestions.map((q) => q.question))}
    {group('工单与人工接待', handoffExamples.filter((q) => q.uid === uid).map((q) => q.question))}
    <section className="example-group multi-turn-examples">
      <h3>多轮对话</h3>
      <p className="panel-description">按顺序发送，等上一轮回复后再追问。</p>
      {multiTurnExamples.filter((q) => q.allAccounts || q.uid === uid).map((example) => <div className="multi-turn-case" key={example.id}>
        <h4>{example.title}</h4>
        {example.questions.map((q, index) => <div className="example-item" key={q}>
          <button className="example-question" onClick={() => onUse(q)}><span className="turn-number">{index + 1}</span>{q}</button>
          <button className="copy-question" onClick={() => copy(q)} aria-label={`复制：${q}`}>复制</button>
        </div>)}
      </div>)}
    </section>
    <p className="panel-footnote">知识库示例选自项目评测集，所有账号均可体验。</p>
  </aside>
}

const PHASE_LABELS = { connecting: '提交中', queued: '排队中', running: '正在处理' }

/** 等待提示：排队位置只在服务端给出时展示；入场前不展示任何执行步骤 */
function waitingText(phase, queuePosition) {
  if (phase === 'queued') return queuePosition ? `排队中，当前第 ${queuePosition} 位。` : '排队中，等待空闲名额。'
  if (phase === 'running') return '已开始处理，等待第一个执行步骤…'
  return '正在连接助手…'
}

export function TracePanel({ trace, sending, phase = 'idle', queuePosition = null, startedAt, error, humanMode }) {
  const [clock, setClock] = useState(0)
  useEffect(() => {
    if (!sending) return undefined
    const timer = setInterval(() => setClock(Date.now()), 200)
    return () => clearInterval(timer)
  }, [sending])
  const elapsed = sending ? Math.max(0, (clock - startedAt) / 1000) : (trace?.execution_time_ms || 0) / 1000
  const detail = trace?.execution_trace
  const statusLabel = sending ? PHASE_LABELS[phase] || '运行中' : error ? '未完成' : trace ? '已完成' : '待开始'
  return <aside className="demo-panel trace-panel" aria-label="执行记录">
    <div className="panel-eyebrow">执行记录 / ACTIVITY</div>
    <div className="trace-title"><h2>这次回复如何完成</h2><span className={`trace-status ${sending ? 'running' : ''}`}>{statusLabel}</span></div>
    <p className="panel-description">实时展示本轮执行步骤与工具调用。</p>
    {(sending || trace) && <div className="trace-metrics"><strong>{elapsed.toFixed(1)}<small> 秒</small></strong><span>{sending && phase !== 'running' ? '已等待' : '本轮耗时'}</span></div>}
    {error ? <div className="trace-empty">{error}</div> : detail ? <>
      <ol className="trace-steps">{detail.stages.map((step, i) => <li key={`${step.name}-${i}`}><span className={`step-dot ${step.status === 'running' ? 'activity-pulse' : ''}`}>{step.status === 'running' ? '·' : '✓'}</span><div>{step.label}<small>{step.name}{step.status === 'running' ? ' · 运行中' : step.duration_ms != null ? ` · ${(step.duration_ms / 1000).toFixed(1)}s` : ''}</small></div></li>)}</ol>
      <h3>工具调用 <span className="count-pill">{detail.tools.length}</span></h3>
      {detail.tools.length ? detail.tools.map((tool, i) => <div className="trace-tool" key={`${tool.name}-${i}`}><span>{tool.label}<small>{tool.name}</small></span><b className={tool.status === 'failed' ? 'failed' : ''}>{tool.status === 'failed' ? '失败' : tool.status === 'running' ? '运行中' : '完成'}</b></div>) : <p className="panel-description">本轮未调用外部工具。</p>}
      <div className="trace-sources">检索来源 <strong>{detail.source_count} 条</strong></div>
    </> : <div className="trace-empty"><span className="trace-symbol">◎</span>{sending ? waitingText(phase, queuePosition) : humanMode ? '当前由人工客服接待。' : '发送一个问题，查看助手的执行记录。'}</div>}
  </aside>
}
