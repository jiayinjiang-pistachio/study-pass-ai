# 提示词版本管理：技术方案与业务流程

> 本文说明 **prompt_templates 模块**的设计取舍、数据模型、分层实现与核心业务流程。
> 想直接跑通「初始化 → 注入 → 改资料 → 回滚」的全流程，见 [`prompt-injection-guide.md`](./prompt-injection-guide.md)。
> 上手指令（环境、缓存命令、排错）见 [`redis-guide.md`](./redis-guide.md)；开发规范见 [`AGENTS.md`](../AGENTS.md)。

---

## 一、目标与范围

### 1. 要解决的问题

- 学面通有 **7 个智能体**，每个智能体在不同业务场景需要独立提示词；
- 提示词需要**版本化**：可追溯、可对比、可一键回滚；
- 需要一份**公共通用约束**（如语言、输出格式），在任意智能体提示词之前统一生效；
- 提示词读取是高频操作，需要 **Redis 缓存**，但不能因 Redis 故障影响可用性。

### 2. 本期范围

| 已实现 | 说明 |
| --- | --- |
| 模板版本链 | 按 `(agent_name, scene)` 独立自增版本 |
| 公共通用模板 | 固定标识 `common` / `common`，读取时自动前置拼接 |
| 一键回滚 | 按 `template_id` 恢复历史版本 |
| Redis 缓存 | 启动预热 + 读取回源 + 变更刷新 |
| 智能体配置 | 7 个智能体映射，配置接口对外暴露 |
| 用户变量注入 | `user_profiles` + 验证 / 转换 / 填充三层管线，`full-prompt` 返回 `rendered_template` |

| 未包含 | 说明 |
| --- | --- |
| 新建版本（接口与服务层） | 暂未实现，待后续需求确定后补充 |
| 模板删除 / 版本列表接口 | 当前仅读取、回滚 |
| 管理员权限 | 任意登录用户均可管理模板，后续按角色收敛 |
| 变量占位符强校验 | `variables` 仅登记变量名，不校验正文中是否使用 |
| 聊天链路接入 | 聊天仍使用硬编码提示词，接入建议见第八节 |

---

## 二、核心概念

### 1. 术语

| 概念 | 含义 |
| --- | --- |
| `agent_name` | 智能体标识；公共通用模板固定为 `common` |
| `scene` | 业务场景；公共通用模板固定为 `common`，私有模板使用智能体专属场景 |
| 作用域（scope） | 唯一的 `(agent_name, scene)` 组合，一个作用域对应一条版本链 |
| `template_type` | `1`=私有模板，`2`=公共模板 |
| `version` | 作用域内自增版本号，从 `1` 开始 |
| `is_active` | `1`=当前生效，`0`=历史版本；每个作用域至多一条 `1` |

### 2. 7 个智能体映射

| agent_name | 展示名 | scene | 职责 |
| --- | --- | --- | --- |
| `flow_controller` | 流程总控 | `workflow` | 多智能体流程编排与任务分发 |
| `resume_parser` | 资料解析 | `resume` | 简历 / 资料解析与结构化信息提取 |
| `quiz_generate` | 出题题库 | `quiz` | 生成题目与题库 |
| `interview_host` | 面试主考官 | `interview` | 模拟面试提问与追问 |
| `interview_evaluator` | 面试评测 | `evaluation` | 面试表现评测与反馈 |
| `difficulty_learner` | 难点学习 | `study` | 难点讲解与针对性学习 |
| `note_archiver` | 笔记归档 | `note` | 笔记整理、归档与结构化 |

映射集中在 `app/services/prompt_template_service.py` 的 `AGENT_CONFIG`，是智能体与场景校验的唯一来源。

### 3. 公共与私有的关系

```
最终提示词 = 公共通用模板（common:common）
           + 空行
           + 私有模板（{agent_name}:{scene}）
```

- 公共模板**全局唯一**，不按场景拆分；
- 读取任意私有模板时自动带入公共模板；
- 任一缺失时只返回存在的一方；两者都不存在 → `404`；
- `GET /api/prompt/templates/common/common` 只返回公共模板。

---

## 三、数据模型

### 1. 表结构 `prompt_templates`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `BIGINT` PK | 自增主键，回滚入参 |
| `agent_name` | `VARCHAR(64)` NULL | 公共模板固定 `common`；私有模板为智能体名 |
| `scene` | `VARCHAR(64)` NOT NULL | 公共模板固定 `common`；私有模板为专属场景 |
| `template_type` | `TINYINT` NOT NULL | `1`=私有，`2`=公共 |
| `template_content` | `MEDIUMTEXT` NOT NULL | 模板正文 |
| `variables` | `VARCHAR(512)` NULL | 变量名 JSON 数组字符串，如 `["tone","difficulty"]` |
| `version` | `INT` NOT NULL | 作用域内自增版本号 |
| `is_active` | `TINYINT` NOT NULL | `0`=历史，`1`=生效，默认 `0` |
| `description` | `VARCHAR(255)` NULL | 版本说明 |
| `created_at` | `BIGINT` NOT NULL | Unix 秒，数据库 `UNIX_TIMESTAMP()` 填充 |

索引与约束：

| 名称 | 类型 | 用途 |
| --- | --- | --- |
| `ix_prompt_templates_agent_scene` | 普通索引 | 作用域查询、版本链扫描 |
| `ix_prompt_templates_agent_scene_active` | 普通索引 | 读取当前生效版本 |
| `uk_prompt_agent_scene_version` | 唯一约束 | 兜底版本号重复 |

迁移脚本：`alembic/versions/98e2d9f04aab_create_prompt_templates_table.py`。

### 2. 为什么用单表版本链

没有拆成「模板表 + 版本表」，原因是：

- 作用域数量固定且很小（7 私有 + 1 公共），单表已足够；
- 一条记录即一个完整版本，读写与回滚都是单表操作；
- `is_active` 直接承载「当前生效」，读取路径最短。

代价是历史版本与当前版本同表，需要靠索引与 `is_active` 条件区分；作用域过滤始终走复合索引。

---

## 四、分层实现

```
HTTP
 │
 ▼
① app/routers/prompt.py            路径 / 鉴权 / response_model / summary
 │
 ▼
② app/schemas/prompt.py            入参校验：公共与私有组合、variables 长度
 │
 ▼
③ app/services/prompt_template_service.py
 │     智能体与场景校验、版本编排、公共+私有拼接、Redis 缓存
 │
 ├──────────────► app/services/prompt_injection_service.py
 │                      验证（清洗 / 限长）→ 转换（格式化 / 默认值）→ 填充（占位符替换）
 │                      │
 │                      └──────────────► app/db/user_profile_repo.py  ◄──► MySQL
 │
 ├──────────────► app/db/prompt_template_repo.py   ◄──► MySQL
 │                      生效查询 / 生效切换（事务）
 │
 └──────────────► app/core/redis_client.py        ◄──► Redis
```

| 文件 | 职责 | 关键点 |
| --- | --- | --- |
| `app/routers/prompt.py` | 4 个 HTTP 接口 | 整组 `Depends(get_current_user)` |
| `app/schemas/prompt.py` | 请求 / 响应模型 | 公共模板强制 `common/common` |
| `app/services/prompt_template_service.py` | 业务规则与缓存编排 | `AGENT_CONFIG`、`get_combined_template`、`rollback` |
| `app/services/prompt_injection_service.py` | 用户变量注入三层管线 | `sanitize_text` / `build_variables` / `render_template` |
| `app/db/prompt_template_repo.py` | 数据存取 | `get_active` / `list_active` / `activate` 事务 |
| `app/db/user_profile_repo.py` | 用户背景资料存取 | `get_by_user_id` / `upsert` |
| `app/db/models.py` | ORM 声明 | `PromptTemplate`、`UserProfile` |
| `app/core/redis_client.py` | Redis 单例 | 1 秒超时，懒加载 |
| `app/core/config.py` | 配置入口 | `REDIS_*`、`PROMPT_CACHE_KEY` |
| `app/main.py` | 启动预热 | `lifespan` 调 `load_active_templates()` |
| `tests/test_prompt_templates.py` | 冒烟测试 | 12 个用例，Redis 不可用自动跳过缓存用例 |
| `tests/test_prompt_injection.py` | 注入测试 | 12 个用例：清洗 / 格式化 / 替换 / 接口集成 |

---

## 五、核心业务流程

> 新建版本暂未实现，待后续需求确定后补充；以下为读取、回滚与预热流程。

### 1. 读取生效模板

两个读取入口共用同一套缓存回源逻辑：

```text
GET /templates/{agent}/{scene} ──► get_active_template
                                      └─ 只读该作用域自身（common/common 即公共模板）

GET /full-prompt?agent_name=&scene= ──► get_combined_template
                                      ├─ common/common：只读 common:common
                                      └─ 私有：public(common:common) + private({agent}:{scene})
                                      └─ 两者拼接 → final_template

每次读取单条作用域时：
    Redis HGET 命中 → 直接返回
    未命中 / Redis 不可用
        → Repo.get_active（MySQL）
        → 命中则 HSET 回填
        → 缺失则删除脏字段
```

- 公共与私有模板**各自独立**走缓存；
- 拼接顺序固定：公共在前、私有在后、中间空行；
- `variables` 合并后按首次出现顺序去重；
- `final_template` 为空、但记录存在时仍正常返回（内容可能只有空白）。

### 2. 一键回滚

```text
POST /api/prompt/rollback { template_id }
        │
        ▼
Repo.activate(template_id)
  ├─ 查记录，不存在 → 404
  ├─ SELECT 同作用域 FOR UPDATE
  ├─ 同作用域全部 is_active=0
  ├─ 目标版本 is_active=1
  └─ COMMIT
        │
        ▼
Service._refresh_scope → Redis 刷新该字段
```

- 回滚**不需要传 agent/scene**，作用域从目标记录推导；
- 回滚目标可以是任意历史版本，不要求相邻；
- 回滚后新版本记录仍保留，可再次回滚。

### 3. 启动预热

`app/main.py` 的 `lifespan` 在线程池中调用 `load_active_templates()`：

1. 查询全部 `is_active=1` 的记录；
2. 用 Pipeline **整体重建** Hash：先 `DEL`，再 `HSET`，最后设置 1 小时 TTL；
3. 成功写日志「提示词缓存预热完成：N 条生效模板」；
4. Redis 异常只告警，服务继续启动，后续读取自动回源。

整体重建能清掉「数据库中已不再生效、但缓存里残留」的字段。

---

## 六、Redis 缓存方案

> 环境与命令见 [`redis-guide.md`](./redis-guide.md)。

### 1. 缓存结构

| 项 | 值 |
| --- | --- |
| Key | `prompt:templates:active`（Hash，可用 `PROMPT_CACHE_KEY` 覆盖） |
| 私有字段 | `{agent_name}:{scene}` |
| 公共字段 | `common:common` |
| Value | 单个版本的 JSON 字符串（`variables` 已解析为数组） |
| TTL | 3600 秒 |

### 2. 读 / 写 / 失效

| 场景 | 行为 |
| --- | --- |
| 启动 | 全量重建 Hash |
| 新建版本（待实现） | 提交 MySQL 后刷新对应字段 |
| 回滚 | 提交 MySQL 后刷新对应字段 |
| 读取未命中 | 查 MySQL → 回填该字段 |
| 读取时 Redis 故障 | 告警并直接查 MySQL |
| 写缓存失败 | 告警，忽略（数据库已成功） |

### 3. 一致性边界

- **单实例 / 共享 Redis 多实例**：写操作主动刷新共享缓存，其他实例通常立即读到新值；
- **绕过服务直接改库**：最多 1 小时后由 TTL 触发回源；
- **Redis 丢数据**：无影响，读取自动回源重建。

### 4. 为什么缓存「生效版本」而不是「全部版本」

- 读多写少，读取只需要当前生效版本；
- 回滚是低频管理操作，直接查 MySQL 并刷新缓存即可；
- 缓存体积恒定为最多 8 个字段，不会随版本增长。

---

## 七、用户变量注入

### 1. 数据表 `user_profiles`

用户背景资料，一人一行，作为提示词变量来源。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `BIGINT` PK | 自增主键 |
| `user_id` | `BIGINT` 唯一 | 外键 `users.id`，`ON DELETE CASCADE`；唯一约束兼作查询索引 |
| `target_job` | `VARCHAR(64)` NULL | 目标岗位 |
| `years_experience` | `INT` NULL | 工作年限，0 表示应届 / 无经验 |
| `target_level` | `VARCHAR(32)` NULL | 目标职级 |
| `target_skills` | `JSON` NULL | 已掌握技能，字符串数组 |
| `weak_topics` | `JSON` NULL | 薄弱点，字符串数组 |
| `created_at` | `BIGINT` NOT NULL | Unix 秒，数据库 `UNIX_TIMESTAMP()` 填充 |

迁移脚本：`alembic/versions/a458fe295081_create_user_profiles_table.py`。
仓储入口：`app/db/user_profile_repo.py`（`get_by_user_id` / `upsert`）。

### 2. 三层处理流程

注入实现在 `app/services/prompt_injection_service.py`，只处理纯文本，不感知 HTTP：

```text
final_template（公共 + 私有拼接）
        │
        ▼
① 验证层  sanitize_text / sanitize_items
   去控制字符与换行 → 移除 { } \ → 折叠空白 → 截断
        │
        ▼
② 转换层  build_variables(profile, declared)
   只取模板 variables 已声明且属于用户资料白名单的字段
   数组用「、」连接；缺失走默认值；年限格式化
        │
        ▼
③ 填充层  render_template(template, variables)
   正则 \{变量名\} + re.sub 回调，按字面替换
   未声明的占位符原样保留
        │
        ▼
rendered_template + injected_variables
```

- 变量白名单固定为 `target_job` / `years_experience` / `target_level` / `target_skills` / `weak_topics`；
- 是否注入由模板自身 `variables` 字段决定，模板未声明的变量不进入 `injected_variables`；
- 用户未填写资料时按默认值渲染（`target_job` 等为 `未提供`，数组为 `暂无`）。

### 3. 占位符与默认值

占位符为单花括号 `{变量名}`，变量名须以字母或下划线开头，仅含字母、数字、下划线。

| 变量 | 示例值 | 缺失时 |
| --- | --- | --- |
| `target_job` | `后端工程师` | `未提供` |
| `years_experience` | `3 年`（0 → `应届/无经验`） | `未提供` |
| `target_level` | `P6` | `未提供` |
| `target_skills` | `Python、MySQL` | `暂无` |
| `weak_topics` | `分布式、缓存` | `暂无` |

### 4. 安全边界

| 项 | 限制 |
| --- | --- |
| 标量长度 | 100 字符 |
| 数组单项长度 | 50 字符 |
| 数组项数 | 最多 20 项（去空、去重后） |
| 总注入文本 | 1000 字符（按固定变量顺序截断） |
| 清洗字符 | 控制字符 / 换行转空格，移除 `{` `}` `\` |

填充层使用 `re.sub` 回调按字面插入变量值，**注入内容不会被当作模板二次解析**；即使值中包含 `{target_job}` 也会原样输出。

### 5. 响应示例

`GET /api/prompt/full-prompt?agent_name=difficulty_learner&scene=study`：

```jsonc
{
  "code": 200,
  "message": "ok",
  "data": {
    "final_template": "请用中文回答。\n\n目标岗位：{target_job}；薄弱点：{weak_topics}",
    "variables": ["target_job", "weak_topics"],
    "rendered_template": "请用中文回答。\n\n目标岗位：后端工程师；薄弱点：分布式、缓存",
    "injected_variables": {
      "target_job": "后端工程师",
      "weak_topics": "分布式、缓存"
    }
  }
}
```

### 6. 资料 CRUD 接口

`/api/profiles` 整组需登录，`user_id` 一律取自令牌，只能操作当前用户自己的资料。

| 方法 | 路径 | 说明 | 异常 |
| --- | --- | --- | --- |
| `POST` | `/api/profiles` | 创建资料 | 已存在 `409` |
| `GET` | `/api/profiles/me` | 查询资料 | 未填写 `404` |
| `PUT` | `/api/profiles/me` | 局部更新（只更新显式传入且非空的字段） | 未填写 `404` |
| `DELETE` | `/api/profiles/me` | 删除资料 | 未填写 `404` |

字段校验（`app/schemas/profile.py`）：`target_job` ≤64、`years_experience` 0..60、`target_level` ≤32、`target_skills` / `weak_topics` ≤20 项且单项 ≤50 字；出参不含 `user_id`。删除资料后，注入自动回退为默认值。

---

## 八、接口契约

> 统一信封 `{code, message, data}`；整组需登录。

> 共 4 个接口：作用域生效模板、一键回滚、完整提示词、智能体配置。
> 新建版本暂未实现，待后续需求确定后补充；当前接口只读与回滚。

### 1. 指定作用域的生效模板

`GET /api/prompt/templates/{agent_name}/{scene}`

只返回该作用域自身的生效版本，**不做公共 / 私有拼接**。`common/common` 返回公共通用模板。

```jsonc
{
  "code": 200,
  "message": "ok",
  "data": {
    "id": 5,
    "agent_name": "difficulty_learner",
    "scene": "study",
    "template_type": 1,
    "template_content": "先讲原理再举例。",
    "variables": ["tone"],
    "version": 3,
    "is_active": 1,
    "description": "难点学习 v3",
    "created_at": 1760000000
  }
}
```

- 作用域未知 / 不存在生效版本：`404`；
- 智能体不支持该场景：`400`。

### 2. 完整提示词（公共 + 私有）

`GET /api/prompt/full-prompt?agent_name={agent_name}&scene={scene}`

```jsonc
{
  "code": 200,
  "message": "ok",
  "data": {
    "agent_name": "difficulty_learner",
    "scene": "study",
    "public_template": { "id": 1, "version": 2, "is_active": 1, "variables": ["language"], "...": "..." },
    "private_template": { "id": 5, "version": 3, "is_active": 1, "variables": ["tone"], "...": "..." },
    "final_template": "请用中文回答，先给结论。\n\n先讲原理再举例。",
    "variables": ["language", "tone"],
    "rendered_template": "请用中文回答，先给结论。\n\n先讲原理再举例。",
    "injected_variables": { "target_job": "未提供" }
  }
}
```

- `final_template` 是未渲染的原始拼接，`rendered_template` 是注入用户变量后的结果；
- `injected_variables` 只包含模板 `variables` 已声明的用户资料变量，详见第七节。

- `common/common`：只返回公共模板（`private_template=null`）；
- 公共缺失：`public_template=null`，只返回私有；
- 两者都缺失：`404`。

### 3. 一键回滚

`POST /api/prompt/rollback`，body：

```json
{ "template_id": 3 }
```

响应为回滚后生效的版本记录。

### 4. 智能体配置

`GET /api/prompt/config/agents`

```jsonc
{
  "code": 200,
  "message": "ok",
  "data": [
    {
      "name": "difficulty_learner",
      "display_name": "难点学习",
      "scenes": ["study"],
      "description": "难点讲解与针对性学习"
    }
  ]
}
```

### 5. 状态码

| 场景 | 状态码 |
| --- | --- |
| `full-prompt` 缺少 `agent_name` / `scene` 查询参数 | `422` |
| 未登录 | `401` |
| 智能体 / 场景不存在；模板不存在 | `404` |
| 智能体不支持该场景；私有模板误用 `common` 场景 | `400` |

---

## 九、与聊天链路的接入建议（未实现）

当前聊天仍使用 `app/services/ai/prompt_layer.py` 的硬编码系统提示词。后续接入建议：

1. 在 `chat_service.prepare_stream` 中，根据 `session_mode` / `select_mode` 映射到 `agent_name`；
2. 调用 `prompt_template_service.get_combined_template(agent, scene)` 取 `final_template`；
3. 作为系统提示词传入 `prompt_layer.build_chat_chain`（或新增接收系统提示词的构建函数）；
4. 模板缺失时回退到现有硬编码提示词，保证聊天可用。

需要额外确定「聊天子模式 → 智能体」的映射关系；当前 `AGENT_CONFIG` 只描述智能体与场景，不包含该映射。

---

## 十、并发与一致性

| 风险 | 处理 |
| --- | --- |
| 同作用域出现两条生效 | 同一事务内先全部置 `0`，再激活目标版本 |
| MySQL 成功、Redis 刷新失败 | 缓存失效，读取回源 MySQL；不影响数据正确性 |
| 缓存读到旧值 | 回滚主动刷新；TTL 兜底；可手动 `DEL` |
| 进程启动时 Redis 不可用 | 仅告警；接口读取降级查库 |

注意：回滚的**数据库事务**与 **Redis 刷新**不是原子的。极端情况下会出现「库已更新、缓存仍旧」，但读取命中旧缓存的窗口仅在刷新失败时存在，且 TTL 会在 1 小时内收敛。

---

## 十一、扩展指引

### 新增智能体

1. 在 `AGENT_CONFIG` 增加 `agent_name → display_name / scenes / description`；
2. 在 `_KNOWN_SCENES` 增加对应场景（若为新场景）；
3. 写入该智能体的私有模板（新建版本功能待后续需求补充）；
4. 重启服务触发预热（不重启也会在读取时回源）。

### 新增公共约束

等新建版本功能落地后，新增 `agent_name='common'`、`scene='common'`、`template_type=2` 的版本并刷新 `common:common`。

### 调整校验规则

- 字段组合：`app/schemas/prompt.py`
- 智能体与场景关系：`AGENT_CONFIG` + `_require_private_scope`
- 错误文案与状态码：`prompt_template_service` 中的 `BusinessException`

---

## 十二、测试覆盖

`tests/test_prompt_templates.py`（12 个用例）：

- 7 个智能体映射与鉴权；
- 版本自增、单一生效、回滚成功 / 模板不存在；
- 作用域接口只返回自身、`full-prompt` 公共 + 私有拼接、`common/common` 只读公共；
- 未知智能体 / 场景与缺失模板的 `404`、场景不匹配的 `400`；
- 新建接口不存在（`POST /api/prompt/templates` → `404`）；
- Redis 写入、读取回填、启动整体重建与残留字段清理；
- Redis 不可用时缓存用例自动跳过。

> 新建版本功能未提供，测试数据直接写 `prompt_templates` 表构造。

`tests/test_prompt_injection.py`（12 个用例）：

- 验证层：控制字符 / 换行 / 花括号清洗、标量截断、数组去重与限项；
- 转换层：数组「、」连接、默认值、年限 0 / N / 缺失、只转换已声明变量、总长度上限；
- 填充层：重复占位符、未声明占位符保留、注入值不被二次解析；
- 接口集成：按登录用户资料渲染 `rendered_template` / `injected_variables`，无资料时走默认值。

运行：

```bash
pytest tests/test_prompt_templates.py tests/test_prompt_injection.py -v
```

---

## 十三、红线

- ❌ Redis 当数据源 —— 数据源只能是 MySQL。
- ❌ 绕过仓储层直接拼 SQL 改 `is_active` —— 会破坏单一生效约束。
- ❌ 公共模板使用 `common` 以外的标识 —— 读取端只认 `common:common`。
- ❌ 直接改库而不刷新缓存 —— 至少 `DEL prompt:templates:active` 或重启服务。
- ❌ 在缓存中写入数据库连接串、密钥等敏感信息。
- ✅ 回滚统一走接口；新建版本待后续需求落地后补充；扩展智能体先改 `AGENT_CONFIG`。
