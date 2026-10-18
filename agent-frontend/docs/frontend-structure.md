# 前端页面结构与组件拆分设计

> **状态**：已实现（对应当前代码，随代码演进）
> **范围**：应用骨架（顶栏 + 侧栏）+「面试间」页面
> **关联规范**：编码与协作约定见仓库根目录 [`AGENTS.md`](../AGENTS.md)，本文件只描述结构设计。
> **最后更新**：2026-10-17

---

## 1. 页面结构分层

### 1.1 布局总览

```
┌───────────────────────────────────────────────────────────────────┐
│ [Logo] 学面通AI      [学习室] [面试间●] [笔记本]                    │  ← 顶栏 (全宽, 72px)
├──────────────────┬────────────────────────────────────────────────┤
│  ＋ 新建会话      │  消息列表（可滚动，米色底 #FAF6EC）              │
│                  │   🤖 AI 气泡（白底描边）        刚刚            │
│  历史会话         │   👤 用户气泡（灰底 #E9E9E9）   刚刚            │
│  ▪ 前端技术面试准备│   …                                            │
│  ▪ 数据库优化策略  │                                                │
│  ▪ 系统架构设计    │────────────────────────────────────────────────│
│  ▪ …             │  [输入你的回答…]        📎             (➤)      │  ← 输入区 (白色, 固定底部)
│  (固定 320px)     │                                                │
└──────────────────┴────────────────────────────────────────────────┘
```

### 1.2 三层结构

| 层级 | 组成 | 说明 |
| --- | --- | --- |
| **全局骨架层** | 顶栏 + 左栏 | 三个模块（学习室 / 面试间 / 笔记本）共用，仅右侧内容区随路由切换 |
| **侧栏层** | 会话历史 | 新建按钮 + 会话列表 + 行内操作（编辑 / 下载 / 删除） |
| **内容层** | `RouterView` 渲染的页面 | `InterviewRoom`（面试间）／ `PlaceholderView`（学习室、笔记本占位） |

> - 顶栏 Tab 高亮态：当前模块以金黄色底（`--color-brand-soft`）高亮，由 `RouterLink` 的 `active-class` 驱动。
> - 内容区由 **Vue Router** 决定渲染哪个页面（`/interview` → `InterviewRoom`，`/study`、`/note` → `PlaceholderView`）。

---

## 2. 组件拆分

### 2.1 组件树（与代码一致）

```
App.vue
└─ layouts/AppShell.vue                       # 顶栏 + 侧栏 + 内容区骨架
   ├─ components/layout/TopNavBar.vue         # 顶栏容器
   │  ├─ (内联) Logo + 「学面通AI」标题        # 黄色圆形 logo，静态展示
   │  └─ components/layout/ModuleTabs.vue     # 学习室 / 面试间 / 笔记本（RouterLink × 3）
   ├─ components/sidebar/ConversationSidebar.vue   # 左栏
   │  ├─ (内联) ＋新建会话按钮
   │  └─ components/sidebar/ConversationList.vue
   │     └─ components/sidebar/ConversationItem.vue  # 图标 + 标题 + 行内重命名 + hover 操作组
   └─ <RouterView />                          # 内容区
      ├─ views/InterviewRoom.vue              # 面试间页面
      │  ├─ components/chat/ChatMessageList.vue
      │  │  ├─ components/chat/ChatMessageItem.vue   # 单条消息（按 role 分派样式）
      │  │  ├─ components/common/LoadingDots.vue     # AI 思考中（replying 时）
      │  │  └─ components/common/EmptyState.vue      # 无消息时
      │  └─ components/chat/ChatInputBar.vue  # 底部输入区
      └─ views/PlaceholderView.vue            # 学习室 / 笔记本占位（el-empty）
```

> 设计稿中的 `AppLogo` / `NewConversationButton` / `ConversationActions` / `MessageAvatar` / `MessageBubble` / `MessageMeta` / `AttachmentButton` / `SendButton` 未单独拆文件：它们要么被内联进父组件（Logo、新建按钮、头像、气泡、时间、附件、发送按钮），要么改用 Element Plus 组件替代（确认弹窗 `ElMessageBox`、空状态 `el-empty`、图标 `@element-plus/icons-vue`）。**当前阶段不做过度拆分**。

### 2.2 通用组件（`src/components/common/`）

| 组件 | 职责 |
| --- | --- |
| `EmptyState.vue` | 空状态占位（封装 `el-empty`） |
| `LoadingDots.vue` | AI 思考中动画 |

> 其余通用能力直接复用 Element Plus：弹窗 `ElMessageBox` / `ElMessage`、加载 `v-loading` / `el-empty`、图标集 `@element-plus/icons-vue`。

### 2.3 非组件层

| 目录 | 内容 | 备注 |
| --- | --- | --- |
| `src/router/` | `index.ts` | history 模式；路由名复用 `ModuleKey`；页面懒加载；`/` 与未匹配路径重定向到面试间 |
| `src/stores/` | `conversation`（会话列表 / 当前会话）、`chat`（消息 / 发送态） | **Pinia setup 风格** store |
| `src/api/` | `request.ts`（统一请求，XHR 封装）、`conversation.ts`（会话 CRUD）、`interview.ts`（面试对话） | 请求统一走此层，禁止组件/store 裸调 |
| `src/mock/` | `index.ts`（Mock.js 拦截）、`data.ts`（种子数据与固定文案） | **仅开发环境**动态加载 |
| `src/composables/` | `useAutoScroll`（滚动贴底 + 「回到最新」） | 逻辑复用 |
| `src/types/` | `chat.ts`、`conversation.ts` | 类型定义 |

### 2.4 目录落位

```
src/
├── api/              # request.ts / conversation.ts / interview.ts
├── assets/           # 需构建处理的静态资源
├── components/
│   ├── common/       # EmptyState / LoadingDots
│   ├── layout/       # TopNavBar / ModuleTabs
│   ├── sidebar/      # ConversationSidebar / ConversationList / ConversationItem
│   └── chat/         # ChatMessageList / ChatMessageItem / ChatInputBar
├── composables/      # useAutoScroll.ts
├── layouts/          # AppShell.vue
├── mock/             # index.ts / data.ts（仅 DEV）
├── router/           # index.ts
├── stores/           # conversation.ts / chat.ts
├── styles/           # _tokens.scss（变量）/ index.scss（reset + CSS 变量）
├── types/            # chat.ts / conversation.ts
├── views/            # InterviewRoom.vue / PlaceholderView.vue
├── App.vue
├── main.ts
└── env.d.ts
```

---

## 3. 数据模型

```ts
// src/types/chat.ts
export type Role = 'ai' | 'user'

export const MessageStatus = {
  Pending: 'pending',
  Streaming: 'streaming',
  Done: 'done',
  Error: 'error',
} as const
export type MessageStatus = (typeof MessageStatus)[keyof typeof MessageStatus]

export interface ChatMessage {
  id: string
  role: Role
  content: string
  createdAt: number
  status?: MessageStatus
}

// src/types/conversation.ts
export const ModuleKey = {
  Study: 'study',
  Interview: 'interview',
  Note: 'note',
} as const
export type ModuleKey = (typeof ModuleKey)[keyof typeof ModuleKey]

export const MODULE_LABELS: Record<ModuleKey, string> = {
  study: '学习室',
  interview: '面试间',
  note: '笔记本',
}

export interface Conversation {
  id: string
  title: string
  icon: string        // 每条会话左侧的图标标识（当前为 emoji）
  module: ModuleKey
  updatedAt: number
}
```

统一响应信封（`src/api/request.ts`）：

```ts
export interface ApiEnvelope<T> {
  code: number      // 0 = 成功
  message: string
  data: T
}
```

> 按规范约束（`erasableSyntaxOnly`），枚举一律用 `as const` 对象 + 联合类型，**禁止 TS `enum`**。

---

## 4. 交互逻辑清单

> 图例：✅ 已实现 ｜ ⚠️ 部分实现 / 占位 ｜ ⬜ 未实现（后续迭代）

### A. 顶栏

| # | 交互 | 状态 | 说明 |
| --- | --- | --- | --- |
| 1 | 点击「学习室 / 面试间 / 笔记本」→ 切换高亮 + 内容区 | ✅ | Vue Router + `RouterLink active-class` |
| 2 | 切换 Tab 保留各模块会话与滚动位置 | ⬜ | 模块为独立路由，切换即重建 |
| 3 | Logo 点击 → 回首页 / 默认模块 | ⬜ | 当前 Logo 为静态展示 |

### B. 侧栏 · 会话

| # | 交互 | 状态 | 说明 |
| --- | --- | --- | --- |
| 4 | 「＋新建会话」→ 新建并置顶选中 | ✅ | `store.create()` → `POST /conversations` |
| 5 | 点击会话项 → 切换并加载消息历史 | ✅ | `store.select()` + `ChatMessageList` 监听 `activeConversationId` |
| 6 | hover 显示 编辑 / 下载 / 删除 | ✅ | CSS `:hover` 显示操作组 |
| 7 | 行内重命名（回车 / 失焦保存，Esc 取消） | ✅ | `ConversationItem` 内联输入框 |
| 8 | 下载 → 导出会话为文件 | ⚠️ | 点击仅 `ElMessage.info('功能开发中')` 占位 |
| 9 | 删除 → 二次确认 → 更新列表 | ✅ | `ElMessageBox.confirm`；删当前会话则切相邻项或空 |
| 10 | 列表按 `updatedAt` 倒序；长标题截断 | ⚠️ | 截断已实现（`.text-ellipsis`）；排序依赖接口返回顺序，前端不重排 |
| 11 | 空状态：无会话时展示引导 | ⬜ | 列表为空时无引导 |

### C. 消息列表

| # | 交互 | 状态 | 说明 |
| --- | --- | --- | --- |
| 12 | 进入会话 → 自动滚到底部 | ✅ | `useAutoScroll` `onMounted` 贴底 |
| 13 | 新消息到达平滑滚底；已上滑则显示「回到最新」 | ✅ | `useAutoScroll` 阈值 80px |
| 14 | AI 流式回复逐块渲染 + 可中断 | ⬜ | 当前接口整条返回，无流式 |
| 15 | AI 思考中显示 `LoadingDots` | ✅ | 由 `chat.replying` 驱动 |
| 16 | 时间显示：刚刚 / N 分钟前 / 具体时间 | ✅ | `ChatMessageItem` 的 `timeLabel` |
| 17 | 长文本换行；代码块高亮 | ⚠️ | 换行已实现（`pre-wrap` + `break-word`）；代码块高亮未做 |
| 18 | 请求失败 → 消息「重试」按钮 | ⬜ | 错误态未统一处理 |
| 19 | hover 消息 → 显示「复制」 | ⬜ | — |

### D. 输入区

| # | 交互 | 状态 | 说明 |
| --- | --- | --- | --- |
| 20 | placeholder + 多行自动增高（上限 120px） | ✅ | `ChatInputBar` 的 `resize()` |
| 21 | Enter 发送 / Shift+Enter 换行 | ✅ | `@keydown.enter.exact.prevent` |
| 22 | 内容为空 → 发送按钮禁用 | ✅ | `canSend` computed |
| 23 | 点击发送 → 用户消息立即上屏 → 调接口 → AI 回复 | ✅ | 乐观上屏（`chat.send`） |
| 24 | 附件 → 选择 / 校验 / 预览 / 上传进度 | ⬜ | 📎 点击仅提示「开发中」 |
| 25 | 发送中禁用重复提交 | ✅ | `canSend` 含 `!replying` |
| 26 | 输入框聚焦态、发送按钮 active 态 | ✅ | `:focus-within` / `:hover` |

### E. 面试间专属（来自流程图，截图未体现）

| # | 交互 | 状态 | 说明 |
| --- | --- | --- | --- |
| 27 | 首条 AI 为欢迎语 + 引导选择职位 | ⚠️ | 欢迎语已实现；职位选择交互未做 |
| 28 | 流程状态机：选职位 → 提问 → 作答 → 评分 / 追问 → 复盘 | ⬜ | 本轮仅打通对话 |
| 29 | 语音输入（ASR）/ 语音播报（TTS） | ⬜ | — |
| 30 | 面试结束 → 生成复盘报告 | ⬜ | — |

### F. 全局

| # | 交互 | 状态 | 说明 |
| --- | --- | --- | --- |
| 31 | 加载态 / 错误态 / 空态统一处理 | ⚠️ | loading 已实现；错误态未统一；空态仅消息列表 |
| 32 | 窄屏响应式：侧栏收起为抽屉 | ⚠️ | `< 768px` 时侧栏 `display: none`，未做抽屉 |
| 33 | 键盘可达性与焦点管理 | ⚠️ | 重命名输入框有焦点处理；未系统化 |

---

## 5. 设计 Token

变量定义在 `src/styles/_tokens.scss`（SCSS 变量，仅变量与 mixin，不产生 CSS 输出），在 `src/styles/index.scss` 中映射为 `:root` 上的 CSS 变量；组件内统一使用 `var(--xxx)`。

| CSS 变量 | 值 | 用途 |
| --- | --- | --- |
| `--color-brand` | `#F5C518` | 主色（发送按钮 / 高亮 Tab / Element Plus 主色） |
| `--color-brand-light` | `#FFD24C` | 主色浅色（渐变起点） |
| `--color-brand-soft` | `#FCE9A8` | 主色柔和底（选中会话 / 激活 Tab） |
| `--color-bg-page` | `#FAF6EC` | 内容区背景（米色） |
| `--color-surface` | `#FFFFFF` | 顶栏 / 侧栏 / AI 气泡 |
| `--color-bubble-user` | `#E9E9E9` | 用户气泡 |
| `--color-text` | `#1F2329` | 主文字 |
| `--color-text-secondary` | `#5F6672` | 次级文字（会话标题） |
| `--color-text-muted` | `#8A9099` | 次要文字 / 时间戳 |
| `--color-border` | `#EFEFEF` | 气泡描边 |
| `--color-divider` | `#F0F0F0` | 分隔线（顶栏 / 侧栏边框） |
| `--color-hover` | `#F7F7F7` | 悬停底色 |
| `--radius-bubble` | `12px` | 气泡圆角 |
| `--radius-control` | `8px` | 按钮 / 输入框圆角 |
| `--radius-pill` | `10px` | 药丸形元素圆角 |
| `--navbar-height` | `72px` | 顶栏高度 |
| `--sidebar-width` | `320px` | 侧栏宽度 |
| `--avatar-size` | `38px` | 消息头像尺寸 |
| `--content-max-width` | `760px` | 内容区最大宽度 |

> 渐变（新建按钮 / Logo）直接用 `linear-gradient(..., var(--color-brand-light), var(--color-brand))`，不单设变量。
> 响应式断点在 SCSS 中以 `$bp-md: 1024px` / `$bp-sm: 768px` 维护（未映射为 CSS 变量）。

---

## 6. 本轮实现约定

- **路由**：`vue-router` history 模式，Tab 切换由路由驱动；路由名复用 `ModuleKey`；页面懒加载；`/` 与未匹配路径重定向到面试间。
- **状态**：`Pinia` setup 风格 store（`conversation` / `chat`）；**当前模块的唯一事实来源是路由**，store 不再存一份当前 Tab。
- **请求层**：`src/api/` 基于原生 `XMLHttpRequest` 统一封装（**刻意不用 axios**：Mock.js 只拦截 XHR，不拦截 `fetch`），响应信封 `{ code, message, data }` 自动解包。
- **Mock**：`mockjs` 通过 `Mock.mock` 拦截 XHR，**仅开发环境**动态加载（`main.ts` 中 `import.meta.env.DEV` 守卫）；`Mock.Random` 只用于易变字段（id / 时间戳 / AI 随机回复），业务关键文案保持固定；接真实后端时删除 mock 拦截即可，业务代码无需改动。
- **UI 库**：Element Plus **全量引入**（`app.use(ElementPlus)` + 引入其 CSS），主题通过 `--el-color-primary` 对齐品牌色。
- **样式**：SCSS + 设计 token → CSS 变量，组件统一 `var(--xxx)`。
- **会话分类图标**本轮用 emoji 占位，后续替换为品牌图标集。

---

## 7. 决策记录

| # | 决策点 | 结论 | 状态 |
| --- | --- | --- | --- |
| 1 | Tab 切换机制 | **Vue Router**（history 模式，可深链） | ✅ 已落地 |
| 2 | 状态管理 | **Pinia**（setup 风格 store） | ✅ 已落地 |
| 3 | 请求库选型 | **原生 XHR 封装**（配合 Mock.js 拦截，不引入 axios） | ✅ 已落地 |
| 4 | 发送快捷键 | Enter 发送 / Shift+Enter 换行 | ✅ 已落地 |
| 5 | 面试流程范围 | 本轮仅打通「对话」；语音 / 复盘 / 状态机后续迭代 | ⬜ 待迭代 |
| 6 | Element Plus 引入方式 | 全量引入（后续可评估按需引入瘦身） | ⬜ 待评估 |
