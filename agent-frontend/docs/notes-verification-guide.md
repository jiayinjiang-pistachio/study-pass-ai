# 笔记本 · 完整链路验证指南

> **状态**：前端已改造为 `note_id` 驱动（2026-11-02，分支 `interview-rtc`）
> **范围**：笔记列表 / 详情 / 新建 / 自动保存 / 手动保存 / 切换 / 删除 / 空状态，覆盖
> 页面 → Pinia → `src/api/notes.ts` → 后端 `/api/notes` → MySQL 的完整链路
> **相关实现**：
> [`src/views/NoteRoom.vue`](../src/views/NoteRoom.vue)、
> [`src/components/note/NotebookEditor.vue`](../src/components/note/NotebookEditor.vue)、
> [`src/stores/note.ts`](../src/stores/note.ts)、
> [`src/api/notes.ts`](../src/api/notes.ts)、
> [`src/components/sidebar/NoteList.vue`](../src/components/sidebar/NoteList.vue)
>
> **后端实现**：
> [`app/routers/note.py`](../../agent-backend/app/routers/note.py)、
> [`app/services/note_service.py`](../../agent-backend/app/services/note_service.py)、
> [`app/db/note_repo.py`](../../agent-backend/app/db/note_repo.py)、
> [`app/schemas/note.py`](../../agent-backend/app/schemas/note.py)
>
> **最后更新**：2026-11-02

---

## 0. 链路总览

```
┌────────────────────────────── 浏览器（agent-frontend） ──────────────────────────────┐
│ NoteRoom.vue / NoteList.vue                                                          │
│        │ 选择 / 新建 / 删除 / 重命名                                                  │
│        ▼                                                                             │
│ stores/note.ts                                                                       │
│   noteList / activeNoteId / activeNote                                               │
│   draftTitle / draftContent  ── 600ms 防抖 ──► saveActiveNote()                      │
│   dirty / saving                                                                     │
│        │                                                                             │
│        ▼                                                                             │
│ api/notes.ts（snake_case 入参，返回后归一为 camelCase + 毫秒时间戳）                  │
│        │                                                                             │
│        ▼                                                                             │
│ api/request.ts（自动带 Bearer、统一解包 {code,message,data}、401 续期）              │
└──────────────────────────────────────┬───────────────────────────────────────────────┘
                                       │ HTTP /api（Vite 代理）
                                       ▼
┌────────────────────────────── agent-backend ─────────────────────────────────────────┐
│ routers/note.py        路径 / 鉴权 / response_model                                  │
│        ▼                                                                             │
│ schemas/note.py        入参校验（title 1..255、content 1..200000）                    │
│        ▼                                                                             │
│ services/note_service.py   user_id 隔离、session 归属校验、局部更新                   │
│        ▼                                                                             │
│ db/note_repo.py        SQLAlchemy → MySQL notes 表                                   │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

### 0.1 必须先明确的 4 个契约

| # | 事实 | 对验证的影响 |
| --- | --- | --- |
| 1 | 详情 / 创建 / 更新接口的笔记对象**直接在 `data` 中**，不是 `data.note` | 看 Network 原始响应时是 `data.{id,title,...}`；`request.ts` 解包后前端拿到的就是笔记对象 |
| 2 | 列表接口**不返回正文 `content`**，且为分页结构 `{items,total,page,page_size}` | 列表只能验证标题/时间；正文必须在 `GET /api/notes/{id}` 验证 |
| 3 | `POST /api/notes` **必须传 `session_id`**，且会话必须属于当前用户 | 前端在首次「新建笔记」时自动复用/创建一个 `session_mode=2` 的隐藏笔记会话 |
| 4 | 后端 `content` 存 Markdown；前端编辑器存 HTML | 加载时若内容是 Markdown 才转 HTML；已是 HTML 则原样展示，避免二次转义 |

### 0.2 数据字段映射（后端 → 前端）

| 后端字段 | 前端字段 | 说明 |
| --- | --- | --- |
| `id` | `id` | `number` |
| `session_id` | `sessionId` | 隐藏笔记会话 id |
| `note_type` | `noteType` | 前端默认 `manual` |
| `title` / `content` | `title` / `content` | 列表无 `content` |
| `tags` | `tags` | `string[]` |
| `created_at` / `updated_at` | `createdAt` / `updatedAt` | 后端为**秒**，前端统一乘 1000 转**毫秒** |

---

## 1. 启动环境

### 1.1 后端（默认 8000）

```bash
cd agent-backend
source .venv/bin/activate
alembic upgrade head
uvicorn app.main:app --reload --reload-exclude 'logs/*' --port 8000
```

`.env` / `.env.dev` 至少需要：

| 变量 | 必需 | 用途 |
| --- | --- | --- |
| `MYSQL_URL` | 是 | `notes` / `sessions` 表 |
| `JWT_SECRET` | 是 | 登录与接口鉴权 |

打开 `http://127.0.0.1:8000/docs`，确认 `notes`、`sessions` 两组接口可见。

### 1.2 前端（默认 5173）

```bash
cd agent-frontend
pnpm install
pnpm dev
```

打开 `http://localhost:5173/login` 并登录。

> **Mock 已移除**：`src/mock/index.ts` 不再引入 `notes`，开发环境请求会直接打到真实后端。
> 如果仍看到「前端技术面试准备 / 数据库优化策略」等示例笔记，说明 dev server 还在使用旧模块，
> 重启 `pnpm dev` 后强制刷新页面。

### 1.3 启动后自检

| 检查项 | 预期 |
| --- | --- |
| 后端 `/health` | `200`，数据库连通 |
| 前端 Network | 请求 `/api/notes`，响应 JSON 为 `{code:200,...}`，不是 Mock 数据 |
| 浏览器 Console | 无 `mockjs` 拦截笔记请求的日志 |

---

## 2. 后端接口链路验证（先独立验证，再验证页面）

以下命令默认：

```bash
BASE=http://127.0.0.1:8000/api
TOKEN=<登录接口返回的 access_token>
AUTH="Authorization: Bearer $TOKEN"
```

### 2.1 登录并获取令牌

```bash
curl -s -X POST "$BASE/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"<用户名>","password":"<密码>"}'
```

预期：

```json
{ "code": 200, "message": "ok", "data": { "access_token": "...", "refresh_token": "..." } }
```

把 `access_token` 填入 `TOKEN`。未带令牌访问 `/api/notes` 应返回 `401`。

### 2.2 准备笔记归属会话（`session_mode=2`）

这是笔记创建的前置条件。前端会自动完成，手工验证时先查再建：

```bash
# 查询已有的笔记会话（取第一条即可）
curl -s "$BASE/sessions?page=1&page_size=1&session_mode=2" -H "$AUTH"

# 没有则创建
curl -s -X POST "$BASE/sessions" -H "$AUTH" \
  -H 'Content-Type: application/json' \
  -d '{"title":"笔记本","session_mode":2}'
```

记下返回 `data.id` 为 `SESSION_ID`。

> `session_mode=2` 的会话只作为笔记归属容器，**不会**出现在学习室 / 面试间的会话列表
> （它们分别按 `session_mode=0/1` 查询）。不传 `session_mode` 调 `/api/sessions` 时会看到它，这是正常现象。

### 2.3 创建笔记

用 Markdown 正文验证后续转换：

```bash
curl -s -X POST "$BASE/notes" -H "$AUTH" \
  -H 'Content-Type: application/json' \
  -d '{
    "session_id": '"$SESSION_ID"',
    "note_type": "manual",
    "title": "数据库复习",
    "content": "## 索引原理\n\n- B+ 树\n- 回表"
  }'
```

预期要点：

- `data` 直接是笔记对象，包含 `id / session_id / title / content / created_at / updated_at`
- `source_run_id` 由后端生成 UUID
- 不包含 `user_id`
- 标题 / 正文原样保存（**不做 Markdown 转换**，转换发生在前端加载时）

记下 `data.id` 为 `NOTE_ID`。

### 2.4 列表：分页且不含正文

```bash
curl -s "$BASE/notes?page=1&page_size=20" -H "$AUTH"
```

预期：

- 顶层为 `{items,total,page,page_size}`
- `items[0]` **没有 `content`**
- 按 `created_at DESC, id DESC` 排序（最新创建的在前）

可继续验证过滤与检索：

```bash
curl -s "$BASE/notes?note_type=manual" -H "$AUTH"
curl -s "$BASE/notes?keyword=索引" -H "$AUTH"     # 标题与正文都参与模糊匹配
```

### 2.5 详情：包含正文

```bash
curl -s "$BASE/notes/$NOTE_ID" -H "$AUTH"
```

预期 `data.content` 仍是 Markdown 原文，例如以 `## 索引原理` 开头。

### 2.6 局部更新：只改标题

```bash
curl -s -X PUT "$BASE/notes/$NOTE_ID" -H "$AUTH" \
  -H 'Content-Type: application/json' \
  -d '{"title":"数据库索引复习"}'
```

预期：

- `data.title` 变为新标题
- `data.content` **保持原 Markdown 不变**
- `updated_at` 刷新

### 2.7 局部更新：正文写回 HTML

前端保存时提交的是编辑器 HTML，可手工模拟：

```bash
curl -s -X PUT "$BASE/notes/$NOTE_ID" -H "$AUTH" \
  -H 'Content-Type: application/json' \
  -d '{"content":"<h2>索引原理</h2><ul><li>B+ 树</li><li>回表</li></ul>"}'
```

预期 `data.content` 原样保存为 HTML。后续前端加载应识别为 HTML，不再转换。

### 2.8 删除

```bash
curl -s -X DELETE "$BASE/notes/$NOTE_ID" -H "$AUTH"
curl -s "$BASE/notes/$NOTE_ID" -H "$AUTH"   # 预期 404
```

### 2.9 异常用例

| 用例 | 请求 | 预期 |
| --- | --- | --- |
| 未登录 | `GET /api/notes`（无令牌） | `401` |
| 会话不存在 | `POST /api/notes` 传不存在的 `session_id` | `404 会话不存在` |
| 越权创建 | 用他人 `session_id` 创建 | `404 会话不存在` |
| 越权读取 | `GET /api/notes/{他人的id}` | `404 笔记不存在` |
| 空标题 | `title` 去空白后为空 | `422` |
| 空正文 | `content` 去空白后为空 | `422` |
| 标题超长 | `title` > 255 字 | `422` |
| 正文超长 | `content` > 200000 字 | `422` |
| 分页越界 | `page_size=101` | `422` |
| 重复删除 | 删除已删除的 id | `404` |

### 2.10 数据库核对

```sql
-- 笔记记录（正文只看前 80 字，避免刷屏）
SELECT id, user_id, session_id, source_run_id, note_type, title,
       LEFT(content, 80) AS content_preview, created_at, updated_at
FROM notes
WHERE user_id = <user_id>
ORDER BY created_at DESC, id DESC;

-- 隐藏笔记会话
SELECT id, title, session_mode
FROM sessions
WHERE user_id = <user_id> AND session_mode = 2;
```

核对点：

- `notes.session_id` 指向 `session_mode=2` 的会话
- 前端保存后 `content` 为 HTML（`<p>` / `<h2>` / `<ul>` 等）
- 删除后记录消失；`updated_at` 在保存后变化

### 2.11 自动化回归

```bash
cd agent-backend
pytest tests/test_notes.py -v
```

覆盖：鉴权、创建 / 详情 / 列表 / 局部更新 / 删除、类型过滤、关键词检索、用户隔离、会话归属校验、字段校验。

---

## 3. 前端页面链路验证

进入左侧「笔记本」，下面每一项都可以在 DevTools → Network 中对照请求。

### 3.1 请求时序

| 操作 | 请求顺序 |
| --- | --- |
| 首次进入笔记本 | `GET /api/notes?page=1&page_size=100` → 若有笔记，`GET /api/notes/{id}`（取正文） |
| 点击「新建笔记」（首次） | `GET /api/sessions?...&session_mode=2` →（无则）`POST /api/sessions` → `POST /api/notes` |
| 点击「新建笔记」（后续） | 直接 `POST /api/notes`（会话 id 已缓存） |
| 编辑标题 / 正文 | 停止输入约 600ms 后 `PUT /api/notes/{id}` |
| 点击「保存」 | 立即 `PUT /api/notes/{id}` |
| 切换笔记 | 先 `PUT /api/notes/{旧id}`（仅当有改动）→ `GET /api/notes/{新id}` |
| 删除当前笔记 | `DELETE /api/notes/{id}`，然后选中下一篇时 `GET /api/notes/{下一篇id}` |

### 3.2 功能验证清单

| # | 操作 | 预期 |
| --- | --- | --- |
| 1 | 使用没有笔记的账号进入笔记本 | 显示空状态「暂无笔记，点击左侧「新建笔记」开始记录」 |
| 2 | 点击「新建笔记」 | 侧栏新增「无标题笔记」，编辑器可输入，标题输入框内容居中 |
| 3 | 查看 Network | 首次会先查/建 `session_mode=2` 会话，再 `POST /api/notes`；请求体含 `session_id / title / content` |
| 4 | 刷新页面 | 新笔记仍在列表，正文从详情接口恢复 |
| 5 | 打开一条后端为 Markdown 的笔记（如测评笔记或 2.3 创建的笔记） | 编辑器显示标题 / 列表等富文本，而不是 `##`、`-` 原文 |
| 6 | 打开 2.7 中已存 HTML 的笔记 | 内容正常展示，Network 中没有因加载立即触发的 `PUT` |
| 7 | 修改正文后等待约 600ms | 出现一次 `PUT /api/notes/{id}`，请求体包含最新 `title` 与 `content` |
| 8 | 保存完成后查看「保存」按钮 | 按钮置灰（无未保存改动）；保存中按钮显示 loading |
| 9 | 修改标题后点击「保存」 | 立即发送 `PUT`，成功后提示「已保存」 |
| 10 | 修改内容后立刻点击另一篇笔记 | 没有任何「未保存更改」弹窗；Network 先 `PUT` 旧笔记，再 `GET` 新笔记；旧笔记修改不丢失 |
| 11 | 切换到没有改动的笔记 | 不发送 `PUT`，直接 `GET` 新笔记 |
| 12 | 侧栏重命名当前笔记 | 标题立即更新，`PUT /api/notes/{id}` 只带 `title`（不带 `content`） |
| 13 | 删除非当前笔记 | 该笔记从列表消失，当前编辑器不变 |
| 14 | 删除当前笔记 | 自动选中列表中的下一篇；没有下一篇则选中上一篇 |
| 15 | 删除最后一篇笔记 | 显示空状态，编辑器卸载 |
| 16 | 从笔记本切到学习室再切回 | 再切回时笔记列表与当前选中项保留；离开前的改动已保存 |
| 17 | 账号 A 创建笔记后退出，登录账号 B | 看不到 A 的笔记；直接请求 A 的 `note_id` 返回 `404` |
| 18 | 查看 Network 列表响应 | `items[].content` 不存在；前端列表只展示标题 |
| 19 | 查看时间字段 | 前端 `updatedAt` 为 13 位毫秒时间戳（后端为 10 位秒） |

### 3.3 编辑器行为验证

| 场景 | 操作 | 预期 |
| --- | --- | --- |
| 初始化不误保存 | 打开一条 Markdown 笔记后不做任何操作，等待 1s | 不产生 `PUT`；`dirty=false`，保存按钮置灰 |
| HTML 不重复转换 | 打开 HTML 正文的笔记后保存一次，再刷新 | 内容结构不变，没有被包成 `<p>&lt;h2&gt;...` |
| 空标题 | 清空标题后等待自动保存 | 标题回退为原值（新建笔记为「无标题笔记」），请求不会 422 |
| 空正文 | 删除全部正文后等待自动保存 | 保存 `<p><br></p>` 等空段落 HTML，不会 422 |
| 快速连续输入 | 连续输入 2s | 只在停止输入后发送一次 `PUT`（防抖 600ms） |
| 保存失败 | 断开后端后修改内容 | 请求层提示错误；草稿保留，切换笔记会被阻止 |
| 离开页面 | 修改后立即点击顶部其他模块 | `onBeforeUnmount` 触发一次保存，不丢失修改 |

### 3.4 与旧实现的回归点

| 检查项 | 预期 |
| --- | --- |
| 侧栏标题 | 笔记本模块显示「新建笔记 / 历史笔记」，学习室和面试间仍显示「新建会话 / 历史会话」 |
| 学习 / 面试会话列表 | 不包含 `session_mode=2` 的隐藏笔记会话 |
| 测评生成的笔记 | 通过 `/notes` 正常出现在笔记本列表（`note_type=learning_quiz`） |
| Mock 数据 | 不再出现旧的 8 条示例笔记 |

---

## 4. 已知限制

| 限制 | 说明 |
| --- | --- |
| 列表最多 100 条 | 前端固定 `page_size=100`（后端上限也是 100），暂无「加载更多」 |
| 隐藏笔记会话 | 首次新建笔记会创建一个 `session_mode=2` 会话；删除该会话会导致后续新建笔记失败，刷新页面后前端会重新查询/创建 |
| 保存格式 | 前端保存后 `content` 为 HTML；后端不再区分 Markdown / HTML，仅原样存储 |
| HTML 判定 | 正文以常见块级标签开头时视为 HTML；纯文本 / Markdown 才转换 |
| 导出功能 | 侧栏「导出」仍为占位提示 |

---

## 5. 故障排查

| 现象 | 可能原因 | 处理 |
| --- | --- | --- |
| 列表为空，但数据库有数据 | 登录账号不一致 / 接口 403 | 检查 Network 中的 `Authorization` 与后端 `user_id` |
| 仍显示旧 Mock 示例笔记 | dev server 未重启或浏览器缓存 | 重启 `pnpm dev`，强制刷新；确认 `src/mock/index.ts` 没有引入 notes |
| 新建笔记报 `404 会话不存在` | 隐藏笔记会话被删除，或前端缓存了失效 id | 刷新页面后重试（会重新查询/创建会话） |
| 保存报 `422` | 标题 / 正文为空或超长 | 确认标题非空、正文 ≤ 200000 字 |
| 打开笔记后立刻产生 `PUT` | 编辑器对 HTML 的规范化回写 | 正常情况下 `syncEditorContent` 会把它同步为基线；若持续出现，检查是否每次切换都新建编辑器组件 |
| 打开笔记显示 `## 标题` 原文 | 内容被错误判定为 HTML | 检查正文是否以普通文本 / Markdown 开头；若是自定义标签开头，可调整为 Markdown |
| 编辑器空白但数据库有内容 | 详情接口失败 / 内容全为空标签 | 看 `GET /api/notes/{id}` 响应与 `data.content` |
| 切换笔记丢失修改 | 保存请求失败且未阻断切换 | 当前实现保存失败会阻止切换；检查 Network 中 `PUT` 是否 4xx/5xx |
| 删除后编辑器没有切换 | 列表为空或删除请求失败 | 检查 `DELETE` 响应与侧栏列表 |

---

## 6. 验收清单

- [ ] 后端 `pytest tests/test_notes.py -v` 全绿
- [ ] `GET /api/notes` 分页结构正确，列表项无 `content`
- [ ] `POST /api/notes` 返回的笔记对象直接在 `data` 中（不是 `data.note`）
- [ ] 创建时 `session_id` 属于当前用户，隐藏会话为 `session_mode=2`
- [ ] 详情接口返回 Markdown / HTML 原文
- [ ] `PUT /api/notes/{id}` 支持只改标题，正文保持不变
- [ ] 越权 / 不存在 / 空标题 / 空正文 / 超长字段返回预期状态码
- [ ] 前端进入笔记本：空列表显示空状态
- [ ] 新建笔记成功，标题输入框居中
- [ ] Markdown 正文在编辑器中正确转为富文本
- [ ] 已是 HTML 的正文不重复转换，加载后不立即触发保存
- [ ] 标题 / 正文修改后 600ms 防抖自动保存
- [ ] 手动保存按钮可用，保存中显示 loading，保存后置灰
- [ ] 切换笔记前静默保存，无「未保存更改」弹窗
- [ ] 删除当前笔记自动选中下一篇 / 上一篇，删空后显示空状态
- [ ] 侧栏重命名只更新标题
- [ ] 刷新页面、切换模块后数据与选中项符合预期
- [ ] 学习室 / 面试间列表不出现隐藏笔记会话
- [ ] `pnpm build` 通过（vue-tsc 无错误）
