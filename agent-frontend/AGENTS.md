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
| 包管理 | **pnpm** | 仓库内已有 `pnpm-lock.yaml`，禁止混用 npm/yarn |
| Node | 见 `.nvmrc`/团队约定 | 类型依赖 `@types/node` 24 |

> 当前脚手架**尚未引入**路由、状态管理、请求库、ESLint/Prettier、测试框架。下文凡涉及这些的部分均标注为「**约定 / 待引入**」，引入前需先在团队内确认。

---

## 2. 目录结构约定

```
src/
├── api/          # 接口层，按业务模块拆分（learn.ts / interview.ts / note.ts ...）
├── assets/       # 需要经构建处理的静态资源（图片、svg、字体）
├── components/   # 可复用组件（基础组件 / 业务通用组件）
├── composables/  # 组合式函数，命名 useXxx.ts
├── layouts/      # 布局组件
├── router/       # 路由配置（待引入）
├── stores/       # Pinia 状态（待引入）
├── styles/       # 全局样式、设计变量（tokens）
├── types/        # 全局类型定义
├── utils/        # 纯工具函数
├── views/        # 页面级组件（与路由一一对应）
├── App.vue
├── main.ts
└── env.d.ts      # 环境变量类型声明
```

规则：
- 新增目录前先确认是否真的必要，避免过度拆分。
- 页面放 `views/`，可复用组件放 `components/`，**不要把页面塞进 `components/`**。
- 一次性使用的组件就近放在其所属目录下，不强行抽到全局 `components/`。

---

## 3. 命名规范

| 对象 | 规范 | 示例 |
| --- | --- | --- |
| 组件文件 | PascalCase | `KnowledgeCard.vue` |
| 页面文件 | PascalCase | `InterviewReview.vue` |
| 组合式函数 | camelCase，`use` 前缀 | `useAudioPlayer.ts` |
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
- 全局共享状态（用户信息、主题、当前会话等）用 Pinia（**待引入**），不要用 `provide/inject` 兜全局状态。

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

## 7. 接口 / 请求层约定（待引入请求库）

- 所有网络请求**统一走 `src/api/`**，禁止在组件中裸写 `fetch` / `axios`。
- 请求基址来自 `import.meta.env.VITE_API_PREFIX`（默认 `/api`），**禁止硬编码后端 host 或端口**。
- 统一封装拦截器：处理 baseURL、超时、鉴权头、错误提示、统一响应结构解包。
- 每个接口定义明确的请求 / 响应类型。
- 流式接口（AI 对话、语音播报等）需封装为独立的 SSE/流式工具，并处理中断与错误重连。
- 请求层落地前，先在团队内确认选型（如 axios / fetch 封装），再统一引入。

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
- ❌ 在组件中裸写 `fetch` / `axios`，绕过 `src/api/`。
- ❌ 在模板里写复杂逻辑或副作用。
- ❌ 组件间复制粘贴逻辑（应抽 composable）。
- ❌ 提交 `node_modules/`、`dist/`、`.env`、本地配置。
- ❌ 混用包管理器（只用 pnpm）。
- ❌ 未授权情况下 push / 强推 / 改历史。
