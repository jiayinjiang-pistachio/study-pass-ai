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
| ORM / 数据库 | SQLAlchemy `2.0.x` + PyMySQL | MySQL 同步驱动，模型声明于 `app/db/models.py` |
| 表结构迁移 | Alembic `1.14.x` | 改模型后 `scripts/db_sync.sh` 一键同步 |
| 配置读取 | `python-dotenv` | 分层加载：真实环境变量 > `.env.{APP_ENV}` > `.env`，入口 `app/core/config.py`（唯一读取入口） |
| 日志 | Loguru `0.7.x` | 开发控制台 + 文件，生产只落文件；按大小滚动（10MB × 5），入口 `app/core/logging.py` |
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
│   │   ├── security.py      #   密码哈希封装
│   │   ├── exceptions.py    #   自定义异常：BusinessException / SystemException
│   │   ├── logging.py       #   日志配置（Loguru + InterceptHandler）：控制台 + 文件滚动
│   │   └── handlers.py      #   全局异常处理器（统一转错误响应信封）
│   ├── routers/             # ① 路由层，按业务模块拆分
│   │   ├── user.py
│   │   └── health.py        #   健康检查（存活 + 数据库连通性），路径 /health
│   ├── schemas/             # ② 校验层，按业务模块拆分
│   │   ├── user.py
│   │   ├── health.py        #   健康检查出参（HealthOut）
│   │   └── response.py      #   统一响应信封（ResponseModel / ErrorResponse / ok）
│   ├── services/            # ③ 业务层，按业务模块拆分
│   │   ├── user_service.py
│   │   └── health_service.py#   健康检查：数据库探活，异常转 SystemException(503)
│   └── db/                  # ④ 数据库层（SQLAlchemy 2.0 + MySQL）
│       ├── base.py          #   ORM 基类（Alembic 感知表结构的入口）
│       ├── models.py        #   表结构声明（User）
│       ├── session.py       #   engine + Session 工厂
│       ├── user_repo.py     #   users 表读写仓储（上层唯一入口）
│       └── health_repo.py   #   数据库连通性探活（SELECT 1）
├── alembic/                 # Alembic 迁移（versions/ 存版本脚本）
│   └── env.py               #   注入 MYSQL_URL、暴露 Base.metadata
├── scripts/
│   └── db_sync.sh           # 改模型后一键生成迁移并同步
├── tests/                   # pytest 冒烟测试（连真实 MySQL，见 §9）
│   ├── conftest.py          #   进程内 ASGI 客户端 + 测试数据清理
│   └── test_smoke.py        #   健康检查 + 用户 CRUD 冒烟用例
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

  `code` **复用 HTTP 状态码**（成功 `200`；错误 `404` / `409` / `422` / `500`），与响应的 HTTP 状态码一致。

- RESTful 语义与状态码：

  | 操作 | 方法 + 路径 | 成功状态码 |
  | --- | --- | --- |
  | 新增 | `POST /api/users` | `200` |
  | 列表 | `GET /api/users` | `200` |
  | 详情 | `GET /api/users/{id}` | `200` |
  | 更新 | `PUT /api/users/{id}` | `200` |
  | 删除 | `DELETE /api/users/{id}` | `200` |

  > 统一信封下成功一律 `200`：删除不用 `204`（无响应体，前端无法解析信封）；新增不用 `201`（避免 body.code 与 HTTP 状态码不一致）。

- **系统接口**（运维探活）**有意不挂 `/api` 前缀**：`GET /health` 校验服务存活 + 数据库连通性，正常 `200`、数据库异常 `503`（由 `health_service` 抛 `SystemException(503)`）。这是对「路径以 `/api` 开头」的唯一例外，新增此类端点需在本文档登记。
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
