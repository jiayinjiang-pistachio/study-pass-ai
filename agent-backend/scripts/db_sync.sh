#!/usr/bin/env bash
# 改完 app/db/models.py 后一键同步表结构到数据库：
#   1) 依据模型与库的差异自动生成迁移脚本
#   2) 升级到最新版本
#
# 用法：
#   scripts/db_sync.sh "调整 users 表字段"
#   scripts/db_sync.sh                 # 缺省说明为 auto migrate
set -euo pipefail

# 切到仓库根目录（脚本所在目录的上一级），保证 alembic.ini 与 app 可被找到
cd "$(dirname "$0")/.."

# 优先用仓库内虚拟环境的 alembic，避免污染全局环境
ALEMBIC="alembic"
if [ -x ".venv/bin/alembic" ]; then
  ALEMBIC=".venv/bin/alembic"
fi

msg="${1:-auto migrate}"

"$ALEMBIC" revision --autogenerate -m "$msg"
"$ALEMBIC" upgrade head

echo "✔ 迁移已生成并升级到最新（$msg）"
