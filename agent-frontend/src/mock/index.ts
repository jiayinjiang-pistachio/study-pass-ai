/**
 * 开发期 Mock：Mock.js 通过替换全局 XMLHttpRequest 拦截请求。
 * 请求层（src/api/request.ts）固定 axios adapter: 'xhr'，因此 Mock 对 axios 同样生效；
 * 若改用 axios 的 fetch 适配器，这里的拦截会失效。
 */
import Mock from 'mockjs'
import type { ChatMessage } from '@/types/chat'
import type { Conversation, ModuleKey } from '@/types/conversation'
import { createGreetingMessage, createSeed } from './data'
import './notes'

const Random = Mock.Random
const API_PREFIX = import.meta.env.VITE_API_PREFIX || '/api'

type ChatModuleKey = Extract<ModuleKey, 'study' | 'interview'>

const seed = createSeed()
const conversations: Conversation[] = seed.conversations
const messages: Record<string, ChatMessage[]> = seed.messages

function ok<T>(data: T): { code: number; message: string; data: T } {
  return { code: 200, message: 'ok', data }
}

function fail(message: string, code = 1): { code: number; message: string; data: null } {
  return { code, message, data: null }
}

function conversationIdFrom(url: string): string {
  return (
    url.match(/\/conversations\/([^/]+)\/messages$/)?.[1] ??
    url.match(/\/conversations\/([^/]+)$/)?.[1] ??
    ''
  )
}

function parseBody<T>(body: string | undefined): T {
  try {
    return JSON.parse(body || '{}') as T
  } catch {
    return {} as T
  }
}

function normalizeModule(value: unknown): ChatModuleKey {
  return value === 'study' ? 'study' : 'interview'
}

/** AI 回复池（Mock.Random 随机选取），按模块区分 */
const AI_REPLY_POOL: Record<ChatModuleKey, string[]> = {
  interview: [
    '回答得不错！我们继续下一个问题：请谈谈你对浏览器事件循环（Event Loop）的理解。',
    '思路清晰。那你能举例说明一下，在什么场景下需要做前端性能优化吗？',
    '很好。接下来这个问题：请解释一下 HTTP 缓存中的强缓存与协商缓存。',
    '不错的回答。请说说你在项目中是如何做状态管理和组件通信的？',
  ],
  study: [
    '理解得很到位。我们接着看下一个知识点：请说说 JavaScript 中 this 的指向规则有哪些？',
    '不错。那你能总结一下 Promise 的三种状态以及它们之间是如何转换的吗？',
    '很好。接下来我们一起梳理一下 HTTP 请求从发出到响应的完整过程。',
    '这个思路是对的。我们再深入一点：谈谈浏览器渲染流水线包含哪些阶段？',
  ],
}

function buildAiReply(module: ChatModuleKey): ChatMessage {
  return {
    id: Random.guid(),
    role: 'ai',
    content: Random.pick(AI_REPLY_POOL[module]) as string,
    createdAt: Date.now(),
    status: 'done',
  }
}

// 模拟网络延迟，便于观察 loading 态
Mock.setup({ timeout: '200-600' })

const conversationsUrl = new RegExp(`${API_PREFIX}/conversations$`)
const messagesUrl = new RegExp(`${API_PREFIX}/conversations/([^/]+)/messages$`)
const conversationUrl = new RegExp(`${API_PREFIX}/conversations/([^/]+)$`)

// 会话列表（全量，按模块由前端过滤）
Mock.mock(conversationsUrl, 'get', () => ok(conversations))

// 新建会话
Mock.mock(conversationsUrl, 'post', (options) => {
  const { module } = parseBody<{ module?: string }>(options.body)
  const moduleKey = normalizeModule(module)
  const conversation: Conversation = {
    id: Random.guid(),
    title: moduleKey === 'study' ? '新学习' : '新会话',
    icon: Random.pick(['💬', '🧭', '📝']) as string,
    module: moduleKey,
    updatedAt: Date.now(),
  }
  conversations.unshift(conversation)
  messages[conversation.id] = [createGreetingMessage(moduleKey)]
  return ok(conversation)
})

// 会话消息列表
Mock.mock(messagesUrl, 'get', (options) => {
  const id = conversationIdFrom(options.url)
  return ok(messages[id] ?? [])
})

// 提交回答，返回 AI 回复
Mock.mock(messagesUrl, 'post', (options) => {
  const id = conversationIdFrom(options.url)
  const { content } = parseBody<{ content?: string }>(options.body)
  const list = messages[id] ?? (messages[id] = [])
  list.push({
    id: Random.guid(),
    role: 'user',
    content: content ?? '',
    createdAt: Date.now(),
    status: 'done',
  })
  const conversation = conversations.find((item) => item.id === id)
  const reply = buildAiReply(normalizeModule(conversation?.module))
  list.push(reply)
  return ok(reply)
})

// 重命名会话
Mock.mock(conversationUrl, 'put', (options) => {
  const id = conversationIdFrom(options.url)
  const target = conversations.find((item) => item.id === id)
  if (!target) return fail('会话不存在', 404)
  const { title } = parseBody<{ title?: string }>(options.body)
  if (title) target.title = title
  target.updatedAt = Date.now()
  return ok(target)
})

// 删除会话
Mock.mock(conversationUrl, 'delete', (options) => {
  const id = conversationIdFrom(options.url)
  const index = conversations.findIndex((item) => item.id === id)
  if (index === -1) return fail('会话不存在', 404)
  conversations.splice(index, 1)
  delete messages[id]
  return ok(null)
})
