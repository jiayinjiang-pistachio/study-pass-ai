# 学面通 AI 后端镜像
# 约束：只跑单 worker —— LangGraph MemorySaver 是进程内 checkpoint，
# 多 worker / 多副本会导致测评提交 409（测评流程已失效）。

FROM python:3.13-slim-bookworm

# 可选镜像源，便于国内构建：docker compose build 时通过 build.args 覆盖
ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai

# libgomp1：onnxruntime（fastembed）运行时依赖；tzdata 保证容器内时区为东八区
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates tzdata libgomp1 \
 && rm -rf /var/lib/apt/lists/* \
 && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

# 先装依赖再拷代码，依赖不变时可复用构建缓存
COPY requirements.txt ./
RUN pip install --index-url "$PIP_INDEX_URL" -r requirements.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts

# 非 root 运行；日志 / 上传 / 模型缓存目录需要有写权限，compose 以卷挂载覆盖
RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /app/logs /app/uploads /app/models \
 && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# --proxy-headers：让 uvicorn 信任网关写入的 X-Forwarded-For / X-Forwarded-Proto，
# 限流按真实客户端 IP 计数；--workers 1 为硬约束，见文件头说明。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips=*"]
