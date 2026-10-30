#!/bin/bash
# Create/refresh the grafana_ro role in the Odoo database.
# Usage (from the folder of docker-compose.yml): ./monitoring/postgres/setup-grafana-role.sh
# Needs ODOO_DB and GRAFANA_DB_PASSWORD in .env, and the grafana
# module installed (its tables are granted).
set -euo pipefail
cd "$(dirname "$0")/../.."

set -a; . ./.env; set +a
: "${ODOO_DB:?set ODOO_DB in .env}"
: "${GRAFANA_DB_PASSWORD:?set GRAFANA_DB_PASSWORD in .env}"

docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$ODOO_DB" \
    -v grafana_password="$GRAFANA_DB_PASSWORD" -v odoo_db="$ODOO_DB" \
    < monitoring/postgres/grafana_ro.sql
echo "grafana_ro ready on database $ODOO_DB"
