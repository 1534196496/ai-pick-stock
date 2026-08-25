#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
compose_file=${V2_COMPOSE_FILE:-"$project_root/compose.v2.yaml"}
backup_dir=${1:-"$project_root/backups/postgres"}
timestamp=$(date -u '+%Y%m%dT%H%M%SZ')
archive="$backup_dir/aipickstock-$timestamp.dump"
temporary="$archive.incomplete"

checksum_create() {
  if command -v sha256sum > /dev/null 2>&1; then
    sha256sum "$1"
  else
    shasum -a 256 "$1"
  fi
}

mkdir -p "$backup_dir"
chmod 700 "$backup_dir"
trap 'rm -f -- "$temporary"' EXIT INT TERM

docker compose -f "$compose_file" exec -T postgres \
  sh -c 'exec pg_dump --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --format=custom --compress=9 --no-owner --no-privileges' \
  > "$temporary"

docker compose -f "$compose_file" exec -T postgres pg_restore --list \
  < "$temporary" > /dev/null

mv "$temporary" "$archive"
chmod 600 "$archive"
(cd "$backup_dir" && checksum_create "$(basename -- "$archive")") > "$archive.sha256"
chmod 600 "$archive.sha256"
trap - EXIT INT TERM

printf '备份完成：%s\n' "$archive"
