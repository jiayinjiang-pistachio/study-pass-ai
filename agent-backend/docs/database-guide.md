# 数据库 & 迁移操作指南（新手上手）

> 面向第一次接触本项目的同学。读完你能独立完成：配好数据库 → 建表 → 跑接口 → 改表结构 → 同步到库 → 出问题能自查。
>
> 相关规范以 [`AGENTS.md`](../AGENTS.md) 为准，本文是**操作手册**，侧重「怎么做」。

---

## 一、先建立心智模型

本项目后端是**四层架构**，数据库相关只涉及最后一层：

```
① routers/   路由层    HTTP 契约
② schemas/   校验层    入参/出参校验
③ services/  业务层    业务规则（唯一性、密码哈希…）
④ db/        数据库层  ← 就是这一层，本文主角
```

数据库层用到三样东西，各管一件事，别混淆：

| 工具 | 一句话职责 | 类比 |
| --- | --- | --- |
| **SQLAlchemy** | 用 Python 类**描述表结构**，并读写数据 | 「表长什么样」的图纸 + 存取工具 |
| **Alembic** | 把「图纸的变化」**生成 SQL 并执行到库** | 施工队：按图纸改造数据库 |
| **PyMySQL** | 真正跟 MySQL 通信的**驱动** | 施工队的运输车 |

关键点：**你只改 Python 模型（图纸），不手写建表 SQL**。建表 / 改表由 Alembic 负责。

---

## 二、环境准备（第一次必做）

### 1. 装 MySQL 并启动

确保本机 MySQL 已安装且 3306 端口在监听：

```bash
mysql -u root -p -e "SELECT VERSION();"
```

### 2. 建库（⚠️ Alembic 不会帮你建库）

Alembic 只建**表**，不会建**库**。先手动建一个空库：

```bash
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS study_pass_ai_database DEFAULT CHARSET utf8mb4;"
```

> 库名随意，但必须和下面 `.env` 里的连接串一致。

### 3. 配置连接串（`.env`）

```bash
cd agent-backend
cp .env.example .env
```

编辑 `.env`，填入真实连接串：

```dotenv
MYSQL_URL=mysql+pymysql://root:你的密码@127.0.0.1:3306/study_pass_ai_database?charset=utf8mb4
```

连接串拆解：

```
mysql+pymysql:// root : 123456 @ 127.0.0.1 : 3306 / study_pass_ai_database ? charset=utf8mb4
└───┬────┘└──┬──┘  └─┬─┘  └─┬─┘  └─┬──┘  └──┬────┘  └──┬──┘  └──────┬──────┘  └──────┬──────┘
  协议+驱动   用户    密码   主机   端口     库名        参数名          参数值
```

- 协议必须是 `mysql+pymysql`（同步驱动）。
- `charset=utf8mb4` 别丢，否则中文/emoji 可能乱码。
- `.env` 已被 `.gitignore` 忽略，**不会提交**，密码安全。

### 4. 装依赖

```bash
source .venv/bin/activate     # 没有 .venv 先 python3 -m venv .venv
pip install -r requirements.txt
```

---

## 三、文件地图（改代码前先认路）

```
agent-backend/
├── app/core/config.py        # 读 .env → 暴露 get_mysql_url()
├── app/db/
│   ├── base.py               # ORM 基类 Base（Alembic 靠它感知表结构）
│   ├── models.py             # ★ 表结构声明（改表就改这里）
│   ├── session.py            # engine + SessionLocal（连库的「连接池」）
│   └── user_repo.py          # ★ users 表读写函数（上层唯一入口）
├── alembic/
│   ├── env.py                # ★ Alembic 运行时：注入 MYSQL_URL、暴露 Base.metadata
│   └── versions/             # 迁移脚本存放处（每个文件 = 一次表结构变更）
├── alembic.ini               # Alembic 配置（连接串留空，由 env.py 注入）
└── scripts/db_sync.sh        # 一键同步脚本
```

⭐ 是日常最常打交道的三个文件。

各文件职责速记：

- **`models.py`**：定义 `class User(Base)`，字段用 `mapped_column(...)`。**表结构只在这里声明**。
- **`session.py`**：`engine` 是连接池，`SessionLocal` 用来开一次数据库会话。业务代码**不直接用**它。
- **`user_repo.py`**：把「开会话 → 增删改查 → 提交 → 转成 dict 返回」封装成 `insert/get/list_all/update/delete/find_by_username`。**services 层只能调这些函数**，不能碰 Session。
- **`alembic/env.py`**：把 `MYSQL_URL` 注入 Alembic，并告诉它「表结构看 `Base.metadata`」。新增模型文件时**必须在这里 import**（见 FAQ）。

---

## 四、第一次跑起来

```bash
cd agent-backend
source .venv/bin/activate

# 1) 建表：把 models.py 的结构应用到库（执行 versions/0001...）
alembic upgrade head

# 2) 确认表已建好
mysql -u root -p study_pass_ai_database -e "SHOW CREATE TABLE users\G"

# 3) 启动服务
uvicorn app.main:app --reload --port 8000
```

浏览器打开 http://127.0.0.1:8000/docs ，试一个创建用户：

```bash
curl -X POST http://127.0.0.1:8000/api/users \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"secret123"}'
# → {"code":200,"message":"ok","data":{"id":1,"username":"alice","create_time":"2026-10-19T..."}}
```

去库里看看，`password` 是 bcrypt 哈希、`create_time` 已自动填好：

```bash
mysql -u root -p study_pass_ai_database -e "SELECT id, username, LEFT(password,7), create_time FROM users;"
```

---

## 五、日常开发：改表结构的标准流程

**核心口诀：改模型 → 生成迁移 → 升级 → 验证。**

假设要给 `users` 加一个 `nickname` 字段：

### 第 1 步：改模型

编辑 `app/db/models.py`：

```python
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(64), nullable=True)  # ← 新增
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
```

### 第 2 步：生成迁移并升级（一键）

```bash
scripts/db_sync.sh "给 users 加 nickname 字段"
```

它等价于手动两步：

```bash
alembic revision --autogenerate -m "给 users 加 nickname 字段"   # 对比模型与库，生成迁移脚本
alembic upgrade head                                            # 把迁移执行到库
```

### 第 3 步：**务必 review 生成的迁移脚本**

打开 `alembic/versions/` 下新生成的文件，确认 `upgrade()` 里的操作符合预期（见 FAQ「autogenerate 不可全信」）。确认无误再算完成。

### 第 4 步：同步上层代码

表结构变了，`user_repo.py` / `schemas/user.py` / `services/user_service.py` 按需跟上。**注意**：`db` 层对外返回 dict，新增字段会自动出现在返回值里，通常无需改动 repo 代码。

---

## 六、命令速查表

所有 alembic 命令都在 `agent-backend/` 目录下执行。

| 命令 | 作用 |
| --- | --- |
| `alembic upgrade head` | 升级到最新版本（建表 / 应用所有未执行的迁移） |
| `alembic upgrade +1` | 只升级一个版本 |
| `alembic downgrade -1` | **回退一个版本**（撤销上一次变更） |
| `alembic downgrade base` | 回退到空库（删除所有本工具建的表） |
| `alembic current` | 查看数据库当前处于哪个版本 |
| `alembic history` | 查看全部迁移历史 |
| `alembic revision --autogenerate -m "说明"` | 对比模型与库，**生成**迁移脚本（不执行） |
| `alembic upgrade head --sql` | **离线**预览将执行的 SQL（不连库，排错好用） |
| `scripts/db_sync.sh "说明"` | 一键 = autogenerate + upgrade |

> `--autogenerate` 依赖「模型」与「当前库」的差异。库连不上、或模型没被导入，都会导致检测不到变化。

---

## 七、常见任务 Cookbook

### 加字段

见第五节。注意加 `nullable=False` 的字段时，**已有数据的表会失败**（老行没值）。两种解法：

- 字段允许为空：`nullable=True`；
- 必须非空：先加可空字段 → 回填数据 → 再生成一个迁移改成非空（或直接在生成的迁移里给 `server_default`）。

### 加一张新表

1. 新建 `app/db/models.py` 里加类（或新开 `app/db/xxx.py` 并继承 `Base`）：

   ```python
   class Note(Base):
       __tablename__ = "notes"
       id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
       title: Mapped[str] = mapped_column(String(128), nullable=False)
   ```

2. ⚠️ **在 `alembic/env.py` 里 import 它**，否则 autogenerate 看不见（见 FAQ）。
3. `scripts/db_sync.sh "新增 notes 表"`。

### 加索引 / 唯一约束

在模型字段上加参数即可，Alembic 会生成 `CREATE INDEX`：

```python
username: Mapped[str] = mapped_column(String(32), unique=True, index=True)   # 唯一索引
email:    Mapped[str] = mapped_column(String(255), index=True)               # 普通索引
```

### 回滚一次变更

```bash
alembic downgrade -1        # 撤销最近一次迁移
```

前提：对应迁移脚本写了 `downgrade()`（`autogenerate` 一般会生成，复杂变更需手补）。

---

## 八、FAQ / 排错

### Q1：`RuntimeError: 环境变量 MYSQL_URL 未配置`

没建 `.env`，或建错位置。`.env` 必须在 `agent-backend/` 根目录（和 `alembic.ini` 同级）。

```bash
cp .env.example .env   # 然后填 MYSQL_URL
```

### Q2：`cryptography is required for sha256_password or caching_sha2_password`

**MySQL 8 默认认证插件是 `caching_sha2_password`，PyMySQL 连接它需要 `cryptography` 包**。本项目已把它写进 `requirements.txt`，正常情况下 `pip install -r requirements.txt` 就装好了。

若仍报此错，说明依赖没装全，补装即可：

```bash
pip install -r requirements.txt
# 或单独装
pip install cryptography
```

### Q3：`Access denied for user 'root'@'localhost'`

连接串里的用户名/密码不对。注意：`.env` 里的密码是**明文**，含特殊字符（如 `@`、`:`、`#`）时要做 URL 编码（`@` → `%40`）。

### Q4：`Unknown database 'xxx'`

库没建。先执行第二节的 `CREATE DATABASE`。

### Q5：`alembic revision --autogenerate` 生成了**空**迁移（`pass`）

autogenerate 没检测到模型变化，常见原因：

1. **新模型没被导入**。Alembic 只能看到「被 import 进 `Base.metadata`」的表。解决办法：在 `alembic/env.py` 里 `import app.db.xxx`，或在 `app/db/models.py` 顶部统一 import 所有模型。
2. **改的是没被 Alembic 识别的部分**（如仅改 `server_default` 的部分场景、列顺序）。需手动补迁移脚本。

### Q6：autogenerate 不可全信

`--autogenerate` 是「尽力而为」，以下情况它检测不到或不准确，**生成后必须人工 review**：

- 索引/约束的重命名（会误判成「删旧的 + 建新的」）；
- 部分列类型修改、默认值变化；
- 数据迁移（改结构的同时要搬数据）——需要手写 `op.execute(...)`。

### Q7：中文乱码 / emoji 存不进

确认连接串带 `?charset=utf8mb4`，且建库时用了 `DEFAULT CHARSET utf8mb4`。

### Q8：`create_time` 和本机时间对不上

`create_time` 由**数据库**用 `func.now()` 填充，取的是 **MySQL 服务器时区**的时间，不是 Python 进程时区。需要统一时区时，在 MySQL 侧设置 `time_zone`，或在模型里改用 Python 侧默认值。

### Q9：想看看 Alembic 到底会执行什么 SQL，但不想连库

```bash
alembic upgrade head --sql
```

离线渲染出 SQL，排错、评审用。

### Q10：能直接在代码里 `Base.metadata.create_all()` 建表吗？

**不要**。本项目约定表结构一律走 Alembic 迁移（见 `AGENTS.md` §7）。`create_all` 会绕过迁移版本管理，导致库结构与迁移历史不一致。

---

## 九、红线（改数据库前必看）

- ❌ 手写建表/改表 SQL 直接跑在库上 —— 一律走 Alembic 迁移，否则模型与库会漂移。
- ❌ 用 `Base.metadata.create_all()` 建表。
- ❌ 把 `MYSQL_URL` / 口令写进 `alembic.ini`、代码或提交到 git。
- ❌ 在 `services` 层直接开 Session 或写 ORM 查询 —— 只能调 `db/xxx_repo.py` 的函数。
- ❌ 密码明文落库 —— 落库前必须经 `app/core/security.py` 哈希。
- ✅ 改模型后：`scripts/db_sync.sh "说明"` → review 迁移脚本 → 起服务验证。

---

## 十、一页速记

```bash
# 首次
cp .env.example .env                                  # 填 MYSQL_URL
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS study_pass_ai_database DEFAULT CHARSET utf8mb4;"
alembic upgrade head                                  # 建表

# 改了 app/db/models.py 之后
scripts/db_sync.sh "说明"                              # 一键同步
# → 打开 alembic/versions/ 下新脚本 review

# 排错三连
alembic current                                       # 我在哪个版本
alembic history                                       # 有哪些版本
alembic upgrade head --sql                            # 会执行什么 SQL
```
