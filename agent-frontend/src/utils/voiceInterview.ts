/**
 * RTC 语音面试纯工具：字幕 TLV 解析、字幕增量合并、qa_object 构建。
 *
 * 字幕通过 RTC 房间二进制消息下发，协议为 TLV：
 *   4 字节 ASCII 消息类型（"subv"） + 4 字节大端负载长度 + UTF-8 JSON 负载。
 * 本文件不依赖组件与请求层，便于页面组件保持简洁。
 */

import type { VoiceQaItem, VoiceRoom } from '@/types/chat'

/** 字幕消息类型 */
const SUBTITLE_MESSAGE_TYPE = 'subv'
/** TLV 头部：4 字节类型 + 4 字节长度 */
const TLV_HEADER_BYTES = 8

export type VoiceSpeaker = 'me' | 'ai'

/** 单条字幕（后端 JSON 负载中的一项） */
export interface VoiceSubtitleItem {
  userId: string
  text: string
  /** AI 字幕的句子完成标记 */
  definite: boolean
  /** 用户字幕的段落完成标记 */
  paragraph: boolean
}

export interface VoiceSubtitleLine {
  id: number
  speaker: VoiceSpeaker
  text: string
}

/** 字幕合并状态：已完成的行 + 正在识别的半句 */
export interface VoiceSubtitleState {
  lines: VoiceSubtitleLine[]
  partial: Record<VoiceSpeaker, string>
  nextId: number
}

export function createSubtitleState(): VoiceSubtitleState {
  return {
    lines: [],
    partial: { me: '', ai: '' },
    nextId: 1,
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function toBoolean(value: unknown): boolean {
  return value === true || value === 1
}

/** 解析 TLV 头部；非 subv 或长度异常返回 null */
export function decodeSubtitleTlv(
  buffer: ArrayBuffer,
): { type: string; value: string } | null {
  if (buffer.byteLength < TLV_HEADER_BYTES) return null

  const typeBytes = new Uint8Array(buffer, 0, 4)
  let type = ''
  for (let i = 0; i < typeBytes.length; i += 1) {
    type += String.fromCharCode(typeBytes[i])
  }
  type = type.replace(/\0/g, '')

  const length = new DataView(buffer, 4, 4).getUint32(0)
  if (length <= 0 || TLV_HEADER_BYTES + length > buffer.byteLength) return null

  const value = new TextDecoder().decode(
    new Uint8Array(buffer, TLV_HEADER_BYTES, length),
  )
  return { type, value }
}

function toSubtitleItem(raw: unknown): VoiceSubtitleItem | null {
  if (!isRecord(raw)) return null

  const rawUserId = raw.userId ?? raw.user_id
  const userId =
    typeof rawUserId === 'string'
      ? rawUserId
      : typeof rawUserId === 'number'
        ? String(rawUserId)
        : ''
  const text = typeof raw.text === 'string' ? raw.text : ''
  if (!userId || !text) return null

  return {
    userId,
    text,
    definite: toBoolean(raw.definite),
    paragraph: toBoolean(raw.paragraph),
  }
}

/**
 * 解析房间二进制消息为字幕数组。
 * 负载形如 `{ data: [{ userId, text, definite, paragraph }] }`，
 * 也兼容把单个字幕对象直接放在根节点的情况。
 */
export function parseSubtitleMessage(buffer: ArrayBuffer): VoiceSubtitleItem[] {
  const tlv = decodeSubtitleTlv(buffer)
  if (!tlv || tlv.type !== SUBTITLE_MESSAGE_TYPE) return []

  let payload: unknown
  try {
    payload = JSON.parse(tlv.value)
  } catch {
    return []
  }

  const rawData = isRecord(payload) ? payload.data : undefined
  const rawList = Array.isArray(rawData)
    ? rawData
    : isRecord(rawData)
      ? [rawData]
      : [payload]

  return rawList
    .map(toSubtitleItem)
    .filter((item): item is VoiceSubtitleItem => item !== null)
}

/** 按后端返回的 user_id / bot_id 判定说话人，未知用户忽略 */
export function resolveSpeaker(
  userId: string,
  selfUserId: string,
  botId: string,
): VoiceSpeaker | null {
  if (userId === botId) return 'ai'
  if (userId === selfUserId) return 'me'
  return null
}

/** AI 字幕以 definite 判断句子结束，用户字幕以 paragraph 判断段落结束 */
function isCompleted(speaker: VoiceSpeaker, item: VoiceSubtitleItem): boolean {
  return speaker === 'ai' ? item.definite : item.paragraph
}

/**
 * 合并一批字幕：未完成的半句覆盖当前 partial，完成的句子追加为正式行。
 * 返回新状态，避免直接改动响应式对象造成时间旅行问题。
 */
export function applySubtitleItems(
  state: VoiceSubtitleState,
  items: VoiceSubtitleItem[],
  selfUserId: string,
  botId: string,
): VoiceSubtitleState {
  const next: VoiceSubtitleState = {
    lines: state.lines.slice(),
    partial: { ...state.partial },
    nextId: state.nextId,
  }

  for (const item of items) {
    const speaker = resolveSpeaker(item.userId, selfUserId, botId)
    if (!speaker) continue

    const text = item.text.trim()
    if (!text) continue

    // 同一句的增量通常是「整句替换」：保留更长的一版，避免文本回退
    const current = next.partial[speaker]
    const merged = text.startsWith(current)
      ? text
      : current.startsWith(text)
        ? current
        : text

    if (!isCompleted(speaker, item)) {
      next.partial[speaker] = merged
      continue
    }

    const last = next.lines[next.lines.length - 1]
    // 同句可能同时收到未完成与完成事件，去重避免重复追加
    if (!(last && last.speaker === speaker && last.text === merged)) {
      next.lines.push({ id: next.nextId, speaker, text: merged })
      next.nextId += 1
    }
    next.partial[speaker] = ''
  }

  return next
}

/**
 * 把字幕整理为「问题 + 回答」对：
 * 连续 AI 句子合并为问题，连续用户句子合并为回答；用户的回答结束一轮问答。
 * 未完成的半句也一并纳入，保证挂断时已说出的内容不丢失。
 */
export function buildQaObject(state: VoiceSubtitleState): VoiceQaItem[] {
  const lines = state.lines.slice()
  if (state.partial.ai.trim()) {
    lines.push({ id: -1, speaker: 'ai', text: state.partial.ai })
  }
  if (state.partial.me.trim()) {
    lines.push({ id: -2, speaker: 'me', text: state.partial.me })
  }

  const result: VoiceQaItem[] = []
  let question = ''
  let answer = ''

  const flush = (): void => {
    const q = question.trim()
    const a = answer.trim()
    if (!q && !a) return
    result.push({
      id: result.length + 1,
      question: q,
      answer: a,
      created_at: Math.floor(Date.now() / 1000),
    })
    question = ''
    answer = ''
  }

  for (const line of lines) {
    if (line.speaker === 'ai') {
      // 用户已作答后再出现 AI 提问，说明上一轮结束
      if (answer) flush()
      question += line.text.trim()
    } else {
      answer += line.text.trim()
    }
  }
  flush()

  return result
}

function toText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

/**
 * RTC 参数归一化：兼容后端 bot_id / bot_user_id、rtc_token / token 两种命名。
 * 关键参数缺失时返回 null，避免用残缺参数进入语音页。
 * 同时用于 history state 的运行时校验（刷新页面后 state 仍存在）。
 */
export function normalizeVoiceRoom(raw: unknown): VoiceRoom | null {
  if (!isRecord(raw)) return null

  const appId = toText(raw.app_id) || toText(raw.appId)
  const roomId = toText(raw.room_id) || toText(raw.roomId)
  const userId = toText(raw.user_id) || toText(raw.userId)
  const botId =
    toText(raw.bot_id) || toText(raw.botId) || toText(raw.bot_user_id)
  const rtcToken =
    toText(raw.rtc_token) || toText(raw.rtcToken) || toText(raw.token)
  if (!appId || !roomId || !userId || !botId || !rtcToken) return null

  const taskId = toText(raw.task_id) || toText(raw.taskId) || roomId
  const expireAt =
    typeof raw.expire_at === 'number'
      ? raw.expire_at
      : typeof raw.expireAt === 'number'
        ? raw.expireAt
        : null

  return {
    appId,
    roomId,
    userId,
    botId,
    rtcToken,
    taskId,
    expireAt,
    started: raw.started === true,
  }
}

/** 秒数 → mm:ss */
export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const mm = String(Math.floor(total / 60)).padStart(2, '0')
  const ss = String(total % 60).padStart(2, '0')
  return `${mm}:${ss}`
}
