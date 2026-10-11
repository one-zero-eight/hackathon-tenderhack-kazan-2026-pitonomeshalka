#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
seed=seeds/db.dump

case "${1:-}" in
  dump|restore) action=$1 ;;
  *) echo "Usage: bash scripts/db_seed.sh {dump|restore} [container-name]" >&2; exit 2 ;;
esac
if (( $# > 2 )); then
  echo "Usage: bash scripts/db_seed.sh {dump|restore} [container-name]" >&2
  exit 2
fi

if [[ $action == restore && ! -s $seed ]]; then
  echo "Missing $seed. Download the shared database seed into seeds/ first." >&2
  exit 1
fi

if [[ -n ${2:-} ]]; then
  container=$2
else
  if [[ $action == restore ]]; then
    docker compose up -d --wait --wait-timeout 120 postgres
  fi
  container=$(docker compose ps -q postgres)
  if [[ -z $container ]]; then
    echo "No running postgres service. Start it or pass an existing container name." >&2
    exit 1
  fi
fi

if [[ $action == dump ]]; then
  mkdir -p seeds
  temporary=$(mktemp seeds/db.dump.XXXXXX)
  trap 'rm -f "$temporary"' EXIT
  docker exec "$container" sh -c 'exec pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --format=custom --compress=6 --no-owner --no-privileges' > "$temporary"
  mv "$temporary" "$seed"
  echo "Created $seed (compressed schema, data, embeddings, and saved history)."
else
  echo "Restoring $seed into $container; existing objects included in the seed will be replaced." >&2
  docker exec -i "$container" sh -c 'exec pg_restore --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --clean --if-exists --no-owner --no-privileges --single-transaction' < "$seed"
  docker exec "$container" sh -c 'exec psql -X --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --set=ON_ERROR_STOP=1 --command="ANALYZE;"'
  echo "Database seed restored."
fi
