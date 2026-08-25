#!/bin/sh
set -eu

root_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
temporary_dir=$(mktemp -d)
trap 'rm -rf "$temporary_dir"' EXIT INT TERM

cd "$temporary_dir"
npx --yes --package openapi-typescript@7.13.0 openapi-typescript \
  "$root_dir/apps/api/openapi.json" \
  -o "$temporary_dir/schema.d.ts"
cmp "$temporary_dir/schema.d.ts" "$root_dir/apps/web/src/shared/api/schema.d.ts"
