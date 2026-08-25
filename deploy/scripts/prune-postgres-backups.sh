#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
backup_dir=${1:-"$project_root/backups/postgres"}
retention_days=${2:-14}
mode=${3:-"--dry-run"}

case "$retention_days" in
  ''|*[!0-9]*)
    printf '保留天数必须是非负整数。\n' >&2
    exit 2
    ;;
esac

if [ ! -d "$backup_dir" ]; then
  printf '备份目录不存在，无需清理：%s\n' "$backup_dir"
  exit 0
fi

find "$backup_dir" -type f \( -name 'aipickstock-*.dump' -o -name 'aipickstock-*.dump.sha256' \) -mtime "+$retention_days" -print |
while IFS= read -r candidate; do
  if [ "$mode" = "--apply" ]; then
    rm -f -- "$candidate"
    printf '已删除过期备份：%s\n' "$candidate"
  else
    printf '将删除：%s\n' "$candidate"
  fi
done

if [ "$mode" != "--apply" ]; then
  printf '当前为预览模式；确认列表后追加 --apply 才会删除。\n'
fi
