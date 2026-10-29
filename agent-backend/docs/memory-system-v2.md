# 记忆系统设计（V2）

> 版本：V2.1（2026-10-27）
> 前置版本：[`memory-system-v1.md`](memory-system-v1.md)（Redis 工作记忆 + MySQL 短期历史）
> V2 新增：用户画像长期记忆 —— 意图判断、SystemMessage 注入、后台异步抽取。
> V2.1 新增：基础五项画像（目标岗位 / 工作年限 / 目标职级 / 已掌握技能 / 薄弱点）纳入抽取范围；三项必填缺失时普通消息也触发抽取；前端新会话开场白表单为主写入路径。

实现位置：`app/services/long_term_memory.py`、`app/services/memory_service.py`、`app/services/ai/prompt_layer.py`、`app/services/chat_service.py`。

> 三层记忆的端到端链路、Redis 工作记忆的缓存读/写/过期路径、三个意图判断的底层原理与示意图，见 [`memory-system-flow.md`](memory-system-flow.md)。

---

## 1. V2 新增能力

| 能力 | 说明 |
| --- | --- |
| 长期画像存取 | 9 个业务字段：`target_job` / `years_experience` / `target_level` / `target_skills` / `weak_topics` / `learning_goal` / `learning_style` / `interview_focus` / `long_term_summary` |
| 写入意图判断 | fastembed + `BAAI/bge-small-zh-v1.5` 计算语义相似度，判断消息是否在描述用户自己 |
| 画像注入 | 画像格式化为 `SystemMessage` 插在 history 最前，链路执行前合并进 system_prompt |
| 异步更新 | 流式回复结束后后台线程调 LLM 抽取画像，写回 MySQL，不阻塞 SSE |
| 必填补全 | 三项必填缺失时，普通消息（≥ 2 字）也会触发抽取；前端开场白表单为主写入路径（V2.1） |

---

## 2. 数据模型

`user_profiles`（一人一行，`user_id` 唯一）：

| 字段 | 类型 | 来源 | 用途 |
| --- | --- | --- | --- |
| `target_job` / `years_experience` / `target_level` | `VARCHAR(64)` / `Integer` / `VARCHAR(32)` | 前端开场白表单（必填）或对话自动抽取 | 提示词变量注入 + 画像注入 |
| `target_skills` / `weak_topics` | JSON 数组 | 前端开场白表单（选填）或对话自动抽取 | 提示词变量注入 + 画像注入 |
| `learning_goal` | `VARCHAR(255)` | 对话自动抽取 | 学习目标 |
| `learning_style` | `VARCHAR(255)` | 对话自动抽取 | 学习偏好 |
| `interview_focus` | JSON 数组 | 对话自动抽取 | 面试重点 / 方向 |
| `long_term_summary` | `TEXT` | 对话自动抽取（滚动合并） | 长期画像摘要 |

`profile_service.create_or_update()` 允许写入全部 9 个业务字段（后台抽取以最新表述为准），白名单仍过滤 `user_id` 等非业务列。

---

## 3. 读取链路：画像如何进入提示词

```mermaid
flowchart TD
    A["MemoryService.load_context(user_id, session_id, user_text, enable_long_term=True)"] --> B["工作记忆 / MySQL 短期历史<br/>（V1 逻辑）"]
    B --> C["Redis seed<br/>只写 Human / AI 消息"]
    C --> D{"enable_long_term？"}
    D -- 否 --> H
    D -- 是 --> E["LongTermMemory.load_memory_context(user_id)"]
    E --> F["MySQL 读取 user_profiles<br/>格式化为【用户画像】文本"]
    F --> G["history 最前插入 SystemMessage"]
    G --> H["返回 {history, input}"]
    H --> I["prompt_layer.merge_history_system_messages()"]
    I --> J["SystemMessage 从 history 移除<br/>内容追加到 system_prompt 末尾"]
    J --> K["最终消息结构：<br/>system（基础规则 + 画像）<br/>history（Human / AI）<br/>human（当前问题）"]
    K --> L["模型"]
```

关键顺序：**先 `seed()`，后注入画像**。如果先注入，冷启动回填会把 `SystemMessage` 当成普通消息写进 Redis，污染后续轮次。

写入路径（V2.1）：前端在**新会话空聊天区**展示开场白表单，用户填写后经资料 CRUD 接口（`POST /api/profiles` / `PUT /api/profiles/me`）直接写库；对话抽取只是补充。卡片在资料未填时出现、可跳过，填写或后台回填齐全后不再展示。读取链路不区分字段来源。

---

## 4. 写入链路：对话如何更新画像

```mermaid
flowchart TD
    A["用户提问"] --> B["chat_service.prepare_stream"]
    B --> C["LongTermMemory.should_write(text, user_id)"]
    C --> D{"语义相似度 ≥ 0.6？"}
    D -- 否 --> E["正常 RAG 检索<br/>（should_retrieve 判定）"]
    D -- 是 --> F["跳过 RAG 检索<br/>profile_intent = True"]
    E --> G["missing_required_fields(user_id)"]
    F --> G
    G --> G2{"意图命中，或必填缺失<br/>且消息 ≥ 2 字？"}
    G2 -- 否 --> H["profile_update = False"]
    G2 -- 是 --> I["profile_update = True"]
    H --> J["模型流式生成"]
    I --> J
    J --> K["MySQL 回写回复 status=1"]
    K --> L["工作记忆 append_turn（V1）"]
    L --> M{"profile_update？"}
    M -- 否 --> N["结束，下发 done"]
    M -- 是 --> O["取最近 4 条历史 Human/AI<br/>+ 本轮 AI 回复"]
    O --> P["submit_profile_update_async<br/>启动 daemon 线程（立即返回）"]
    P --> Q["LLM 抽取 JSON：9 个业务画像字段"]
    Q --> R{"有效字段？"}
    R -- 否 --> S["只记日志，不写库"]
    R -- 是 --> T["profile_service.create_or_update<br/>upsert user_profiles"]
```

要点：

- **意图命中必写**：普通知识问答不会触发画像更新，避免无意义的模型调用。
- **必填缺失兜底（V2.1）**：`target_job` / `years_experience` / `target_level` 任一缺失时，去空白后 ≥ 2 字的普通消息也触发抽取，用于接住「3 年」「后端开发」这类简短回答；单字确认语（如「好」）不触发。该路径**照常检索 RAG**。
- **意图命中时跳过 RAG**：画像类表达不需要知识库资料，避免把「我想转行」误当成检索问题。
- **异步执行**：线程启动后立即返回，LLM / 数据库失败只记日志，不影响 SSE `done`。
- **只看最近 4 条**：避免把整段历史塞进抽取提示词，控制成本与时延。

---

## 5. 意图判断

```text
用户消息 ──► fastembed 向量 ──┐
                              ├─► 余弦相似度 ──► max ≥ 0.6 ?
12 条意图示例 ──► 向量（缓存）┘
```

示例覆盖：目标岗位、学习计划、学习偏好、面试关注点、薄弱点、技能栈（如「我熟悉 Python、MySQL 和 Redis」）等自我描述。模型不可用或相似度不足时返回 `False`，对话继续走普通链路；必填缺失时的兜底触发见 §4。

---

## 6. 多轮时序

```mermaid
sequenceDiagram
    autonumber
    participant FE as 前端
    participant CS as chat_service
    participant LT as LongTermMemory
    participant MS as MemoryService
    participant DB as MySQL
    participant LLM as 模型

    Note over FE,DB: 画像读取（每轮提问）
    FE->>CS: 提问
    CS->>LT: should_write(问题, user_id)
    LT-->>CS: True / False
    CS->>MS: load_context(user_id, session_id, input)
    MS->>DB: 读 user_profiles
    DB-->>MS: 画像字段
    MS-->>CS: history 最前含 SystemMessage
    CS->>LLM: system（含画像）+ 历史 + 当前问题
    LLM-->>FE: 流式 delta

    Note over FE,DB: 画像写入（意图命中 / 必填缺失）
    CS->>DB: 回写回复 status=1
    CS->>MS: append_turn（工作记忆）
    CS->>LT: submit_profile_update_async(最近 4 条 + 回复)
    LT->>LLM: 抽取 9 个业务画像字段 JSON
    LLM-->>LT: JSON
    LT->>DB: upsert user_profiles
```

另有一条前置写入路径：新会话空聊天区由前端展示开场白表单，用户提交后直接调资料 CRUD 接口写 `user_profiles`，不经过 SSE；画像读取与对话链路无感知。

---

## 7. 参数

| 参数 | 值 | 位置 |
| --- | --- | --- |
| 向量模型 | `BAAI/bge-small-zh-v1.5` | `app/services/embedding.py` `EMBED_MODEL`（长期记忆与流程总控共用） |
| 意图相似度阈值 | 0.6 | `INTENT_THRESHOLD` |
| 意图判断最短长度 | 4 字 | `INTENT_MIN_CHARS` |
| 意图示例数量 | 12 条 | `PROFILE_INTENT_EXAMPLES` |
| 必填补全触发最短长度 | 2 字 | `PROFILE_ANSWER_MIN_CHARS` |
| 必填字段 | `target_job` / `years_experience` / `target_level` | `REQUIRED_PROFILE_FIELDS` |
| 画像更新上下文 | 最近 4 条历史 + 本轮回复 | `chat_service._recent_context()` |
| 摘要上限 | 2000 字 | `SUMMARY_MAX_CHARS` |
| 单字段上限 | 255 字 | `FIELD_MAX_CHARS` |
| 面试重点上限 | 10 项 × 50 字 | `FOCUS_MAX_ITEMS` / `FOCUS_ITEM_MAX_CHARS` |
| 技能 / 薄弱点上限 | 20 项 × 50 字 | `LIST_MAX_ITEMS` / `LIST_ITEM_MAX_CHARS` |
| 工作年限范围 | 0..60（0 = 应届 / 无经验） | `YEARS_MIN` / `YEARS_MAX` |
| 岗位 / 职级上限 | 64 / 32 字 | `JOB_MAX_CHARS` / `LEVEL_MAX_CHARS` |

---

## 8. 降级行为

| 场景 | 行为 | 对对话的影响 |
| --- | --- | --- |
| fastembed 未安装 / 模型加载失败 | `should_write()` 记 WARNING 并返回 False | 不跳过 RAG，不更新画像 |
| 画像读取失败 | `load_memory_context()` 返回空串 | 本轮无画像，其余记忆正常 |
| LLM 抽取失败 / JSON 非法 | 后台线程记 WARNING，不写库 | 本轮回复正常 |
| 抽取结果为空 | 不写库 | 本轮回复正常 |
| 并发更新同一用户 | 后写覆盖先写 | 可能丢失其中一次抽取结果（V2 边界） |
| 首次调用 fastembed | 下载模型，可能耗时 | 首次进入意图判断的请求变慢 |

---

## 9. 与 V1 的差异

| 维度 | V1 | V2 |
| --- | --- | --- |
| 记忆范围 | 单会话：Redis 原文 + 摘要 | 新增跨会话用户画像 |
| 历史注入 | 只注入 Human / AI 消息 | 画像以 `SystemMessage` 注入并合并进 system_prompt |
| 写入触发 | 每轮成功后写工作记忆 | 命中画像意图，或必填缺失且消息 ≥ 2 字时后台更新画像（V2.1） |
| RAG | 每轮按意图判断 | 命中画像意图时跳过（必填补全路径不跳过） |
| 外部依赖 | Redis / MySQL / LLM | 新增 fastembed 本地模型 |

---

## 10. V2 边界与后续

- 画像更新按「最近 4 条 + 本轮回复」抽取，长对话早期信息依赖 `long_term_summary` 滚动保留。
- 后台抽取覆盖全部 9 个业务字段，词汇型字段（技能 / 薄弱点）由模型输出「合并后的完整列表」；抽取出错时可能截断用户手工填写的内容，暂无版本历史可回滚。
- 必填缺失时的兜底抽取只在消息 ≥ 2 字时触发，过长或含糊的表达可能抽不出字段（不写库，等待后续轮次）。
- 开场白表单的跳过状态仅保存在前端内存，刷新页面后会重新出现，直到资料填写齐全。
- 后台线程无重试与队列，失败即丢弃（日志可追踪）。
- 意图判断阈值固定 0.6，未按用户或场景自适应。
- fastembed 模型在进程内单例缓存，多实例各自加载。
