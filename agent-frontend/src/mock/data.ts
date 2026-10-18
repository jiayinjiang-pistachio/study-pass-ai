import Mock from 'mockjs'
import type { ChatMessage } from '@/types/chat'
import type { Conversation } from '@/types/conversation'

const Random = Mock.Random

/** 会话标题/图标为业务固定值（对齐设计稿），id 与时间由 Mock.Random 生成 */
const CONVERSATION_SEEDS: Array<Pick<Conversation, 'title' | 'icon'>> = [
  { title: '前端技术面试准备', icon: '💻' },
  { title: '数据库优化策略', icon: '🗄️' },
  { title: '系统架构设计', icon: '🏗️' },
  { title: '云计算基础', icon: '☁️' },
  { title: '移动端开发要点', icon: '📱' },
  { title: '网络安全防护', icon: '🔒' },
  { title: '数据分析方法', icon: '📊' },
  { title: '机器学习入门', icon: '🤖' },
]

export const GREETING =
  '你好！我是学面通AI面试官，很高兴为你提供面试模拟服务。请告诉我你想练习哪个职位的面试？比如前端工程师、后端工程师或者产品经理等。'

function minutesAgo(minutes: number): number {
  return Date.now() - minutes * 60 * 1000
}

function message(role: ChatMessage['role'], content: string, createdAt: number): ChatMessage {
  return { id: Random.guid(), role, content, createdAt, status: 'done' }
}

/** 首个会话的完整面试对话（对齐设计稿内容） */
function createInterviewDialogue(): ChatMessage[] {
  return [
    message('ai', GREETING, minutesAgo(12)),
    message('user', '我想练习前端工程师的面试，主要关注JavaScript和React相关的知识点。', minutesAgo(11)),
    message('ai', '很好！我们来开始第一个问题：\n请解释一下JavaScript中的闭包是什么？它有什么应用场景？', minutesAgo(10)),
    message(
      'user',
      '闭包是指一个函数能够访问并"记住"其外部作用域中的变量，即使在其外部函数已经返回之后。主要应用场景包括数据封装、模块模式、以及创建私有变量等。',
      minutesAgo(9),
    ),
    message('ai', '回答得很好！接下来请解释一下React中的虚拟DOM是如何工作的，以及它如何提高性能？', minutesAgo(8)),
    message(
      'user',
      '虚拟DOM是React用来提升性能的关键技术。它是一个轻量级的JavaScript对象树，是对真实DOM的抽象表示。当组件状态发生变化时，React会创建一个新的虚拟DOM树，然后与之前的虚拟DOM树进行比较(diff算法)，找出最小的变化集，最后只更新真实DOM中需要改变的部分，从而减少昂贵的DOM操作。',
      minutesAgo(7),
    ),
    message('ai', '非常棒的解释！现在让我们深入一点：你能谈谈React Hooks的工作原理吗？特别是useState和useEffect？', minutesAgo(6)),
  ]
}

export interface MockSeed {
  conversations: Conversation[]
  messages: Record<string, ChatMessage[]>
}

export function createSeed(): MockSeed {
  const conversations: Conversation[] = CONVERSATION_SEEDS.map((seed, index) => ({
    id: Random.guid(),
    title: seed.title,
    icon: seed.icon,
    module: 'interview',
    updatedAt: minutesAgo(Random.integer(1, 30) + index * 40),
  }))

  const messages: Record<string, ChatMessage[]> = {}
  conversations.forEach((conversation, index) => {
    messages[conversation.id] =
      index === 0 ? createInterviewDialogue() : [message('ai', GREETING, conversation.updatedAt)]
  })

  return { conversations, messages }
}

/** 新建会话时的欢迎语 */
export function createGreetingMessage(): ChatMessage {
  return message('ai', GREETING, Date.now())
}
