# 学面通 AI · agent-backend

学习 / 面试 AI 助手的后端服务。当前以「用户模块」为样板，落地**路由层 / 校验层 / 业务层 / 数据库层**四层架构。

> 开发规范见 [`AGENTS.md`](./AGENTS.md)（唯一权威规范）。

## 快速开始

```bash
# 1. 创建并激活虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置数据库连接（复制模板并填写真实 MySQL 连接串）
cp .env.example .env

# 4. 建表（首次执行；之后改模型再同步见下方「数据库迁移」）
alembic upgrade head

# 5. 启动服务（默认 8000，与前端 Vite 代理对齐）
uvicorn app.main:app --reload --port 8000
```

- Swagger UI：http://127.0.0.1:8000/docs
- 健康检查：`GET /health`（存活 + 数据库连通性；数据库异常返回 503）
- 流式对话需在 `.env` 中配置 `LLM_PROVIDER / LLM_MODEL / LLM_API_KEY`（OpenAI 兼容协议，可选 `LLM_BASE_URL`）；未配置时仅该接口返回 503，其他接口不受影响。
- 提示词版本管理默认使用本机 Redis 做缓存（`REDIS_HOST=127.0.0.1`、`REDIS_PORT=6379`、`REDIS_DB=0`，可选 `REDIS_PASSWORD`）；Redis 不可用时自动回源 MySQL，接口不受影响。

## 数据库迁移（Alembic）

> 新手完整上手流程见 **[docs/database-guide.md](./docs/database-guide.md)**（环境准备、改表流程、命令速查、常见问题）。

表结构由 SQLAlchemy 模型声明（`app/db/models.py`），迁移由 Alembic 管理。连接串从环境变量 `MYSQL_URL` 读取（见 `.env`），**不写入 `alembic.ini`**。

```bash
# 改完 models.py 后，一键生成迁移并同步到数据库
scripts/db_sync.sh "调整 users 表字段"

# 等价于手动两步：
# alembic revision --autogenerate -m "调整 users 表字段"
# alembic upgrade head
```

## 目录结构（四层）

```
app/
├── main.py                   # 应用入口：创建 FastAPI 实例、配置日志、注册异常处理器与路由
├── core/
│   ├── config.py             # 通用能力：读取环境变量（MYSQL_URL / JWT_SECRET 等）
│   ├── security.py           # 密码哈希（passlib + bcrypt）+ JWT 令牌签发/校验
│   ├── exceptions.py         # 自定义异常：BusinessException / SystemException
│   ├── logging.py            # 日志配置
│   ├── rate_limit.py         # 固定窗口 + IP 维度限流（注册接口依赖）
│   ├── redis_client.py       # Redis 客户端（提示词缓存，不可用不阻断启动）
│   └── handlers.py           # 全局异常处理器（统一错误响应）
├── routers/
│   ├── deps.py               # ① 路由层共享依赖：get_current_user（Bearer 鉴权）
│   ├── user.py               #   用户 CRUD（整组需登录）
│   ├── auth.py               #   注册 / 登录 / 刷新令牌 / 当前用户
│   ├── session.py            #   会话管理 + 会话内消息（整组需登录）
│   ├── interview.py          #   面试详情（按 interview_id + user_id）
│   ├── file.py               #   文件上传 / 头像读取
│   ├── prompt.py             #   提示词版本管理（读取 / 新建 / 回滚 / 智能体配置）
│   └── health.py             #   健康检查（存活 + 数据库连通性）
├── schemas/
│   ├── user.py               # ② 校验层：Pydantic v2 请求 / 响应模型
│   ├── auth.py               #   注册 / 登录 / 刷新入参 + 令牌出参
│   ├── session.py            #   会话入参 / 出参
│   ├── message.py            #   聊天消息出参（正文 + 附件段）
│   ├── interview.py          #   面试详情出参（含 qa_object）
│   ├── prompt.py             #   提示词入参 / 出参
│   ├── file.py               #   文件上传出参
│   ├── health.py             #   健康检查出参
│   └── response.py           # 统一响应信封
├── services/
│   ├── user_service.py       # ③ 业务层：业务规则
│   ├── auth_service.py       #   鉴权业务：登录校验、签发 / 刷新令牌、解析当前用户
│   ├── session_service.py    #   会话分页 / 创建 / 编辑 + 级联删除
│   ├── message_service.py    #   会话消息分页（正文与附件段分离）
│   ├── prompt_template_service.py # 提示词版本管理：智能体配置 / 拼接 / 回滚 / Redis 缓存
│   ├── interview_service.py  #   面试详情（interview_id + user_id）
│   ├── upload_service_minio.py # 文件上传（MinIO + resources 元数据）
│   ├── resource_cleanup.py   #   过期资源清理
│   └── health_service.py     #   健康检查：数据库探活，异常转 503
└── db/                       # ④ 数据库层：SQLAlchemy 2.0 + MySQL
    ├── base.py               #   ORM 基类
    ├── models.py             #   表结构声明（User / ChatSession / ChatMessage / Interview / PromptTemplate / Resource）
    ├── session.py            #   engine + Session 工厂
    ├── user_repo.py          #   users 表读写仓储
    ├── session_repo.py       #   sessions 表读写仓储
    ├── message_repo.py       #   chat_messages 表读写仓储
    ├── interview_repo.py     #   interviews 表读写仓储
    ├── prompt_template_repo.py # prompt_templates 表读取 / 生效切换仓储
    ├── resource_repo.py      #   resources 表读写仓储
    └── health_repo.py        #   数据库连通性探活（SELECT 1）

alembic/                      # 迁移脚本（versions/ 存版本）
scripts/db_sync.sh            # 一键生成迁移并同步
tests/                        # pytest 冒烟测试（连真实 MySQL）
├── test_sessions.py          #   会话 / 消息 / 面试详情 / 级联删除
├── test_stream_chat.py       #   流式对话 / SSE / 上下文 / 失败落库
├── test_prompt_templates.py  #   提示词版本 / 拼接 / 回滚 / Redis 缓存
└── test_resources.py         #   过期资源清理
```

## 测试

> 健康检查与冒烟测试完整上手流程见 **[docs/health-testing-guide.md](./docs/health-testing-guide.md)**（探活原理、夹具、新增用例、常见问题）。

```bash
pip install -r requirements-dev.txt          # 测试依赖（pytest / httpx / pytest-asyncio）
alembic upgrade head                         # 确保测试库已建表
pytest tests/ -v                             # 运行全部测试（含会话 / 资源清理）
```

> 测试连 `.env` 里的真实 MySQL，创建的用户带 `smoke_*` 前缀并在用例后自动清理；如需隔离，把 `MYSQL_URL` 指向独立的测试库。提示词缓存用例在 Redis 不可用时自动跳过，不影响其余用例。

## 用户接口

| 方法 | 路径 | 说明 | 成功码 |
| --- | --- | --- | --- |
| POST | `/api/users` | 创建用户 | 200 |
| GET | `/api/users` | 用户列表 | 200 |
| GET | `/api/users/{id}` | 用户详情 | 200 |
| PUT | `/api/users/{id}` | 更新用户 | 200 |
| DELETE | `/api/users/{id}` | 删除用户 | 200 |
| POST | `/api/auth/register` | 用户注册 | 200 |
| POST | `/api/auth/login` | 用户登录（签发双令牌） | 200 |
| POST | `/api/auth/refresh` | 用刷新令牌换新令牌 | 200 |
| GET | `/api/auth/me` | 当前登录用户 | 200 |
| POST | `/api/files` | 通用文件上传（multipart，字段 `file`，可选 `upload_purpose` / `storage_scene`） | 200 |
| GET | `/api/files/avatar/{id}` | 读取用户头像（公开，返回图片二进制，供 `<img>` 直接访问） | 200 |
| GET | `/api/sessions?page=&page_size=` | 当前用户会话列表（分页，按创建时间倒序） | 200 |
| POST | `/api/sessions` | 创建会话（`title` + `session_mode`，兼容 `session_model`） | 200 |
| PUT | `/api/sessions/{id}` | 编辑会话标题 | 200 |
| DELETE | `/api/sessions/{id}` | 级联删除会话（消息 / 面试 / 附件资源与 MinIO 对象） | 200 |
| GET | `/api/sessions/{id}/messages?page=&page_size=` | 会话消息分页（正文 + 附件段 + status/interview_id） | 200 |
| POST | `/api/sessions/{id}/stream-chat` | 流式对话（SSE：meta → delta* → done / error） | 200 |
| GET | `/api/interviews/{id}` | 面试详情（含 `qa_object`，按 id + 当前用户查询） | 200 |
| GET | `/api/prompt/templates/{agent_name}/{scene}` | 指定作用域的生效模板（只返回自身，不拼接） | 200 |
| POST | `/api/prompt/rollback` | 一键回滚到指定版本（body `template_id`） | 200 |
| GET | `/api/prompt/full-prompt?agent_name=&scene=` | 完整提示词（公共 + 私有拼接） | 200 |
| GET | `/api/prompt/config/agents` | 7 个智能体映射（名称 / 展示名 / 专属场景） | 200 |

不带 `/api` 前缀的端点：`GET /health`（存活 + 数据库连通性探活）与 `/uploads/*`（旧版本地头像的静态访问，新上传统一走 MinIO）。

> 除注册 / 登录 / 刷新 / 健康检查 / 头像读取（`/api/files/avatar/{id}`）外，接口需携带 `Authorization: Bearer <access_token>`；令牌缺失 / 过期 / 非法一律 **401**。`/api/users` 整组接口需登录。

### 注册接口

`POST /api/auth/register` 复用 `user_service.create_user`（bcrypt 哈希，禁止明文入库），并叠加三道防线：

- **弱密码校验**（校验层 `schemas/auth.py`）：命中弱口令黑名单、缺字母、缺数字、或包含用户名 → `422`；
- **接口限流**（`core/rate_limit.py`）：固定窗口 + IP 维度，默认 **5 次/min**，超限 → `429`（进程内内存实现，仅单机有效）。

```bash
curl -X POST http://127.0.0.1:8000/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"bob","password":"abc12345"}'
# → {"code":200,"message":"ok","data":{"id":1,"username":"bob","avatar":null,"create_time":"..."}}（无 password）
# 弱密码 / 重复用户名 / 超限分别返回 422 / 409 / 429
```

### 鉴权（JWT）

> 实现原理（全景时序图、令牌结构、鉴权判定树、分层地图）见 **[docs/jwt-auth-guide.md](./docs/jwt-auth-guide.md)**。

登录签发 **访问令牌（Access Token，默认 30 分钟）** 与 **刷新令牌（Refresh Token，默认 7 天）**，均为 HS256 无状态 JWT；签名密钥经环境变量 `JWT_SECRET` 注入（**缺失时服务启动即报错**）。

```bash
# 1) 登录拿双令牌
curl -X POST http://127.0.0.1:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"bob","password":"abc12345"}'
# → {"code":200,"data":{"access_token":"...","refresh_token":"...","token_type":"bearer"}}

# 2) 携带访问令牌访问受保护接口
curl http://127.0.0.1:8000/api/auth/me -H "Authorization: Bearer <access_token>"   # 200
curl http://127.0.0.1:8000/api/users                                               # 401（无令牌）

# 2.1) 通用文件上传（需登录，multipart 字段 file）
curl -X POST http://127.0.0.1:8000/api/files \
  -H "Authorization: Bearer <access_token>" \
  -F "file=@avatar.png" -F "upload_purpose=1" -F "storage_scene=0"
# → {"kind":"image","url":"minio:/ai-resource/users/1/<md5>.png","resource_id":1,
#    "storage_path":"minio:/ai-resource/users/1/<md5>.png","expire_time":null,...}
# 支持图片 / 文档 / 音频（MP3/WAV/OGG/OPUS/M4A/AAC/FLAC/WebM，音频按文档上限 10MB）。
# upload_purpose=1 且为图片时更新 users.avatar（存 MinIO 路径）。
# storage_scene：0=长期 30 天，1=短期 2 小时，2=只写元数据不存原文件。
# 元数据落 MySQL resources，原文件落 MinIO；同用户相同内容按 MD5 去重。

# 3) 访问令牌过期（401）时，用刷新令牌换新令牌后重试原请求
curl -X POST http://127.0.0.1:8000/api/auth/refresh \
  -H 'Content-Type: application/json' -d '{"refresh_token":"<refresh_token>"}'      # 200 新 access_token
```

- 刷新令牌**只能**用于 `/api/auth/refresh`，不能访问受保护接口（`type` 声明区分）；访问令牌过期时，前端应调 `/api/auth/refresh` 换新令牌并自动重试原请求。
- 令牌为无状态 JWT，**暂不支持主动吊销 / 登出**（后续需要再引入黑名单或落库）。

### 会话与聊天消息

```bash
# 创建会话（session_model 为兼容旧文档的等价字段名）
curl -X POST http://127.0.0.1:8000/api/sessions \
  -H "Authorization: Bearer <access_token>" -H 'Content-Type: application/json' \
  -d '{"title":"Python 学习","session_mode":0}'

# 会话列表 / 编辑标题 / 删除（级联清理消息、面试、附件资源与 MinIO 对象）
curl "http://127.0.0.1:8000/api/sessions?page=1&page_size=20" -H "Authorization: Bearer <access_token>"
curl -X PUT http://127.0.0.1:8000/api/sessions/1 -H "Authorization: Bearer <access_token>" \
  -H 'Content-Type: application/json' -d '{"title":"新标题"}'
curl -X DELETE http://127.0.0.1:8000/api/sessions/1 -H "Authorization: Bearer <access_token>"

# 会话消息（按时间正序分页）
curl "http://127.0.0.1:8000/api/sessions/1/messages?page=1&page_size=20" \
  -H "Authorization: Bearer <access_token>"
# → items: [{id, request_text, response_text, request_segments, response_segments,
#            status, interview_id, created_at}]

# 面试详情（含 qa_object；只能查自己的记录）
curl http://127.0.0.1:8000/api/interviews/1 -H "Authorization: Bearer <access_token>"
```

- **正文与附件分离**：`request_text` / `response_text` 是聊天正文；`request_segments` / `response_segments` 只存附件段 `{type: file|image|audio, resource_id, file_name?, url?}`。AI 回复的文本始终进 `response_text`，附件进 `response_segments`。
- **消息状态**：`status` 0=生成中、1=完成、2=失败；`interview_id` 指向关联面试记录（普通聊天为 `null`），供前端渲染面试卡片。
- **用户隔离**：会话、消息、面试详情均按令牌中的 `user_id` 查询，他人的资源统一返回 `404`。
- **级联删除**：解析消息附件段收集 `resource_id`，按 `interviews → chat_messages → sessions` 顺序删库，再删除当前用户自己的 `resources` 元数据与 MinIO 对象（先删对象，失败则保留元数据等待过期清理重试）。

### 流式对话（SSE）

```bash
curl -N -X POST http://127.0.0.1:8000/api/sessions/1/stream-chat \
  -H "Authorization: Bearer <access_token>" -H 'Content-Type: application/json' \
  -d '{"request_text":"解释一下 Python GIL","select_mode":1}'
```

事件顺序（每行 `data` 均为 JSON）：

```text
event: meta
data: {"session_id":1,"message_id":12,"request_id":"..."}

event: delta
data: {"content":"GIL 是"}

event: done
data: {"message_id":12,"status":1}
```

- 校验与用户消息落库在建立流之前完成：`404 / 422 / 503` 仍返回标准 JSON 信封；流开始后失败以 `event: error` 返回（`{code, message}`），已生成的部分内容会保留。
- 落库语义：用户消息先写入 `status=0`；成功后回写 `response_text` 并置 `status=1`；模型失败或客户端断开时保留部分内容并置 `status=2`。
- AI 代码分三层：`app/services/ai/llm.py`（provider → 模型实例）、`prompt_layer.py`（系统提示词与链路组装）、`memory.py`（数据库多轮历史 → 上下文）；`chat_service.py` 负责编排与 SSE 输出。
- 记忆层只取最近 `MEMORY_MAX_TURNS` 轮 `status=1` 的消息，单条超过 `MEMORY_MESSAGE_MAX_CHARS` 截断，`file_extracted_text` 非空时拼入对应用户消息。

### 提示词版本管理

> 技术方案与业务流程（数据模型、版本链、缓存一致性、接口契约）见 **[docs/prompt-template-guide.md](./docs/prompt-template-guide.md)**。
> Redis 安装、缓存结构与排错完整上手流程见 **[docs/redis-guide.md](./docs/redis-guide.md)**（环境准备、缓存结构、常用命令、常见问题）。

多智能体提示词按 `(agent_name, scene)` 维护独立版本链：公共通用模板固定 `agent_name='common'` + `scene='common'`，叠加在私有模板之前。数据源是 MySQL，Redis Hash `prompt:templates:active` 只缓存当前生效版本（启动预热、变更即刷新、未命中回源）。

**7 个智能体映射**

| agent_name | 展示名 | scene |
| --- | --- | --- |
| `flow_controller` | 流程总控 | `workflow` |
| `resume_parser` | 资料解析 | `resume` |
| `quiz_generate` | 出题题库 | `quiz` |
| `interview_host` | 面试主考官 | `interview` |
| `interview_evaluator` | 面试评测 | `evaluation` |
| `difficulty_learner` | 难点学习 | `study` |
| `note_archiver` | 笔记归档 | `note` |

```bash
# 1) 指定作用域的生效模板（只返回自身，不拼接）
curl http://127.0.0.1:8000/api/prompt/templates/difficulty_learner/study \
  -H "Authorization: Bearer <access_token>"
# 公共通用模板：GET /api/prompt/templates/common/common

# 2) 完整提示词：公共通用模板 + 私有模板拼接（公共在前，空行分隔）
curl 'http://127.0.0.1:8000/api/prompt/full-prompt?agent_name=difficulty_learner&scene=study' \
  -H "Authorization: Bearer <access_token>"
# → {public_template, private_template, final_template, variables, ...}
# 只看公共通用模板：?agent_name=common&scene=common

# 3) 一键回滚：把历史版本重新置为生效
curl -X POST http://127.0.0.1:8000/api/prompt/rollback \
  -H "Authorization: Bearer <access_token>" -H 'Content-Type: application/json' \
  -d '{"template_id":1}'

# 4) 智能体映射（7 个）
curl http://127.0.0.1:8000/api/prompt/config/agents -H "Authorization: Bearer <access_token>"
```

- **写入**：新建版本功能暂未实现，待提示词注入功能需求确定后再补充；当前仅提供读取与回滚。
- **规则**：公共通用模板固定 `agent_name='common', scene='common', template_type=2`；私有模板为智能体名 + 专属场景、`template_type=1`；未知智能体 / 场景 `404`，智能体不支持的场景 `400`。
- **版本与生效**：版本号按作用域自增；新版本默认生效并下线旧版本，同一作用域始终只有一条 `is_active=1`（事务行锁 + 唯一键兜底）。
- **缓存**：私有字段 `{agent_name}:{scene}`、公共字段 `common:common`；Redis 故障不影响接口，读取自动回源 MySQL 并回填。缓存 Key 可用 `PROMPT_CACHE_KEY` 覆盖。

### 统一响应信封

所有接口（成功 / 失败）返回同一结构，`code` 复用 HTTP 状态码：

```jsonc
// 成功
{ "code": 200, "message": "ok", "data": { /* 业务数据，可为 null */ } }
// 失败（HTTP 状态码同为 404）
{ "code": 404, "message": "用户 1 不存在", "detail": "user_id=1" }
```

`message` 面向用户（中文），`detail` 面向开发者（定位用，可为 null）。

### 示例

```bash
# 创建
curl -X POST http://127.0.0.1:8000/api/users \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"secret123"}'

# 查询列表
curl http://127.0.0.1:8000/api/users

# 更新（只更新传入字段）
curl -X PUT http://127.0.0.1:8000/api/users/1 \
  -H 'Content-Type: application/json' \
  -d '{"password":"newsecret123"}'

# 删除
curl -X DELETE http://127.0.0.1:8000/api/users/1
```

## 说明

- **统一错误处理**：业务层抛 `BusinessException`（4xx）/ `SystemException`（5xx），由全局处理器统一转成错误信封；业务错误记 `WARNING`、系统错误记 `ERROR`（含堆栈，供定位）。日志级别可用环境变量 `LOG_LEVEL` 覆盖。
- **密码安全**：明文仅作为入参，落库前经 `passlib[bcrypt]` 单向哈希；响应模型不含 `password`。
- **令牌鉴权**：JWT（PyJWT，HS256）由 `app/core/security.py` 统一签发 / 校验；密钥经环境变量 `JWT_SECRET` 注入，**缺失时启动报错**。受保护接口经 `app/routers/deps.py` 的 `get_current_user` 校验 `Authorization: Bearer`。
- **数据存储**：`users` 表由 SQLAlchemy 2.0 声明、MySQL 持久化；表结构变更走 Alembic 迁移（`scripts/db_sync.sh`）。上层只经 `app/db/user_repo.py` 读写。
- **User 表字段**：`id`（自增主键）、`username`（唯一索引）、`password`（bcrypt 哈希）、`create_time`（数据库自动填充当前时间）。
- **依赖锁定**：`bcrypt` 锁定 `4.0.1`（`passlib 1.7.4` 与 `bcrypt>=4.1` 不兼容），详见 `requirements.txt` 注释。
