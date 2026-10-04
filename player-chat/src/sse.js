export class StreamError extends Error {
  constructor(event) {
    super(event.message || '回复未完成')
    this.code = event.code || 'error'
    this.retryAfter = event.retry_after || null
    this.partial = Boolean(event.partial)
  }
}

// 以 ":" 开头的心跳注释行没有 data 字段，会被直接忽略。
export async function consumeEvents(response, onEvent) {
  if (!response.body) throw new Error('流式响应不可用')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let terminal = false
  const dispatch = (block) => {
    const data = block.split(/\r?\n/).filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n')
    if (!data) return
    const event = JSON.parse(data)
    if (event.type === 'error') throw new StreamError(event)
    if (event.type === 'done') terminal = true
    onEvent(event)
  }
  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      let separator
      while ((separator = /\r?\n\r?\n/.exec(buffer))) {
        dispatch(buffer.slice(0, separator.index))
        buffer = buffer.slice(separator.index + separator[0].length)
      }
      if (done) break
    }
    if (buffer.trim()) dispatch(buffer)
    if (!terminal) throw new Error('连接中断，回复未完成')
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}
