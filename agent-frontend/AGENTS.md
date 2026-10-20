# 学面通 AI · agent-frontend 前端开发规范

> 本文件是本项目前端开发的**唯一权威规范（Single Source of Truth）**，所有团队成员与 AI 助手在开发前都必须遵守。
>
> **自动引用机制**：
> - Claude Code 通过 `CLAUDE.md` 自动加载本文件；
> - Cursor / Codex / 其他支持 `AGENTS.md` 的工具会直接读取本文件。
>
> 修改规范时**只改本文件**，不要在别处重复维护，避免多处不一致。

---

## 0. 项目概览

- **产品**：学面通 AI —— 面向求职者的「学习 + 面试」AI 助手。
- **核心模块**（来自 `prepare/flow_chart.drawio`）：
  - **学习模块**：知识精讲（结构化知识卡片 + 一对一语音播客）、刷题测评（AI 生成题库 → 评分 → 薄弱点分析）、快速回答、直接生成答案、笔记。
  - **面试模块**：简历优化（上传 → 深度分析 → 优缺点评判 → 重新生成可下载 Word）、模拟面试（语音一对一）、面试复盘、知识精讲、快速回答、笔记。
- **本仓库**：`agent-frontend`，即上述产品的 Web 前端。后端接口在开发/预览时由 Vite 代理转发。

---

## 1. 技术栈（以 `package.json` 为准）

| 类别 | 选型 | 说明 |
| --- | --- | --- |
| 框架 | Vue `3.5.x` | 统一使用组合式 API + `<script setup>` |
| 语言 | TypeScript `~6.0` | 严格模式，禁止 `any` |
| 构建 | Vite `^8.3` | 别名 `@` → `src` |
| 类型检查 | `vue-tsc` | 构建前置检查（`vue-tsc -b`） |
| 路由 | vue-router `^5.4` | history 模式，路由以模块名命名 |
| 状态管理 | Pinia `^4.1` | setup 风格 store |
| 请求库 | axios `^1.20` | 统一实例 + 拦截器；固定 `adapter: 'xhr'` 以兼容 Mock.js（见 §7） |
| UI 组件库 | Element Plus `^2.14` + `@element-plus/icons-vue` | **全量引入**（见下方说明） |
| 富文本编辑器 | wangEditor-next `@wangeditor-next/editor` + `@wangeditor-next/editor-for-vue` `^6.5` | 仅笔记本模块使用（约定见 §4.5） |
| 样式 | SCSS（`sass`） | 组件 `<style lang="scss" scoped>` + 全局设计 token |
| 接口 Mock | `mockjs`（devDependency） | **仅开发环境**，通过拦截 XHR 生效 |
| 包管理 | **pnpm** | 仓库内已有 `pnpm-lock.yaml`，禁止混用 npm/yarn |
| Node | 见 `.nvmrc`/团队约定 | 类型依赖 `@types/node` 24 |

> **尚未引入**：ESLint / Prettier、单元测试框架、Git hook。下文凡涉及这些的部分均标注为「**待引入**」，引入前需先在团队内确认。
>
> **Element Plus 目前为全量引入**，产物 JS 约 1 MB（gzip 约 330 KB）。后续若要瘦身，可改用 `unplugin-vue-components` 按需引入（需新增 devDependencies，先确认）。
>
> **wangEditor-next 仅被笔记本路由引用**，构建时自动拆进 `NoteRoom` 异步 chunk（约 640 KB / gzip 200 KB），不影响学习室 / 面试间的首屏体积。

---

## 2. 目录结构约定

```
src/
├── api/              # 接口层：request.ts（axios 统一请求）+ 按业务拆分（auth.ts / file.ts / conversation.ts / interview.ts / note.ts）
├── assets/           # 需要经构建处理的静态资源（图片、svg、字体）
├── components/       # 可复用组件
│   ├── common/       # 通用展示组件（EmptyState / LoadingDots）
│   ├── layout/       # 顶栏相关（TopNavBar / ModuleTabs）
│   ├── sidebar/      # 侧栏（ConversationSidebar / ConversationList / NoteList / SidebarItem）
│   └── chat/         # 聊天区（ChatMessageList / ChatMessageItem / ChatInputBar）
├── composables/      # 组合式函数，命名 useXxx.ts（useAutoScroll / useCurrentModule）
├── layouts/          # 布局组件（AppShell.vue）
├── mock/             # 接口 Mock（仅开发环境加载，见 §7.2；index.ts / data.ts / notes.ts）
├── router/           # 路由配置
├── stores/           # Pinia 状态（auth / conversation / chat / note）
├── styles/           # 全局样式与设计 token（_tokens.scss / index.scss）
├── types/            # 全局类型定义（conversation / chat / note）
├── utils/            # 纯工具函数（token.ts：本地令牌读写）
├── views/            # 页面级组件（与路由一一对应：LoginView / StudyRoom / InterviewRoom / NoteRoom）
├── App.vue
├── main.ts
└── env.d.ts          # 环境变量类型声明
```

规则：
- 新增目录前先确认是否真的必要，避免过度拆分。
- 页面放 `views/`，可复用组件放 `components/`，**不要把页面塞进 `components/`**。
- 一次性使用的组件就近放在其所属目录下，不强行抽到全局 `components/`。
- 组件按领域归入 `components/` 下的子目录（layout / sidebar / chat / common），新增领域时再开子目录。

---

## 3. 命名规范

| 对象 | 规范 | 示例 |
| --- | --- | --- |
| 组件文件 | PascalCase | `KnowledgeCard.vue` |
| 页面文件 | PascalCase | `InterviewReview.vue` |
| 组合式函数 | camelCase，`use` 前缀 | `useAudioPlayer.ts` |
| Pinia Store | camelCase，`useXxxStore` | `useConversationStore` |
| 工具/接口文件 | camelCase | `request.ts`、`learn.ts` |
| 目录 | 小写单词或 kebab-case | `components/`、`mock-interview/` |
| 变量 / 函数 | camelCase | `questionList`、`fetchQuiz()` |
| 常量 | UPPER_SNAKE_CASE | `MAX_RETRY` |
| 类型 / 接口 | PascalCase，**不加 `I` 前缀** | `QuizQuestion`、`UserProfile` |
| 布尔值 | `is/has/should` 前缀 | `isLoading`、`hasError` |
| 事件（emit） | camelCase 定义，模板用 kebab-case 监听 | `defineEmits<{ submit: [] }>` → `@submit` |

---

## 4. Vue 编码规范

### 4.1 SFC 结构
统一顺序：`<script setup lang="ts">` → `<template>` → `<style scoped>`。

```vue
<script setup lang="ts">
// 1. imports
// 2. props / emits / defineModel
// 3. 响应式状态、computed
// 4. 生命周期
// 5. 方法
</script>

<template>
  <!-- 模板保持简洁，复杂逻辑抽到 script -->
</template>

<style scoped>
/* 默认 scoped */
</style>
```

### 4.2 组件约定
- 一律使用 `<script setup>`，不使用 Options API。
- `props` 用 `defineProps<Props>()` 泛型写法并配 `withDefaults` 设默认值。
- `emits` 用 `defineEmits<{ ... }>()` 类型化写法。
- 组件必须显式声明 `props` / `emits` 类型，禁止隐式 `any`。
- 组件超过 ~300 行或有多个独立区块时，考虑拆分。
- 模板中避免复杂表达式，逻辑放 `computed` / 方法。

### 4.3 状态与逻辑复用
- 跨组件复用逻辑一律抽成 `composables/useXxx.ts`，不要在组件间复制粘贴。
- 全局共享状态（用户信息、主题、当前会话、消息等）一律用 **Pinia setup 风格 store**，不要用 `provide/inject` 兜全局状态，也不要在模块里放裸的单例响应式对象。
  - 统一用 `defineStore('xxx', () => { ... })` 写法，store 文件放 `src/stores/`。
  - 组件里读取 store 时用 `storeToRefs(store)` 解构响应式状态，方法直接 `store.xxx()` 调用。
  - store 只负责状态与业务动作，**网络请求一律走 `src/api/`**（见 §7），不在 store 里裸写请求。
  - 不要在 store 之外再维护一份同义状态（例如既用路由表示当前 Tab、又用 store 存一份当前 Tab），避免双份事实来源。

### 4.4 路由约定
- 用 **vue-router** history 模式，`src/router/index.ts` 统一配置；路由以模块名命名（`study` / `interview` / `note`），名称复用 `ModuleKey` 常量。
- 页面组件放 `src/views/`，路由一律**懒加载**（`component: () => import('@/views/Xxx.vue')`）。
- **当前模块 / Tab 的唯一事实来源是路由**，不要再用 store 或组件本地状态另存一份。组件统一用 `useCurrentModule()`（读路由 `name`）派生当前模块。
- **模块决定数据源**：学习室 / 面试间（`study` / `interview`）展示会话（`stores/conversation.ts`），笔记本（`note`）展示笔记（`stores/note.ts`）；侧栏据此切换列表与「新建」按钮文案。会话的选中态按模块分别记录（`conversation.activeByModule`），保证切模块时各自高亮不互相串用。
- 切换模块用 `RouterLink`（配 `active-class` 控制高亮），不要在 `@click` 里手写 `router.push` 拼字符串路径。
- 未匹配路径需配置兜底重定向（`/:pathMatch(.*)*`）。
- history 模式在**生产环境需要服务端配置 SPA fallback**（所有路径回退到 `index.html`），部署时不要遗漏。
- **鉴权路由**：`/login` 为公开路由，其余业务路由由 `router.beforeEach` 校验本地令牌；未登录跳登录页并携带 `redirect`，登录成功后回跳。`AppShell` 作为布局路由（嵌套子路由）承载业务页面，登录页不套布局。

### 4.5 富文本编辑器（wangEditor-next）

笔记本模块的正文编辑统一用 wangEditor-next，`Editor` / `Toolbar` 组件来自 `@wangeditor-next/editor-for-vue`：

- **必须**在引入处 `import '@wangeditor-next/editor/dist/css/style.css'`，否则编辑器无样式。
- 内容用 `v-model` 双向绑定；外部切换文档时直接改绑定的 ref 即可（组件内部会自动 `setHtml`），不要手动写实例内容。
- `onCreated` / `onChange` 等回调**只能**通过组件事件（`@onCreated` / `@onChange`）监听，写进 `defaultConfig` 会直接抛错。
- 组件卸载时**必须**调用 `editor.destroy()`，否则残留 DOM 与事件监听。
- 工具栏能力用 `toolbarKeys` 显式声明，只保留设计稿需要的按钮；`uploadImage` 依赖后端上传接口，未接入前用 `insertImage`（填图片 URL）代替。

---

## 5. TypeScript 规范

- **禁止 `any`**，不确定用 `unknown` 并做类型收窄；确需逃逸用 `// @ts-expect-error 原因` 并写明理由。
- 接口/响应数据结构必须定义类型，放在 `types/` 或就近的 `api/xxx.ts`。
- 注意 `tsconfig.app.json` 已开启以下约束，编写代码时需遵守：
  - `noUnusedLocals` / `noUnusedParameters`：**禁止未使用的变量与参数**（构建会报错）。
  - `erasableSyntaxOnly: true`：**禁止 TS `enum`、`namespace`、构造函数参数属性**等运行时语法。枚举请改用 `as const` 对象 + 联合类型：

    ```ts
    // ✅ 正确
    export const QuizMode = {
      Quick: 'quick',
      Deep: 'deep',
    } as const
    export type QuizMode = (typeof QuizMode)[keyof typeof QuizMode]

    // ❌ 禁止
    // enum QuizMode { Quick, Deep }
    ```
  - `noFallthroughCasesInSwitch`：`switch` 禁止 case 穿透。
- 类型导入优先使用 `import type { ... }`。

---

## 6. 样式规范

- 组件样式默认 `<style scoped>`；仅全局样式（重置、变量）放 `src/styles/`。
- 设计变量（颜色、间距、圆角、字号）统一用 CSS 变量集中在 `src/styles/`，组件内引用变量，**禁止散落魔法值**。
- 类名使用 kebab-case；复杂组件可用 BEM 风格（`card__title--active`）。
- 避免 `!important`；避免深层选择器穿透 scoped（确需穿透用 `:deep()`）。
- 移动端优先，响应式断点统一管理，不写死设备尺寸。
- 本项目含语音/播客交互，注意 `prefers-reduced-motion` 等无障碍与动效降级。

---

## 7. 接口 / 请求层与 Mock 约定

### 7.1 请求层（`src/api/`）

- 所有网络请求**统一走 `src/api/`**，禁止在组件或 store 中裸写 `fetch` / `XMLHttpRequest` / `axios`。
- 统一入口 `src/api/request.ts`，基于 **axios** 封装（唯一实例 + 请求 / 响应拦截器）：
  - 请求拦截器自动附加 `Authorization: Bearer <access_token>`；响应拦截器统一解包信封、弹出全局错误提示。
  - **必须固定 `adapter: 'xhr'`**：开发期 Mock.js 通过替换全局 `XMLHttpRequest` 拦截请求，显式固定适配器可避免未来切换到 fetch 适配器导致 Mock 失效（见 §7.2）。
- 请求基址来自 `import.meta.env.VITE_API_PREFIX`（默认 `/api`），**禁止硬编码后端 host 或端口**。
- 统一响应结构约定为信封 `{ code, message, data }`：`code === 200` 视为成功并**解包返回 `data`**，否则抛 `ApiError`（携带 `code` / `message`）。后端错误响应的 `code` 复用 HTTP 状态码（404 / 409 / 422 / 500），并额外带 `detail`（面向开发者定位）。
- **鉴权与续期**：请求层自动为受保护接口附加 `Authorization: Bearer <access_token>`；收到 `401` 时用本地 `refresh_token` 调 `/api/auth/refresh`（并发请求共享同一次刷新）并重试一次，刷新失败则清理本地令牌并跳转登录页。令牌存于 localStorage，读写统一走 `src/utils/token.ts`。
- **头像上传**：注册页选择头像时**只做本地预览**（`URL.createObjectURL`，限制 JPG / PNG / WebP / GIF 且 ≤ 2MB），不发请求；点击注册后按「建号 → 自动登录拿令牌 → `POST /api/files` 上传」执行，上传用 `FormData`（字段 `file`），请求层自动带 Bearer。后端自动识别类型：图片会更新头像并返回 `{url, md5, size, kind}`，文档只保存。头像上传失败不阻断登录。当前用户（含 `avatar` URL）由 `stores/auth.ts` 全局维护，顶栏从 store 读取展示。通用文件接口封装在 `src/api/file.ts`。
- **错误提示**：请求层统一弹出后端 `message`（短时间去重，可用 `silent` 关闭），调用方不要重复提示同一错误。
- 每个接口在 `src/api/xxx.ts` 中定义明确的请求 / 响应类型，并按业务域拆分文件（如 `conversation.ts` / `interview.ts` / `note.ts`）。
- 流式接口（AI 对话、语音播报等）需封装为独立的 SSE / 流式工具，并处理中断与错误重连。

### 7.2 Mock 层（`src/mock/`，仅开发环境）

- **仅开发环境加载**：在 `main.ts` 中以 `if (import.meta.env.DEV) await import('./mock')` 动态引入，**生产构建不含 mockjs**。
- **与 axios 的兼容方式**：Mock.js 通过替换全局 `XMLHttpRequest` 生效，`src/api/request.ts` 的 axios 实例固定 `adapter: 'xhr'`，因此 Mock 对 axios 请求同样生效。**禁止把 axios 改为 fetch 适配器**；必须保证 `./mock` 在首个请求发出前加载。
- 用 `Mock.mock(rurl, rtype, handler)` 拦截请求：`rurl` 支持字符串或正则，`rtype` 为小写方法名；正则捕获组可用于提取路径参数（如会话 id）。
- 用 `Mock.setup({ timeout })` 模拟网络延迟；用 `Mock.Random`（`guid` / `integer` / `pick` 等）生成易变字段（id、时间戳、AI 随机回复）。
- **业务关键文案保持固定**（如欢迎语、示例对话），不要用随机值，避免还原度与可测性下降。
- 接真实后端时：删除/停用 `src/mock/` 的拦截即可，`src/api/` 与业务代码无需改动。

---

## 8. 环境变量约定

- **只有以 `VITE_` 开头的变量才会注入前端代码**；其余（如 `API_PROXY_TARGET`）仅供 `vite.config.ts` 在构建/开发服务器侧读取，**业务代码中禁止访问**。
- 环境文件：`.env.development`（开发）、`.env.test`（测试）、`.env.production`（生产）。
- 新增环境变量时，**必须同步更新 `src/env.d.ts` 的 `ImportMetaEnv` 接口**，保证类型提示。
- **密钥、Token 等敏感信息一律不得写入任何 `.env*` 或前端代码**（前端产物对用户完全可见）；敏感配置放后端。
- 提交 `.env.development / .env.test / .env.production`（非敏感）；不提交本地 `.env`（根 `.gitignore` 已忽略）。

---

## 9. 资源与静态文件

- **会被构建处理**（哈希、压缩、引用）的资源放 `src/assets/`，通过 `import` 使用。
- **原样拷贝**、需固定路径访问的资源放 `public/`，用绝对路径引用（如 `/favicon.svg`）。
- 大体积媒体（音频/视频）评估按需加载，避免拖慢首屏。
- 图片优先使用现代格式（webp/avif），并显式设置宽高避免布局抖动。

---

## 10. Git 规范

- 提交信息遵循 **Conventional Commits**（与仓库现有历史一致）：

  ```
  <type>(<scope>): <描述>

  type: feat | fix | docs | style | refactor | perf | test | chore | build | ci
  scope: learn | interview | note | resume | api | ui | deps ...
  ```

  示例：`feat(interview): 新增模拟面试语音录制组件`
- 分支策略：`main` 保持可发布；功能分支 `feature/xxx`，修复 `fix/xxx`，分支名用 kebab-case。
- 小步提交，一次提交聚焦一件事；**禁止把格式化/无关改动混入功能提交**。
- 提交前确保 `pnpm build` 通过（含 `vue-tsc` 类型检查）。
- **未经明确授权，不要 `git push`、不要改历史、不要强推。**

---

## 11. 代码质量与命令

```bash
pnpm install     # 安装依赖
pnpm dev         # 本地开发（默认 http://localhost:5173，代理 /api → API_PROXY_TARGET）
pnpm build       # 类型检查 + 生产构建（提交前必跑）
pnpm preview     # 预览生产构建（默认 4173）
```

- 提交前必须保证 `pnpm build` 无错误、无类型报错。
- `pnpm dev` 会自动加载 mock 层（`src/mock/`，仅 DEV），无需手动切换；`pnpm build` / `pnpm preview` 不含 mock。
- **待引入（引入前需团队确认）**：
  - ESLint + Prettier 统一风格与自动修复；
  - 单元测试（Vitest）/ 组件测试框架；
  - Git hook（husky + lint-staged）在提交时自动检查。
- 在引入上述工具前，靠本规范人工约束；引入后以工具配置为准并更新本文件。

---

## 12. 与 AI 助手协作约定

- AI 改动代码前**先阅读相关文件**，理解现有实现再动手，不要凭猜测修改。
- 严格遵守本规范；如与规范冲突，以本规范为准，并说明冲突点。
- **不擅自引入新依赖、不擅自大改目录结构或架构**；此类改动需先说明理由并取得确认。
- 不生成或提交任何密钥、凭据、真实用户数据。
- 不执行未经确认的破坏性或对外可见操作（推送、发 PR、改 CI、删分支等）。
- 保持改动范围聚焦：修 bug 就只修 bug，不做顺带重构或"顺手优化"。

---

## 13. 禁止事项（红线）

- ❌ 硬编码后端地址 / 端口 / 密钥。
- ❌ 使用 `any`、TS `enum`、`namespace`、构造函数参数属性。
- ❌ 在组件或 store 中裸写 `fetch` / `XMLHttpRequest` / `axios`，绕过 `src/api/`。
- ❌ 除路由外再维护一份「当前模块 / Tab」状态（双份事实来源）。
- ❌ 在模板里写复杂逻辑或副作用。
- ❌ 组件间复制粘贴逻辑（应抽 composable）。
- ❌ 提交 `node_modules/`、`dist/`、`.env`、本地配置。
- ❌ 混用包管理器（只用 pnpm）。
- ❌ 未授权情况下 push / 强推 / 改历史。
