# 学面通 AI · agent-backend 后端开发规范

> 本文件是本项目后端开发的**唯一权威规范（Single Source of Truth）**，所有团队成员与 AI 助手在开发前都必须遵守。
>
> **自动引用机制**：
> - Claude Code 通过 `CLAUDE.md` 自动加载本文件；
> - Cursor / Codex / 其他支持 `AGENTS.md` 的工具会直接读取本文件。
>
> 修改规范时**只改本文件**，不要在别处重复维护，避免多处不一致。

---

## 0. 项目概览

- **产品**：学面通 AI —— 面向求职者的「学习 + 面试」AI 助手。
- **本仓库**：`agent-backend`，产品后端服务。当前以「用户模块」为样板落地四层架构，后续模块照此扩展。
- **接口前缀**：统一 `/api`，与前端 Vite 代理（`/api` → `http://127.0.0.1:8000`）对齐。**改端口必须同步改前端 `API_PROXY_TARGET`**。

---

## 1. 技术栈（以 `requirements.txt` 为准）

| 类别 | 选型 | 说明 |
| --- | --- | --- |
| Web 框架 | FastAPI `0.143.x` | 全量类型注解，自动生成 OpenAPI 文档 |
| ASGI 服务器 | Uvicorn `0.54.x` | 开发用 `--reload` |
| 数据校验 | Pydantic `v2` `2.14.x` | 请求 / 响应模型，统一在校验层定义 |
| 密码哈希 | `passlib[bcrypt]` | 统一入口在 `app/core/security.py` |
| 令牌鉴权 | `PyJWT` `2.10.x` | HS256 签发 / 校验 Access、Refresh 令牌，入口 `app/core/security.py`；密钥走环境变量 `JWT_SECRET` |
| ORM / 数据库 | SQLAlchemy `2.0.x` + PyMySQL | MySQL 同步驱动，模型声明于 `app/db/models.py` |
| 对象存储 | MinIO Python SDK `7.1.x` | 原文件落桶，元数据存 MySQL；入口 `app/core/minio_client.py` |
| 缓存 | Redis（`redis-py 8.1.x`） | 提示词生效模板缓存（Hash）+ 会话工作记忆，不可用时分别回源 MySQL；入口 `app/core/redis_client.py` |
| 表结构迁移 | Alembic `1.14.x` | 改模型后 `scripts/db_sync.sh` 一键同步 |
| 配置读取 | `python-dotenv` | 分层加载：真实环境变量 > `.env.{APP_ENV}` > `.env`，入口 `app/core/config.py`（唯一读取入口） |
| 日志 | Loguru `0.7.x` | 开发控制台 + 文件，生产只落文件；按大小滚动（10MB × 5），入口 `app/core/logging.py` |
| AI 编排 | LangChain `langchain-core 1.7` + `langchain-openai 1.7` | OpenAI 兼容协议；模型 / 提示词封装在 `app/services/ai/`，记忆读取在 `app/services/memory_service.py`，长期记忆在 `app/services/long_term_memory.py` |
| 工作流编排 | LangGraph `1.2.x` | 学习测评等跨请求状态机，完整状态落 `workflow_runs.state_json`；入口 `app/services/learning_workflow.py` |
| 语义判断 | fastembed `0.9.x` | 长期记忆写入意图判断（`BAAI/bge-small-zh-v1.5`，首次使用时下载模型并缓存）；入口 `app/services/long_term_memory.py` |
| 语言 | Python `3.13` | 使用 `X | None` 现代联合类型写法 |
| 包管理 | **venv + pip** | 运行期依赖以 `requirements.txt` 为准；测试依赖另见 `requirements-dev.txt` |

> **依赖锁定注意**：`bcrypt` 必须锁 `4.0.1`。`bcrypt>=4.1` 移除了 `__about__`，`5.x` 更把「超 72 字节密码」从截断改为抛错，会导致 `passlib 1.7.4` 初始化后端直接崩溃。**升级 passlib 前不要放开此锁。**

---

## 2. 四层架构（核心约定）

请求自上而下流动，**只能相邻层调用，禁止跨层**：

```
HTTP 请求
   │
   ▼
① routers/   路由层   ── 只管 HTTP 契约：路径、方法、状态码、response_model
   │
   ▼
② schemas/   校验层   ── Pydantic v2 模型：入参校验 + 出参裁剪
   │
   ▼
③ services/  业务层   ── 业务规则：唯一性校验、密码哈希、字段组装
   │
   ▼
④ db/        数据库层 ── 数据存取（SQLAlchemy 2.0 + MySQL，Alembic 管理表结构）
```

### 2.1 目录结构

```
agent-backend/
├── app/
│   ├── main.py              # 应用入口：创建 FastAPI 实例、配置日志、注册异常处理器与路由
│   ├── core/                # 跨层通用能力（安全、配置、异常、日志等），不依赖业务
│   │   ├── config.py        #   配置读取（唯一入口）：分层加载 .env / .env.{APP_ENV}
│   │   ├── security.py      #   安全能力：密码哈希（bcrypt）+ JWT 令牌签发/校验
│   │   ├── exceptions.py    #   自定义异常：BusinessException / SystemException
│   │   ├── logging.py       #   日志配置（Loguru + InterceptHandler）：控制台 + 文件滚动
│   │   ├── handlers.py      #   全局异常处理器（统一转错误响应信封）
│   │   ├── minio_client.py  #   MinIO 客户端：建桶、对象读写、storage_path 转换
│   │   ├── redis_client.py  #   Redis 客户端：懒加载单例（提示词缓存 + 工作记忆，不可用不阻断启动）
│   │   └── rate_limit.py    #   进程内固定窗口限流（IP 维度），注册接口依赖
│   ├── routers/             # ① 路由层，按业务模块拆分
│   │   ├── deps.py          #   路由层共享依赖：get_current_user（Bearer 鉴权）
│   │   ├── user.py          #   用户 CRUD（整组需登录）
│   │   ├── auth.py          #   鉴权接口：注册 / 登录 / 刷新令牌 / 当前用户
│   │   ├── session.py       #   会话管理 + 会话内聊天消息（整组需登录）
│   │   ├── interview.py     #   面试详情（按 interview_id + user_id）
│   │   ├── learning_workflow.py # 学习测评工作流：发起 / 提交 / 详情（整组需登录）
│   │   ├── file.py          #   通用文件上传 / 头像读取（上传需登录，头像公开）
│   │   ├── profile.py       #   用户背景资料 CRUD（仅当前用户，整组需登录）
│   │   ├── prompt.py        #   提示词版本管理（读取 / 回滚 / 智能体配置）
│   │   └── health.py        #   健康检查（存活 + 数据库连通性），路径 /health
│   ├── schemas/             # ② 校验层，按业务模块拆分
│   │   ├── user.py
│   │   ├── auth.py          #   注册 / 登录 / 刷新入参 + 令牌出参（RegisterIn / LoginIn / RefreshIn / TokenOut）
│   │   ├── session.py       #   会话入参 / 出参（SessionCreate / SessionUpdate / SessionOut / SessionListOut）
│   │   ├── message.py       #   聊天消息出参（MessageOut / MessageListOut / SegmentOut）
│   │   ├── chat.py          #   流式对话入参（StreamChatIn / SegmentIn）
│   │   ├── interview.py     #   面试详情出参（InterviewOut，含 qa_object）
│   │   ├── learning_workflow.py # 测评入参 / 出参（Start / Submit / Detail）
│   │   ├── profile.py       #   背景资料入参 / 出参（ProfileCreate / ProfileUpdate / ProfileOut）
│   │   ├── prompt.py        #   提示词出参（PromptTemplateOut / ActivePromptOut / AgentConfigOut）
│   │   ├── file.py          #   文件上传出参（FileOut：url / md5 / size / kind / resource_id 等）
│   │   ├── health.py        #   健康检查出参（HealthOut）
│   │   └── response.py      #   统一响应信封（ResponseModel / ErrorResponse / ok）
│   ├── services/            # ③ 业务层，按业务模块拆分
│   │   ├── user_service.py
│   │   ├── auth_service.py  #   鉴权业务：登录校验、签发 / 刷新令牌、解析当前用户
│   │   ├── session_service.py #  会话分页 / 创建 / 编辑 + 级联删除（含附件资源）
│   │   ├── message_service.py #  会话消息分页查询（正文与附件段分离）
│   │   ├── chat_service.py  #   流式对话：校验 / 检索 / 落库 / SSE 编排
│   │   ├── memory_service.py #  记忆：WorkingMemory（Redis）/ InstantMemory（MySQL 短期）/ LongTermMemory 挂载与统一入口
│   │   ├── long_term_memory.py # 长期记忆：画像读取 / fastembed 意图判断 / 后台 LLM 抽取画像
│   │   ├── ai/              #   AI 两层：llm（模型）/ prompt_layer（提示词与链路）
│   │   ├── profile_service.py #   用户背景资料 CRUD（一人一份，按当前用户隔离）
│   │   ├── prompt_template_service.py # 提示词版本管理：智能体配置 / 拼接 / 回滚 / Redis 缓存
│   │   ├── prompt_injection_service.py # 提示词变量注入：验证（清洗 / 限长）→ 转换（格式化 / 默认值）→ 填充（占位符替换）
│   │   ├── interview_service.py # 面试详情查询（interview_id + user_id 防越权）
│   │   ├── learning_workflow.py # 学习测评：LangGraph 出题 / 评测图 + 状态持久化
│   │   ├── file_type.py     #   上传文件类型识别（文件头 / 扩展名）与大小上限
│   │   ├── upload_service.py#   旧本地磁盘上传逻辑（教学保留，运行时不使用）
│   │   ├── upload_service_minio.py # 运行逻辑：MinIO 落对象 + resources 元数据 + 用户级去重
│   │   ├── avatar_service.py #   用户头像读取：resources/用户头像路径 → MinIO 字节流
│   │   ├── resource_cleanup.py # 每天 03:00 清理过期资源（先删对象再删元数据）
│   │   └── health_service.py#   健康检查：数据库探活，异常转 SystemException(503)
│   ├── rag/                 # RAG 知识库（向量化入库，独立于四层调用链）
│   │   ├── core.py          #   解析 → 清洗 → 分类 → 分块 → 向量化 → 写 Qdrant + 原文入 MySQL（对外仅 ingest_file）
│   │   ├── retriever.py     #   问题向量化 → Qdrant 近邻检索（user_id 隔离 + 可选 doc_category）→ 回表取原文（对外仅 search_similar_chunks）
│   │   ├── context.py       #   检索意图判断（should_retrieve）+ 命中片段格式化（format_retrieved_chunks）
│   │   ├── chunk_store.py   #   切片原文读写 MySQL knowledge_chunks（save_chunks / fetch_chunks_by_vector_ids）
│   │   └── ocr.py           #   扫描页 OCR 兜底：PDFium 渲染 → 火山引擎 OCRNormal（对外仅 ocr_pdf）
│   └── db/                  # ④ 数据库层（SQLAlchemy 2.0 + MySQL）
│       ├── base.py          #   ORM 基类（Alembic 感知表结构的入口）
│       ├── models.py        #   表结构声明（User / UserProfile / ChatSession / ChatMessage / Interview / WorkflowRun / PromptTemplate / KnowledgeChunk / Resource）
│       ├── session.py       #   engine + Session 工厂
│       ├── user_repo.py     #   users 表读写仓储（上层唯一入口）
│       ├── user_profile_repo.py # user_profiles 表读写仓储（按用户查询 / upsert）
│       ├── session_repo.py  #   sessions 表读写仓储（列表 / 归属校验 / 更新 / 删除）
│       ├── message_repo.py  #   chat_messages 表读写仓储（分页 / 记忆历史 / 回写 / 级联清理）
│       ├── interview_repo.py#   interviews 表读写仓储（按 id + user_id 查询 / 按会话删除）
│       ├── workflow_run_repo.py # workflow_runs 表读写仓储（按 run_id + user_id 查询）
│       ├── prompt_template_repo.py # prompt_templates 表读取 / 生效切换仓储
│       ├── resource_repo.py #   resources 表读写仓储（去重预查 / 过期扫描）
│       ├── knowledge_chunk_repo.py # knowledge_chunks 回查（历史消息重建来源）
│       └── health_repo.py   #   数据库连通性探活（SELECT 1）
├── alembic/                 # Alembic 迁移（versions/ 存版本脚本）
│   └── env.py               #   注入 MYSQL_URL、暴露 Base.metadata
├── scripts/
│   ├── db_sync.sh           # 改模型后一键生成迁移并同步
│   ├── agent_prompt.py      # 各智能体动态提示词模板（v1/v2）+ 演示用户资料
│   └── init_prompt.py       # 初始化模板与用户资料到 MySQL（可重复执行）
├── tests/                   # pytest 冒烟测试（连真实 MySQL，见 §9）
│   ├── conftest.py          #   进程内 ASGI 客户端 + 测试数据清理 + 鉴权夹具
│   ├── test_smoke.py        #   健康检查 + 用户 CRUD 冒烟用例（CRUD 需鉴权）
│   ├── test_auth.py         #   鉴权冒烟用例（注册 / 登录 / 刷新 / me / 文件上传）
│   ├── test_sessions.py     #   会话 / 消息 / 面试详情 / 级联删除用例
│   ├── test_stream_chat.py  #   流式对话用例（假链路，覆盖 SSE / 上下文 / 失败落库）
│   ├── test_prompt_templates.py # 提示词版本 / 拼接 / 回滚 / Redis 缓存用例
│   ├── test_prompt_injection.py # 提示词变量注入：清洗 / 格式化 / 替换 / 接口集成用例
│   ├── test_profiles.py     # 用户背景资料 CRUD / 409 冲突 / 校验用例
│   ├── test_agent_prompt.py # 初始化模板数据校验（作用域 / 占位符 / 变量白名单）
│   ├── test_rag_chat.py     #   RAG 对话链路：意图判断 / 资料注入 / 来源落库与历史回显
│   ├── test_long_term_memory.py # 长期记忆：画像格式化 / 意图判断 / 抽取清洗 / 后台写入
│   ├── test_long_term_chat.py #   流式对话接入长期记忆：跳过 RAG / 必填缺失触发抽取
│   ├── test_working_memory.py #   Redis 工作记忆读写 / 摘要 / 降级
│   ├── test_learning_workflow.py # 学习测评：出题 / 评分 / 作答校验 / 越权隔离
│   └── test_resources.py    #   过期资源清理用例
├── alembic.ini              # Alembic 配置（连接串留空，由 env.py 注入）
├── pytest.ini               # pytest 配置（asyncio_mode=auto、pythonpath=.）
├── .env.example             # 基础环境变量模板（真实 .env 被 gitignore）
├── .env.dev.example         # 开发环境覆盖模板（真实 .env.dev 被 gitignore）
├── .env.prod.example        # 生产环境覆盖模板（真实 .env.prod 被 gitignore）
├── logs/                    # 日志输出目录（运行期生成，被 gitignore）
├── requirements.txt         # 运行期依赖
├── requirements-dev.txt     # 测试依赖（pytest / httpx / pytest-asyncio）
├── .gitignore
├── AGENTS.md                # 本规范
└── CLAUDE.md                # 引用本规范
```

### 2.2 各层职责与红线

| 层 | 应该做 | 禁止做 |
| --- | --- | --- |
| **routers** | 声明路径 / 状态码 / `response_model`；透传参数 | ❌ 写业务判断、直接碰 `db` |
| **schemas** | 字段校验、类型约束、出参裁剪 | ❌ 访问数据库、写业务逻辑 |
| **services** | 业务规则、编排 db 与 core | ❌ 直接返回未裁剪的敏感字段 |
| **db** | 数据存取，返回记录**副本** | ❌ 感知 HTTP、导入 fastapi |

**新增一个业务模块 = 在四层各加一个文件**（`routers/xxx.py`、`schemas/xxx.py`、`services/xxx_service.py`，必要时加 `db/xxx.py`），并在 `main.py` 注册路由。不要在层内塞入其他层的职责。

### 2.3 错误处理约定

- 业务错误在 **services 层**统一抛 `BusinessException`（可预期，4xx，如 404 不存在、409 冲突），系统级故障抛 `SystemException`（不可预期，5xx）；两类异常定义在 `app/core/exceptions.py`，均携带 `message`（面向用户）与 `detail`（面向开发者定位）。
- 异常由 `app/core/handlers.py` 的**全局异常处理器**统一转成错误响应信封 `{code, message, detail}`（`code` 复用 HTTP 状态码）；路由层因此保持极薄，**不做 try/except**。
- 参数错误由 **schemas 层**自动产生，全局处理器把 `RequestValidationError` 转成 `422` 信封，不手写校验代码。
- 框架 `HTTPException`（如 404 路由不存在）与未捕获的 `Exception` 也由全局处理器兜底成同一信封，避免泄漏内部细节。
- 日志约定：业务 / 参数错误记 `WARNING`，系统 / 未捕获错误记 `ERROR`（含堆栈，供后端定位）。

---

## 3. 命名规范

| 对象 | 规范 | 示例 |
| --- | --- | --- |
| 模块文件 | 小写单词 | `security.py`、`session.py` |
| 业务 service 文件 | 小写 + `_service` 后缀 | `user_service.py` |
| 路由 / 校验文件 | 与业务模块同名 | `user.py` |
| 函数 / 变量 | snake_case | `create_user`、`hashed_password` |
| 类 / 模型 | PascalCase | `UserCreate`、`UserOut` |
| 常量 | UPPER_SNAKE_CASE | `PASSWORD_MIN_LENGTH` |
| 私有函数 | 下划线前缀 | `_ensure_unique()` |

**校验模型命名**：入参用 `XxxCreate` / `XxxUpdate`，出参用 `XxxOut`，公共字段抽 `XxxBase`；统一响应信封固定用 `ResponseModel` / `ErrorResponse`（见 §6）。

**异常类命名**：自定义异常统一以 `Exception` 结尾（`BusinessException` / `SystemException`），放 `app/core/exceptions.py`。

---

## 4. Pydantic v2 约定

- 统一使用 **v2 语法**：`model_config = ConfigDict(...)`、`model_dump()`、`model_validate()`，禁止 v1 的 `class Config` / `.dict()` / `.json()`。
- 可选字段写 `X | None`，默认值 `None`。
- 出参模型**必须显式排除敏感字段**（如 `password`），即使业务层误传也不会外泄。
- 更新类模型（`XxxUpdate`）字段全部可选，业务层用 `model_dump(exclude_unset=True, exclude_none=True)` 实现「只更新传入的字段」。
- 邮箱等格式字段用 `EmailStr`（依赖 `email-validator`）。

---

## 5. 安全约定

- **密码绝不落明文**：一律经 `app/core/security.py` 的 `hash_password()` 处理后存储，出参模型不含 `password`。
- 哈希算法只在此模块配置，业务层不感知算法细节。
- 密钥、Token、数据库口令等敏感信息**只放环境变量 / 后端配置**，禁止硬编码、禁止提交。
- **配置读取只走 `app/core/config.py`**：其他层（含 `logging.py`）从该模块取类型化配置项，**禁止直接 `os.getenv`**。
- 环境变量**分层加载**，优先级 `真实环境变量 > .env.{APP_ENV} > .env`（`APP_ENV` 取 `dev`（默认）/ `prod`）；生产密钥建议用真实环境变量注入，不落 `.env.prod`。
- 错误响应的 `detail` 仅用于后端定位，**禁止回传堆栈、密码、Token 等敏感信息**；面向用户的提示放 `message`。
- **JWT 密钥只走环境变量 `JWT_SECRET`**（入口 `app/core/config.py` 的 `get_jwt_secret()`，缺失即报错），禁止硬编码 / 提交；令牌算法与有效期也经环境变量可配（`JWT_ALGORITHM` / `ACCESS_TOKEN_EXPIRE_MINUTES` / `REFRESH_TOKEN_EXPIRE_DAYS`）。登录失败统一文案「用户名或密码错误」，不区分账号是否存在（防用户名枚举）。
- 输入校验交给 schemas 层，不手写字符串拼接式校验。

> **日志体系**：`app/core/logging.py` 的 `setup_logging()` 在 `main.py` 启动时调用一次，底层用 **Loguru**。开发（`dev`）输出控制台 + 文件，生产（`prod`）只落文件；文件按大小滚动（10MB × 5）写入 `logs/app.log`（`LOG_DIR` 可覆盖，相对路径锚定仓库根）。标准库 `logging`（含 uvicorn 与项目内 `logging.getLogger`）经 `InterceptHandler` 汇入 Loguru，访问日志同样落文件且不重复；业务代码只管 `logging.getLogger(__name__)` 打日志，不要自行 `basicConfig` / 加 handler。业务错误记 `WARNING`、系统错误记 `ERROR`（见 §2.3）。

---

## 6. 接口约定

- 路径统一以 `/api` 开头，资源用复数名词（`/api/users`）。
- **统一响应信封**（成功 / 失败结构一致，定义在 `app/schemas/response.py`）：

  ```jsonc
  // 成功
  { "code": 200, "message": "ok", "data": { /* 业务数据，可为 null */ } }
  // 失败
  { "code": 404, "message": "用户 1 不存在", "detail": "user_id=1" }
  ```

  `code` **复用 HTTP 状态码**（成功 `200`；错误 `401` / `404` / `409` / `422` / `429` / `500`），与响应的 HTTP 状态码一致。

- RESTful 语义与状态码：

  | 操作 | 方法 + 路径 | 成功状态码 |
  | --- | --- | --- |
  | 新增 | `POST /api/users` | `200` |
  | 列表 | `GET /api/users` | `200` |
  | 详情 | `GET /api/users/{id}` | `200` |
  | 更新 | `PUT /api/users/{id}` | `200` |
  | 删除 | `DELETE /api/users/{id}` | `200` |
  | 注册 | `POST /api/auth/register` | `200` |
  | 登录 | `POST /api/auth/login` | `200` |
  | 刷新令牌 | `POST /api/auth/refresh` | `200` |
  | 当前用户 | `GET /api/auth/me` | `200` |
  | 上传文件 | `POST /api/files` | `200` |
  | 会话列表（分页） | `GET /api/sessions?page=&page_size=` | `200` |
  | 创建会话 | `POST /api/sessions` | `200` |
  | 编辑会话标题 | `PUT /api/sessions/{session_id}` | `200` |
  | 删除会话（级联） | `DELETE /api/sessions/{session_id}` | `200` |
  | 会话消息（分页） | `GET /api/sessions/{session_id}/messages?page=&page_size=` | `200` |
  | 流式对话（SSE） | `POST /api/sessions/{session_id}/stream-chat` | `200` |
  | 面试详情 | `GET /api/interviews/{interview_id}` | `200` |
  | 发起学习测评 | `POST /api/learning-workflows/start` | `200` |
  | 提交测评作答 | `POST /api/learning-workflows/{run_id}/submit` | `200` |
  | 测评运行详情 | `GET /api/learning-workflows/{run_id}` | `200` |
  | 创建背景资料 | `POST /api/profiles` | `200` |
  | 查询背景资料 | `GET /api/profiles/me` | `200` |
  | 更新背景资料 | `PUT /api/profiles/me` | `200` |
  | 删除背景资料 | `DELETE /api/profiles/me` | `200` |
  | 作用域生效模板 | `GET /api/prompt/templates/{agent_name}/{scene}` | `200` |
  | 一键回滚 | `POST /api/prompt/rollback` | `200` |
  | 完整提示词（公共 + 私有） | `GET /api/prompt/full-prompt?agent_name=&scene=` | `200` |
  | 智能体配置 | `GET /api/prompt/config/agents` | `200` |

  > 统一信封下成功一律 `200`：删除不用 `204`（无响应体，前端无法解析信封）；新增不用 `201`（避免 body.code 与 HTTP 状态码不一致）。

- **鉴权约定**：除注册 / 登录 / 刷新 / 健康检查外，接口需携带 `Authorization: Bearer <access_token>`；令牌缺失 / 过期 / 非法 / 类型不符一律返回 `401`（由 `core/security.decode_token` 与 `routers/deps.get_current_user` 抛 `BusinessException(401)`）。**刷新令牌只能用于 `/api/auth/refresh`**，不能访问受保护接口（`type` 声明区分）；访问令牌过期时由前端调 `/api/auth/refresh` 换新令牌后重试原请求。令牌为无状态 JWT，**暂不支持主动吊销 / 登出**（后续需要再引入黑名单或落库）。
- **注册接口安全约定**（`POST /api/auth/register`）：复用 `user_service.create_user`（bcrypt 哈希，禁止明文入库）；弱密码（黑名单 / 缺字母 / 缺数字 / 含用户名）由**校验层** `schemas/auth.py` 拦截 → `422`；接口限流由 `core/rate_limit.py` 的依赖实现（固定窗口 + IP 维度，默认 5 次/min），超限抛 `BusinessException(429)`。限流为**进程内内存**实现，仅单机有效，多实例部署需换共享存储。
- **通用文件上传约定**（`POST /api/files`）：`multipart/form-data`，字段 `file`，**需登录**；可选表单字段 `upload_purpose`（0=普通资源 / 1=用户头像，默认 0）与 `storage_scene`（0=长期 30 天 / 1=短期 2 小时 / 2=只提取内容不存原文件，默认 0）。**文档支持 PDF / DOC / DOCX / TXT，音频支持 MP3 / WAV / OGG / OPUS / M4A / AAC / FLAC / WebM**（均按扩展名白名单 + 文件头校验）；图片（JPG / PNG / WebP / GIF）仅用于头像（`upload_purpose=1`），普通上传不接受图片；其他类型或文件头不符一律 `422`，图片超 2MB（`AVATAR_MAX_BYTES`）或文档 / 音频超 10MB（`FILE_MAX_BYTES`）返回 `413`。**元数据写 `resources` 表，原文件落 MinIO**：对象 key 为 `users/{user_id}/{MD5}{ext}`，`storage_path` 格式 `minio:/{bucket}/{object_key}`；`(file_hash, user_id)` 唯一键实现用户级去重（先查库，数据库唯一键兜底）。仅 `upload_purpose=1` 且为图片时更新 `users.avatar`（库里存 `storage_path`）。对外响应中的 `avatar` 由校验层转成公开读取地址 `/api/files/avatar/{user_id}?v={md5}`（`v` 用于头像更新后失效缓存）。`storage_scene=2` 只写元数据、不上传对象（`storage_path` 为空串）。**文档必传表单字段 `doc_category`（`resume` / `study_material` / `general`），缺失或非法一律 `422`；音频 / 头像忽略该字段并存 `NULL`。** 文档落库后经 `BackgroundTasks` **异步**执行 RAG（解析 → 清洗 → 分块 → DashScope 向量化 → Qdrant 存向量 + MySQL `knowledge_chunks` 存原文），失败只记日志、不影响上传结果。PDF 解析用 PDFium 逐页取文本层，按「图片覆盖率 ≥ 0.5 且有效字符 < 200」判定扫描页，仅对这些页渲染 200 DPI 调火山引擎 `OCRNormal`，再与文本层按页序合并；方案说明见 [`docs/scanned-pdf-ocr.md`](docs/scanned-pdf-ocr.md)。同用户同内容重复上传时若分类相同则直接复用、不重复入库；分类变化则更新 `doc_category`，并以 `replace=True` 先按 `resource_id` 删除旧向量再重灌。响应返回 `{url, md5, size, kind, resource_id, storage_path, expire_time, doc_category, reused}`，`reused` 表示是否复用了已有资源。过期资源由 `resource_cleanup` 每天 03:00 先删 MinIO 对象、再删元数据。
- **会话与聊天消息约定**：
  - 会话整组接口（`/api/sessions`、`/api/sessions/{id}/messages`）需登录，所有查询按令牌中的 `user_id` 隔离；资源不存在或不属于当前用户一律 `404`（不区分「不存在」与「无权限」，避免泄露）。
  - 创建会话入参 `title` + `session_mode`（0=学习，1=面试，2=笔记），同时兼容需求文档字段名 `session_model`（`AliasChoices`）；出参不暴露 `user_id`。
  - 分页统一 `{items,total,page,page_size}`：`page ≥ 1`、`page_size` 1..100；会话按 `created_at DESC, id DESC`，消息按 `created_at ASC, id ASC`。
  - `chat_messages` 语义：**聊天正文在 `request_text` / `response_text`**；`request_segments` / `response_segments` **只存附件段**（`{type: file|image|audio, resource_id, file_name?, url?}`），AI 回复文本始终进 `response_text`。消息出参还包含 `status`（0=生成中，1=完成，2=失败）与 `interview_id`（普通聊天为 `null`），供前端面试卡片逻辑使用。历史消息的 `sources` 由 `reference_sources` 回查 `knowledge_chunks` + `resources` 重建；知识块已删除时仍返回该条目，`text` 为「该参考片段已被删除」。
  - **级联删除**（`DELETE /api/sessions/{id}`）：先解析消息附件段收集 `resource_id`，再按 `interviews → chat_messages → sessions` 的依赖顺序删库；最后仅删除当前用户自己的 `resources` 元数据与 MinIO 对象（先删对象、成功后再删元数据，失败则保留元数据交给过期清理重试）。
- **流式对话约定**（`POST /api/sessions/{session_id}/stream-chat`）：
  - 入参 `request_text`（必填，去空白后 1..20000 字）、`select_mode`（0..5）、`request_id`（可选，缺省由后端生成）、`request_segments`（仅可引用当前用户自己的 `resource_id`，越权返回 404）。
  - **响应为 `text/event-stream`，不使用统一 JSON 信封**；这是 SSE 接口的既定例外，因此不声明 `response_model`。
  - 校验与用户消息落库在建立流之前完成，404 / 422 / 503 仍返回标准 JSON 错误信封；流开始后失败以 SSE `error` 事件返回。
  - 事件：`meta`（`session_id` / `message_id` / `request_id`）→ `delta`（`{content}`）→ `done`（`{message_id, status, sources}`）；异常以 `error`（`{code, message}`）收尾。响应头含 `Cache-Control: no-cache`、`X-Accel-Buffering: no`，避免反向代理缓冲。
  - 落库：用户消息先以 `status=0`（生成中）写入；成功回写 `response_text` + `status=1`，并写入 `reference_sources`（只存 `[{chunk_id, score}]`）；模型失败或客户端断开时保留已生成的部分内容并置 `status=2`。
  - **RAG 按需检索**：`should_retrieve(request_text)` 先跳过空 / 极短 / 确认语 / 礼貌语 / 推进语；命中时才调用 `search_similar_chunks(query, user_id, top_k=3)`，把 `format_retrieved_chunks` 生成的参考文本拼到本轮问题前，并在系统提示词后追加 `build_rag_system_prompt` 的回答规则。检索失败降级为普通对话，不阻断流式生成。`done.sources` 为完整来源（`chunk_id` / `resource_id` / `chunk_index` / `file_name` / `score` / `text`），顺序与注入的 `[1] [2]` 编号一致。
  - AI 分层（`app/services/ai/`）：`llm.py` 只负责 provider → 模型实例；`prompt_layer.py` 只负责系统提示词与 `prompt | model | parser` 链路。`chat_service.py` 只做编排与 SSE 输出。
  - 记忆读取（`app/services/memory_service.py`）：`MemoryService.load_context()` 是统一入口，**Redis 工作记忆优先、MySQL 短期记忆兜底**，默认 `enable_long_term=True`。
    - `WorkingMemory`（Redis）：key `memory:working:{user_id}:{session_id}`，value 为 `{"raw": [{role, content}], "summary": str}`，TTL 8 小时，读写后自动续期；读失败 / 无数据返回空结构，写失败只记日志，任何 Redis 异常都不向上抛。原文累计超过 8000 字时调用 `quick_summarize` 把更早内容并入摘要，只保留最近 6 条原文；摘要硬截断 500 字，总结失败则保留完整原文等待下轮重试。
    - `InstantMemory`（MySQL）：`load()` 按 `created_at` 倒序取最近 `MEMORY_MAX_TURNS` 轮 `status=1` 的消息 → `_fit_char_budget` 先按 `MEMORY_MESSAGE_MAX_CHARS` 截断单条、再按总预算（12000 字）丢弃更旧消息 → `build_chat_history_from_rows` 转成 LangChain 消息；`file_extracted_text` 非空时拼入对应的用户消息。Redis 为空（新会话 / 过期 / 故障）时回退该路径，并把结果 `seed()` 回 Redis，保证后续轮次继续累积。
    - `LongTermMemory`（`app/services/long_term_memory.py`）：从 `user_profiles` 读取 `target_job / years_experience / target_level / target_skills / weak_topics / learning_goal / learning_style / interview_focus / long_term_summary`，格式化成画像文本并以 `SystemMessage` 插在 history 最前；该消息在 `seed()` 之后注入，不会写入 Redis 工作记忆。`prompt_layer` 在执行链路前把 history 中所有 `SystemMessage` 取出、从 history 移除，并追加到 `system_prompt` 末尾（两个换行分隔）。
    - 当前问题存在摘要时以 `【会话摘要】\n...` 前缀注入 `input`，不额外插入 system 消息；AI 回复成功后 `append_turn()` 把**原始问题**（不含 RAG 拼接资料）与回复写入工作记忆。
  - 长期记忆写入：`chat_service.prepare_stream` 先调用 `LongTermMemory.should_write()`（fastembed 本地向量 + 余弦相似度，阈值 0.6，模型异常降级为 False）；命中画像写入意图时跳过 RAG 检索。**触发条件**为「意图命中」或「三项必填资料缺失（`missing_required_fields()` 非空）且本轮消息去空白后 ≥ 2 字」；后者不跳过 RAG，用于接住用户对开场白表单的简短回答（如「3 年」「后端开发」）。流成功后用最近 4 条历史消息 + 本轮回复调用 `submit_profile_update_async()`，后台线程让 LLM 抽取全部 9 个业务画像字段（`target_job / years_experience / target_level / target_skills / weak_topics` 及 `learning_goal / learning_style / interview_focus / long_term_summary`），经 `profile_service.create_or_update()` 写回 `user_profiles`；抽取为空或任一步失败只记日志。**画像以新会话开场白表单为主（前端写入）、对话抽取为补充**，AI 不在对话中反复追问缺失项。
  - 模型统一走 OpenAI 兼容协议，配置项 `LLM_PROVIDER / LLM_MODEL / LLM_API_KEY / LLM_BASE_URL / LLM_TEMPERATURE / LLM_TIMEOUT / LLM_MAX_RETRIES`；密钥只放环境变量，缺失时该接口返回 503，不影响其他接口启动。
- **面试记录约定**：`interviews.user_id` 记录归属；`GET /api/interviews/{interview_id}` 必须按 `interview_id + user_id` 查询，返回含 `qa_object` 的详情，防止越权读取他人面试记录。
- **学习测评工作流约定**（`/api/learning-workflows`，整组需登录）：
  - 两次请求闭环：`POST /start` 出题（`quiz_ready`）→ `POST /{run_id}/submit` 评分（`completed`）；`GET /{run_id}` 返回状态与完整 `state`。`run_id` 为 UUID，按 `user_id` 隔离，越权 / 不存在统一 `404`。
  - LangGraph 编排（`app/services/learning_workflow.py`）：启动图 `prepare_learning_context → generate_quiz → END`，提交图 `evaluate_and_review → END`；状态字段固定为 `run_id / user_id / session_id / request_text / provider / question_count / quiz / answers / evaluation / score / weaknesses / review / status`，完整落 `workflow_runs.state_json`。
  - 题目结构 `{question_id, type, stem, options: [{key, text}]}`，题型 `single_choice / multiple_choice / short_answer`；**标准答案不落库、不返回前端**，评分由提交时的模型调用完成。前端只提交 `answers: [{question_id, value}]`（单选字符串、多选数组、简答字符串）。
  - 作答校验：必须覆盖全部题目、不允许重复 / 未知题目 / 非法选项 / 空作答，违规返回 `422`；仅 `quiz_ready` 可提交，已完成重复提交返回 `409`。模型失败时运行记录置 `failed` 并写 `error_message`，配置缺失返回 `503`、模型 / 解析失败返回 `502`。
  - 模型输出的 JSON 由 `app/services/ai/json_utils.py` 的 `parse_json_object()` 统一解析（截取首个 `{` 到末个 `}`），提示词中的 JSON 示例必须作为静态 `SystemMessage` 传入。
  - Swagger 联调步骤、反向用例与落库核对见 [`docs/learning-workflow-api-guide.md`](docs/learning-workflow-api-guide.md)。
- **用户背景资料约定**（`/api/profiles`，整组需登录）：一人一份（`user_profiles.user_id` 唯一），`user_id` 一律取自令牌，不接受客户端传入，因此只能操作自己的资料。`POST /api/profiles` 创建（已存在 → `409`）；`GET/PUT/DELETE /api/profiles/me` 查询 / 局部更新 / 删除（不存在 → `404`）。字段：`target_job`（≤64）、`years_experience`（0..60）、`target_level`（≤32）、`target_skills` / `weak_topics`（字符串数组，≤20 项、单项 ≤50 字）。出参不含 `user_id`。资料供提示词变量注入使用，删除后注入回退为默认值。
- **提示词版本管理约定**（`/api/prompt`，整组需登录）：
  - 数据表 `prompt_templates`：`agent_name`、`scene`、`template_type`（1=私有，2=公共）、`template_content`、`variables`（JSON 数组字符串）、`version`、`is_active`、`description`、`created_at`。
  - **公共通用模板固定标识 `agent_name='common'` + `scene='common'`**（`template_type=2`）；私有模板为智能体名 + 专属场景（`template_type=1`）。组合不符由校验层拦截 → 422；未知智能体 / 场景 → 404，智能体不支持的场景 → 400。
  - 7 个智能体映射（`prompt_template_service.AGENT_CONFIG`，`GET /api/prompt/config/agents` 暴露）：`flow_controller`/流程总控/`workflow`、`resume_parser`/资料解析/`resume`、`quiz_generate`/出题题库/`quiz`、`interview_host`/面试主考官/`interview`、`interview_evaluator`/面试评测/`evaluation`、`difficulty_learner`/难点学习/`study`、`note_archiver`/笔记归档/`note`。
  - 版本号按 `(agent_name, scene)` 独立自增；同一作用域仅一条 `is_active=1`。**新建版本暂未实现**，待后续需求确定后再补充（接口与服务层均不提供写入）；当前仅支持读取与回滚，回滚即把指定历史版本重新置为生效。
  - `GET /api/prompt/templates/{agent_name}/{scene}` 只返回该作用域自身的生效版本（`common/common` 即公共模板），返回 `PromptTemplateOut`。
  - `GET /api/prompt/full-prompt?agent_name=&scene=` 拼接公共与私有：返回 `public_template`、`private_template`、`final_template`（公共在前、空行分隔）与合并去重后的 `variables`；`common/common` 只取公共通用模板。
  - **初始化与验证**：`scripts/agent_prompt.py` 维护各智能体 v1/v2 动态模板，`scripts/init_prompt.py` 幂等写入 `prompt_templates` + 演示用户资料并刷新缓存；逐步验证流程见 [`docs/prompt-injection-guide.md`](docs/prompt-injection-guide.md)。
  - **用户变量注入**（`prompt_injection_service`）：按当前登录用户在 `user_profiles` 中的资料，把 `{target_job}` / `{years_experience}` / `{target_level}` / `{target_skills}` / `{weak_topics}` 替换为实际值，响应额外返回 `rendered_template` 与 `injected_variables`；`final_template` 保持未渲染原文。三层流程：验证层（去控制字符 / 换行 / 花括号 / 反斜杠，标量 100 字、数组项 50 字、最多 20 项、总注入 1000 字）→ 转换层（数组用「、」连接，缺失默认 `未提供` / `暂无`，年限 0 为 `应届/无经验`）→ 填充层（只替换模板 `variables` 已声明的占位符，未声明的原样保留，注入值不二次解析）。无资料时按默认值渲染。
  - Redis 只作缓存：Hash `prompt:templates:active`（`PROMPT_CACHE_KEY`），字段私有 `{agent}:{scene}`、公共 `common:common`。启动时全量预热，写入 / 回滚后刷新对应字段；未命中或 Redis 不可用一律回源 MySQL。TTL 1 小时用于多实例部署的最终一致。
- **系统接口 / 静态资源**：`GET /health`（运维探活）与 `/uploads/*`（旧版本地文件静态访问，由 `main.py` 挂载）**有意不挂 `/api` 前缀**：前者校验服务存活 + 数据库连通性，正常 `200`、数据库异常 `503`（由 `health_service` 抛 `SystemException(503)`）；后者仅兼容历史上已落盘的头像/文件，新上传统一走 MinIO。这是对「路径以 `/api` 开头」的例外，新增此类端点需在本文档登记。
- **头像读取例外**：`GET /api/files/avatar/{user_id}` **无需鉴权且返回二进制**（不是统一信封），因为浏览器 `<img src>` 不会携带 `Authorization` 头；供头像展示使用，按 user_id 只暴露头像对象，不暴露其他资源。
- 每个路由**必须声明 `response_model`**，出参信封用 `ResponseModel[XxxOut]`（列表用 `ResponseModel[list[XxxOut]]`），保证出参被裁剪且有文档。
- 路由返回值统一用 `ok(data)` 包成成功信封，**不要手写 `{"code": ...}`**。
- 每个路由**必须写 `summary`**，便于 `/docs` 阅读。
- 需要跨域直连时再引入 `CORSMiddleware`；当前前端走 Vite 代理（同源），默认不开启。

---

## 7. 数据库层约定

- 使用 **SQLAlchemy 2.0 + MySQL**（同步驱动 PyMySQL）持久化；表结构声明在 `app/db/models.py`。
- 表结构变更**必须走 Alembic 迁移**：改完模型执行 `scripts/db_sync.sh "说明"`（等价于 `alembic revision --autogenerate` + `alembic upgrade head`）。**禁止在代码里用 `create_all` 建表**，避免与迁移职责重叠。
- 连接串从环境变量 `MYSQL_URL` 读取（`app/core/config.py` 统一入口），**禁止写进 `alembic.ini` 或硬编码**。
- 上层（services）只能通过 `app/db/xxx_repo.py` 暴露的函数读写，**禁止直接访问 Session / ORM 对象**。
- `db` 层对外返回记录**副本**（普通 `dict`），不把会话内 ORM 对象交给调用方。
- 更换存储实现时，**只改 `db/` 层**，上层调用签名保持不变。
- `prompt_templates` 的 `(agent_name, scene, version)` 唯一键兜底版本号；公共通用模板固定作用域 `(common, common)`，与私有模板走同一套逻辑，「单一生效」由仓储层 `SELECT ... FOR UPDATE` 事务行锁保证。
- `user_profiles` 一人一行（`user_id` 唯一，外键 `users.id` + `ON DELETE CASCADE`），存目标岗位 / 工作年限 / 目标等级 / 已掌握技能 / 薄弱点，供提示词变量注入读取；数组字段用 MySQL `JSON`。基础五项可由前端开场白表单（资料 CRUD 接口）写入，也可由对话后台抽取回填；长期字段 `learning_goal` / `learning_style`（`VARCHAR(255)`）、`interview_focus`（`JSON` 数组）、`long_term_summary`（`TEXT`）只由对话后台自动抽取。后台写入经 `profile_service.create_or_update()` 白名单过滤（允许全部 9 个业务字段，拒绝 `user_id` 等非业务列）。上层只经 `app/db/user_profile_repo.py` 读写。
- `workflow_runs` 是跨请求工作流实例表：`run_id`（UUID）对外唯一标识，`user_id` / `session_id` 外键 `ON DELETE CASCADE`（会话删除即清理流程），`workflow_type` 标识流程类型（当前为 `learning_quiz`），`status` 取 `running / quiz_ready / completed / failed`，完整状态存 `state_json`（`JSON`），失败原因存 `error_message`，完成后写 `completed_at`。上层只经 `app/db/workflow_run_repo.py` 读写，所有查询必须同时带 `run_id + user_id`。
- `chat_messages` 的附件段用 MySQL `JSON` 列存储（`request_segments` / `response_segments`，可为 `NULL`），正文不入 JSON；`reference_sources` 同为可空 `JSON`，只存 `[{chunk_id, score}]`（知识块全文不落消息表，历史回显时按 `chunk_id` 回查）。`status` 为 `Integer`（0/1/2），`interview_id` 为可空 `BigInteger`（**不建外键**，避免与 `interviews.message_id` 形成循环依赖）。`interviews.user_id` 必填并建索引，所有详情查询必须同时带 `interview_id` 与 `user_id`。
- `resources.doc_category` 为可空 `String(32)`，取值 `resume` / `study_material` / `general`，仅 `resource_type=0` 文档有意义，非文档为 `NULL`。同内容去重命中且分类变化时，由 `app/db/resource_repo.py` 的 `update_doc_category()` 更新，并触发该 `resource_id` 的向量重灌。
- **RAG 双存储**：Qdrant 集合 `knowledge_chunks` 只存向量与过滤字段（`user_id` / `doc_category` / `file_name` / `chunk_index` / `resource_id`），**不存原文**；原文与统计字段落 MySQL `knowledge_chunks`（`vector_id` / `resource_id` / `chunk_index` / `text` / `char_count`），`vector_id` 即 Qdrant Point id，两边一一对应。`resource_id` 外键级联删除，重灌时按 `resource_id` 先删后插；写入顺序为「先 Qdrant、后 MySQL」，MySQL 失败会尽力回删刚写入的向量。检索走 `rag/retriever.py`：按 `user_id` 隔离、可选 `doc_category` 收窄，分数阈值 0.4，命中后按 `vector_id` 回查原文；对话来源只在 `chat_messages.reference_sources` 存 `chunk_id + score`。

---

## 8. 代码风格

- 全量类型注解：函数入参与返回值都标注类型。
- 使用 Python 3.10+ 联合类型写法 `X | None`，不用 `Optional[X]`。
- 注释写「**为什么**」而非「是什么」：显而易见的代码不加注释，关键约束（如 bcrypt 72 字节上限、依赖锁定原因）必须注释说明。
- 模块顶部写一句话 docstring 说明该层职责。
- 保持函数短小聚焦，一个函数做一件事；不为一次性逻辑抽象工具类。
- 不做需求之外的「顺手重构」。

---

## 9. 环境与命令

```bash
# 创建并激活虚拟环境（仓库内已有 .venv/ 时跳过创建）
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量（复制模板为 .env 填真实值；可选再复制 .env.dev / .env.prod 覆盖）
cp .env.example .env
# cp .env.dev.example .env.dev      # 开发覆盖：LOG_LEVEL=DEBUG、控制台日志
# cp .env.prod.example .env.prod    # 生产覆盖：LOG_LEVEL=WARNING、只落文件
# APP_ENV 决定叠加哪个覆盖文件：dev（默认）/ prod，可 export APP_ENV=prod 切换
# 注意：.env 必须填 JWT_SECRET（缺失时服务启动即报错）

# 建表 / 同步表结构（改完 app/db/models.py 后执行）
alembic upgrade head
scripts/db_sync.sh "说明"     # 等价于 autogenerate + upgrade 的一键同步

# 启动开发服务（默认 8000，与前端代理对齐）
uvicorn app.main:app --reload --reload-exclude 'logs/*' --port 8000
# 日志落 logs/app.log（滚动），dev 同时输出控制台

# 接口文档
#   Swagger UI : http://127.0.0.1:8000/docs
#   OpenAPI    : http://127.0.0.1:8000/openapi.json

# 测试（连真实 MySQL，需先 alembic upgrade head）
pip install -r requirements-dev.txt
pytest tests/test_smoke.py -v
```

- 提交前确保服务能正常启动、`/docs` 可打开。
- 提交前跑一遍 `pytest tests/test_smoke.py -v`，冒烟测试应全绿。
- **待引入（引入前需团队确认）**：格式化 / Lint（ruff）、Git hook。

---

## 10. Git 规范

- 提交信息遵循 **Conventional Commits**（与仓库现有历史一致）：

  ```
  <type>(<scope>): <描述>

  type: feat | fix | docs | style | refactor | perf | test | chore | build | ci
  scope: user | api | db | deps ...
  ```

  示例：`feat(user): 新增用户更新接口`
- 小步提交，一次提交聚焦一件事；禁止把格式化 / 无关改动混入功能提交。
- **未经明确授权，不要 `git push`、不要改历史、不要强推。**

---

## 11. 与 AI 助手协作约定

- 改动代码前**先阅读相关文件**，理解现有实现再动手，不要凭猜测修改。
- 严格遵守本规范；如与规范冲突，以本规范为准，并说明冲突点。
- **不擅自引入新依赖、不擅自大改目录结构或架构**；此类改动需先说明理由并取得确认。
- 不生成或提交任何密钥、凭据、真实用户数据。
- 不执行未经确认的破坏性或对外可见操作（推送、发 PR、改 CI、删分支等）。
- 保持改动范围聚焦：修 bug 就只修 bug。

---

## 12. 禁止事项（红线）

- ❌ 密码明文落库或出现在任何响应中。
- ❌ 路由层写业务逻辑，或跨层直接调用 `db`。
- ❌ 使用 Pydantic v1 语法（`class Config` / `.dict()`）。
- ❌ 硬编码端口 / 密钥 / 数据库口令。
- ❌ 直接读写 `db` 层内部字典，绕过其函数。
- ❌ 在路由中手写 `try/except` 处理业务错误（应抛 `BusinessException` / `SystemException`，交全局处理器）。
- ❌ 在错误响应的 `detail` 中回传堆栈 / 密码 / Token 等敏感信息。
- ❌ 手写 `{"code": ...}` 拼装成功响应（应用 `ok(data)` + `response_model=ResponseModel[...]`）。
- ❌ 提交 `.venv/`、`__pycache__/`、`.env`。
- ❌ 未授权情况下 push / 强推 / 改历史。
