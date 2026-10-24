# 提示词注入操作指南（验证版）

> 本文面向第一次验证提示词注入的同学：先理解 `prompt_templates` 与 `user_profiles` 的关系，
> 再按步骤在 Swagger UI 中完成「初始化 → 查看 → 改资料 → 回滚」全流程。
>
> 设计细节见 [`prompt-template-guide.md`](./prompt-template-guide.md)；开发规范见 [`AGENTS.md`](../AGENTS.md)。

---

## 一、先理清关系：两张表各管什么

```
prompt_templates（模板，跟"能力"有关，与具体用户无关）
├── common:common        v1 / v2   ← 公共通用规则
└── difficulty_learner:study v1 / v2 ← 私有智能体指令
            │
            │ ① 取各自 is_active=1 的版本，公共在前、私有在后拼接
            ▼
      final_template（仍含 {target_job} 等占位符）
            │
            │ ② 按当前登录用户在 user_profiles 中查值
            │    只替换模板 variables 里声明过的占位符
            ▼
   rendered_template + injected_variables
```

| 维度 | `prompt_templates` | `user_profiles` |
| --- | --- | --- |
| 数据粒度 | 每个 `(agent_name, scene)` 一条版本链 | 每个用户一行（`user_id` 唯一） |
| 存什么 | 提示词正文、声明的变量名、版本、是否生效 | 目标岗位 / 年限 / 职级 / 技能 / 薄弱点 |
| 是否随用户变化 | 否，所有用户共用 | 是，每个用户不同 |
| 谁决定注入哪些变量 | 模板 `variables` 字段 | 不决定；只提供值 |
| 版本控制 | v1 / v2，v2 生效、v1 可回滚 | 无版本，直接更新 |

**关联点只有一个：变量名。**

- 模板正文写 `{target_job}`，同时在 `variables` 里声明 `"target_job"`；
- `user_profiles` 里恰好有 `target_job` 字段；
- 三者名字对上，才会注入。模板没声明 → 占位符原样保留；用户没填 → 用默认值。

因此：

- **换用户**：模板不变，`rendered_template` 随 `user_profiles` 变化；
- **换版本 / 回滚**：用户资料不变，注入规则不变，只有模板正文变化；
- **改用户资料**：不会新增模板版本，下一次请求 `full-prompt` 立即生效。

---

## 二、初始化数据

### 1. 执行初始化脚本

```bash
cd agent-backend
source .venv/bin/activate

# 确认表结构最新（首次或刚拉代码时）
alembic upgrade head

# 写入模板 + 演示用户资料，并刷新 Redis 缓存
python scripts/init_prompt.py
```

预期输出（版本 id 以实际数据库为准）：

```text
✔ 提示词模板已同步（每作用域 v1 历史 / v2 生效）：
  作用域                                v1_id   v2_id
  common:common                        171     172
  flow_controller:workflow             173     174
  resume_parser:resume                 175     176
  quiz_generate:quiz                   177     178
  interview_host:interview             179     180
  interview_evaluator:evaluation       181     182
  difficulty_learner:study             183     184
  note_archiver:note                   185     186

✔ 用户背景资料已写入：user_id=1549，username=prompt_demo
  target_job=后端开发工程师，years_experience=3，target_level=P6
  演示账号：prompt_demo / abc12345

✔ Redis 缓存：已刷新
```

脚本做了三件事：

1. `prompt_templates`：8 个作用域 × 每个 v1 / v2，共 16 条；**v2 生效，v1 下线**作为回滚目标；
2. `users` + `user_profiles`：确保演示账号 `prompt_demo / abc12345` 存在，并写入背景资料；
3. 刷新 Redis 缓存（Redis 不可用时只告警，接口读取会自动回源 MySQL）。

> **可重复执行**：再次运行会原地更新 v1 / v2，不会产生 v3；版本 id 保持不变。
> 想绑定自己的账号：`python scripts/init_prompt.py --username <已存在用户名>`（只写资料，不改密码）。

### 2. 确认数据

```sql
SELECT id, agent_name, scene, version, is_active
FROM prompt_templates
ORDER BY agent_name, scene, version;

SELECT user_id, target_job, years_experience, target_level, target_skills, weak_topics
FROM user_profiles;
```

---

## 三、启动服务并打开 API Docs

```bash
uvicorn app.main:app --reload --port 8000
```

浏览器打开 **http://127.0.0.1:8000/docs**。

---

## 四、在 Swagger UI 中逐步验证

### Step 1 登录并授权

1. 展开 `POST /api/auth/login` → **Try it out**；
2. 请求体：

   ```json
   { "username": "prompt_demo", "password": "abc12345" }
   ```

3. **Execute**，从响应 `data.access_token` 复制访问令牌；
4. 点击页面右上角 **Authorize**，把令牌粘贴进去（**不要加 `Bearer ` 前缀**），点 Authorize。

> 之后所有要求登录的接口都会自动带上 `Authorization: Bearer <token>`。
> 未授权时访问提示词接口返回 `401`。

### Step 2 查看用户背景资料（注入的数据来源）

展开 `GET /api/profiles/me` → **Execute**：

```jsonc
{
  "code": 200,
  "message": "ok",
  "data": {
    "id": 13,
    "target_job": "后端开发工程师",
    "years_experience": 3,
    "target_level": "P6",
    "target_skills": ["Python", "MySQL", "Redis", "FastAPI"],
    "weak_topics": ["分布式事务", "高并发缓存一致性"],
    "created_at": 1792768317
  }
}
```

这些就是稍后注入到 `{target_job}` 等占位符里的值。

### Step 3 查看智能体配置

展开 `GET /api/prompt/config/agents` → **Execute**，应返回 7 个智能体。
每个智能体的 `scenes` 就是它的私有模板场景，例如 `difficulty_learner` → `study`。

### Step 4 获取完整提示词（核心步骤）

展开 `GET /api/prompt/full-prompt` → **Try it out**，填写：

| 参数 | 值 |
| --- | --- |
| `agent_name` | `difficulty_learner` |
| `scene` | `study` |

**Execute** 后重点看 4 个字段：

```jsonc
{
  "public_template":  { "version": 2, "is_active": 1, "...": "..." },
  "private_template": { "version": 2, "is_active": 1, "...": "..." },

  // 未渲染：公共 + 私有拼接后的原文，占位符还在
  "final_template": "你是「学面通」求职辅导助手……目标岗位 {target_job}……\n\n你是「学面通」的难点学习助手……",

  // 已渲染：占位符替换成当前用户的资料
  "rendered_template": "你是「学面通」求职辅导助手……目标岗位 后端开发工程师，目标职级 P6，工作年限 3 年……\n\n你是「学面通」的难点学习助手……薄弱点：分布式事务、高并发缓存一致性……",

  // 本次实际注入了哪些变量（模板已声明 + 用户资料里有）
  "injected_variables": {
    "target_job": "后端开发工程师",
    "years_experience": "3 年",
    "target_level": "P6",
    "weak_topics": "分布式事务、高并发缓存一致性"
  },

  "variables": ["target_job", "target_level", "years_experience", "weak_topics"]
}
```

对照关系：

| 字段 | 含义 |
| --- | --- |
| `variables` | 公共 + 私有模板声明变量的并集（去重） |
| `final_template` | 模板原文，用于排查占位符写对没有 |
| `rendered_template` | 最终可直接作为系统提示词的文本 |
| `injected_variables` | 实际替换的变量名 → 值 |

> 只使用 `rendered_template` 作为系统提示词；`final_template` 仅用于调试对照。

### Step 5 修改资料，观察注入结果变化

1. 展开 `PUT /api/profiles/me` → **Try it out**，请求体：

   ```json
   {
     "target_job": "云原生平台工程师",
     "target_level": "P7",
     "weak_topics": ["Kubernetes 调度", "服务网格"]
   }
   ```

2. **Execute**，确认字段已更新；
3. 再次执行 Step 4 的 `GET /api/prompt/full-prompt`。

此时 `final_template` **完全没变**，但 `rendered_template` 中的岗位、职级、薄弱点已变成新值，
`injected_variables` 同步更新。这说明：**模板版本与用户资料相互独立**。

> 注意：`PUT` 只更新传入且非空的字段，未传的 `target_skills` 保持原值。

### Step 6 演示版本回滚

版本号只保留 v1 / v2，v2 生效、v1 下线。使用初始化输出的 `difficulty_learner:study` 的 **v1_id**：

1. 展开 `POST /api/prompt/rollback` → **Try it out**，请求体：

   ```json
   { "template_id": 183 }
   ```

2. **Execute**，响应 `data.version` 为 `1`、`is_active` 为 `1`；
3. 再次执行 Step 4：`private_template.version` 变为 `1`，`rendered_template` 末尾的私有部分
   退回 v1（更简短的「先讲原理，再给例子，最后给出练习建议」）；
4. 再用 v2_id 回滚恢复：

   ```json
   { "template_id": 184 }
   ```

5. 再次查询，`private_template.version` 回到 `2`。

> 回滚只影响指定作用域（这里是 `difficulty_learner:study`），公共模板仍为 v2，用户资料不变。
> 每次回滚都会立即刷新 Redis 缓存。

### Step 7 查看单个作用域的生效版本

展开 `GET /api/prompt/templates/{agent_name}/{scene}`，填 `difficulty_learner` / `study`：

- 只返回该作用域自身的生效版本，**不做公共 + 私有拼接**；
- 公共模板用 `common` / `common` 查看；
- 响应包含 `id` / `version` / `variables` 等字段，可作为回滚时的 `template_id` 来源。

### Step 8 验证默认值（可选）

1. 展开 `DELETE /api/profiles/me` → **Execute**（删除演示资料）；
2. 执行 Step 4：`rendered_template` 中岗位变为 `未提供`、薄弱点变为 `暂无`，接口不报错；
3. 重新执行初始化脚本即可恢复演示资料：

   ```bash
   python scripts/init_prompt.py
   ```

---

## 五、智能体与注入变量对照

初始化模板各自声明的变量（v2）：

| agent_name | scene | 注入变量 |
| --- | --- | --- |
| `common` | `common` | `target_job`、`target_level`、`years_experience` |
| `flow_controller` | `workflow` | `target_job`、`target_level`、`target_skills` |
| `resume_parser` | `resume` | `target_job`、`years_experience`、`target_skills` |
| `quiz_generate` | `quiz` | `target_job`、`target_skills`、`weak_topics` |
| `interview_host` | `interview` | `target_job`、`target_level`、`years_experience` |
| `interview_evaluator` | `evaluation` | `target_job`、`target_level`、`weak_topics` |
| `difficulty_learner` | `study` | `target_job`、`weak_topics`、`years_experience` |
| `note_archiver` | `note` | `target_job`、`target_skills` |

格式规则：数组用「、」连接；年限 `0` → `应届/无经验`、`N` → `N 年`；
缺失标量 → `未提供`；空数组 → `暂无`。

---

## 六、常见问题

| 现象 | 原因 / 处理 |
| --- | --- |
| `401 未提供认证凭证` | 未点 Authorize，或粘贴令牌时多了 `Bearer ` 前缀 |
| `404 提示词模板不存在` | 未执行初始化脚本，或查询了不存在的作用域 |
| `400 智能体不支持场景` | `agent_name` 与 `scene` 不匹配（见第四节对照表） |
| `rendered_template` 里仍有 `{xxx}` | 模板 `variables` 未声明该变量（预期行为，不注入） |
| `injected_variables` 少了某字段 | 模板未声明，或用户资料该字段为空 |
| 改了资料但结果没变 | 确认改的是当前登录用户（`/api/profiles/me`），并重新请求 `full-prompt` |
| Redis 报连接失败 | 不影响接口；读取自动回源 MySQL，启动脚本只告警 |
| 回滚 404 | `template_id` 不存在；用初始化输出或 `GET /api/prompt/templates/...` 的 `id` |

---

## 七、一页速记

```text
初始化：python scripts/init_prompt.py          # 8 作用域 × v1/v2 + prompt_demo 资料
启动：  uvicorn app.main:app --port 8000       # http://127.0.0.1:8000/docs

验证顺序：
登录拿 token → Authorize
  → GET /api/profiles/me                       # 看注入值从哪来
  → GET /api/prompt/full-prompt?agent_name=difficulty_learner&scene=study
        final_template     = 模板原文（含占位符）
        rendered_template  = 注入后的最终提示词
        injected_variables = 实际替换的变量
  → PUT /api/profiles/me                       # 改资料 → 再查 full-prompt
  → POST /api/prompt/rollback {v1_id}          # 回滚 → 再查 full-prompt → 回滚回 v2
```

核心一句话：**模板负责「说什么」，用户资料负责「对谁说」；变量名是两者唯一的契约。**
