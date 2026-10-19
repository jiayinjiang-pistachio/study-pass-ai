# 环境变量分层 & 日志体系操作指南（新手上手）

> 面向第一次接触本项目的同学。读完你能独立完成：配好 dev/prod 两套环境变量 → 让敏感信息只走配置层 → 让日志既进控制台又落文件 → 出问题能靠日志自查。
>
> 相关规范以 [`AGENTS.md`](../AGENTS.md) §5 为准，本文是**操作手册**，侧重「怎么做」。

---

## 一、先建立心智模型

### 1. 环境变量分层：一份基础 + 按环境覆盖

同一个项目要跑在两种环境里，需求不同：

| 环境 | 数据库 | 日志级别 | 日志去向 |
| --- | --- | --- | --- |
| 开发 `dev` | 本机 MySQL | `DEBUG` | 控制台 + 文件（要即时看） |
| 生产 `prod` | 线上 MySQL | `WARNING` | 只落文件（要留痕、少噪音） |

如果把两套值混在一个 `.env` 里，每次切环境都要手动改，极易改错、也容易把线上口令带进仓库。

本项目的做法是**分层**——用一个变量 `APP_ENV` 决定「叠加哪一层」：

```
优先级（高 → 低）：  真实环境变量  >  .env.{APP_ENV}  >  .env
```

- **`.env`（基础层）**：两种环境都一样的公共值，如 `APP_ENV`、`MYSQL_URL`。
- **`.env.{APP_ENV}`（覆盖层）**：只写「这个环境不一样」的项，如 `.env.dev` 里的 `LOG_LEVEL=DEBUG`。没写的项自动继承基础层。
- **真实环境变量**：由 CI / 服务器 / 容器注入（如 `APP_ENV=prod LOG_LEVEL=ERROR uvicorn ...`）。**它永远最高优先**，用来临时覆盖或注入生产密钥。

`APP_ENV` 默认 `dev`。取值 `dev` / `prod`。

### 2. 配置读取只有一个入口

**所有配置都从 `app/core/config.py` 读，其他任何地方都不准直接写 `os.getenv`。**

为什么？敏感信息（数据库口令等）如果散落在各模块里各读各的，一旦要改名、要脱敏、要排查「这个值到底从哪来」，就得满仓库找。收敛到一处后，配置的来源与优先级只有一份逻辑。

### 3. 日志体系：一份格式，两种去向

底层用 **Loguru**（`app/core/logging.py`），对业务代码屏蔽细节：

- **开发**：日志同时进控制台和文件，你边跑边看。
- **生产**：只落文件，避免刷屏、避免多余日志。
- 文件按大小**滚动**：单文件满 10MB 就切一个，最多保留 5 个（`app.log`、`app.log.1`…），不会无限涨。
- **uvicorn 自带日志已接管**：标准库 `logging`（含 uvicorn 启动信息、访问日志 `uvicorn.access`）经 `InterceptHandler` 汇入 Loguru，格式统一、同样落文件，且**不会重复打印**。

---

## 二、文件地图（改配置/日志前先认路）

```
agent-backend/
├── app/core/
│   ├── config.py             # ★ 配置唯一入口：分层加载 + 暴露类型化配置项
│   └── logging.py            # ★ 日志配置：setup_logging()，Loguru 控制台 + 文件滚动
├── .env                      # 基础层（真实值，gitignore，不入库）
├── .env.dev                  # 开发覆盖层（gitignore）
├── .env.prod                 # 生产覆盖层（gitignore）
├── .env.example              # ★ 基础层模板（入库）
├── .env.dev.example          # ★ 开发覆盖模板（入库）
├── .env.prod.example         # ★ 生产覆盖模板（入库）
└── logs/                     # 日志输出目录（运行期生成，gitignore）
    └── app.log               # 当前日志文件
```

`config.py` 暴露的配置项（其他层只能从这里取）：

| 配置项 | 环境变量 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `APP_ENV` | `APP_ENV` | `dev` | 运行环境，决定叠加哪个覆盖文件 |
| `IS_PROD` | — | `APP_ENV == "prod"` | 便捷布尔 |
| `MYSQL_URL` | `MYSQL_URL` | 无（必填） | 数据库连接串，经 `get_mysql_url()` 读取 |
| `LOG_LEVEL` | `LOG_LEVEL` | `INFO` | 日志级别 |
| `LOG_DIR` | `LOG_DIR` | `logs/` | 日志目录；相对路径锚定仓库根 |
| `LOG_FILE_NAME` | `LOG_FILE_NAME` | `app.log` | 日志文件名 |
| `LOG_TO_CONSOLE` | `LOG_TO_CONSOLE` | dev=`true` / prod=`false` | 是否输出控制台 |

---

## 三、第一次跑起来

```bash
cd agent-backend
source .venv/bin/activate

# 1) 建基础配置（填真实 MYSQL_URL）
cp .env.example .env

# 2)（可选）建开发覆盖层，让本地日志更啰嗦、好排查
cp .env.dev.example .env.dev

# 3) 启动
uvicorn app.main:app --reload --reload-exclude 'logs/*' --port 8000
```

启动后：

- 控制台会打印统一格式日志；
- 同时 `logs/app.log` 里也有一份；
- 打开 http://127.0.0.1:8000/docs 点一个接口，回到 `logs/app.log` 能看到对应的访问日志。

看日志：

```bash
tail -f logs/app.log          # 实时跟随
```

---

## 四、环境变量分层怎么用

### 切换环境

`APP_ENV` 决定加载哪个覆盖文件。两种切法：

```bash
# 方式 A：改基础 .env 里的 APP_ENV（持久，适合本地长期切）
#   .env  →  APP_ENV=prod

# 方式 B：命令行临时指定（推荐，优先级最高，不影响文件）
APP_ENV=prod uvicorn app.main:app --port 8000
```

### 覆盖优先级实测

```bash
# .env.dev 里是 LOG_LEVEL=DEBUG，真实环境变量能压过它：
LOG_LEVEL=ERROR uvicorn app.main:app --port 8000    # 生效的是 ERROR
```

顺序永远是：**真实环境变量 > `.env.{APP_ENV}` > `.env`**。

### 生产环境（推荐姿势）

生产**不要**把口令写进 `.env.prod` 再提交到服务器，而是用真实环境变量注入（K8s Secret / systemd / CI 变量等）：

```bash
APP_ENV=prod \
MYSQL_URL='mysql+pymysql://user:pass@db-host:3306/study_pass?charset=utf8mb4' \
uvicorn app.main:app --host 0.0.0.0 --port 8000
# → 日志级别走 .env.prod 的 WARNING，控制台关闭，只落 logs/app.log
```

---

## 五、日志体系怎么用

### 在代码里打日志

项目内统一用**标准库** `logging.getLogger(__name__)`（已被 Loguru 接管）：

```python
import logging

logger = logging.getLogger(__name__)      # 用模块名作 logger 名，定位方便

logger.info("用户创建成功 | user_id=%s", user_id)     # 关键流程，留痕
logger.warning("参数不合法 | %s", detail)             # 预期内的异常
logger.error("写库失败 | %s", detail, exc_info=True)  # 系统错误，附堆栈
```

> 也可以直接用 Loguru：`from loguru import logger` 后 `logger.info(...)`。两条路都走同一格式、同一文件，按团队习惯选一种即可。

约定（见 `AGENTS.md` §2.3）：

- 业务 / 参数错误（4xx）记 **`WARNING`**，不打堆栈；
- 系统 / 未捕获错误（5xx）记 **`ERROR`**，附堆栈供定位。

### 避免多余日志

- **不要用 `print`**，统一走 `logger`，否则不进文件、没级别、没时间戳。
- **不要在正常路径刷 `INFO`**：循环里、每次请求的琐碎细节不要打，留给 `DEBUG`。
- 日志格式统一由 `logging.py` 决定，**业务代码不要自己 `basicConfig` / 加 handler**，否则会重复输出。

### 日志落到哪、怎么滚动

- 文件：`logs/app.log`（可用 `LOG_DIR` / `LOG_FILE_NAME` 改）。
- 滚动：单文件满 10MB 切分，最多保留 5 个文件。
- 编码固定 `utf-8`，中文不乱码。
- **目录不可写时自动降级**为仅控制台，保证应用仍能启动（会在控制台提示一条 warning）。

---

## 六、常见任务 Cookbook

### 新增一个配置项

1. 在 `app/core/config.py` 里加类型化读取：

   ```python
   FEATURE_FLAG_X: bool = os.getenv("FEATURE_FLAG_X", "false").strip().lower() in {"1", "true", "yes", "on"}
   ```

2. 在 `.env.example`（及各覆盖模板）里加注释与示例。
3. 其他层 `from app.core.config import FEATURE_FLAG_X` 使用——**不要直接 `os.getenv`**。

### 调整日志级别 / 目录 / 是否输出控制台

改环境变量即可，无需动代码：

```bash
LOG_LEVEL=DEBUG LOG_TO_CONSOLE=true LOG_DIR=/var/log/study-pass uvicorn app.main:app
```

或写进对应环境的 `.env.{APP_ENV}`。

### 调整滚动策略（大小 / 保留数）

`app/core/logging.py` 顶部的 `_ROTATION`、`_RETENTION` 两个常量（即 Loguru 的 `rotation` / `retention`）：

```python
_ROTATION = "10 MB"   # 单文件满 10MB 滚动；也可写 "1 day"、"00:00"（每天零点）
_RETENTION = 5        # 最多保留 5 个文件；也可写 "7 days"
```

### 本地快速切到「生产样子」验证

```bash
APP_ENV=prod uvicorn app.main:app --port 8000
# 预期：控制台安静（无 INFO 刷屏），logs/app.log 只记 WARNING 及以上
```

---

## 七、命令速查表

| 目的 | 命令 |
| --- | --- |
| 建基础配置 | `cp .env.example .env` |
| 建开发覆盖 | `cp .env.dev.example .env.dev` |
| 建生产覆盖 | `cp .env.prod.example .env.prod` |
| 用指定环境启动 | `APP_ENV=prod uvicorn app.main:app --port 8000` |
| 临时改日志级别 | `LOG_LEVEL=DEBUG uvicorn app.main:app --port 8000` |
| 实时看日志 | `tail -f logs/app.log` |
| 清空日志 | `rm -f logs/app.log` |
| 确认忽略规则生效 | `git check-ignore .env .env.dev .env.prod logs/app.log` |

---

## 八、FAQ / 排错

### Q1：`RuntimeError: 环境变量 MYSQL_URL 未配置`

没建 `.env`，或建错位置。`.env` 必须在 `agent-backend/` 根目录（与 `alembic.ini` 同级）。

```bash
cp .env.example .env   # 然后填 MYSQL_URL
```

### Q2：我改了 `.env.dev`，但没生效

三种常见原因：

1. **`APP_ENV` 不是 `dev`**。覆盖层文件名必须与 `APP_ENV` 对应：`APP_ENV=dev` 才加载 `.env.dev`。用 `APP_ENV=prod` 时 `.env.dev` 根本不会被读。
2. **该项已被真实环境变量占用**。真实环境变量优先级最高，会盖过文件值。检查是否 shell 里 export 过。
3. **改完没重启服务**。环境变量在进程启动时读取一次，改文件后要重启 uvicorn。

### Q3：`prod` 下控制台什么都不打印了，是不是坏了？

不是。生产默认 `LOG_TO_CONSOLE=false`，日志只落文件。去看 `logs/app.log`：

```bash
tail -f logs/app.log
```

想在控制台也看到，显式打开即可：`LOG_TO_CONSOLE=true`。

### Q4：同一条日志在控制台出现了两遍

多半是业务代码自己又加了 handler（如 `logging.basicConfig()` 或手动 `addHandler`），与 Loguru 的接管叠加了。本项目已在 `logging.py` 统一接管，**业务代码只管 `logging.getLogger(__name__)` 和打日志，不要再配 handler**。

### Q5：`logs/` 目录建不出来 / 报权限错误

`LOG_DIR` 指向了无写权限的路径。日志模块会自动降级为仅控制台并在控制台提示一条 warning，应用仍能启动。把 `LOG_DIR` 指到可写目录即可：

```bash
LOG_DIR=/tmp/study-pass-logs uvicorn app.main:app
```

### Q6：密码里有 `$`，配置读出来却变了样

本项目已对 `.env` 关闭了变量插值（`interpolate=False`），`$` 会被当普通字符。若你**手工**用其它工具读 `.env`，注意其默认可能开启插值。稳妥做法：生产口令用真实环境变量注入，或对特殊字符做 URL 编码。

### Q7：日志文件会无限增长吗？

不会。Loguru 按大小滚动（`rotation="10 MB"`），单文件满 10MB 就切分，最多保留 5 个文件（`retention=5`），总占用有上限。

### Q8：为什么 `git status` 里看不到 `.env.dev` / `logs/`？

它们已被 `.gitignore` 忽略，这是**预期行为**——真实配置与日志都不该入库。只有 `*.example` 模板会被跟踪。

### Q9：能直接把口令写进 `.env.prod` 提交吗？

**不能**。`.env.prod` 同样被 gitignore，且生产口令应通过真实环境变量注入，不落文件。仓库里只保留 `.env.prod.example` 模板。

### Q10：怎么确认某文件到底有没有被忽略？

```bash
git check-ignore -v .env.dev logs/app.log
```

命中会打印是哪条规则匹配的；无输出表示没被忽略。

---

## 九、红线（改配置/日志前必看）

- ❌ 在业务代码里硬编码口令 / 密钥 / 端口 —— 一律走 `app/core/config.py`。
- ❌ 在 `config.py` 之外直接 `os.getenv` —— 破坏「配置唯一入口」。
- ❌ 用 `print` 打日志，或在业务代码里自己 `basicConfig` / 加 handler。
- ❌ 把真实 `.env` / `.env.dev` / `.env.prod` / `logs/` 提交入库。
- ❌ 把生产口令写进 `.env.prod` 文件（应走真实环境变量注入）。
- ❌ 在正常路径刷大量 `INFO` 日志，制造噪音。
- ✅ 新增配置项：改 `config.py` → 补 `.env.example` → 其他层从 config 导入。

---

## 十、一页速记

```bash
# 首次
cp .env.example .env            # 填 MYSQL_URL
cp .env.dev.example .env.dev    # 开发覆盖（可选）

# 日常启动（开发）
uvicorn app.main:app --reload --reload-exclude 'logs/*' --port 8000

# 切生产样子 / 临时改级别
APP_ENV=prod uvicorn app.main:app --port 8000
LOG_LEVEL=DEBUG uvicorn app.main:app --port 8000

# 看日志
tail -f logs/app.log

# 心智模型
#   配置优先级： 真实环境变量 > .env.{APP_ENV} > .env
#   配置入口：   app/core/config.py（唯一）
#   日志去向：   dev 控制台+文件 / prod 只文件；10MB × 5 滚动
#   日志约定：   4xx → WARNING，5xx → ERROR（含堆栈）
```
