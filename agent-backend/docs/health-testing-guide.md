# 健康检查 & 冒烟测试操作指南（新手上手）

> 面向第一次接触本项目的同学。读完你能独立完成：看懂 `/health` 怎么判活 → 跑通冒烟测试 → 新增/调试用例 → 出问题能自查。
>
> 相关规范以 [`AGENTS.md`](../AGENTS.md) §6/§9 为准，本文是**操作手册**，侧重「怎么做」。

---

## 一、先建立心智模型

### 1. 健康检查：服务活着 ≠ 依赖可用

`GET /health` 回答两个问题：

1. **服务存活**：进程能响应请求（能返回就说明活着）；
2. **数据库连通性**：真正执行一次 `SELECT 1`，确认数据库可连。

两者都 OK 返回 `200`；数据库连不上返回 `503`（Service Unavailable）。**为什么单列 503**：给运维 / 负载均衡用——503 表示「服务在，但依赖挂了」，不该把流量打进来；200 才代表可以接客。

> 它**有意不挂 `/api` 前缀**（本项目其余接口都挂），因为这是运维探活端点，与业务接口区分。这是 `AGENTS.md` §6 唯一登记的例外。

### 2. 冒烟测试：用最少的用例，验证「主流程没坏」

**冒烟测试（smoke test）** 不追求覆盖每个分支，只快速回答一个问题：**核心接口还能不能用？** 一旦挂了，说明这次改动破坏了主干，立刻停下排查。

本项目冒烟测试的选型：

| 工具 | 作用 |
| --- | --- |
| **pytest** | 测试框架：发现用例、断言、夹具（fixture） |
| **httpx** | HTTP 客户端，用 `ASGITransport` **在进程内**直接驱动 FastAPI，无需另起服务器 |
| **pytest-asyncio** | 让 `async def` 用例 / 夹具生效（`asyncio_mode=auto`，不用逐个加装饰器） |

关键点：测试**连的是真实 MySQL**（`.env` 的 `MYSQL_URL`），不是 mock——所以它同时验证了「HTTP 层 + 业务层 + 数据库层」整条链路。

### 3. 测试数据怎么不污染开发库

每个用例创建的用户名都带**运行级唯一前缀** `smoke_<随机>_`，用例结束后夹具按前缀把本轮创建的用户删掉。这样既不与真实数据冲突，也不留垃圾。

---

## 二、文件地图（改代码前先认路）

```
agent-backend/
├── app/
│   ├── routers/health.py          # ★ 路由层：GET /health
│   ├── schemas/health.py          #   校验层：HealthOut
│   ├── services/health_service.py # ★ 业务层：探活，失败抛 SystemException(503)
│   └── db/health_repo.py          # ★ 数据库层：ping() 执行 SELECT 1
├── tests/
│   ├── conftest.py                # ★ 夹具：进程内客户端 + 测试数据清理
│   └── test_smoke.py              # ★ 冒烟用例（健康检查 + 用户 CRUD）
├── pytest.ini                     # pytest 配置
└── requirements-dev.txt           # 测试依赖（pytest / httpx / pytest-asyncio）
```

请求链路（沿用四层架构）：

```
GET /health
   │
   ▼
routers/health.py        声明路径 / response_model，返回 ok(...)
   │
   ▼
services/health_service.py   调 health_repo.ping()；失败 → SystemException(503)
   │
   ▼
db/health_repo.py        engine.connect() + SELECT 1
   │
   ▼
core/handlers.py         全局处理器：把 SystemException 转成 {code:503,...} 信封并记 ERROR
```

**路由层不写 try/except**——异常一律抛给全局处理器，这是本项目的红线（见 `AGENTS.md` §2.3）。

---

## 三、第一次跑起来

前置：**本地 MySQL 已启动**，且已建表。

```bash
cd agent-backend
source .venv/bin/activate

# 1) 装测试依赖（运行期不需要）
pip install -r requirements-dev.txt

# 2) 确保测试库有表
alembic upgrade head

# 3) 跑冒烟测试
pytest tests/test_smoke.py -v
```

预期：`10 passed`。

手动验证健康检查（另起端口，避免打扰 8000 上的 dev server）：

```bash
uvicorn app.main:app --port 8010

# 另一个终端
curl -s -w '\n%{http_code}\n' http://127.0.0.1:8010/health
# → {"code":200,"message":"ok","data":{"status":"ok","database":"up"}}
#   200
```

想看 503 长什么样，把数据库停掉再 `curl`：

```bash
curl -s -w '\n%{http_code}\n' http://127.0.0.1:8010/health
# → {"code":503,"message":"数据库连接异常","detail":"...(底层异常信息)"}
#   503
```

---

## 四、健康检查怎么用

### 成功 / 失败响应

```jsonc
// 200：服务存活 + 数据库可连
{ "code": 200, "message": "ok", "data": { "status": "ok", "database": "up" } }

// 503：数据库不可用（走全局错误信封）
{ "code": 503, "message": "数据库连接异常", "detail": "…" }
```

### 探活原理

`health_repo.ping()` 只做一次最轻量的往返：

```python
with engine.connect() as conn:
    conn.execute(text("SELECT 1"))
```

连不上时抛底层异常，`health_service` 捕获后转成 `SystemException(503)`，交给全局处理器。**探活不查业务表**，只验证连接，所以很快、也不受表结构影响。

### 加新的依赖探活（如 Redis）

在 `health_service.check()` 里追加即可，失败同样抛 `SystemException(503)`，响应体可加字段：

```python
def check() -> dict:
    _ping_database()      # 现逻辑
    _ping_redis()         # 新依赖，失败抛 SystemException(503)
    return {"status": "ok", "database": "up", "redis": "up"}
```

同时更新 `app/schemas/health.py` 的 `HealthOut` 字段。

---

## 五、冒烟测试怎么用

### 用例清单（`tests/test_smoke.py`）

| 用例 | 验证点 |
| --- | --- |
| `test_health_ok` | `/health` 200 且 `database=up` |
| `test_health_db_down_returns_503` | 探活抛错 → 503（monkeypatch 模拟，不停库） |
| `test_create_user` | 建用户 200，返回含 `id`/`create_time`，**不含 password** |
| `test_create_duplicate_username_409` | 重名 → 409 |
| `test_create_invalid_payload_422` | 密码过短 → 422（校验层拦截） |
| `test_get_user_ok` | 查详情 200 |
| `test_get_user_not_found_404` | 不存在 → 404 |
| `test_list_users` | 列表 200 且为数组 |
| `test_update_user` | 更新 200 且字段生效 |
| `test_delete_user` | 删除 200，再删 → 404 |

### 核心夹具（`tests/conftest.py`）

```python
@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=app)          # 进程内驱动，无需 uvicorn
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

@pytest.fixture
def username():
    return f"{TEST_PREFIX}{uuid.uuid4().hex[:8]}"       # 唯一用户名，避免冲突

@pytest.fixture(autouse=True)
def cleanup_users():
    yield                                               # yield 保证用例失败也会执行清理
    for u in user_repo.list_all():
        if u["username"].startswith(TEST_PREFIX):
            user_repo.delete(u["id"])
```

### 新增一个用例

```python
async def test_get_user_bad_id_type(client):
    """id 非整数由校验层拦截 → 422。"""
    resp = await client.get("/api/users/abc")
    assert resp.status_code == 422
    assert resp.json()["code"] == 422
```

要点：用 `client` 夹具发请求，断言 **HTTP 状态码** + **信封里的 `code`**；需要造数据的用 `username` 夹具拿唯一名字，清理交给 `cleanup_users`，**用例里不用手写删除**。

### 模拟依赖故障

不用真停库，用 `monkeypatch` 换掉探活函数即可（`test_health_db_down_returns_503` 就是这么做的）：

```python
def boom() -> None:
    raise RuntimeError("simulated db down")

monkeypatch.setattr(health_repo, "ping", boom)
resp = await client.get("/health")      # → 503
```

---

## 六、命令速查表

| 目的 | 命令 |
| --- | --- |
| 装测试依赖 | `pip install -r requirements-dev.txt` |
| 建表（首次） | `alembic upgrade head` |
| 跑冒烟测试 | `pytest tests/test_smoke.py -v` |
| 跑全部测试 | `pytest -v` |
| 只跑一个用例 | `pytest tests/test_smoke.py::test_health_ok -v` |
| 按关键字跑 | `pytest -k health -v` |
| 首次失败即停 | `pytest tests/test_smoke.py -x` |
| 显示 print/日志 | `pytest tests/test_smoke.py -s` |
| 手动探活 | `curl -s -w '\n%{http_code}\n' http://127.0.0.1:8010/health` |

---

## 七、FAQ / 排错

### Q1：测试全红，报连不上数据库 / `Can't connect to MySQL`

测试连的是 `.env` 里的真实 MySQL。检查：

1. 本地 MySQL 是否在跑（`mysql -u root -p -e "SELECT VERSION();"`）；
2. `.env` 的 `MYSQL_URL` 是否正确（见 [database-guide.md](./database-guide.md)）。

### Q2：报 `Table 'xxx.users' doesn't exist`

测试库还没建表。执行：

```bash
alembic upgrade head
```

### Q3：`ModuleNotFoundError: No module named 'app'`

`pytest.ini` 里的 `pythonpath = .` 没生效，或你不在 `agent-backend/` 目录下跑。确认在仓库根执行 `pytest`，且 `pytest.ini` 存在。

### Q4：`async def` 用例被跳过 / 报 event loop 相关错误

确认 `pytest.ini` 里有：

```ini
asyncio_mode = auto
asyncio_default_fixture_loop_scope = function
```

`auto` 让 async 用例/夹具自动识别；`function` 保证夹具与用例共用同一个事件循环（跨 loop 会报错）。

### Q5：`test_health_db_down_returns_503` 之外，我手动停库为什么 503 的 `detail` 很长？

`detail` 是底层异常信息（面向开发者定位），不是给用户看的。对外提示是 `message`（"数据库连接异常"），符合 `AGENTS.md` §5「`detail` 不回传敏感信息」。

### Q6：跑测试时出现 `HTTP_422_UNPROCESSABLE_ENTITY is deprecated` 告警

这是 starlette 的弃用提示，来自 `app/core/handlers.py` 用的旧常量名（新名为 `HTTP_422_UNPROCESSABLE_CONTENT`）。**不影响结果**，属既有代码，与测试无关。

### Q7：测试会不会污染我的开发库？

不会（正常情况下）。测试创建的用户名带 `smoke_*` 前缀，用例结束由 `cleanup_users` 夹具删除。**但**它确实写进了 `.env` 指向的库；如需彻底隔离，把 `MYSQL_URL` 指向一个独立的测试库再跑。

### Q8：用例中途失败，测试数据会残留吗？

不会。清理夹具用的是 `yield` 形式，**无论用例通过与否，收尾代码都会执行**。

### Q9：为什么用 httpx 的 `ASGITransport`，而不是 `fastapi.testclient.TestClient`？

`TestClient` 本质也是 httpx 的封装。这里直接用 `httpx.AsyncClient + ASGITransport`，一是贴合「pytest + httpx」的要求，二是 async 客户端与 async 用例天然契合。两者都**在进程内**驱动应用，不需要起服务器。

### Q10：`/health` 为什么没有 `/api` 前缀？

它是运维探活端点，与业务接口区分，`AGENTS.md` §6 明确登记了这条例外。**新增此类系统端点需在规范里登记**。

---

## 八、红线（改健康检查/测试前必看）

- ❌ 在路由层写 `try/except` 处理探活失败 —— 应抛 `SystemException`，交全局处理器。
- ❌ 健康检查里查业务表 / 跑重查询 —— 只做最轻量的 `SELECT 1`。
- ❌ 在 `detail` 里回传堆栈 / 口令等敏感信息。
- ❌ 在测试里手写删除清理、或用固定用户名 —— 用 `username` 夹具 + `cleanup_users`。
- ❌ 让测试依赖「服务器已启动」—— 用 `ASGITransport` 在进程内跑。
- ✅ 新增接口时，同步补一条冒烟用例；提交前跑 `pytest tests/test_smoke.py -v` 应全绿。

---

## 九、一页速记

```bash
# 首次
pip install -r requirements-dev.txt
alembic upgrade head

# 日常
pytest tests/test_smoke.py -v          # 冒烟全绿再提交
pytest tests/test_smoke.py::test_health_ok -v   # 单跑一个

# 手动探活
uvicorn app.main:app --port 8010
curl -s -w '\n%{http_code}\n' http://127.0.0.1:8010/health

# 心智模型
#   /health = 存活 + 数据库连通性；正常 200，数据库异常 503（有意不挂 /api）
#   探活：db/health_repo.ping() → SELECT 1；失败抛 SystemException(503)
#   测试：pytest + httpx(ASGITransport，进程内) + pytest-asyncio(auto)
#   数据：连真实 MySQL，用户名带 smoke_* 前缀，用例后自动清理
```
