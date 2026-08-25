#!/bin/sh
set -eu

if [ "$#" -ne 2 ]; then
  printf '用法：%s <backup.dump> <aipickstock_restore_开头的临时库名>\n' "$0" >&2
  exit 2
fi

backup_file=$1
temporary_database=$2
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
compose_file=${V2_COMPOSE_FILE:-"$project_root/compose.v2.yaml"}

checksum_verify() {
  if command -v sha256sum > /dev/null 2>&1; then
    sha256sum -c "$1"
  else
    shasum -a 256 -c "$1"
  fi
}

if [ ! -f "$backup_file" ]; then
  printf '备份文件不存在：%s\n' "$backup_file" >&2
  exit 2
fi

case "$temporary_database" in
  aipickstock_restore_[A-Za-z0-9_]*) ;;
  *)
    printf '拒绝恢复：目标库名必须以 aipickstock_restore_ 开头且只含字母、数字、下划线。\n' >&2
    exit 2
    ;;
esac

if [ -f "$backup_file.sha256" ]; then
  (cd "$(dirname -- "$backup_file")" && checksum_verify "$(basename -- "$backup_file.sha256")")
fi

exists=$(docker compose -f "$compose_file" exec -T postgres \
  sh -c 'psql --username "$POSTGRES_USER" --dbname postgres --tuples-only --no-align --command "SELECT 1 FROM pg_database WHERE datname = '\''$1'\''"' sh "$temporary_database")
if [ "$exists" = "1" ]; then
  printf '拒绝覆盖：临时数据库已存在：%s\n' "$temporary_database" >&2
  exit 2
fi

docker compose -f "$compose_file" exec -T postgres \
  sh -c 'createdb --username "$POSTGRES_USER" "$1"' sh "$temporary_database"

if ! docker compose -f "$compose_file" exec -T postgres \
  sh -c 'pg_restore --username "$POSTGRES_USER" --dbname "$1" --exit-on-error --no-owner --no-privileges' sh "$temporary_database" \
  < "$backup_file"; then
  printf '恢复失败，临时库已保留供排查：%s\n' "$temporary_database" >&2
  exit 1
fi

docker compose -f "$compose_file" exec -T postgres \
  sh -c 'psql --username "$POSTGRES_USER" --dbname "$1" --command "SELECT version_num FROM alembic_version;" --command "SELECT schemaname, relname, n_live_tup FROM pg_stat_user_tables ORDER BY relname;"' sh "$temporary_database"

printf '临时恢复完成：%s（脚本不会自动删除该数据库）\n' "$temporary_database"
