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
│   └── handlers.py           # 全局异常处理器（统一错误响应）
├── routers/
│   ├── deps.py               # ① 路由层共享依赖：get_current_user（Bearer 鉴权）
│   ├── user.py               #   用户 CRUD（整组需登录）
│   ├── auth.py               #   注册 / 登录 / 刷新令牌 / 当前用户
│   └── health.py             #   健康检查（存活 + 数据库连通性）
├── schemas/
│   ├── user.py               # ② 校验层：Pydantic v2 请求 / 响应模型
│   ├── auth.py               #   注册 / 登录 / 刷新入参 + 令牌出参
│   ├── health.py             #   健康检查出参
│   └── response.py           # 统一响应信封
├── services/
│   ├── user_service.py       # ③ 业务层：业务规则
│   ├── auth_service.py       #   鉴权业务：登录校验、签发 / 刷新令牌、解析当前用户
│   └── health_service.py     #   健康检查：数据库探活，异常转 503
└── db/                       # ④ 数据库层：SQLAlchemy 2.0 + MySQL
    ├── base.py               #   ORM 基类
    ├── models.py             #   表结构声明（User / ChatSession / ChatMessage / Interview）
    ├── session.py            #   engine + Session 工厂
    ├── user_repo.py          #   users 表读写仓储（上层唯一入口）
    └── health_repo.py        #   数据库连通性探活（SELECT 1）

alembic/                      # 迁移脚本（versions/ 存版本）
scripts/db_sync.sh            # 一键生成迁移并同步
tests/                        # pytest 冒烟测试（连真实 MySQL）
```

## 测试

> 健康检查与冒烟测试完整上手流程见 **[docs/health-testing-guide.md](./docs/health-testing-guide.md)**（探活原理、夹具、新增用例、常见问题）。

```bash
pip install -r requirements-dev.txt          # 测试依赖（pytest / httpx / pytest-asyncio）
alembic upgrade head                         # 确保测试库已建表
pytest tests/test_smoke.py -v                # 运行冒烟测试
```

> 测试连 `.env` 里的真实 MySQL，创建的用户带 `smoke_*` 前缀并在用例后自动清理；如需隔离，把 `MYSQL_URL` 指向独立的测试库。

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
