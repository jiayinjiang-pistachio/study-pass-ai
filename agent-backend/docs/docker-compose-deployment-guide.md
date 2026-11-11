# 学面通 AI · Docker Compose 部署指南

> 适用版本：`docker-compose.yml` + `deploy/caddy/`（Caddy 自动签发证书）。
> 部署形态：**单机单实例**，一台服务器跑全部服务；后端固定单 worker。

---

## 1. 架构

```
浏览器
  │  80 / 443
  ▼
Caddy（自动 HTTPS：证书申请 + 301 跳转 + 续期）
  ├─ 主站域名      → 前端静态资源 + /api、/uploads、/health 反代 backend:8000（SSE 不缓冲）
  └─ MinIO 域名    → 反代 minio:9000（保留 Host，预签名 URL 才可校验）

backend:8000 ── MySQL 8（业务数据）
             ├─ Redis（限流计数 / 工作记忆 / 提示词缓存）
             ├─ MinIO（对象存储：文档、头像、知识卡图片与音频）
             └─ Qdrant（知识库向量；原文仍在 MySQL）
```

### 服务与端口

| 服务 | 镜像 / 构建 | 宿主端口 | 说明 |
| --- | --- | --- | --- |
| `caddy` | `deploy/caddy/Dockerfile`（构建前端产物） | `80`、`443` | 唯一对外入口；证书自动管理 |
| `backend` | `agent-backend/Dockerfile` | 不暴露 | FastAPI，单 worker |
| `migrate` | 与 backend 同镜像 | 无 | 一次性执行 `alembic upgrade head` |
| `mysql` | `mysql:8.0` | 不暴露 | 首次启动自动建库建用户 |
| `redis` | `redis:7.4-alpine` | 不暴露 | AOF 持久化 + 密码 |
| `minio` | `minio/minio` | `127.0.0.1:9001` | 控制台仅本机；S3 API 走 Caddy |
| `qdrant` | `qdrant/qdrant` | 不暴露 | 向量库 |

### 数据卷（`docker volume ls` 可见）

| 卷 | 内容 | 是否必须备份 |
| --- | --- | --- |
| `study-pass_mysql_data` | 全部业务数据 | **是** |
| `study-pass_minio_data` | 文档 / 头像 / 知识卡图片与音频 | **是** |
| `study-pass_caddy_data` | ACME 证书与账户状态 | 建议（丢了会重新签发） |
| `study-pass_redis_data` | 可重建缓存 | 否 |
| `study-pass_qdrant_data` | 向量索引（可由 MySQL 原文重建，但成本高） | 建议 |
| `study-pass_backend_logs` | 应用日志 | 否 |
| `study-pass_backend_uploads` | 历史本地文件静态目录 | 建议 |
| `study-pass_model_cache` | fastembed 向量模型 | 否（可重新下载） |

### 设计取舍

- 不使用 systemd + 宿主机 Python / MySQL / Redis / Nginx，全部容器化，一条 compose 管到底。
- **证书由 Caddyfile 自动申请与续期**，不需要 certbot，也不需要手动拷贝证书。
- 后端只有一个进程：这是硬约束，见 §10「测评提交 409」。
- 只有 Caddy 暴露宿主端口，其余服务只在内网可达，减少攻击面。

---

## 2. 前置条件

### 2.1 服务器

- Ubuntu 24.04 x86_64（推荐）；4C16G 起步，8C32G 更稳。
- 磁盘 ≥ 80GB（SSD）；知识卡图片和播客音频增长较快。
- Docker Engine ≥ 24，Docker Compose v2 ≥ 2.20（需要 `--env-file` 与 `service_completed_successfully`）。
- 仅开放 `22 / 80 / 443`；`3306 / 6379 / 8000 / 9000 / 6333` 不要暴露到公网。
- 国内服务器需完成 ICP 备案；域名 DNS 解析到本机公网 IP。

安装 Docker（官方脚本）：

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"   # 重新登录后生效
docker compose version            # 应显示 v2.x
```

> 国内拉取镜像较慢时，请给 Docker 配置镜像加速器（`/etc/docker/daemon.json`），
> 或改用云厂商提供的容器镜像服务。加速器只影响基础镜像拉取，不影响业务镜像构建。

### 2.2 域名（生产）

Caddy 默认通过 HTTP-01 校验自动签证书，因此：

1. `study.example.com` 与 `storage.example.com` 都解析到本机公网 IP；
2. **不要**同时解析 AAAA 到不可达的 IPv6（会让校验失败）；
3. 80 / 443 对公网可达；若前面有 CDN/WAF，需放行回源并关闭对 80 端口的强制 HTTPS 拦截。

### 2.3 本地试跑（可选）

用 `study.localhost` / `storage.localhost`，把域名映射到本机：

```bash
# macOS / Linux
sudo sh -c 'printf "127.0.0.1 study.localhost\n127.0.0.1 storage.localhost\n" >> /etc/hosts'
```

`.env.docker` 中站点地址写 `http://` 前缀即可关闭自动 HTTPS（见 §4）。

---

## 3. 获取代码

```bash
git clone <仓库地址> study-pass-ai
cd study-pass-ai
```

部署相关文件：

```
docker-compose.yml
.env.docker.example          # 环境变量模板
agent-backend/Dockerfile
deploy/caddy/Dockerfile
deploy/caddy/Caddyfile
.dockerignore
agent-backend/.dockerignore
```

---

## 4. 环境变量

```bash
cp .env.docker.example .env.docker
chmod 600 .env.docker
```

所有 compose 命令都必须带 `--env-file .env.docker`（变量插值只读这个文件）。为减少遗漏，可先设别名：

```bash
alias dc='docker compose --env-file .env.docker'
```

### 4.1 必改项

| 变量 | 说明 |
| --- | --- |
| `SITE_APP` | 主站站点地址，Caddyfile 直接使用。本地 `http://study.localhost`；生产纯域名 `study.example.com` |
| `SITE_STORAGE` | MinIO 站点地址。本地 `http://storage.localhost`；生产 `storage.example.com` |
| `MINIO_PUBLIC_HOST` | 预签名 URL 的主机名，**必须与 `SITE_STORAGE` 的主机名一致且不带端口** |
| `MINIO_SECURE` | 与 `SITE_STORAGE` 协议一致：http → `false`，https → `true` |
| `MYSQL_ROOT_PASSWORD` | MySQL root 口令 |
| `MYSQL_PASSWORD` | 应用数据库口令（只用于 `MYSQL_URL` 拼装） |
| `REDIS_PASSWORD` | Redis 口令，不能留空 |
| `MINIO_ROOT_PASSWORD` | MinIO 管理口令（≥ 8 位） |
| `JWT_SECRET` | 登录令牌签名密钥，≥ 32 位随机串 |
| `LLM_API_KEY` / `LLM_MODEL` | 大模型；缺省时其余接口可用，但对话接口 503 |

生成随机值：

```bash
openssl rand -hex 32   # JWT_SECRET
openssl rand -hex 24   # 各类口令
```

口令只用字母数字，避免 `$`（会被 compose 当变量）、`@ / :`（会破坏 `MYSQL_URL`）。

### 4.2 生产建议

```dotenv
SITE_APP=study.example.com
SITE_STORAGE=storage.example.com
MINIO_PUBLIC_HOST=storage.example.com
MINIO_SECURE=true
APP_ENV=prod
LOG_LEVEL=WARNING
LOG_TO_CONSOLE=false
```

- `APP_ENV=prod` 会关闭 `/docs`、`/redoc`、`/openapi.json`（安全考虑）。
  **仅在本地调试时**改成 `dev`。
- 启动期会对 MySQL / MinIO 鉴权并预热提示词缓存、下载向量模型，首次启动约 1~3 分钟。
- 国内构建可启用镜像源：

```dotenv
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
NPM_REGISTRY=https://registry.npmmirror.com
```

> 模型下载必须保持 `HF_HUB_DISABLE_XET=1`（compose 已内置）。用 `hf-mirror.com` 时不关闭
> Xet 会 401；模型缓存在 `model_cache` 卷，删除该卷后需要重新下载。

---

## 5. 首次部署

### 5.1 构建并启动

```bash
docker compose --env-file .env.docker pull mysql redis minio qdrant
docker compose --env-file .env.docker up -d --build
```

顺序由 `depends_on` 保证：MySQL 健康 → `migrate` 建表成功 → backend 启动 → Caddy 就绪。
首次构建会下载 Python / Node 依赖与基础镜像，耗时取决于网络。

查看状态：

```bash
docker compose --env-file .env.docker ps
docker compose --env-file .env.docker logs -f migrate
docker compose --env-file .env.docker logs -f backend
```

`migrate` 是预期「退出 0」的一次性容器；若为 `Exited (1)`，先看日志再排查数据库。

### 5.2 初始化提示词模板（必须执行一次）

提示词模板与智能体配置存 MySQL，空库时各工作流会退化为内置角色提示词。建表后执行：

```bash
# 强烈建议：先注册你自己的账号，再把演示资料写到该账号，避免产生演示用户
docker compose --env-file .env.docker exec backend \
  python scripts/init_prompt.py --username <你的用户名>

# 或使用脚本自带的演示账号 prompt_demo（密码会打印在终端）
docker compose --env-file .env.docker exec backend python scripts/init_prompt.py
```

脚本可重复执行：模板固定维护 v1（可回滚）/ v2（生效），不会产生新版本。

### 5.3 首次登录

- 生产：浏览器访问 `https://study.example.com` → 注册 → 登录。
- 本地：`http://study.localhost`（需先改 `/etc/hosts`）。

---

## 6. 验证

```bash
# 1) 健康检查（返回 {"code":200,...,"data":{"status":"ok","database":"up"}}）
curl -sS http://127.0.0.1/health            # 本地
curl -sS https://study.example.com/health   # 生产

# 2) 证书（生产）
curl -sSI https://study.example.com | head -1   # 期望 HTTP/2 200 或 301→200
docker compose --env-file .env.docker logs caddy | tail -30

# 3) MinIO 预签名（上传头像后检查返回 URL 的域名）
#    期望：http(s)://<MINIO_PUBLIC_HOST>/ai-resource/... 可直接在浏览器打开

# 4) SSE 流式（登录后取 token；可观察 meta/step/agent/done 逐条到达）
#    浏览器打开学习室发「来 3 道练习题」，能看到时间轴节点实时增长
```

逐项自测清单：

- [ ] `/health` 返回 `database: up`
- [ ] 注册 / 登录 / 刷新令牌正常
- [ ] 新建会话并发送普通对话，SSE 内容**逐字**出现（不是等结束才整段出现）
- [ ] 上传 PDF 后提问能检索到参考资料（Qdrant 正常）
- [ ] 知识卡能出图；配置播客凭证后能生成音频
- [ ] 头像 / 知识卡图片 URL 直接可访问（MinIO 预签名 Host 正确）
- [ ] 生产环境访问 `/docs` 返回 404
- [ ] `docker compose ps` 无 unhealthy / 重启循环

---

## 7. 日常运维

```bash
alias dc='docker compose --env-file .env.docker'

# 查看状态 / 资源
dc ps
docker stats --no-stream

# 日志（按服务）
dc logs -f --tail=200 backend
dc logs -f --tail=200 caddy

# 重启单个服务
dc restart backend

# 进入容器排障
dc exec backend bash
dc exec mysql bash

# 停止（保留数据卷）
dc down

# 危险：删除全部数据（数据库 / 对象存储 / 模型缓存）
# dc down -v
```

日志落在 `backend_logs` 卷的 `/app/logs/app.log`，按 10MB × 5 滚动。

---

## 8. 备份、升级与回滚

### 8.1 备份

```bash
mkdir -p ~/backup/study-pass

# ① MySQL（逻辑备份，含建库语句）
docker compose --env-file .env.docker exec -T mysql \
  sh -c 'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" \
  --single-transaction --routines --triggers "$MYSQL_DATABASE"' \
  | gzip > ~/backup/study-pass/mysql-$(date +%F).sql.gz

# ② MinIO 对象（数据卷打包；服务短暂停止保证一致）
docker compose --env-file .env.docker stop minio
docker run --rm -v study-pass_minio_data:/data -v ~/backup/study-pass:/backup \
  alpine tar czf /backup/minio-$(date +%F).tar.gz -C /data .
docker compose --env-file .env.docker start minio

# ③ 同步到异地
scp -r ~/backup/study-pass user@backup-host:/data/study-pass/

# ④ 建议：给当前镜像打标签，便于快速回滚
docker tag study-pass-backend:latest study-pass-backend:$(date +%Y%m%d%H%M)
```

### 8.2 升级

```bash
git pull

# 先备份（见上），再执行
# migrate 与 backend 各自独立构建，依赖或代码变化时两者都要重建
docker compose --env-file .env.docker build backend migrate caddy
docker compose --env-file .env.docker run --rm migrate        # alembic upgrade head
docker compose --env-file .env.docker up -d --no-build
docker compose --env-file .env.docker ps
docker compose --env-file .env.docker logs --tail=50 backend
```

`migrate` 只做向前迁移；**回退代码前先确认没有不兼容的表结构变更**。需要回滚时：

```bash
docker tag study-pass-backend:<旧标签> study-pass-backend:latest
docker compose --env-file .env.docker up -d --no-build backend
```

数据库回滚只能靠备份还原，不要在线降级 Alembic 版本。

### 8.3 恢复

```bash
docker compose --env-file .env.docker stop backend
# MySQL
gunzip -c mysql-YYYY-MM-DD.sql.gz | docker compose --env-file .env.docker exec -T mysql \
  sh -c 'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"'
# MinIO
docker compose --env-file .env.docker stop minio
docker run --rm -v study-pass_minio_data:/data -v ~/backup/study-pass:/backup \
  alpine sh -c 'rm -rf /data/* && tar xzf /backup/minio-YYYY-MM-DD.tar.gz -C /data'
docker compose --env-file .env.docker start minio backend
```

---

## 9. HTTPS 与证书（Caddyfile）

### 9.1 自动签发

生产环境 `SITE_APP` / `SITE_STORAGE` 写纯域名后，Caddy 启动时自动：

1. 申请 Let's Encrypt / ZeroSSL 证书（HTTP-01 校验，需要 80 端口公网可达）；
2. 80 端口自动 301 跳转到 443；
3. 证书到期前自动续期，状态持久化在 `caddy_data` 卷。

不需要安装 certbot，也不要手工往容器里拷证书。

### 9.2 修改站点配置

`Caddyfile` 以只读方式挂载到容器，改完后热重载：

```bash
vim deploy/caddy/Caddyfile
docker compose --env-file .env.docker exec caddy \
  caddy reload --config /etc/caddy/Caddyfile
```

格式校验（可选）：

```bash
docker compose --env-file .env.docker exec caddy \
  caddy validate --config /etc/caddy/Caddyfile
```

### 9.3 域名或协议变化时

必须同时改三处，否则会出现 403 / 图片打不开：

1. `SITE_APP` / `SITE_STORAGE`；
2. `MINIO_PUBLIC_HOST`（与 `SITE_STORAGE` 主机名一致）；
3. `MINIO_SECURE`（与 `SITE_STORAGE` 协议一致）。

改完执行 `docker compose --env-file .env.docker up -d backend caddy`（backend 需要重建容器
才能读到新的 `MINIO_ENDPOINT`）。

### 9.4 本地 HTTP 模式

`SITE_APP=http://study.localhost`、`SITE_STORAGE=http://storage.localhost` 时 Caddy 只监听 80，
不会发起 ACME。浏览器访问主站正常，但部分依赖安全上下文的能力（如音视频采集）在
`http://` 下可能受限；需要时用自签证书或内网域名 + Caddy 内部 CA。

### 9.5 证书申请失败

看 `docker compose --env-file .env.docker logs caddy`，常见原因：

- 域名解析不到本机 / AAAA 指向错误地址；
- 80 或 443 被安全组 / 防火墙 / CDN 拦截；
- 触发 CA 频率限制（测试时可在 Caddyfile 全局块临时指定 staging CA）：

```caddyfile
{
    acme_ca https://acme-staging-v02.api.letsencrypt.org/directory
}
```

---

## 10. 常见问题

| 现象 | 排查 |
| --- | --- |
| 构建 backend 失败（`No matching distribution pypdfium2`） | 依赖已锁 `5.15.2` 提供 cp313 Linux wheel；确认拉到了最新 `requirements.txt`，必要时 `docker compose build --no-cache backend` |
| 拉镜像报 `manifest unknown` / tag 不存在 | 基础镜像 tag 与上游仓库会随时间变化：把 `docker-compose.yml` 中对应镜像改为可用的稳定 tag（如 `qdrant/qdrant:latest`、`caddy:2-alpine`），再重新 `up -d`；升级前先验证 |
| pip / pnpm 下载很慢或超时 | 在 `.env.docker` 设置 `PIP_INDEX_URL`、`NPM_REGISTRY` 后重新 `build` |
| `/health` 503 / `database: down` | `dc logs backend`；确认 `MYSQL_URL` 用户/口令；`dc exec mysql mysqladmin ping` |
| MySQL 提示 `Access denied` | 首次启动后改 `.env.docker` 的口令不会自动改库内账号：需在 MySQL 内 `ALTER USER`，或删除 `mysql_data` 卷重建（会丢数据） |
| Redis `NOAUTH Authentication required` | `REDIS_PASSWORD` 与容器内 `--requirepass` 不一致；同步后 `dc up -d redis backend` |
| 图片 / 头像链接 403 或 `SignatureDoesNotMatch` | `MINIO_PUBLIC_HOST` 与浏览器实际域名不一致；`MINIO_SECURE` 与协议不一致；`SITE_STORAGE` 主机名带端口或协议 |
| 知识卡图片打不开但接口成功 | 同上，检查预签名域名能被浏览器访问（`curl -I <image_url>`） |
| SSE 不是逐字输出 | 确认 Caddy `flush_interval -1` 未被改动；中间若有 CDN，关闭其响应缓冲；浏览器代理 / 企业网关也可能缓冲 |
| 上传返回 413 | Caddyfile `request_body max_size 12MB` 与后端 `FILE_MAX_BYTES`（默认 10MB）；大文件需同时调大 |
| 接口 429 频繁 | Redis 限流生效；按需调 `RATE_LIMIT_*`（需在 compose `environment` 中显式加入变量）后重建 backend |
| 测评提交返回 `409 测评流程已失效` | 后端被扩到多 worker / 多副本，或重启过：`MemorySaver` 是进程内状态。保持 `--workers 1` 且单副本 |
| 启动日志 `语义意图模型预热失败` / 模型下载 401 | `HF_ENDPOINT=https://hf-mirror.com` 且 `HF_HUB_DISABLE_XET=1`；检查 `model_cache` 卷可写 |
| 知识卡提示“播客不可用”但图片正常 | 未配置 `PODCAST_TTS_APP_ID / PODCAST_TTS_ACCESS_KEY`，属于预期降级 |
| Caddy 启动报 `host not found in upstream`? | Caddy 用动态上游：确认 `backend` / `minio` 容器在运行，`dc logs caddy` |
| 端口 443 被占用 | 宿主机有其他 TLS 服务；`ss -lntp \| grep 443` 后停掉或改端口映射 |
| 磁盘持续增长 | 知识卡图片 / 音频与聊天数据；用 MinIO 对象与 MySQL 备份策略治理，勿直接删卷 |

---

## 11. 安全清单

- 安全组 / 防火墙只放行 `22 / 80 / 443`；不要映射 `3306 / 6379 / 8000 / 9000 / 6333`。
- MinIO 控制台只绑定 `127.0.0.1:9001`，通过 SSH 隧道访问：`ssh -L 9001:127.0.0.1:9001 <server>`。
- `APP_ENV=prod`（默认）关闭接口文档；不要在生产改成 `dev`。
- `.env.docker` 权限 `600`，值不写入任何文档 / 聊天记录；JWT 与各类密钥定期轮换。
- 后端容器以非 root 用户（uid 10001）运行。
- SSH 只允许密钥登录，禁用密码；建议安装 fail2ban。
- 定期备份 MySQL 与 MinIO，并验证恢复流程；备份文件异地存放、加密。
- 基础镜像固定大版本，升级前先在测试环境验证；生产可用 digest 固定。
- 不要执行 `docker compose down -v`，除非确认数据可丢。

---

## 12. 命令速查

```bash
alias dc='docker compose --env-file .env.docker'

dc up -d --build                 # 构建并启动
dc ps                            # 状态
dc logs -f backend               # 后端日志
dc logs -f caddy                 # 证书 / 访问日志
dc exec backend bash             # 进容器
dc exec caddy caddy reload --config /etc/caddy/Caddyfile
dc run --rm migrate              # 手动执行迁移
dc exec backend python scripts/init_prompt.py --username <用户名>
dc restart backend
dc down                          # 停止（保留卷）
docker stats --no-stream         # 资源
```
