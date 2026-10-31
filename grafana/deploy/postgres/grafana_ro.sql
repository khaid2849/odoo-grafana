-- Read-only role for Grafana and postgres-exporter.
-- Run through setup-grafana-role.sh (psql variables: grafana_password, odoo_db).
-- Column-level grants keep e-mail bodies, password hashes and TOTP secrets out
-- of reach. Re-run after installing/upgrading grafana.

SELECT 'CREATE ROLE grafana_ro LOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'grafana_ro') \gexec

ALTER ROLE grafana_ro WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'grafana_password';
ALTER ROLE grafana_ro SET default_transaction_read_only = on;
ALTER ROLE grafana_ro SET statement_timeout = '30s';
-- pg_stat_* views, pg_stat_statements text and size functions
GRANT pg_monitor TO grafana_ro;
GRANT CONNECT ON DATABASE :"odoo_db" TO grafana_ro;
GRANT USAGE ON SCHEMA public TO grafana_ro;

CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- Tables of modules that may not be installed (mail, grafana...)
-- are skipped instead of failing the whole script.
DO $$
DECLARE
    grant_spec record;
BEGIN
    FOR grant_spec IN SELECT * FROM (VALUES
        ('grafana_slow_request', NULL),
        ('grafana_slow_query', NULL),
        ('ir_cron', 'id, cron_name, active, nextcall, lastcall, failure_count, first_failure_date, '
                    'interval_number, interval_type, priority'),
        ('mail_mail', 'id, state, create_date'),
        ('res_users', 'id, active, share, create_date'),
        ('res_users_log', 'id, create_uid, create_date'),
        ('res_device_log', 'id, user_id, last_activity, first_activity, revoked'),
        ('ir_module_module', 'id, name, state, latest_version, application')
    ) AS t(table_name, columns)
    LOOP
        IF to_regclass('public.' || grant_spec.table_name) IS NULL THEN
            RAISE NOTICE 'table % not found, skipped', grant_spec.table_name;
        ELSIF grant_spec.columns IS NULL THEN
            EXECUTE format('GRANT SELECT ON public.%I TO grafana_ro', grant_spec.table_name);
        ELSE
            EXECUTE format('GRANT SELECT (%s) ON public.%I TO grafana_ro', grant_spec.columns, grant_spec.table_name);
        END IF;
    END LOOP;
END
$$;
