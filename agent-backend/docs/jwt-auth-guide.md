# JWT 鉴权技术实现原理（图解）

> 面向要读懂 / 改动本项目鉴权的同学。读完你能独立回答：登录时发生了什么、请求是怎么被鉴权拦下的、令牌过期后怎么自动续、每个文件为什么放在那一层。
>
> 相关规范以 [`AGENTS.md`](../AGENTS.md) §5/§6 为准，本文是**原理图 + 走查手册**，侧重「为什么这样设计、数据怎么流动」。

---

## 一、先建立心智模型

一句话：**登录发两枚令牌 → 受保护接口验令牌 → 访问令牌过期用刷新令牌换新的**。

三件事各由一段代码负责，互不耦合：

| 环节 | 干什么 | 代码位置 |
| --- | --- | --- |
| **签发** | 校验账号密码，签发 Access + Refresh | `services/auth_service.py` + `core/security.py` |
| **校验** | 每个受保护请求解析 `Authorization: Bearer` | `routers/deps.py` |
| **续期** | 用 Refresh 换新 Access（前端拿到 401 后调用） | `services/auth_service.py` |

三个关键约束（贯穿全文）：

1. **密钥只走环境变量** `JWT_SECRET`，缺失时服务**启动即失败**（`main.py` 调 `get_jwt_secret()`）。
2. **无状态**：令牌不落库，服务端不记会话；代价是暂不支持主动吊销 / 登出。
3. **两类令牌用 `type` 声明区分**：Refresh 只能用于 `/refresh`，拿它访问受保护接口会被拒（401）。

---

## 二、全景原理图

```
 前端 / 客户端                    FastAPI 应用                          MySQL
      │                              │                                   │
      │ ① POST /api/auth/login       │                                   │
      │   {username, password}       │  auth_service.login()             │
      ├─────────────────────────────>│   ├─ user_repo.find_by_username ─>│
      │                              │   ├─ verify_password(bcrypt)      │
      │                              │   └─ issue_tokens() → 签发 JWT     │
      │   {access_token, refresh}    │                                   │
      │<─────────────────────────────┤                                   │
      │                              │                                   │
      │ ② GET /api/users             │                                   │
      │   Authorization: Bearer AT   │  deps.get_current_user()          │
      ├─────────────────────────────>│   ├─ decode_token(AT,"access")    │
      │                              │   └─ auth_service.resolve_user ──>│
      │   200 {data:[...]}           │                                   │
      │<─────────────────────────────┤                                   │
      │                              │                                   │
      │ ③ AT 已过期 → 再发一次        │                                   │
      ├─────────────────────────────>│  decode → ExpiredSignatureError   │
      │   401 {code:401}             │  （全局处理器转成错误信封）         │
      │<─────────────────────────────┤                                   │
      │                              │                                   │
      │ ④ POST /api/auth/refresh     │                                   │
      │   {refresh_token}            │  decode_token(RT,"refresh")       │
      ├─────────────────────────────>│  issue_tokens() → 新一对令牌       │
      │   {新的 access_token}         │                                   │
      │<─────────────────────────────┤                                   │
      │                              │                                   │
      │ ⑤ 用新 AT 重试 ② 的原请求      │                                   │
      ├─────────────────────────────>│  → 200                            │
```

> ①②④⑤ 是正常链路；③ 是「过期」信号。**第 ⑤ 步「自动重试」属于前端行为**（本项目后端只负责在 ③ 返回规范的 `401` 并在 ④ 提供换新接口）。前端接入方式见 §八。

---

## 三、令牌长什么样

### JWT 结构

```
        eyJhbGciOiJIUzI1NiJ9 . eyJzdWIiOiI5NyIsInR5cGUiOiJhY2Nlc3Mi...  .  <签名>
        └──────┬───────┘   └──────────────┬──────────────┘          └───┬───┘
             header                    payload                    signature
        {"alg":"HS256","typ":"JWT"}   （见下表）      HMAC-SHA256(header.payload, JWT_SECRET)
```

- 前两段是 **Base64URL，可被任何人解出**（**不含敏感信息**，故 payload 里不放密码等）。
- 第三段用 `JWT_SECRET` 签名：改了 payload 签名就对不上 → 校验失败 → 401。

### 本项目写入的 claims（`core/security.py:_encode`）

| 字段 | 含义 | 示例 |
| --- | --- | --- |
| `sub` | 用户 id（**JWT 规范要求字符串**，故 `str(user_id)`） | `"97"` |
| `type` | 令牌类型：`access` / `refresh` | `"access"` |
| `iat` | 签发时间 | `1792402946` |
| `exp` | 过期时间 | `1792404746` |

### 两类令牌的区别（`core/config.py`）

| | Access Token | Refresh Token |
| --- | --- | --- |
| `type` | `access` | `refresh` |
| 默认有效期 | `ACCESS_TOKEN_EXPIRE_MINUTES=30`（30 分钟） | `REFRESH_TOKEN_EXPIRE_DAYS=7`（7 天） |
| 用途 | 访问所有受保护接口 | **仅**用于 `POST /api/auth/refresh` |
| 能否访问业务接口 | ✅ | ❌（`type` 不符 → 401） |

---

## 四、文件地图与分层

```
                    ┌──────────────────────────────────────────────────────┐
   HTTP 请求 ───────>│ ① routers/                                            │
                    │    auth.py   register / login / refresh / me          │
                    │    user.py   用户 CRUD（整组挂鉴权）                    │
                    │    deps.py   get_current_user：解析 Bearer → 当前用户   │  ← 鉴权入口
                    └───────────────────────┬──────────────────────────────┘
                                            │ 只调 services（不直接碰 db）
                    ┌───────────────────────▼──────────────────────────────┐
                    │ ② schemas/auth.py                                     │
                    │    RegisterIn / LoginIn / RefreshIn / TokenOut        │  入参校验 · 出参裁剪
                    └───────────────────────┬──────────────────────────────┘
                                            │
                    ┌───────────────────────▼──────────────────────────────┐
                    │ ③ services/auth_service.py                           │
                    │    authenticate / login / issue_tokens / refresh /    │  业务规则
                    │    resolve_user                                       │
                    └───────┬───────────────────────────────┬──────────────┘
                            │                               │
          ┌─────────────────▼───────────────┐   ┌───────────▼──────────────┐
          │ core/security.py                │   │ ④ db/user_repo.py        │
          │   密码哈希（bcrypt）             │   │   find_by_username / get │  数据存取
          │   JWT 签发 / 校验                │   └───────────┬──────────────┘
          └─────────────────┬───────────────┘               │
                            │                    ┌──────────▼──────────────┐
          ┌─────────────────▼───────────────┐   │ MySQL：users 表          │
          │ core/config.py                  │   └─────────────────────────┘
          │   get_jwt_secret() ← 环境变量    │
          └─────────────────────────────────┘
```

**为什么这么放（设计取舍）**：

- **令牌工具在 `core/security.py`**：它是「安全能力」，纯函数、不感知 HTTP 与业务；与已有的 `hash_password` 同一入口，换算法只改一处。
- **HTTP 鉴权依赖在 `routers/deps.py` 而非 `core/`**：AGENTS.md §2.1 规定 `core/` **不依赖业务**，而该依赖需要查用户；放路由层可直接调 services，符合「相邻层调用」。
- **登录 / 刷新业务在 `services/auth_service.py`**：编排 `user_repo`（取用户）与 `core/security`（验密码、签令牌），错误抛 `BusinessException`。
- **`user.py` 用「路由级依赖」保护整组**：一行 `dependencies=[Depends(get_current_user)]` 覆盖全部 CRUD，不逐个路由写。

---

## 五、三条链路详解

### 链路 1 · 登录（`POST /api/auth/login`）

```
LoginIn(username, password)
   │
   ▼  routers/auth.py: login()
auth_service.login(username, password)
   │
   ├─ authenticate()
   │     user = user_repo.find_by_username(username)
   │     if user is None or not verify_password(...)  ──► BusinessException(401, "用户名或密码错误")
   │        ▲ 两种情况用同一文案：不暴露账号是否存在（防用户名枚举）
   │
   └─ issue_tokens(user["id"])
         ├─ create_access_token(id)  → JWT(type=access, exp=+30min)
         └─ create_refresh_token(id) → JWT(type=refresh, exp=+7d)
   │
   ▼
ok({access_token, refresh_token, token_type:"bearer"})  → 200
```

要点：**登录不区分「用户不存在 / 密码错误」**，统一 401；密码只经 `verify_password` 比对哈希，明文不落库、不回传。

### 链路 2 · 鉴权（每个受保护请求）

`deps.get_current_user` 是**唯一鉴权入口**，被 `user.py` 的路由级依赖和 `auth.py:/me` 共用。它是一棵「任一不满足即 401」的判定树：

```
Authorization: Bearer <token> 存在？
   │
   ├─ 否 ─────────────────────────────► 401  未提供认证凭证
   └─ 是
       jwt.decode(token, JWT_SECRET, ["HS256"])
       │
       ├─ 过期 ExpiredSignatureError ──► 401  登录状态已过期
       ├─ 非法 InvalidTokenError ──────► 401  凭证无效
       └─ 通过
           type == "access" ？
           ├─ 否 ──────────────────────► 401  凭证类型错误
           └─ 是
               resolve_user(int(sub))：用户存在？
               ├─ 否 ──────────────────► 401  用户不存在
               └─ 是 ──────────────────► 返回 user dict（放行，进入路由函数）
```

所有 401 都是 `BusinessException(http_status=401)`，由 `core/handlers.py` 统一转成 `{code:401, message, detail}` 信封并记 `WARNING`——**路由层不写 try/except**。

```
请求 ──► routers/user.py（路由级 Depends）
              │
              ▼
        routers/deps.py: get_current_user
              │  任一失败抛 BusinessException(401)
              ▼
        core/handlers.py: @app.exception_handler(BusinessException)
              │  记 WARNING + 构造 ErrorResponse
              ▼
        {"code":401,"message":"...","detail":"..."}   HTTP 401
```

### 链路 3 · 续期（`POST /api/auth/refresh`）

```
RefreshIn(refresh_token)
   │
   ▼  routers/auth.py: refresh()
auth_service.refresh(refresh_token)
   │
   ├─ decode_token(RT, expected_type="refresh")
   │     ├─ 过期 / 非法 / type != refresh ──► 401
   │     └─ user_id = int(payload["sub"])
   │
   ├─ user_repo.get(user_id) is None ──► 401  用户不存在
   │
   └─ issue_tokens(user_id)  → 新一对 Access + Refresh
   │
   ▼
ok({新的 access_token, refresh_token, token_type:"bearer"})  → 200
```

要点：**Refresh 只认 `type=refresh`**；拿 Access 当 Refresh 用会因类型不符被拒（401）。换新后前端拿新的 Access 重试原请求（§八）。

---

## 六、密钥与配置

```
.env / 真实环境变量                 app/core/config.py              app/core/security.py
  JWT_SECRET=xxxxxxxx   ──load──►  JWT_SECRET                    ──►  jwt.encode/decode(
  JWT_ALGORITHM=HS256              get_jwt_secret()  ← 缺失即 RuntimeError    算法=JWT_ALGORITHM,
  ACCESS_TOKEN_EXPIRE_MINUTES=30   ACCESS_TOKEN_EXPIRE_MINUTES        密钥=get_jwt_secret())
  REFRESH_TOKEN_EXPIRE_DAYS=7      REFRESH_TOKEN_EXPIRE_DAYS
                                        ▲
                                        │ main.py 启动即调用
                                   get_jwt_secret()  → 未配置则启动失败（fail-fast）
```

- 优先级（见 AGENTS.md §5）：`真实环境变量 > .env.{APP_ENV} > .env`。
- **生产**建议用真实环境变量注入，不落 `.env.prod`。
- 生成密钥：`python -c "import secrets; print(secrets.token_urlsafe(48))"`。

---

## 七、状态码语义（本项目鉴权相关）

| 码 | 触发 | message |
| --- | --- | --- |
| `200` | 登录 / 刷新成功；带有效令牌访问 | `ok` |
| `401` | 未带令牌 / 令牌过期 / 令牌非法 / 类型不符 / 用户已删 / 密码错误 | 见各 `message` |
| `409` | 注册重名 | 用户名已被占用 |
| `422` | 入参校验失败（如弱密码、字段缺失） | 请求参数不合法 |
| `429` | 注册超限（5 次/min） | 注册过于频繁，请稍后再试 |

> `code` 与 HTTP 状态码始终一致，前端可只看 HTTP 状态码判断是否需要刷新。

---

## 八、前端如何接「自动续期」

后端已就绪（`401` 信号 + `/api/auth/refresh` 接口），前端在统一请求封装里加一层**响应拦截**即可（本项目 `agent-frontend/src/api/request.ts` 目前是原生 XHR 封装，**尚未接入**）：

```
请求发出 ──► 响应状态 401？
   ├─ 否 → 正常返回
   └─ 是
       ├─ 已有刷新在途？ → 把本请求挂入等待队列（避免并发重复刷新）
       └─ 否
           ├─ 用 refresh_token 调 POST /api/auth/refresh
           ├─ 成功 → 存新 access_token，重放队列里的请求 + 原请求
           └─ 失败（refresh 也 401）→ 清空令牌，跳登录页
```

要点：**必须做「刷新去重」**——多个请求同时 401 时只刷新一次，其余等新令牌，否则会并发刷新、互相覆盖。

---

## 九、常见任务 Cookbook

### 新增一个受保护接口

```python
from fastapi import Depends
from .deps import get_current_user

@router.get("/something", response_model=ResponseModel[SomeOut], summary="...")
def something(current_user: dict = Depends(get_current_user)) -> dict:
    return ok(...)
```
若整组都要鉴权，直接挂在 `APIRouter(..., dependencies=[Depends(get_current_user)])`。

### 调整令牌有效期

改 `.env`（或环境变量）：`ACCESS_TOKEN_EXPIRE_MINUTES=60`、`REFRESH_TOKEN_EXPIRE_DAYS=30`；无需改代码。

### 换签名算法 / 密钥轮换

- 换算法：设 `JWT_ALGORITHM`（对称算法用 HS 系列；非对称需另加密钥配置）。
- 轮换密钥：改 `JWT_SECRET` 会让**所有旧令牌立即失效**（无状态、无法续期），用户需重新登录。

---

## 十、FAQ / 排错

### Q1：启动报 `RuntimeError: 环境变量 JWT_SECRET 未配置`
`.env` 里没填 `JWT_SECRET`。补一行即可（见 §六）。

### Q2：登录返回 500，日志 `invalid salt` / bcrypt 报错
`bcrypt` 版本被升到 `>=4.1`。本项目锁定 `bcrypt==4.0.1`，见 `requirements.txt` 注释。

### Q3：接口一直 401，但令牌看着没过期
排查顺序：① 请求头是否 `Authorization: Bearer <token>`（Bearer 后有空格）；② 是不是拿 **refresh** 当 access 用（`type` 不符）；③ 该用户是否已被删除（`resolve_user` 返回 401）。

### Q4：Access 过期后必须重新登录吗？
不用。用 refresh_token 调 `/api/auth/refresh` 换新 access 即可（§五·链路 3）。

### Q5：怎么让某个令牌立即失效（登出）？
当前**无状态实现不支持**。需要时引入 refresh 黑名单或落库（改动点：`auth_service.refresh` + 新增存储），届时在 AGENTS.md 登记。

### Q6：为什么登录失败和「用户不存在」提示一样？
刻意为之：统一「用户名或密码错误」，避免攻击者据此枚举出哪些用户名存在。

### Q7：令牌 payload 里能看到用户 id，安全吗？
安全。payload 是明文但不含敏感信息，且**被密钥签名**——篡改任一字段都会导致签名校验失败（401）。真正的安全边界是 `JWT_SECRET` 不泄露。

### Q8：多个请求同时 401，会重复刷新吗？
后端不关心；前端接入时**必须做刷新去重**（§八），否则并发刷新互相覆盖。

---

## 十一、红线（改鉴权前必看）

- ❌ 把 `JWT_SECRET` 硬编码 / 提交进仓库 —— 只走环境变量。
- ❌ 在令牌 payload 里放密码等敏感信息（payload 可被解出）。
- ❌ 在路由层写 `try/except` 处理鉴权失败 —— 应抛 `BusinessException(401)`，交全局处理器。
- ❌ 让 `core/` 依赖业务（如让 `core/security.py` 去查库）—— 查用户放 `services`。
- ❌ 用 Refresh 令牌访问业务接口 —— 必须 `type=access`。
- ✅ 新增受保护接口时同步补冒烟用例（401 + 带令牌 200），提交前 `pytest -q` 全绿。

---

## 十二、一页速记

```
# 心智模型
#   登录发两枚 JWT：access(30min) 访问接口 / refresh(7d) 只换新
#   鉴权入口：routers/deps.py::get_current_user（读 Bearer → 解令牌 → 查用户）
#   续期：access 过期返回 401 → 前端调 /api/auth/refresh → 用新 access 重试
#   密钥：JWT_SECRET 只走环境变量，缺失即启动失败；无状态，暂不支持登出

# 数据流
#   login  ──► auth_service.login ──► security.create_*_token ──► JWT
#   请求    ──► deps.get_current_user ──► security.decode_token ──► user_repo.get
#   refresh ──► auth_service.refresh ──► decode(type=refresh) ──► issue_tokens

# 分层
#   ① routers/auth.py·user.py·deps.py   ② schemas/auth.py
#   ③ services/auth_service.py          ④ db/user_repo.py
#   横切：core/security.py（令牌+哈希）· core/config.py（密钥）

# 命令
#   生成密钥： python -c "import secrets; print(secrets.token_urlsafe(48))"
#   跑测试：   pytest tests/test_auth.py -v
```
