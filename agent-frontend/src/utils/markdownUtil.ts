/**
 * 通用 Markdown 渲染工具（AI 对话答案美化）。
 *
 * 能力：
 * - markdown-it 解析基础 Markdown（标题、列表、引用、链接、图片、表格、代码块等）；
 * - Prism.js 代码高亮，代码块带语言标识；
 * - 表格横向滚动、斑马纹、悬浮高亮；
 * - 代码块主题色通过 CSS 变量暴露，可在任意项目中覆盖；
 * - 仅依赖 markdown-it / prismjs，不依赖 Vue 或项目内其他模块，可直接迁移。
 *
 * 安全约定：markdown-it 关闭原始 HTML（html: false），代码内容经 Prism 转义，
 * 链接由 markdown-it 的 validateLink 过滤，避免把模型输出直接当 HTML 执行。
 *
 * 样式通过 ensureMarkdownStyles() 注入一次，所有选择器都以 .md-content 为根，
 * 不会污染宿主项目的全局样式。可通过覆盖 .md-content 上的 --md-* 变量定制主题。
 */

import MarkdownIt from 'markdown-it'
import type { RendererRule } from 'markdown-it'
import Prism from 'prismjs'
import type { Grammar } from 'prismjs'

// Prism 核心自带 markup / css / clike / javascript，其余常用语言按需注册。
// 注意顺序：tsx 依赖 jsx + typescript，cpp 依赖 c，csharp 依赖 clike。
import 'prismjs/components/prism-typescript'
import 'prismjs/components/prism-jsx'
import 'prismjs/components/prism-tsx'
import 'prismjs/components/prism-json'
import 'prismjs/components/prism-bash'
import 'prismjs/components/prism-python'
import 'prismjs/components/prism-java'
import 'prismjs/components/prism-sql'
import 'prismjs/components/prism-c'
import 'prismjs/components/prism-cpp'
import 'prismjs/components/prism-csharp'
import 'prismjs/components/prism-go'
import 'prismjs/components/prism-rust'
import 'prismjs/components/prism-yaml'
import 'prismjs/components/prism-markdown'

const STYLE_ID = 'md-content-styles'

/** 语言别名 → Prism 语言名，保证 js / ts / py 等常见写法也能高亮。 */
const LANGUAGE_ALIASES: Record<string, string> = {
  js: 'javascript',
  ts: 'typescript',
  py: 'python',
  sh: 'bash',
  shell: 'bash',
  zsh: 'bash',
  yml: 'yaml',
  html: 'markup',
  xml: 'markup',
  svg: 'markup',
  md: 'markdown',
  'c++': 'cpp',
  'c#': 'csharp',
  cs: 'csharp',
  golang: 'go',
  rs: 'rust',
}

/** 代码块主题与表格样式；全部挂在 .md-content 下，避免影响宿主页面。 */
export const MARKDOWN_STYLES = `
.md-content {
  --md-text: inherit;
  --md-muted: #6b7280;
  --md-border: #e5e7eb;
  --md-link: #0969da;
  --md-inline-code-bg: #f3f4f6;
  --md-inline-code-fg: #c7254e;
  --md-code-bg: #1e1e1e;
  --md-code-header-bg: #252526;
  --md-code-header-border: #333333;
  --md-code-fg: #d4d4d4;
  --md-code-lang: #9cdcfe;
  --md-token-comment: #6a9955;
  --md-token-punctuation: #d4d4d4;
  --md-token-keyword: #569cd6;
  --md-token-string: #ce9178;
  --md-token-number: #b5cea8;
  --md-token-function: #dcdcaa;
  --md-token-class: #4ec9b0;
  --md-token-property: #9cdcfe;
  --md-token-operator: #d4d4d4;
  --md-token-regex: #d16969;
  --md-token-deleted: #f44747;
  --md-token-inserted: #b5cea8;
  --md-table-head-bg: #f6f8fa;
  --md-table-stripe-bg: #fafbfc;
  --md-table-hover-bg: #eef6ff;
  --md-table-border: #e5e7eb;
  --md-blockquote-border: #d0d7de;

  white-space: normal;
  color: var(--md-text);
  font-size: 15px;
  line-height: 1.7;
  word-break: break-word;
}

.md-content > :first-child {
  margin-top: 0;
}

.md-content > :last-child {
  margin-bottom: 0;
}

.md-content h1,
.md-content h2,
.md-content h3,
.md-content h4,
.md-content h5,
.md-content h6 {
  margin: 1.3em 0 0.6em;
  font-weight: 600;
  line-height: 1.35;
}

.md-content h1 { font-size: 1.5em; }
.md-content h2 { font-size: 1.3em; }
.md-content h3 { font-size: 1.15em; }
.md-content h4,
.md-content h5,
.md-content h6 { font-size: 1em; }

.md-content p {
  margin: 0.8em 0;
}

.md-content ul,
.md-content ol {
  margin: 0.8em 0;
  padding-left: 1.5em;
}

.md-content li + li {
  margin-top: 0.25em;
}

.md-content a {
  color: var(--md-link);
  text-decoration: none;
}

.md-content a:hover {
  text-decoration: underline;
}

.md-content strong {
  font-weight: 600;
}

.md-content del {
  color: var(--md-muted);
}

.md-content blockquote {
  margin: 1em 0;
  padding: 0.2em 1em;
  border-left: 3px solid var(--md-blockquote-border);
  color: var(--md-muted);
}

.md-content hr {
  margin: 1.2em 0;
  border: none;
  border-top: 1px solid var(--md-border);
}

.md-content img {
  display: block;
  max-width: 100%;
  height: auto;
  margin: 0.8em 0;
  border-radius: 8px;
}

.md-content :not(pre) > code {
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--md-inline-code-bg);
  color: var(--md-inline-code-fg);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
  font-size: 0.9em;
}

.md-content .md-code {
  margin: 1em 0;
  overflow: hidden;
  border-radius: 8px;
  background: var(--md-code-bg);
}

.md-content .md-code__header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  background: var(--md-code-header-bg);
  border-bottom: 1px solid var(--md-code-header-border);
  color: var(--md-code-lang);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
  font-size: 12px;
  line-height: 1;
}

.md-content .md-code__header::before {
  content: "";
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
  opacity: 0.7;
}

.md-content .md-code__pre {
  margin: 0;
  padding: 14px 16px;
  overflow-x: auto;
  background: var(--md-code-bg);
  color: var(--md-code-fg);
  font-size: 13px;
  line-height: 1.65;
  tab-size: 2;
  -webkit-overflow-scrolling: touch;
}

.md-content .md-code__code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
  white-space: pre;
}

.md-content .md-table-wrap {
  max-width: 100%;
  margin: 1em 0;
  overflow-x: auto;
  border: 1px solid var(--md-table-border);
  border-radius: 8px;
  -webkit-overflow-scrolling: touch;
}

.md-content .md-table-wrap table {
  width: 100%;
  min-width: 420px;
  border-collapse: collapse;
  font-size: 14px;
}

.md-content .md-table-wrap th,
.md-content .md-table-wrap td {
  padding: 10px 14px;
  border-bottom: 1px solid var(--md-table-border);
  text-align: left;
  white-space: nowrap;
}

.md-content .md-table-wrap thead th {
  background: var(--md-table-head-bg);
  font-weight: 600;
}

.md-content .md-table-wrap tbody tr:nth-child(even) {
  background: var(--md-table-stripe-bg);
}

.md-content .md-table-wrap tbody tr:hover {
  background: var(--md-table-hover-bg);
}

.md-content .md-table-wrap tbody tr:last-child td {
  border-bottom: none;
}

/* Prism token 配色：全部通过 CSS 变量暴露，覆盖变量即可切换代码主题。 */
.md-content .token.comment,
.md-content .token.prolog,
.md-content .token.doctype,
.md-content .token.cdata {
  color: var(--md-token-comment);
}

.md-content .token.punctuation {
  color: var(--md-token-punctuation);
}

.md-content .token.namespace {
  opacity: 0.7;
}

.md-content .token.property,
.md-content .token.tag,
.md-content .token.boolean,
.md-content .token.number,
.md-content .token.constant,
.md-content .token.symbol {
  color: var(--md-token-number);
}

.md-content .token.selector,
.md-content .token.attr-name,
.md-content .token.string,
.md-content .token.char,
.md-content .token.builtin,
.md-content .token.inserted {
  color: var(--md-token-string);
}

.md-content .token.operator,
.md-content .token.entity,
.md-content .token.url,
.md-content .token.variable {
  color: var(--md-token-operator);
}

.md-content .token.atrule,
.md-content .token.attr-value,
.md-content .token.keyword {
  color: var(--md-token-keyword);
}

.md-content .token.function,
.md-content .token.class-name {
  color: var(--md-token-function);
}

.md-content .token.regex,
.md-content .token.important {
  color: var(--md-token-regex);
}

.md-content .token.deleted {
  color: var(--md-token-deleted);
}

.md-content .token.important,
.md-content .token.bold {
  font-weight: 600;
}

.md-content .token.italic {
  font-style: italic;
}
`

/** 把语言写法归一化为 Prism 语言名；未知语言回退为安全的短标识。 */
function normalizeLanguage(rawLanguage: string): string {
  const raw = rawLanguage.trim().toLowerCase()
  if (!raw) return 'text'
  const normalized = LANGUAGE_ALIASES[raw] ?? raw
  return normalized.replace(/[^a-z0-9-]/g, '') || 'text'
}

const md = new MarkdownIt({
  // 不解析模型输出里的原始 HTML，避免 XSS；需要 HTML 时应由调用方显式开启并自行净化。
  html: false,
  linkify: true,
  // AI 答案常用单换行分隔内容，按聊天场景渲染为 <br>。
  breaks: true,
})

const escapeHtml = (value: string): string => md.utils.escapeHtml(value)

/** 所有代码块共用：语言标识 + Prism 高亮 + 可横向滚动。 */
function renderCodeBlock(content: string, rawLanguage: string): string {
  const displayLanguage = rawLanguage.trim() || 'text'
  const language = normalizeLanguage(displayLanguage)
  const grammar = Prism.languages[language] as Grammar | undefined
  const highlighted = grammar
    ? Prism.highlight(content, grammar, language)
    : escapeHtml(content)

  return [
    '<div class="md-code">',
    `<div class="md-code__header"><span class="md-code__lang">${escapeHtml(displayLanguage)}</span></div>`,
    `<pre class="md-code__pre"><code class="md-code__code language-${escapeHtml(language)}">${highlighted}</code></pre>`,
    '</div>',
  ].join('')
}

/** 默认 token 渲染，供后续规则在“原规则不存在”时兜底。 */
const renderToken: RendererRule = (tokens, idx, options, _env, self) =>
  self.renderToken(tokens, idx, options)

// 围栏代码块：带语言标签。
md.renderer.rules.fence = (tokens, idx) => {
  const token = tokens[idx]
  if (!token) return ''
  return renderCodeBlock(token.content, token.info.trim().split(/\s+/)[0] ?? '')
}

// 缩进代码块：同样走统一代码样式（无语言则标记为 text）。
md.renderer.rules.code_block = (tokens, idx) => {
  const token = tokens[idx]
  return renderCodeBlock(token?.content ?? '', '')
}

// 表格外层包一层滚动容器，配合 CSS 实现横向滚动、斑马纹、悬浮高亮。
const defaultTableOpen = md.renderer.rules.table_open ?? renderToken
md.renderer.rules.table_open = (tokens, idx, options, env, self) =>
  `<div class="md-table-wrap">${defaultTableOpen(tokens, idx, options, env, self)}`

const defaultTableClose = md.renderer.rules.table_close ?? renderToken
md.renderer.rules.table_close = (tokens, idx, options, env, self) =>
  `${defaultTableClose(tokens, idx, options, env, self)}</div>`

// 外链统一新窗口打开，并补 rel 防止反向页劫持。
const defaultLinkOpen = md.renderer.rules.link_open ?? renderToken
md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  const token = tokens[idx]
  const href = token?.attrGet('href')
  if (typeof href === 'string' && /^https?:\/\//i.test(href)) {
    token?.attrSet('target', '_blank')
    token?.attrSet('rel', 'noopener noreferrer')
  }
  return defaultLinkOpen(tokens, idx, options, env, self)
}

// 图片懒加载，避免长对话中的大量图片阻塞首屏。
const defaultImage = md.renderer.rules.image ?? renderToken
md.renderer.rules.image = (tokens, idx, options, env, self) => {
  tokens[idx]?.attrSet('loading', 'lazy')
  return defaultImage(tokens, idx, options, env, self)
}

/**
 * 注入 Markdown 样式（幂等）。SSR / Node 环境下无 document 时安全跳过；
 * 浏览器端由 renderMarkdown 自动调用，也可在应用启动时手动调用一次。
 */
export function ensureMarkdownStyles(doc: Document | null = typeof document === 'undefined' ? null : document): void {
  if (!doc) return

  const existing = doc.getElementById(STYLE_ID)
  if (existing) {
    // 开发期 HMR 更新时同步最新样式，避免旧样式残留。
    if (existing.textContent !== MARKDOWN_STYLES) {
      existing.textContent = MARKDOWN_STYLES
    }
    return
  }

  const style = doc.createElement('style')
  style.id = STYLE_ID
  style.textContent = MARKDOWN_STYLES
  doc.head.appendChild(style)
}

/**
 * 渲染 Markdown 为可直接交给 v-html / innerHTML 的 HTML。
 *
 * 返回结果自带 .md-content 根节点，宿主只需提供容器宽度；
 * 样式会在浏览器端首次调用时自动注入一次。
 */
export function renderMarkdown(source: string): string {
  ensureMarkdownStyles()
  if (!source) return ''
  return `<div class="md-content">${md.render(source)}</div>`
}
