# 网关镜像：构建前端静态产物 + Caddy 运行时（自动 HTTPS）
# 构建上下文是仓库根目录（同时需要 agent-frontend 与 deploy/caddy）。

FROM node:22-alpine AS frontend

ARG NPM_REGISTRY=https://registry.npmjs.org

WORKDIR /app

# 仓库锁定 lockfileVersion 9.0，固定 pnpm 9 保证 --frozen-lockfile 可复现；
# 用 npm 的 --registry 安装 pnpm，国内镜像源才能生效（corepack 会忽略该设置）
RUN npm install -g pnpm@9.15.0 --registry="$NPM_REGISTRY"

COPY agent-frontend/package.json agent-frontend/pnpm-lock.yaml ./
RUN pnpm config set registry "$NPM_REGISTRY" \
 && pnpm install --frozen-lockfile

COPY agent-frontend/ ./
# .env.production 中的 VITE_API_PREFIX=/api 会打进产物；接口由 Caddy 同源转发
RUN pnpm build

FROM caddy:2.10-alpine

COPY --from=frontend /app/dist/ /srv/
COPY deploy/caddy/Caddyfile /etc/caddy/Caddyfile

EXPOSE 80
EXPOSE 443
