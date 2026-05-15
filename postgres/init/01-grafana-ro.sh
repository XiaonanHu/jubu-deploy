#!/bin/bash
# Create the read-only `grafana_ro` role on first-boot of a fresh Postgres
# volume.  The Postgres entrypoint runs every *.sh and *.sql file in
# /docker-entrypoint-initdb.d/ exactly once, in lexical order.  On an
# existing deployment, run this command by hand:
#
#   docker compose exec -e GRAFANA_RO_PASSWORD=... postgres \
#       /docker-entrypoint-initdb.d/01-grafana-ro.sh
#
# Idempotent: the DO block skips role creation if it already exists.

set -euo pipefail

if [[ -z "${GRAFANA_RO_PASSWORD:-}" ]]; then
  echo "01-grafana-ro: GRAFANA_RO_PASSWORD not set; skipping read-only role creation"
  exit 0
fi

psql -v ON_ERROR_STOP=1 \
     --username "${POSTGRES_USER:-jubu}" \
     --dbname   "${POSTGRES_DB:-jubu}" <<-EOSQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'grafana_ro') THEN
        EXECUTE format('CREATE ROLE grafana_ro LOGIN PASSWORD %L', '${GRAFANA_RO_PASSWORD}');
    ELSE
        EXECUTE format('ALTER ROLE grafana_ro WITH PASSWORD %L', '${GRAFANA_RO_PASSWORD}');
    END IF;
END \$\$;

GRANT CONNECT ON DATABASE ${POSTGRES_DB:-jubu} TO grafana_ro;
GRANT USAGE   ON SCHEMA public TO grafana_ro;
GRANT SELECT  ON ALL TABLES    IN SCHEMA public TO grafana_ro;
GRANT SELECT  ON ALL SEQUENCES IN SCHEMA public TO grafana_ro;

-- Future tables (e.g. telemetry_events in Phase 1) get SELECT automatically.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES    TO grafana_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON SEQUENCES TO grafana_ro;
EOSQL

echo "01-grafana-ro: read-only role 'grafana_ro' created/refreshed"
