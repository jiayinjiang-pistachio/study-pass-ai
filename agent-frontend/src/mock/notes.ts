import Mock from 'mockjs'
import type { Note } from '@/types/note'

const Random = Mock.Random
const API_PREFIX = import.meta.env.VITE_API_PREFIX || '/api'

function ok<T>(data: T): { code: number; message: string; data: T } {
  return { code: 0, message: 'ok', data }
}

function fail(message: string, code = 1): { code: number; message: string; data: null } {
  return { code, message, data: null }
}

function parseBody<T>(body: string | undefined): T {
  try {
    return JSON.parse(body || '{}') as T
  } catch {
    return {} as T
  }
}

function noteIdFrom(url: string): string {
  return (
    url.match(/\/notes\/([^/]+)\/content$/)?.[1] ?? url.match(/\/notes\/([^/]+)$/)?.[1] ?? ''
  )
}

const SAMPLE_CONTENT = `<h2>JavaScript 闭包</h2><h3>定义</h3><p>闭包是指一个函数能够访问并“记住”其外部作用域中的变量，即使在其外部函数已经返回之后。</p><h3>应用场景</h3><ul><li>数据封装</li><li>模块模式</li><li>创建私有变量</li></ul><h2>React 虚拟 DOM</h2><h3>工作原理</h3><p>虚拟 DOM 是 React 用来提升性能的关键技术。它是一个轻量级的 JavaScript 对象树，是对真实 DOM 的抽象表示。</p><h3>性能提升机制</h3><ol><li>当组件状态发生变化时，React 会创建一个新的虚拟 DOM 树</li><li>与之前的虚拟 DOM 树进行比较（diff 算法）</li><li>找出最小的变化集</li><li>只更新真实 DOM 中需要改变的部分，从而减少昂贵的 DOM 操作</li></ol>`

/** 笔记标题/图标为业务固定值（对齐设计稿），id 与时间由 Mock.Random 生成 */
const NOTE_SEEDS: Array<Pick<Note, 'title' | 'icon'>> = [
  { title: '前端技术面试准备', icon: '💻' },
  { title: '数据库优化策略', icon: '🗄️' },
  { title: '系统架构设计', icon: '🏗️' },
  { title: '云计算基础', icon: '☁️' },
  { title: '移动端开发要点', icon: '📱' },
  { title: '网络安全防护', icon: '🔒' },
  { title: '数据分析方法', icon: '📊' },
  { title: '机器学习入门', icon: '🤖' },
]

function minutesAgo(minutes: number): number {
  return Date.now() - minutes * 60 * 1000
}

const notes: Note[] = NOTE_SEEDS.map((seed, index) => ({
  id: Random.guid(),
  title: seed.title,
  icon: seed.icon,
  content: index === 0 ? SAMPLE_CONTENT : '',
  updatedAt: minutesAgo(Random.integer(1, 30) + index * 40),
}))

const notesUrl = new RegExp(`${API_PREFIX}/notes$`)
const noteContentUrl = new RegExp(`${API_PREFIX}/notes/([^/]+)/content$`)
const noteUrl = new RegExp(`${API_PREFIX}/notes/([^/]+)$`)

// 笔记列表
Mock.mock(notesUrl, 'get', () => ok(notes))

// 新建笔记
Mock.mock(notesUrl, 'post', () => {
  const note: Note = {
    id: Random.guid(),
    title: '新建笔记',
    icon: '📝',
    content: '',
    updatedAt: Date.now(),
  }
  notes.unshift(note)
  return ok(note)
})

// 保存笔记内容
Mock.mock(noteContentUrl, 'put', (options) => {
  const id = noteIdFrom(options.url)
  const target = notes.find((item) => item.id === id)
  if (!target) return fail('笔记不存在', 404)
  const { content } = parseBody<{ content?: string }>(options.body)
  if (typeof content === 'string') target.content = content
  target.updatedAt = Date.now()
  return ok(target)
})

// 重命名笔记
Mock.mock(noteUrl, 'put', (options) => {
  const id = noteIdFrom(options.url)
  const target = notes.find((item) => item.id === id)
  if (!target) return fail('笔记不存在', 404)
  const { title } = parseBody<{ title?: string }>(options.body)
  if (title) target.title = title
  target.updatedAt = Date.now()
  return ok(target)
})

// 删除笔记
Mock.mock(noteUrl, 'delete', (options) => {
  const id = noteIdFrom(options.url)
  const index = notes.findIndex((item) => item.id === id)
  if (index === -1) return fail('笔记不存在', 404)
  notes.splice(index, 1)
  return ok(null)
})
