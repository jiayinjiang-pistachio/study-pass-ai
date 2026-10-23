/**
 * 通用 SSE 响应解析工具（fetch + ReadableStream）。
 *
 * EventSource 只支持 GET，无法携带 POST 请求体与 Authorization 头，
 * 因此流式对话统一用 fetch 读取响应体，再按 SSE 规范切分事件。
 * 本文件只负责协议解析，不关心业务事件名与数据格式。
 */

export interface SseMessage {
  /** 事件名；未声明 event 字段时按规范回退为 message */
  event: string
  /** 多行 data 按规范以换行拼接 */
  data: string
}

function parseBlock(block: string): SseMessage | null {
  let event = 'message'
  const dataLines: string[] = []

  for (const line of block.split('\n')) {
    // 兼容 CRLF 换行
    const clean = line.endsWith('\r') ? line.slice(0, -1) : line
    if (!clean || clean.startsWith(':')) continue

    const colon = clean.indexOf(':')
    const field = colon === -1 ? clean : clean.slice(0, colon)
    let value = colon === -1 ? '' : clean.slice(colon + 1)
    // 规范：冒号后的单个空格仅是分隔符，不属于数据
    if (value.startsWith(' ')) value = value.slice(1)

    if (field === 'event') event = value
    else if (field === 'data') dataLines.push(value)
  }

  return dataLines.length ? { event, data: dataLines.join('\n') } : null
}

/** 持续读取响应体并按空行切分事件，遇到事件即回调。 */
export async function readSse(
  response: Response,
  onMessage: (message: SseMessage) => void,
): Promise<void> {
  const reader = response.body?.getReader()
  if (!reader) throw new Error('当前环境不支持流式响应')

  const decoder = new TextDecoder()
  let buffer = ''

  const flush = (chunk: string): void => {
    const message = parseBlock(chunk)
    if (message) onMessage(message)
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      // 事件分隔符统一成 LF；服务端用 \n\n，兼容其他实现的 CRLF
      buffer = buffer.replace(/\r\n/g, '\n')
      let boundary = buffer.indexOf('\n\n')
      while (boundary !== -1) {
        flush(buffer.slice(0, boundary))
        buffer = buffer.slice(boundary + 2)
        boundary = buffer.indexOf('\n\n')
      }
    }

    buffer = (buffer + decoder.decode()).replace(/\r\n/g, '\n')
    if (buffer.trim()) flush(buffer)
  } finally {
    reader.releaseLock()
  }
}
