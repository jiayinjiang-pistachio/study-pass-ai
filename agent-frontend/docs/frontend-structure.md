# 前端页面结构与组件拆分设计

> **状态**：已实现（对应当前代码，随代码演进）
> **范围**：登录 / 注册页 + 应用骨架（顶栏 + 侧栏）+「学习室」「面试间」「笔记本」三个页面
> **关联规范**：编码与协作约定见 [`AGENTS.md`](../AGENTS.md)，本文件只描述结构设计。
> **最后更新**：2026-10-19

---

## 1. 页面结构分层

### 1.1 布局总览

三个模块共用「顶栏 + 侧栏」骨架，仅右侧内容区随路由切换。

**聊天页（学习室 `/study` / 面试间 `/interview`）**

```
┌───────────────────────────────────────────────────────────────────┐
│ [Logo] 学面通AI      [学习室●] [面试间] [笔记本]                    │  ← 顶栏 (全宽, 72px)
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

**笔记本（`/note`，无底部输入区）**

```
┌───────────────────────────────────────────────────────────────────┐
│ [Logo] 学面通AI      [学习室] [面试间] [笔记本●]                    │  ← 顶栏 (全宽, 72px)
├──────────────────┬────────────────────────────────────────────────┤
│  ＋ 新建笔记      │   ┌────────────────────────────────────────┐   │
│                  │   │ [B][I][U][列表][缩进] | [链接][图][🗑]   │   │  ← 工具栏 (wangEditor)
│  历史笔记         │   ├────────────────────────────────────────┤   │
│  ▪ 前端技术面试准备│   │ 前端技术面试准备                        │   │  ← 标题输入
│  ▪ 数据库优化策略  │   ├────────────────────────────────────────┤   │
│  ▪ 系统架构设计    │   │ 富文本正文（卡片内独立滚动）             │   │  ← 编辑器
│  ▪ …             │   └────────────────────────────────────────┘   │
│  (固定 320px)     │                                                │
└──────────────────┴────────────────────────────────────────────────┘
```

### 1.2 三层结构

| 层级 | 组成 | 说明 |
| --- | --- | --- |
| **全局骨架层** | 顶栏 + 左栏 | 三个模块（学习室 / 面试间 / 笔记本）共用，仅右侧内容区随路由切换 |
| **侧栏层** | 会话 / 笔记列表 | 新建按钮（文案随模块变化）+ 列表 + 行内操作（编辑 / 下载 / 删除） |
| **内容层** | `RouterView` 渲染的页面 | `StudyRoom`（学习室）／ `InterviewRoom`（面试间）为聊天页；`NoteRoom`（笔记本）为富文本编辑页 |

> - 顶栏 Tab 高亮态：当前模块以金黄色底（`--color-brand-soft`）高亮，由 `RouterLink` 的 `active-class` 驱动。
> - 内容区由 **Vue Router** 决定渲染哪个页面（`/study` → `StudyRoom`，`/interview` → `InterviewRoom`，`/note` → `NoteRoom`）。
> - **侧栏数据源随当前模块切换**：学习室 / 面试间展示会话（`conversation` store），笔记本展示笔记（`note` store）；当前模块由 `useCurrentModule()` 读路由 `name` 得出，侧栏据此切换列表与「新建」按钮文案。

**认证页（`/login`，无骨架）**

```
┌───────────────────────────────────────────────────────────────────┐
│                     奶油色背景（--color-bg-page）                   │
│                    ┌─────────────────────────┐                     │
│                    │  [橙色 Logo] 学面通AI    │                     │
│                    │        ◯ 海滨插画        │                     │
│                    │    登录   注册           │                     │
│                    │  ───────────────         │                     │
│                    │  [👤 用户名或邮箱      ] │                     │
│                    │  [🔒 密码             ] │                     │
│                    │  [🔒 确认密码]（注册态） │                     │
│                    │  [📷 点击头像上传]（注册态）│  ← 仅本地预览      │
│                    │  [      登录 / 注册     ] │  ← 橙色全宽按钮     │
│                    └─────────────────────────┘                     │
└───────────────────────────────────────────────────────────────────┘
```

- `/login` 为公开路由，不套 `AppShell`；其余路由由前置守卫校验本地令牌，未登录跳登录页并携带 `redirect`，登录成功后回跳。
- 登录 / 注册共用一张卡片，通过 Tab 切换；注册态多一个「确认密码」输入框与头像选择入口。
- 头像选择只生成本地预览；注册流程为「文本信息建号 → 自动登录拿 Token → 带 Bearer 调 `POST /api/files` 上传」，失败不阻断登录。

---

## 2. 组件拆分

### 2.1 组件树（与代码一致）

```
App.vue
└─ <RouterView />
   ├─ views/LoginView.vue                     # 登录 / 注册（公开路由，无骨架）
   └─ layouts/AppShell.vue                    # 顶栏 + 侧栏 + 内容区骨架（需登录）
      ├─ components/layout/TopNavBar.vue      # 顶栏容器
      │  ├─ (内联) Logo + 「学面通AI」标题     # 黄色圆形 logo，静态展示
      │  ├─ components/layout/ModuleTabs.vue  # 学习室 / 面试间 / 笔记本（RouterLink × 3）
      │  └─ (内联) 当前用户头像 + 用户名 + 退出登录
      ├─ components/sidebar/ConversationSidebar.vue   # 左栏（按当前模块切换列表与按钮文案）
      │  ├─ (内联) ＋新建会话 / ＋新建笔记 按钮
      │  ├─ components/sidebar/ConversationList.vue   # 学习室 / 面试间（按模块过滤）
      │  │  └─ components/sidebar/SidebarItem.vue     # 图标 + 标题 + 行内重命名 + hover 操作组
      │  └─ components/sidebar/NoteList.vue           # 笔记本
      │     └─ components/sidebar/SidebarItem.vue     # 会话 / 笔记共用同一列表项组件
      └─ <RouterView />                       # 内容区
         ├─ views/StudyRoom.vue               # 学习室（与面试间同构）
         │  ├─ components/chat/ChatMessageList.vue
         │  └─ components/chat/ChatInputBar.vue
         ├─ views/InterviewRoom.vue           # 面试间页面
         │  ├─ components/chat/ChatMessageList.vue
         │  │  ├─ components/chat/ChatMessageItem.vue   # 单条消息（按 role 分派样式）
         │  │  ├─ components/common/LoadingDots.vue     # AI 思考中（replying 时）
         │  │  └─ components/common/EmptyState.vue      # 无消息时
         │  └─ components/chat/ChatInputBar.vue  # 底部输入区
         └─ views/NoteRoom.vue                # 笔记本（富文本编辑，无底部输入区）
            ├─ (内联) 标题输入 + 删除笔记按钮
            └─ @wangeditor-next/editor-for-vue   # Toolbar + Editor（wangEditor-next）
```

> 设计稿中的 `AppLogo` / `NewConversationButton` / `ConversationActions` / `MessageAvatar` / `MessageBubble` / `MessageMeta` / `AttachmentButton` / `SendButton` 未单独拆文件：它们要么被内联进父组件（Logo、新建按钮、头像、气泡、时间、附件、发送按钮），要么改用 Element Plus 组件替代（确认弹窗 `ElMessageBox`、空状态 `el-empty`、图标 `@element-plus/icons-vue`）。**当前阶段不做过度拆分**。
>
> 会话与笔记的列表项结构一致（图标 + 标题 + 行内重命名 + hover 操作组），因此合并为通用的 `SidebarItem`，由 `ConversationList` / `NoteList` 各自连接对应 store，避免复制粘贴。原先的 `ConversationItem` 与占位页 `PlaceholderView` 已删除。

### 2.2 通用组件（`src/components/common/`）

| 组件 | 职责 |
| --- | --- |
| `EmptyState.vue` | 空状态占位（封装 `el-empty`） |
| `LoadingDots.vue` | AI 思考中动画 |

> 其余通用能力直接复用 Element Plus：弹窗 `ElMessageBox` / `ElMessage`、加载 `v-loading` / `el-empty`、图标集 `@element-plus/icons-vue`。

### 2.3 非组件层

| 目录 | 内容 | 备注 |
| --- | --- | --- |
| `src/router/` | `index.ts` | history 模式；路由名复用 `ModuleKey`；页面懒加载；`/login` 公开，其余路由由前置守卫校验令牌 |
| `src/stores/` | `auth`（令牌 / 当前用户 / 登录注册退出）、`conversation`（会话列表 / 各模块选中态）、`chat`（消息 / 发送态）、`note`（笔记列表 / 当前笔记 / 内容） | **Pinia setup 风格** store |
| `src/api/` | `request.ts`（axios 实例 + 拦截器）、`auth.ts`（登录 / 注册 / 当前用户）、`file.ts`（通用文件上传）、`conversation.ts`（会话 CRUD）、`interview.ts`（对话消息）、`note.ts`（笔记 CRUD 与内容保存） | 请求统一走此层，禁止组件/store 裸调 |
| `src/mock/` | `index.ts`（Mock.js 拦截）、`data.ts`（会话种子数据与固定文案，分学习 / 面试两组）、`notes.ts`（笔记种子数据与拦截） | **仅开发环境**动态加载；axios 固定 xhr adapter 以被 Mock.js 拦截 |
| `src/utils/` | `token.ts`（localStorage 令牌读写） | 请求层与路由守卫共用 |
| `src/composables/` | `useAutoScroll`（滚动贴底 + 「回到最新」）、`useCurrentModule`（从路由 `name` 派生当前模块） | 逻辑复用 |
| `src/types/` | `chat.ts`、`conversation.ts`、`note.ts` | 类型定义 |

### 2.4 目录落位

```
src/
├── api/              # request.ts（axios）/ auth.ts / file.ts / conversation.ts / interview.ts / note.ts
├── assets/           # 需构建处理的静态资源
├── components/
│   ├── common/       # EmptyState / LoadingDots
│   ├── layout/       # TopNavBar / ModuleTabs
│   ├── sidebar/      # ConversationSidebar / ConversationList / NoteList / SidebarItem
│   └── chat/         # ChatMessageList / ChatMessageItem / ChatInputBar
├── composables/      # useAutoScroll.ts / useCurrentModule.ts
├── layouts/          # AppShell.vue（业务页面布局）
├── mock/             # index.ts / data.ts / notes.ts（仅 DEV，拦截 XHR）
├── router/           # index.ts（含登录守卫）
├── stores/           # auth.ts / conversation.ts / chat.ts / note.ts
├── styles/           # _tokens.scss（变量）/ index.scss（reset + CSS 变量）
├── types/            # chat.ts / conversation.ts / note.ts
├── utils/            # token.ts（localStorage 令牌）
├── views/            # LoginView.vue / StudyRoom.vue / InterviewRoom.vue / NoteRoom.vue
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
  module: ModuleKey   // 仅 study / interview；笔记本用独立的 Note
  updatedAt: number
}

// src/types/note.ts
export interface Note {
  id: string
  title: string
  icon: string
  content: string     // 富文本 HTML
  updatedAt: number
}
```

统一响应信封（`src/api/request.ts`）：

```ts
export interface ApiEnvelope<T> {
  code: number                 // 200 = 成功；错误复用 HTTP 状态码（401 / 404 / 409 / 413 / 422 / 429 / 500）
  message: string              // 面向用户的中文提示
  detail?: string | null       // 面向开发者的定位信息
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
| 2 | 切换 Tab 保留各模块选中态与滚动位置 | ⚠️ | 各模块选中项已分别记录（`conversation.activeByModule`）；滚动位置未保留，切换即重建 |
| 3 | Logo 点击 → 回首页 / 默认模块 | ⬜ | 当前 Logo 为静态展示 |

### B. 侧栏 · 会话

| # | 交互 | 状态 | 说明 |
| --- | --- | --- | --- |
| 4 | 「＋新建会话 / ＋新建笔记」→ 新建并置顶选中 | ✅ | 按钮文案随模块变化；会话走 `conversation.create(module)`，笔记走 `note.create()` |
| 5 | 点击会话项 → 切换并加载消息历史 | ✅ | `conversation.select(module, id)` + `ChatMessageList` 按当前模块读 `activeByModule` |
| 6 | hover 显示 编辑 / 下载 / 删除 | ✅ | CSS `:hover` 显示操作组 |
| 7 | 行内重命名（回车 / 失焦保存，Esc 取消） | ✅ | `SidebarItem` 内联输入框（会话 / 笔记共用） |
| 8 | 下载 → 导出会话为文件 | ⚠️ | 点击仅 `ElMessage.info('功能开发中')` 占位 |
| 9 | 删除 → 二次确认 → 更新列表 | ✅ | `ElMessageBox.confirm`（确认文案按「会话 / 笔记」区分）；删当前项则切首项或空 |
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

### F. 笔记本（富文本编辑，`/note`）

| # | 交互 | 状态 | 说明 |
| --- | --- | --- | --- |
| 31 | 底部**无**聊天输入区 | ✅ | 笔记本只做富文本编辑，不接对话 |
| 32 | 工具栏：加粗 / 斜体 / 下划线 / 列表 / 缩进 / 链接 / 插入图片 | ✅ | wangEditor `Toolbar`，`toolbarKeys` 显式声明 |
| 33 | 标题行内编辑（回车 / 失焦保存） | ✅ | 卡片顶部 `<input>` → `note.rename()` |
| 34 | 正文编辑 → 防抖自动保存（约 600ms） | ✅ | `@onChange` → `note.saveContent()` |
| 35 | 切换侧栏笔记 → 编辑器内容随之切换 | ✅ | `watch(activeNoteId)` 改绑定 ref（组件内部自动 `setHtml`） |
| 36 | 删除笔记 → 二次确认 → 删除当前笔记 | ✅ | 工具栏行尾垃圾桶按钮 + `ElMessageBox.confirm` |

### G. 全局

| # | 交互 | 状态 | 说明 |
| --- | --- | --- | --- |
| 37 | 加载态 / 错误态 / 空态统一处理 | ⚠️ | loading 已实现；错误态未统一；空态仅消息列表 |
| 38 | 窄屏响应式：侧栏收起为抽屉 | ⚠️ | `< 768px` 时侧栏 `display: none`，未做抽屉 |
| 39 | 键盘可达性与焦点管理 | ⚠️ | 重命名输入框有焦点处理；未系统化 |

### H. 登录 / 注册与鉴权（`/login`）

| # | 交互 | 状态 | 说明 |
| --- | --- | --- | --- |
| 40 | 未登录访问业务路由 → 跳转 `/login` | ✅ | `router.beforeEach` 检查 localStorage 中的 access_token，携带 `redirect` |
| 41 | 登录 / 注册 Tab 切换 | ✅ | 共用卡片；注册态多「确认密码」；切换时清空密码 |
| 42 | 登录成功 → 保存双令牌 → 回跳原页面 | ✅ | 写 localStorage（`utils/token.ts`），无 redirect 时默认跳面试间 |
| 43 | 注册成功 → 自动登录 | ✅ | 注册接口成功后立即调用登录接口 |
| 44 | 注册前端校验 | ✅ | 用户名非空且 ≤ 32；密码 6–72 位、含字母与数字、不含用户名、两次一致 |
| 45 | 请求自动带 Bearer；401 自动刷新并重试 | ✅ | axios 拦截器；并发 401 共享同一次刷新 |
| 46 | 刷新失败 → 清理令牌 → 跳登录 | ✅ | 同时弹出「登录状态已过期」提示 |
| 47 | 顶栏展示当前用户 + 退出登录 | ✅ | 头像与用户名来自 `auth` store；退出清理 localStorage 并跳 `/login` |
| 48 | 注册选择头像 → 仅本地预览 | ✅ | `URL.createObjectURL` 预览，限制 JPG / PNG / WebP / GIF 且 ≤ 2MB；切换/离开时释放 |
| 49 | 注册成功 → 自动登录 → 上传头像 | ✅ | 建号后调用登录拿 Token，再以 `FormData` 调通用接口 `POST /api/files`；图片由后端识别并更新 avatar，失败不阻断登录 |

---

## 5. 设计 Token

变量定义在 `src/styles/_tokens.scss`（SCSS 变量，仅变量与 mixin，不产生 CSS 输出），在 `src/styles/index.scss` 中映射为 `:root` 上的 CSS 变量；组件内统一使用 `var(--xxx)`。

| CSS 变量 | 值 | 用途 |
| --- | --- | --- |
| `--color-brand` | `#F5C518` | 主色（发送按钮 / 高亮 Tab / Element Plus 主色） |
| `--color-brand-light` | `#FFD24C` | 主色浅色（渐变起点） |
| `--color-brand-soft` | `#FCE9A8` | 主色柔和底（选中会话 / 激活 Tab） |
| `--color-accent` | `#FF7A1A` | 登录页强调色（Logo / 激活 Tab / 提交按钮） |
| `--color-accent-hover` | `#FF8F3D` | 强调色悬停 |
| `--color-accent-active` | `#EA6A0A` | 强调色按下 |
| `--color-accent-soft` | `#FFF1E6` | 强调色柔和底（退出登录 hover） |
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
| `--editor-max-width` | `880px` | 笔记本编辑器卡片最大宽度 |

> 渐变（新建按钮 / Logo）直接用 `linear-gradient(..., var(--color-brand-light), var(--color-brand))`，不单设变量。
> 响应式断点在 SCSS 中以 `$bp-md: 1024px` / `$bp-sm: 768px` 维护（未映射为 CSS 变量）。

---

## 6. 本轮实现约定

- **路由**：`vue-router` history 模式，Tab 切换由路由驱动；路由名复用 `ModuleKey`；页面懒加载；`/` 与未匹配路径重定向到面试间；`/login` 为公开路由，其余路由由前置守卫校验本地令牌。
- **鉴权**：登录签发 access / refresh 双令牌并存入 localStorage；axios 请求拦截器自动附加 `Authorization: Bearer`；401 时用 refresh token 换新并重试一次（并发去重），失败则清理令牌并跳登录页。
- **文件上传**：注册页选择头像时只本地预览；注册→自动登录→带令牌调通用接口 `POST /api/files`（`multipart/form-data`，字段 `file`，封装于 `src/api/file.ts`）。后端按用户分目录存为 `/uploads/users/{userId}/{MD5}.{ext}`，图片会同时更新头像，文档只保存；Vite 开发/预览服务器同时代理 `/uploads`。头像 URL 与用户名统一由 `auth` store 维护，顶栏直接读取。
- **状态**：`Pinia` setup 风格 store（`auth` / `conversation` / `chat` / `note`）；**当前模块的唯一事实来源是路由**，store 不再存一份当前 Tab。
- **模块决定数据源**：学习室 / 面试间展示会话（`conversation` store，选中态按模块分别记录于 `activeByModule`），笔记本展示笔记（`note` store，独立数据源）；侧栏由 `useCurrentModule()` 读路由 `name` 切换列表与按钮文案。
- **富文本编辑器**：笔记本正文用 **wangEditor-next**（`@wangeditor-next/editor` + `-for-vue`）。约定：必须引入其 CSS；内容用 `v-model` 绑定，外部切换笔记只需改绑定的 ref（组件内部自动 `setHtml`）；`onCreated` / `onChange` 只能走组件事件（写进 `defaultConfig` 会抛错）；组件卸载须调用 `editor.destroy()`；`toolbarKeys` 显式声明，图片用 `insertImage`（`uploadImage` 依赖后端上传接口）。
- **请求层**：`src/api/` 基于 **axios** 统一封装（唯一实例 + 请求 / 响应拦截器），响应信封 `{ code, message, data }` 自动解包；错误统一 `ElMessage` 提示（短时间去重）；axios 固定 `adapter: 'xhr'`。
- **Mock**：`mockjs` 通过替换全局 `XMLHttpRequest` 拦截请求，**仅开发环境**动态加载（`main.ts` 中 `import.meta.env.DEV` 守卫，且在首个请求前完成）；因 axios 固定 xhr adapter，Mock 对 axios 请求同样生效，**不要改用 fetch 适配器**。`Mock.Random` 只用于易变字段（id / 时间戳 / AI 随机回复），业务关键文案保持固定；接真实后端时删除 mock 拦截即可，业务代码无需改动。
- **UI 库**：Element Plus **全量引入**（`app.use(ElementPlus)` + 引入其 CSS），主题通过 `--el-color-primary` 对齐品牌色。
- **样式**：SCSS + 设计 token → CSS 变量，组件统一 `var(--xxx)`。
- **会话分类图标**本轮用 emoji 占位，后续替换为品牌图标集。

---

## 7. 决策记录

| # | 决策点 | 结论 | 状态 |
| --- | --- | --- | --- |
| 1 | Tab 切换机制 | **Vue Router**（history 模式，可深链） | ✅ 已落地 |
| 2 | 状态管理 | **Pinia**（setup 风格 store） | ✅ 已落地 |
| 3 | 请求库选型 | **axios + xhr adapter**（拦截器统一鉴权 / 续期；xhr adapter 兼容 Mock.js） | ✅ 已落地 |
| 4 | 发送快捷键 | Enter 发送 / Shift+Enter 换行 | ✅ 已落地 |
| 5 | 面试流程范围 | 本轮仅打通「对话」；语音 / 复盘 / 状态机后续迭代 | ⬜ 待迭代 |
| 6 | Element Plus 引入方式 | 全量引入（后续可评估按需引入瘦身） | ⬜ 待评估 |
| 7 | 笔记本富文本编辑器选型 | **wangEditor-next**（`-for-vue` 提供 `Editor` / `Toolbar`，`v-model` 开箱即用；仅笔记本路由引用，构建自动拆入 `NoteRoom` 异步 chunk） | ✅ 已落地 |
| 8 | 笔记数据来源 | **独立数据源**（`note` store + `src/api/note.ts` + `mock/notes.ts`），与会话分离，侧栏按模块切换 | ✅ 已落地 |
| 9 | 侧栏按模块过滤 | 由 `useCurrentModule()` 读路由 `name` 决定列表与文案；会话选中态按模块记录于 `activeByModule`，避免串用 | ✅ 已落地 |
| 10 | 登录鉴权方案 | JWT 双令牌 + localStorage；路由守卫拦截未登录；axios 401 自动刷新并重试 | ✅ 已落地 |
| 11 | 登录页视觉 | 独立于 `AppShell` 的居中卡片；登录 / 注册 Tab 共用表单 | ✅ 已落地 |
| 12 | 注册头像上传时机 | 选择时只本地预览；建号并自动登录后，携带 Bearer 调用通用上传接口，避免未认证请求 | ✅ 已落地 |
| 13 | 文件存储 | 按 `users/{userId}/` 分目录，文件名用内容 MD5（去重）；图片自动更新头像，文档只保存 | ✅ 已落地 |
