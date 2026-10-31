#!/usr/bin/env python3
"""Generate the provisioned Odoo dashboards (dashboards/*.json).

Dashboards are kept as code so panels stay consistent across files; edit this
script and re-run it rather than hand-editing the JSON:

    python3 monitoring/grafana/build_dashboards.py
"""
import json
import pathlib

OUT = pathlib.Path(__file__).parent / 'dashboards'

PROM = {'type': 'prometheus', 'uid': 'prometheus'}
LOKI = {'type': 'loki', 'uid': 'loki'}
PG = {'type': 'grafana-postgresql-datasource', 'uid': 'odoo-postgres'}


class Layout:
    """Places panels left-to-right on Grafana's 24-column grid."""

    def __init__(self):
        self.x = self.y = self.row_h = 0
        self.next_id = 1
        self.panels = []

    def add(self, panel, w, h):
        if self.x + w > 24:
            self.x, self.y, self.row_h = 0, self.y + self.row_h, 0
        panel['id'] = self.next_id
        panel['gridPos'] = {'x': self.x, 'y': self.y, 'w': w, 'h': h}
        self.next_id += 1
        self.x += w
        self.row_h = max(self.row_h, h)
        self.panels.append(panel)

    def row(self, title):
        if self.x:
            self.x, self.y, self.row_h = 0, self.y + self.row_h, 0
        self.add({'type': 'row', 'title': title, 'collapsed': False, 'panels': []}, 24, 1)
        self.x, self.y, self.row_h = 0, self.y + 1, 0


def prom(expr, legend='', instant=False, fmt='time_series'):
    return {'datasource': PROM, 'expr': expr, 'legendFormat': legend, 'instant': instant,
            'range': not instant, 'format': fmt}


def loki(expr, legend='', instant=False):
    return {'datasource': LOKI, 'expr': expr, 'legendFormat': legend,
            'queryType': 'instant' if instant else 'range'}


def sql(raw, fmt='table'):
    return {'datasource': PG, 'rawSql': raw.strip(), 'format': fmt, 'editorMode': 'code', 'rawQuery': True}


def stat(title, target, unit='short', thresholds=None, decimals=None, description=''):
    steps = [{'color': 'green', 'value': None}] + [
        {'color': color, 'value': value} for value, color in (thresholds or [])
    ]
    defaults = {'unit': unit, 'thresholds': {'mode': 'absolute', 'steps': steps}}
    if decimals is not None:
        defaults['decimals'] = decimals
    return {
        'type': 'stat', 'title': title, 'description': description, 'datasource': target['datasource'],
        'targets': [dict(target, refId='A')],
        'fieldConfig': {'defaults': defaults, 'overrides': []},
        'options': {'reduceOptions': {'calcs': ['lastNotNull'], 'fields': '', 'values': False},
                    'colorMode': 'value', 'graphMode': 'area', 'justifyMode': 'auto', 'textMode': 'auto'},
    }


def timeseries(title, targets, unit='short', stack=False, description='', bars=False):
    return {
        'type': 'timeseries', 'title': title, 'description': description, 'datasource': targets[0]['datasource'],
        'targets': [dict(t, refId=chr(65 + i)) for i, t in enumerate(targets)],
        'fieldConfig': {'defaults': {
            'unit': unit,
            'custom': {
                'drawStyle': 'bars' if bars else 'line', 'lineWidth': 1, 'fillOpacity': 60 if bars else 12,
                'showPoints': 'never', 'spanNulls': True,
                'stacking': {'mode': 'normal' if stack else 'none', 'group': 'A'},
            },
        }, 'overrides': []},
        'options': {'legend': {'displayMode': 'list', 'placement': 'bottom', 'showLegend': True},
                    'tooltip': {'mode': 'multi', 'sort': 'desc'}},
    }


def table(title, target, overrides=None, description='', sort=None):
    panel = {
        'type': 'table', 'title': title, 'description': description, 'datasource': target['datasource'],
        'targets': [dict(target, refId='A')],
        'fieldConfig': {'defaults': {'custom': {'align': 'auto', 'cellOptions': {'type': 'auto'}}},
                        'overrides': overrides or []},
        'options': {'showHeader': True, 'cellHeight': 'sm'},
        # instant Prometheus queries add a Time column that is the same on every row
        'transformations': [{'id': 'organize', 'options': {'excludeByName': {'Time': True}}}],
    }
    if sort:
        panel['options']['sortBy'] = [{'displayName': sort, 'desc': True}]
    return panel


def unit_override(name, unit, gauge=False):
    props = [{'id': 'unit', 'value': unit}]
    if gauge:
        props.append({'id': 'custom.cellOptions', 'value': {'type': 'gauge', 'mode': 'basic'}})
    return {'matcher': {'id': 'byName', 'options': name}, 'properties': props}


def bar_gauge(title, target, unit='short'):
    return {
        'type': 'bargauge', 'title': title, 'datasource': target['datasource'],
        'targets': [dict(target, refId='A')],
        'fieldConfig': {'defaults': {'unit': unit, 'color': {'mode': 'palette-classic'}}, 'overrides': []},
        'options': {'orientation': 'horizontal', 'displayMode': 'basic', 'showUnfilled': True,
                    'reduceOptions': {'calcs': ['lastNotNull'], 'fields': '', 'values': True}},
    }


def logs(title, target):
    return {
        'type': 'logs', 'title': title, 'datasource': target['datasource'],
        'targets': [dict(target, refId='A')],
        'options': {'showTime': True, 'wrapLogMessage': True, 'sortOrder': 'Descending',
                    'enableLogDetails': True, 'prettifyLogMessage': False, 'dedupStrategy': 'none'},
    }


def query_var(name, label, datasource, query, multi=True, include_all=True):
    return {
        'name': name, 'label': label, 'type': 'query', 'datasource': datasource,
        'query': query, 'definition': query if isinstance(query, str) else '',
        'refresh': 2, 'multi': multi, 'includeAll': include_all, 'allValue': '.*',
        'current': {'selected': True, 'text': ['All'], 'value': ['$__all']}, 'sort': 1,
    }


def dashboard(uid, title, description, layout, variables=(), time_from='now-6h', refresh='30s', tags=()):
    return {
        'uid': uid, 'title': title, 'description': description,
        'tags': ['odoo', *tags], 'timezone': 'browser', 'editable': True,
        'schemaVersion': 39, 'version': 1, 'refresh': refresh, 'graphTooltip': 1,
        'time': {'from': time_from, 'to': 'now'},
        'templating': {'list': list(variables)},
        'annotations': {'list': []},
        'links': [{'type': 'dashboards', 'tags': ['odoo'], 'asDropdown': True, 'title': 'Odoo dashboards',
                   'includeVars': False, 'keepTime': True}],
        'panels': layout.panels,
    }


# --------------------------------------------------------------------------
# Performance (Prometheus)
# --------------------------------------------------------------------------
def performance():
    sel = '{db=~"$db"}'
    rate = '$__rate_interval'
    L = Layout()
    L.row('Overview')
    L.add(stat('Requests / s', prom(f'sum(rate(odoo_http_requests_total{sel}[{rate}]))'), 'reqps', decimals=2), 4, 4)
    L.add(stat('p95 latency', prom(
        f'histogram_quantile(0.95, sum by (le) (rate(odoo_http_request_duration_seconds_bucket{sel}[{rate}])))'),
        's', [(1, 'orange'), (3, 'red')]), 4, 4)
    L.add(stat('5xx error rate', prom(
        f'sum(rate(odoo_http_requests_total{{db=~"$db",status=~"5.."}}[{rate}])) '
        f'/ clamp_min(sum(rate(odoo_http_requests_total{sel}[{rate}])), 1e-9)'),
        'percentunit', [(0.01, 'orange'), (0.05, 'red')]), 4, 4)
    L.add(stat('In flight', prom('sum(odoo_http_requests_in_progress)'), 'short', [(4, 'orange'), (8, 'red')]), 4, 4)
    L.add(stat('Slow requests / min', prom(f'sum(rate(odoo_http_slow_requests_total{sel}[{rate}])) * 60'),
               'short', [(1, 'orange'), (5, 'red')], decimals=2), 4, 4)
    L.add(stat('Worker memory', prom('sum(odoo_worker_memory_rss_bytes > 0)'), 'bytes'), 4, 4)

    L.row('HTTP')
    L.add(timeseries('Requests / s by status', [
        prom(f'sum by (status) (rate(odoo_http_requests_total{sel}[{rate}]))', '{{status}}')], 'reqps', stack=True), 12, 8)
    L.add(timeseries('Latency percentiles', [
        prom(f'histogram_quantile({q}, sum by (le) (rate(odoo_http_request_duration_seconds_bucket{sel}[{rate}])))',
             f'p{int(q * 100)}') for q in (0.5, 0.95, 0.99)], 's'), 12, 8)
    L.add(timeseries('Time spent per route (top 10)', [prom(
        f'topk(10, sum by (route) (rate(odoo_http_request_duration_seconds_sum{sel}[{rate}])))', '{{route}}')],
        's', stack=True, description='Seconds of worker time per second, by route. The biggest bands are '
                                     'where optimisation pays off most.'), 12, 8)
    L.add(timeseries('p95 latency by route (top 10)', [prom(
        f'topk(10, histogram_quantile(0.95, sum by (le, route) '
        f'(rate(odoo_http_request_duration_seconds_bucket{sel}[{rate}]))))', '{{route}}')], 's'), 12, 8)

    L.row('SQL')
    L.add(timeseries('SQL queries per request by route (top 10)', [prom(
        f'topk(10, sum by (route) (rate(odoo_http_sql_queries_total{sel}[{rate}])) '
        f'/ sum by (route) (rate(odoo_http_request_duration_seconds_count{sel}[{rate}])))', '{{route}}')],
        'short', description='A high, growing count usually means an N+1 pattern (loop of browse/read).'), 12, 8)
    L.add(timeseries('Share of request time spent in SQL', [prom(
        f'sum(rate(odoo_http_sql_duration_seconds_total{sel}[{rate}])) '
        f'/ clamp_min(sum(rate(odoo_http_request_duration_seconds_sum{sel}[{rate}])), 1e-9)', 'SQL share')],
        'percentunit', description='Low share with high latency means the time goes to Python (ORM, '
                                   'computes, rendering), not to PostgreSQL.'), 6, 8)
    L.add(timeseries('Slow SQL queries / min', [prom(
        f'sum(rate(odoo_sql_slow_queries_total{sel}[{rate}])) * 60', 'slow queries')], 'short', bars=True), 6, 8)

    L.row('ORM calls (call_kw)')
    L.add(table('Most expensive model methods (selected range)', prom(
        'topk(20, sum by (model, method) (increase(odoo_rpc_duration_seconds_total{db=~"$db"}[$__range])))',
        instant=True, fmt='table'), overrides=[unit_override('Value', 's', gauge=True)], sort='Value'), 12, 10)
    L.add(table('Most frequent model methods (selected range)', prom(
        'topk(20, sum by (model, method) (increase(odoo_rpc_calls_total{db=~"$db"}[$__range])))',
        instant=True, fmt='table'), overrides=[unit_override('Value', 'short', gauge=True)], sort='Value'), 12, 10)

    L.row('Scheduled actions')
    L.add(timeseries('Cron runs by outcome', [prom(
        f'sum by (status) (increase(odoo_cron_runs_total{sel}[{rate}]))', '{{status}}')],
        'short', stack=True, bars=True), 8, 8)
    L.add(timeseries('Cron p95 duration (top 10)', [prom(
        f'topk(10, histogram_quantile(0.95, sum by (le, cron) (rate(odoo_cron_duration_seconds_bucket{sel}[$__rate_interval]))))',
        '{{cron}}')], 's'), 8, 8)
    L.add(table('Failed crons (selected range)', prom(
        'sum by (cron) (increase(odoo_cron_runs_total{db=~"$db",status="failed"}[$__range])) > 0',
        instant=True, fmt='table'), sort='Value'), 8, 8)

    L.row('Processes')
    L.add(timeseries('Memory per worker', [prom('odoo_worker_memory_rss_bytes > 0', 'pid {{pid}}')], 'bytes',
                     description='Compare with limit_memory_soft: workers above it are recycled after their '
                                 'current request.'), 12, 8)
    L.add(timeseries('Warnings / errors per minute', [prom(
        'sum by (level) (rate(odoo_log_messages_total[$__rate_interval])) * 60', '{{level}}')], 'short',
        stack=True, bars=True), 12, 8)

    var = query_var('db', 'Database', PROM, {'query': 'label_values(odoo_http_requests_total, db)',
                                            'refId': 'PrometheusVariableQueryEditor-VariableQuery'})
    return dashboard('odoo-performance', 'Odoo / Performance',
                     'HTTP latency, SQL load, ORM hot spots, cron jobs and workers.',
                     L, [var], tags=['performance'])


# --------------------------------------------------------------------------
# Logs (Loki)
# --------------------------------------------------------------------------
def logs_dashboard():
    base = '{job="odoo", db=~"$db", level=~"$level"} |~ "(?i)$search"'
    L = Layout()
    L.add(stat('Errors (range)', loki(
        'sum(count_over_time({job="odoo", db=~"$db", level=~"ERROR|CRITICAL"}[$__range]))', instant=True),
        'short', [(1, 'orange'), (20, 'red')]), 6, 4)
    L.add(stat('Warnings (range)', loki(
        'sum(count_over_time({job="odoo", db=~"$db", level="WARNING"}[$__range]))', instant=True),
        'short', [(50, 'orange')]), 6, 4)
    L.add(stat('HTTP 5xx (range)', loki(
        'sum(count_over_time({job="odoo", db=~"$db"} | json | __error__="" | logger="odoo.http.server" | status=~"5.." [$__range]))',
        instant=True), 'short', [(1, 'red')]), 6, 4)
    L.add(stat('Requests > 500 SQL queries', loki(
        'sum(count_over_time({job="odoo", db=~"$db"} | json | __error__="" | logger="odoo.http.server" | query_count > 500 [$__range]))',
        instant=True), 'short', [(1, 'orange')]), 6, 4)

    L.add(timeseries('Log volume by level', [loki(
        f'sum by (level) (count_over_time({base} [$__auto]))', '{{level}}')], 'short', stack=True, bars=True), 16, 8)
    L.add(table('Top error sources (range)', loki(
        'topk(15, sum by (logger) (count_over_time({job="odoo", db=~"$db", level=~"ERROR|CRITICAL|WARNING"} '
        '[$__range])))', instant=True), sort='Value'), 8, 8)

    # Plain-text lines (written before grafana_log_json was enabled) do not parse as
    # JSON and are shown unchanged.
    fmt = ('| json | line_format "{{if .message}}{{.logger}}{{if .uid}} [uid {{.uid}}]{{end}} {{.message}}'
           '{{if .exception}}\\n{{.exception}}{{end}}{{else}}{{__line__}}{{end}}"')
    L.add(logs('Errors and warnings', loki(
        f'{{job="odoo", db=~"$db", level=~"ERROR|CRITICAL|WARNING"}} |~ "(?i)$search" {fmt}')), 24, 12)
    L.add(logs('Heavy requests (access log: > 100 SQL queries or > 2 s)', loki(
        '{job="odoo", db=~"$db"} | json | __error__="" | logger="odoo.http.server" | query_count > 100 or query_time > 2 or remaining_time > 2 '
        '| line_format "{{.status}} {{.http_method}} {{.path}}  queries={{.query_count}} sql={{.query_time}}s '
        'python={{.remaining_time}}s"')), 24, 10)
    L.add(logs('All logs', loki(f'{base} {fmt}')), 24, 14)

    variables = [
        query_var('db', 'Database', LOKI, {'type': 1, 'label': 'db', 'stream': '{job="odoo"}', 'refId': 'LokiVariableQueryEditor-VariableQuery'}),
        {'name': 'level', 'label': 'Level', 'type': 'custom', 'multi': True, 'includeAll': True, 'allValue': '.*',
         'query': 'DEBUG,INFO,WARNING,ERROR,CRITICAL',
         'current': {'selected': True, 'text': ['All'], 'value': ['$__all']},
         'options': []},
        {'name': 'search', 'label': 'Search (regex)', 'type': 'textbox', 'query': '',
         'current': {'text': '', 'value': ''}},
    ]
    return dashboard('odoo-logs', 'Odoo / Logs', 'Odoo server logs shipped to Loki by Alloy.',
                     L, variables, time_from='now-3h', tags=['logs'])


# --------------------------------------------------------------------------
# Business & database (PostgreSQL, read-only role)
# --------------------------------------------------------------------------
def business():
    L = Layout()
    L.row('Users')
    L.add(stat('Active users (15 min)', sql(
        "SELECT count(DISTINCT user_id) AS value FROM res_device_log "
        "WHERE last_activity > (now() AT TIME ZONE 'UTC') - interval '15 minutes' AND NOT revoked")), 6, 4)
    L.add(stat('Internal users', sql(
        "SELECT count(*) AS value FROM res_users WHERE active AND NOT share")), 6, 4)
    L.add(stat('Portal users', sql(
        "SELECT count(*) AS value FROM res_users WHERE active AND share")), 6, 4)
    L.add(stat('Database size', sql(
        "SELECT pg_database_size(current_database()) AS value"), 'bytes'), 6, 4)
    L.add(timeseries('Logins per day', [sql(
        "SELECT date_trunc('day', create_date) AS time, count(*) AS logins FROM res_users_log "
        "WHERE $__timeFilter(create_date) GROUP BY 1 ORDER BY 1", 'time_series')], bars=True), 12, 8)
    L.add(timeseries('Distinct active users per hour', [sql(
        "SELECT $__timeGroupAlias(last_activity, '1h'), count(DISTINCT user_id) AS users FROM res_device_log "
        "WHERE $__timeFilter(last_activity) GROUP BY 1 ORDER BY 1", 'time_series')], bars=True), 12, 8)

    L.row('Queues & scheduled actions')
    L.add(bar_gauge('Outgoing mail by state', sql(
        "SELECT state AS metric, count(*) AS value FROM mail_mail GROUP BY state ORDER BY 2 DESC")), 8, 8)
    L.add(table('Scheduled actions health', sql("""
        SELECT cron_name AS "Action",
               active AS "Active",
               nextcall AS "Next call (UTC)",
               lastcall AS "Last call (UTC)",
               failure_count AS "Failures",
               CASE WHEN active AND nextcall < (now() AT TIME ZONE 'UTC') - interval '10 minutes'
                    THEN extract(epoch FROM (now() AT TIME ZONE 'UTC') - nextcall) END AS "Overdue"
        FROM ir_cron
        ORDER BY failure_count DESC, active DESC, nextcall
    """), overrides=[unit_override('Overdue', 's')],
        description='Overdue = the action should have run more than 10 minutes ago (cron workers busy, '
                    'stuck or not running).'), 16, 8)

    L.row('Slow request log (grafana)')
    L.add(timeseries('Slow requests per hour', [sql(
        "SELECT $__timeGroupAlias(request_date, '1h'), count(*) AS requests FROM grafana_slow_request "
        "WHERE $__timeFilter(request_date) GROUP BY 1 ORDER BY 1", 'time_series')], bars=True), 12, 8)
    L.add(timeseries('Slow request duration split', [sql(
        "SELECT $__timeGroupAlias(request_date, '1h'), sum(query_time_ms) / 1000 AS \"SQL\", "
        "sum(python_time_ms) / 1000 AS \"Python\" FROM grafana_slow_request "
        "WHERE $__timeFilter(request_date) GROUP BY 1 ORDER BY 1", 'time_series')], 's', stack=True, bars=True), 12, 8)
    L.add(table('Slowest endpoints', sql("""
        SELECT coalesce(rpc_model || '.' || rpc_method, route) AS "Endpoint",
               count(*) AS "Hits",
               round(avg(duration_ms)::numeric) AS "Avg (ms)",
               round(max(duration_ms)::numeric) AS "Max (ms)",
               round(avg(query_count)::numeric) AS "Avg queries",
               round((sum(query_time_ms) / nullif(sum(duration_ms), 0) * 100)::numeric) AS "SQL %%"
        FROM grafana_slow_request
        WHERE $__timeFilter(request_date)
        GROUP BY 1
        ORDER BY sum(duration_ms) DESC
        LIMIT 25
    """.replace('%%', '%'))), 12, 10)
    L.add(table('Costliest slow queries (by fingerprint)', sql("""
        SELECT query_hash AS "Fingerprint",
               count(*) AS "Count",
               round(sum(duration_ms)::numeric) AS "Total (ms)",
               round(avg(duration_ms)::numeric) AS "Avg (ms)",
               left(min(query), 300) AS "Query"
        FROM grafana_slow_query
        WHERE $__timeFilter(request_date)
        GROUP BY query_hash
        ORDER BY sum(duration_ms) DESC
        LIMIT 25
    """)), 12, 10)

    L.row('Data volume')
    L.add(table('Largest tables', sql("""
        SELECT relname AS "Table",
               n_live_tup AS "Rows",
               pg_total_relation_size(relid) AS "Total size",
               pg_indexes_size(relid) AS "Index size"
        FROM pg_stat_user_tables
        ORDER BY pg_total_relation_size(relid) DESC
        LIMIT 20
    """), overrides=[unit_override('Total size', 'bytes', gauge=True), unit_override('Index size', 'bytes')]), 12, 10)
    L.add(table('Most written tables (since stats reset)', sql("""
        SELECT relname AS "Table",
               n_tup_ins AS "Inserts",
               n_tup_upd AS "Updates",
               n_tup_del AS "Deletes"
        FROM pg_stat_user_tables
        ORDER BY n_tup_ins + n_tup_upd + n_tup_del DESC
        LIMIT 20
    """)), 12, 10)
    return dashboard('odoo-business', 'Odoo / Business & Database',
                     'Users, mail queue, scheduled actions, slow request log and data volume.',
                     L, time_from='now-7d', refresh='5m', tags=['business'])


# --------------------------------------------------------------------------
# PostgreSQL (postgres-exporter + pg_stat_statements)
# --------------------------------------------------------------------------
def postgres():
    sel = '{datname=~"$datname"}'
    rate = '$__rate_interval'
    L = Layout()
    L.add(stat('Up', prom('max(pg_up)'), 'bool', [(0.5, 'green')]), 4, 4)
    L.add(stat('Connections', prom(f'sum(pg_stat_activity_count{sel})')), 4, 4)
    L.add(stat('Cache hit ratio', prom(
        f'sum(rate(pg_stat_database_blks_hit{sel}[{rate}])) / clamp_min(sum(rate(pg_stat_database_blks_hit{sel}[{rate}])) '
        f'+ sum(rate(pg_stat_database_blks_read{sel}[{rate}])), 1e-9)'), 'percentunit', decimals=2,
        description='Below ~99% the working set no longer fits in shared_buffers.'), 4, 4)
    L.add(stat('Transactions / s', prom(
        f'sum(rate(pg_stat_database_xact_commit{sel}[{rate}]) + rate(pg_stat_database_xact_rollback{sel}[{rate}]))'),
        'ops', decimals=1), 4, 4)
    L.add(stat('Deadlocks (range)', prom(f'sum(increase(pg_stat_database_deadlocks{sel}[$__range]))', instant=True),
               'short', [(1, 'red')]), 4, 4)
    L.add(stat('Database size', prom(f'sum(pg_database_size_bytes{sel})'), 'bytes'), 4, 4)

    L.add(timeseries('Connections by state', [prom(
        f'sum by (state) (pg_stat_activity_count{sel})', '{{state}}')], stack=True,
        description='Many "idle in transaction" connections point to long Odoo transactions holding locks.'), 12, 8)
    L.add(timeseries('Commits / rollbacks', [
        prom(f'sum(rate(pg_stat_database_xact_commit{sel}[{rate}]))', 'commit'),
        prom(f'sum(rate(pg_stat_database_xact_rollback{sel}[{rate}]))', 'rollback')], 'ops'), 12, 8)
    L.add(timeseries('Rows', [
        prom(f'sum(rate(pg_stat_database_tup_{kind}{sel}[{rate}]))', kind)
        for kind in ('fetched', 'returned', 'inserted', 'updated', 'deleted')], 'rps'), 12, 8)
    L.add(timeseries('Locks by mode', [prom(f'sum by (mode) (pg_locks_count{sel})', '{{mode}}')], stack=True), 12, 8)

    L.add(table('Top queries by total time (pg_stat_statements)', sql("""
        SELECT calls AS "Calls",
               round(total_exec_time::numeric) AS "Total (ms)",
               round(mean_exec_time::numeric, 2) AS "Mean (ms)",
               rows AS "Rows",
               round((100.0 * shared_blks_hit / nullif(shared_blks_hit + shared_blks_read, 0))::numeric, 1) AS "Hit %%",
               left(query, 400) AS "Query"
        FROM pg_stat_statements s
        JOIN pg_database d ON d.oid = s.dbid
        WHERE d.datname = current_database()
        ORDER BY total_exec_time DESC
        LIMIT 25
    """.replace('%%', '%')), description='Cumulative since the last pg_stat_statements_reset().'), 24, 12)
    L.add(table('Sequential scans on large tables (index candidates)', sql("""
        SELECT relname AS "Table",
               seq_scan AS "Seq scans",
               seq_tup_read AS "Rows read by seq scans",
               idx_scan AS "Index scans",
               n_live_tup AS "Rows"
        FROM pg_stat_user_tables
        WHERE n_live_tup > 10000
        ORDER BY seq_tup_read DESC
        LIMIT 15
    """), description='Large tables read mostly by sequential scans often miss an index on a field used in '
                      'domains (add index=True on the Odoo field).'), 12, 10)
    L.add(table('Dead tuples / vacuum', sql("""
        SELECT relname AS "Table",
               n_dead_tup AS "Dead rows",
               n_live_tup AS "Live rows",
               last_autovacuum AS "Last autovacuum",
               last_autoanalyze AS "Last autoanalyze"
        FROM pg_stat_user_tables
        ORDER BY n_dead_tup DESC
        LIMIT 15
    """)), 12, 10)
    L.add(table('Unused indexes', sql("""
        SELECT s.relname AS "Table",
               s.indexrelname AS "Index",
               pg_relation_size(s.indexrelid) AS "Size"
        FROM pg_stat_user_indexes s
        JOIN pg_index i ON i.indexrelid = s.indexrelid
        WHERE s.idx_scan = 0 AND NOT i.indisunique AND NOT i.indisprimary
        ORDER BY pg_relation_size(s.indexrelid) DESC
        LIMIT 15
    """), overrides=[unit_override('Size', 'bytes')],
        description='Never used since the last stats reset; they cost write time and disk.'), 24, 8)

    var = query_var('datname', 'Database', PROM, {'query': 'label_values(pg_stat_database_xact_commit, datname)',
                                                  'refId': 'PrometheusVariableQueryEditor-VariableQuery'})
    return dashboard('odoo-postgres', 'Odoo / PostgreSQL',
                     'PostgreSQL health from postgres-exporter and pg_stat_statements.',
                     L, [var], tags=['postgres'])


if __name__ == '__main__':
    OUT.mkdir(exist_ok=True)
    for build in (performance, logs_dashboard, business, postgres):
        board = build()
        path = OUT / f"{board['uid']}.json"
        path.write_text(json.dumps(board, indent=2) + '\n')
        print(f"wrote {path} ({len(board['panels'])} panels)")
