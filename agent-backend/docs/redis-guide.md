# Redis 上手指南（提示词缓存）

> 面向第一次接触本项目 Redis 的同学。读完你能独立完成：装好 Redis → 配好连接 → 看懂缓存结构 → 验证读写 → 清缓存 / 排错。
>
> 相关规范以 [`AGENTS.md`](../AGENTS.md) 为准，本文是**操作手册**，侧重「怎么做」。

---

## 一、先建立心智模型

**本项目里 Redis 只是缓存，不是数据源。**

```
MySQL prompt_templates   ← 唯一事实来源（模板、版本、生效状态）
        │ 启动预热 / 读取未命中
        ▼
Redis Hash               ← 只是「当前生效模板」的快照
prompt:templates:active
```

一条铁律：**Redis 挂了、数据丢了都不影响正确性**。读取会自动回源 MySQL 并回填；写入先落库成功，再刷新缓存。

| 组件 | 职责 | 代码入口 |
| --- | --- | --- |
| Redis | 缓存生效模板，减少 MySQL 查询 | `app/core/redis_client.py` |
| 连接配置 | 从 `.env` 读取 host / port / db / password | `app/core/config.py` |
| 缓存编排 | 预热、读取、回填、变更后刷新 | `app/services/prompt_template_service.py` |
| 数据源 | 模板与版本链 | `app/db/prompt_template_repo.py` |
| 启动预热 | 服务启动时把生效模板灌进 Redis | `app/main.py` 的 `lifespan` |

---

## 二、环境准备（第一次必做）

### 1. 安装并启动 Redis

**macOS（Homebrew）**

```bash
brew install redis
brew services start redis      # 后台常驻，端口 6379
```

**Docker（跨平台，推荐团队统一）**

```bash
docker run -d --name study-redis -p 6379:6379 redis:7-alpine
```

**Ubuntu / Debian**

```bash
sudo apt update && sudo apt install redis-server
sudo systemctl enable --now redis-server
```

### 2. 确认能连上

```bash
redis-cli ping
# → PONG
```

> 连不上时先看端口：`lsof -nP -iTCP:6379 -sTCP:LISTEN`。

### 3. 配置 `.env`

Redis 配置都有默认值，本机默认配置可以**完全不填**。需要改时在 `agent-backend/.env` 中覆盖：

```dotenv
# 可选：默认 127.0.0.1:6379 / db 0 / 无密码
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_DB=0
# REDIS_PASSWORD=your_password
# PROMPT_CACHE_KEY=prompt:templates:active
```

- 生产环境建议用真实环境变量注入密码，不落 `.env.prod`。
- 多个项目共用一台 Redis 时，用 `REDIS_DB` 或 `PROMPT_CACHE_KEY` 前缀隔离。

### 4. 装依赖

```bash
source .venv/bin/activate
pip install -r requirements.txt        # 已包含 redis==8.1.0
```

---

## 三、缓存里到底存了什么

### 1. Key 与字段

- **Key**：`prompt:templates:active`（Hash 类型，可用 `PROMPT_CACHE_KEY` 覆盖）
- **Field**：
  - 私有模板：`{agent_name}:{scene}`，如 `difficulty_learner:study`
  - 公共通用模板：`common:common`
- **Value**：该生效版本的 JSON 字符串

### 2. 一条缓存长什么样

```bash
redis-cli HGET prompt:templates:active difficulty_learner:study
```

```json
{
  "id": 12,
  "agent_name": "difficulty_learner",
  "scene": "study",
  "template_type": 1,
  "template_content": "你是难点学习助手，先讲原理再举例。",
  "variables": ["tone", "difficulty"],
  "version": 3,
  "is_active": 1,
  "description": "难点学习 v3",
  "created_at": 1760000000
}
```

### 3. 7 个智能体与字段对应

| agent_name | scene | 私有缓存字段 |
| --- | --- | --- |
| `flow_controller` | `workflow` | `flow_controller:workflow` |
| `resume_parser` | `resume` | `resume_parser:resume` |
| `quiz_generate` | `quiz` | `quiz_generate:quiz` |
| `interview_host` | `interview` | `interview_host:interview` |
| `interview_evaluator` | `evaluation` | `interview_evaluator:evaluation` |
| `difficulty_learner` | `study` | `difficulty_learner:study` |
| `note_archiver` | `note` | `note_archiver:note` |

公共通用模板固定字段 `common:common`，读取任意私有模板时会自动前置拼接。

### 4. 什么时候写缓存

| 时机 | 行为 |
| --- | --- |
| 服务启动 | `load_active_templates()` 全量重建 Hash，并设置 1 小时 TTL |
| 写入新版本（功能待实现） | 先提交 MySQL，成功后刷新该作用域字段 |
| 一键回滚 | 先提交 MySQL，成功后刷新该作用域字段 |
| 读取未命中 | 查 MySQL → 回填该字段；MySQL 也没有则删除脏字段 |
| 读取时 Redis 不可用 | 告警日志 + 直接查 MySQL，不影响接口 |

> TTL 1 小时是**多实例部署的兜底**：本地写操作会主动刷新共享 Redis；若有人绕过服务直接改库，最多 1 小时后自动对齐。

---

## 四、第一次跑起来

```bash
cd agent-backend
source .venv/bin/activate

# 1) 确认 Redis
redis-cli ping

# 2) 启动服务
uvicorn app.main:app --reload --port 8000
```

启动日志里应出现：

```text
提示词缓存预热完成：N 条生效模板
```

N 为当前数据库里的生效模板数。若 Redis 没启动，会看到：

```text
提示词缓存预热失败，读取时将回源数据库
```

**这只是告警，服务照常启动**。

模板写入功能暂未提供（待提示词注入需求确定后补充）。调试时可先用仓储层造数据，再手动预热缓存：

```bash
source .venv/bin/activate

# 公共通用模板 + 私有模板（仅本地调试用）
python - <<'PY'
from app.db.models import PromptTemplate
from app.db.session import SessionLocal
from app.services.prompt_template_service import load_active_templates

with SessionLocal() as session:
    session.add_all([
        PromptTemplate(
            agent_name="common", scene="common", template_type=2,
            template_content="请用中文回答。", version=1, is_active=1,
            description="local demo public",
        ),
        PromptTemplate(
            agent_name="difficulty_learner", scene="study", template_type=1,
            template_content="先讲原理再举例。", version=1, is_active=1,
            description="local demo private",
        ),
    ])
    session.commit()
load_active_templates()
PY

# 看缓存
redis-cli HKEYS prompt:templates:active
# → common:common, difficulty_learner:study

redis-cli HGET prompt:templates:active difficulty_learner:study
```

---

## 五、日常排查：常用命令

```bash
redis-cli ping                              # 连通性
redis-cli INFO server | head -5             # 版本与运行信息
redis-cli HKEYS prompt:templates:active     # 当前有哪些生效模板字段
redis-cli HGETALL prompt:templates:active   # 查看全部缓存内容
redis-cli HGET prompt:templates:active common:common
redis-cli TTL prompt:templates:active       # 剩余过期时间（秒；-1 永不过期，-2 不存在）
redis-cli TYPE prompt:templates:active      # 应为 hash
```

清缓存（安全，读取时会自动回源并回填）：

```bash
redis-cli DEL prompt:templates:active
```

> ⚠️ 不要在生产共享 Redis 上执行 `FLUSHALL` / `FLUSHDB`，会影响同实例的其他业务。

---

## 六、常见任务 Cookbook

### 手动预热缓存（不重启服务）

```bash
cd agent-backend
source .venv/bin/activate
python -c "from app.services.prompt_template_service import load_active_templates; print(load_active_templates())"
```

### 改了数据库后缓存没变

1. 先确认是否走了接口修改（走接口会自动刷新）；
2. 若是直接改库，手动删除 Key，下一次读取自动回源：

   ```bash
   redis-cli DEL prompt:templates:active
   ```

3. 或直接重启服务触发全量预热。

### 换 Redis 实例 / 改密码

改 `.env` 后重启服务即可。连接是在首次使用缓存时懒加载的单例，不会读取旧配置。

### 新增一个智能体

1. 在 `app/services/prompt_template_service.py` 的 `AGENT_CONFIG` 中加一项；
2. 在 `_KNOWN_SCENES` 中加入它的 scene；
3. 重启服务（无需改表结构、无需清缓存）。

### 本地不想跑 Redis

可以。所有提示词接口仍可用（自动回源 MySQL），只是每次读取多一次数据库查询。适合临时开发。

---

## 七、FAQ / 排错

### Q1：日志出现 `ConnectionError: Error 61 connecting to 127.0.0.1:6379`

Redis 没启动或端口不对。启动 Redis 后刷新即可：

```bash
redis-cli ping        # 期望 PONG
```

服务不需要重启：下一次缓存操作会自动重连。

### Q2：`NOAUTH Authentication required`

Redis 配了密码，但 `.env` 没填 `REDIS_PASSWORD`（或填错）。

### Q3：`WRONGPASS invalid username-password pair`

`REDIS_PASSWORD` 不对；若 Redis 6+ ACL 使用了用户名，当前客户端只支持默认用户 + 密码。

### Q4：接口正常，但 `HGETALL` 是空的

- 数据库里没有生效模板（`prompt_templates.is_active=1` 为 0 条）；
- 或启动预热时 Redis 不可用且之后还没发生读取 / 写入。

直接向 `prompt_templates` 写入一条生效模板，或执行「手动预热」。

### Q5：多实例部署，A 实例改了模板，B 实例多久生效？

写操作提交 MySQL 后会立即刷新共享 Redis，B 实例的读取直接命中新值，**通常即时生效**。TTL 1 小时只用于兜底绕过服务直接改库的场景。

### Q6：Redis 数据丢了会怎样？

无影响。Redis 里只有可重建的缓存，重启服务或首次读取会自动回源 MySQL。

### Q7：为什么缓存读取只有 1 秒超时？

`app/core/redis_client.py` 把连接 / 读写超时都设为 1 秒：**缓存不可用时应快速失败并回源数据库**，而不是拖慢接口。不要随意调大。

### Q8：测试需要 Redis 吗？

不强制。`tests/test_prompt_templates.py` 的缓存用例在 Redis 不可用时会自动跳过，其余用例照常运行。想跑全量缓存用例就先执行 `redis-cli ping`。

### Q9：能在代码里直接 `redis_client.get_client()` 读写业务数据吗？

不要把 Redis 当数据库用。当前约定：**只有 `prompt_template_service` 通过 Redis 读写成缓存**；其他业务需要缓存时，在对应 service 里封装，并保证「Redis 失败可回源」。

### Q10：缓存 Key 的字段会不会无限增长？

不会。Key 是单个 Hash，字段数量 = 生效模板数量（7 个私有作用域 + 1 个公共作用域，最多 8 个）。启动预热会整体重建。

---

## 八、红线（改缓存前必看）

- ❌ 把 Redis 当唯一数据源 —— 数据源只能是 MySQL，Redis 丢了必须能重建。
- ❌ 在 `.env` 之外的代码里硬编码 host / port / 密码。
- ❌ 把业务敏感数据（密码、Token）写入缓存。
- ❌ 在共享 Redis 上执行 `FLUSHALL` / `FLUSHDB`。
- ❌ 让缓存异常冒泡成接口 5xx —— 必须降级回源 MySQL。
- ✅ 模板变更统一走接口（自动刷新缓存）；直接改库后手动 `DEL` 或重启服务。

---

## 九、一页速记

```bash
# 环境
brew services start redis              # 或 docker run -d -p 6379:6379 redis:7-alpine
redis-cli ping                         # → PONG

# 观察
redis-cli HKEYS prompt:templates:active
redis-cli HGETALL prompt:templates:active
redis-cli TTL prompt:templates:active

# 清缓存（安全）
redis-cli DEL prompt:templates:active

# 手动预热
python -c "from app.services.prompt_template_service import load_active_templates; print(load_active_templates())"

# 排错三连
redis-cli ping
tail -f logs/app.log | grep -i redis
curl http://127.0.0.1:8000/api/prompt/templates/difficulty_learner/study -H "Authorization: Bearer <token>"
```
