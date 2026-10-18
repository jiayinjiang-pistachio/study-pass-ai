import Mock from 'mockjs'
import type { ChatMessage } from '@/types/chat'
import type { Conversation, ModuleKey } from '@/types/conversation'

const Random = Mock.Random

type ChatModuleKey = Extract<ModuleKey, 'study' | 'interview'>

/** 会话标题/图标为业务固定值（对齐设计稿），id 与时间由 Mock.Random 生成 */
const CONVERSATION_SEEDS: Record<ChatModuleKey, Array<Pick<Conversation, 'title' | 'icon'>>> = {
  interview: [
    { title: '前端技术面试准备', icon: '💻' },
    { title: '数据库优化策略', icon: '🗄️' },
    { title: '系统架构设计', icon: '🏗️' },
    { title: '云计算基础', icon: '☁️' },
    { title: '移动端开发要点', icon: '📱' },
    { title: '网络安全防护', icon: '🔒' },
    { title: '数据分析方法', icon: '📊' },
    { title: '机器学习入门', icon: '🤖' },
  ],
  study: [
    { title: 'JavaScript 核心知识精讲', icon: '📘' },
    { title: 'React 组件化实践', icon: '⚛️' },
    { title: '算法与数据结构', icon: '🧮' },
    { title: '计算机网络基础', icon: '🌐' },
    { title: '操作系统原理', icon: '🖥️' },
    { title: '数据库系统概论', icon: '🗃️' },
  ],
}

export const GREETINGS: Record<ChatModuleKey, string> = {
  interview:
    '你好！我是学面通AI面试官，很高兴为你提供面试模拟服务。请告诉我你想练习哪个职位的面试？比如前端工程师、后端工程师或者产品经理等。',
  study:
    '你好！我是学面通AI学习助手，很高兴为你提供学习辅导服务。请告诉我你想学习哪个方向？比如前端开发、后端架构或者数据分析等。',
}

function minutesAgo(minutes: number): number {
  return Date.now() - minutes * 60 * 1000
}

function message(role: ChatMessage['role'], content: string, createdAt: number): ChatMessage {
  return { id: Random.guid(), role, content, createdAt, status: 'done' }
}

/** 首个面试会话的完整对话（对齐设计稿内容） */
function createInterviewDialogue(): ChatMessage[] {
  return [
    message('ai', GREETINGS.interview, minutesAgo(12)),
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

/** 首个学习会话的完整对话（知识精讲示例） */
function createStudyDialogue(): ChatMessage[] {
  return [
    message('ai', GREETINGS.study, minutesAgo(14)),
    message('user', '我想系统学习一下 JavaScript 的事件循环机制。', minutesAgo(13)),
    message(
      'ai',
      '好的，我们从三个部分来讲：\n1. 调用栈（Call Stack）：同步代码的执行栈；\n2. 任务队列：宏任务（setTimeout、I/O）与微任务（Promise.then、queueMicrotask）；\n3. 事件循环：每次同步代码执行完，先清空所有微任务，再取一个宏任务执行。',
      minutesAgo(12),
    ),
    message('user', '那微任务和宏任务的执行顺序能举个例子吗？', minutesAgo(11)),
    message(
      'ai',
      '当然。例如：\nconsole.log(1)\nsetTimeout(() => console.log(2))\nPromise.resolve().then(() => console.log(3))\nconsole.log(4)\n输出顺序是 1、4、3、2：同步代码先执行，随后清空微任务(3)，最后执行宏任务(2)。',
      minutesAgo(10),
    ),
    message('ai', '要不要我为你出几道相关的练习题，检验一下掌握程度？', minutesAgo(9)),
  ]
}

export interface MockSeed {
  conversations: Conversation[]
  messages: Record<string, ChatMessage[]>
}

export function createSeed(): MockSeed {
  const conversations: Conversation[] = []
  const messages: Record<string, ChatMessage[]> = {}

  ;(Object.keys(CONVERSATION_SEEDS) as ChatModuleKey[]).forEach((moduleKey) => {
    const dialogue = moduleKey === 'interview' ? createInterviewDialogue() : createStudyDialogue()
    CONVERSATION_SEEDS[moduleKey].forEach((seed, index) => {
      const conversation: Conversation = {
        id: Random.guid(),
        title: seed.title,
        icon: seed.icon,
        module: moduleKey,
        updatedAt: minutesAgo(Random.integer(1, 30) + index * 40),
      }
      conversations.push(conversation)
      messages[conversation.id] =
        index === 0 ? dialogue : [message('ai', GREETINGS[moduleKey], conversation.updatedAt)]
    })
  })

  return { conversations, messages }
}

/** 新建会话时的欢迎语 */
export function createGreetingMessage(module: ChatModuleKey): ChatMessage {
  return message('ai', GREETINGS[module], Date.now())
}
