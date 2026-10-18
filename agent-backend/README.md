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

# 3. 启动服务（默认 8000，与前端 Vite 代理对齐）
uvicorn app.main:app --reload --port 8000
```

- Swagger UI：http://127.0.0.1:8000/docs
- 健康检查：`GET /api/health`

## 目录结构（四层）

```
app/
├── main.py              # 应用入口：创建 FastAPI 实例、注册路由
├── core/security.py     # 通用能力：密码哈希（passlib + bcrypt）
├── routers/user.py      # ① 路由层：HTTP 契约
├── schemas/user.py      # ② 校验层：Pydantic v2 请求 / 响应模型
├── services/user_service.py  # ③ 业务层：业务规则
└── db/memory.py         # ④ 数据库层：内存字典模拟
```

## 用户接口

| 方法 | 路径 | 说明 | 成功码 |
| --- | --- | --- | --- |
| POST | `/api/users` | 创建用户 | 201 |
| GET | `/api/users` | 用户列表 | 200 |
| GET | `/api/users/{id}` | 用户详情 | 200 |
| PUT | `/api/users/{id}` | 更新用户 | 200 |
| DELETE | `/api/users/{id}` | 删除用户 | 204 |

### 示例

```bash
# 创建
curl -X POST http://127.0.0.1:8000/api/users \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","email":"alice@example.com","password":"secret123","full_name":"Alice"}'

# 查询列表
curl http://127.0.0.1:8000/api/users

# 更新（只更新传入字段）
curl -X PUT http://127.0.0.1:8000/api/users/1 \
  -H 'Content-Type: application/json' \
  -d '{"full_name":"Alice Chen"}'

# 删除
curl -X DELETE http://127.0.0.1:8000/api/users/1
```

## 说明

- **密码安全**：明文仅作为入参，落库前经 `passlib[bcrypt]` 单向哈希；响应模型不含 `password`。
- **数据存储**：数据库层为内存字典，进程重启即清空，仅用于开发 / 演示；替换真实数据库时只改 `app/db/`。
- **依赖锁定**：`bcrypt` 锁定 `4.0.1`（`passlib 1.7.4` 与 `bcrypt>=4.1` 不兼容），详见 `requirements.txt` 注释。
