"""Prometheus metric definitions shared by every Odoo process.

Odoo runs several processes in prefork mode (HTTP workers, cron workers, the
gevent worker), and a Prometheus scrape lands on whichever HTTP worker accepts
the connection. When ``PROMETHEUS_MULTIPROC_DIR`` is set, ``prometheus_client``
writes every sample to mmap files in that directory and the ``/metrics``
endpoint aggregates them across processes. Without it (threaded dev server)
the default in-process registry is used.
"""
import os

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client import multiprocess

import odoo.release

MULTIPROC_DIR = os.environ.get('PROMETHEUS_MULTIPROC_DIR')

# Latency buckets tuned for an ERP: most RPCs are 10-500ms, reports and
# imports can take tens of seconds.
LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120)
CRON_BUCKETS = (0.1, 0.5, 1, 5, 15, 30, 60, 120, 300, 600, 1800, 3600)

HTTP_REQUESTS = Counter(
    'odoo_http_requests_total',
    'HTTP requests served, by route pattern and status code.',
    ['db', 'route', 'http_method', 'status'],
)
HTTP_DURATION = Histogram(
    'odoo_http_request_duration_seconds',
    'Wall-clock time spent serving an HTTP request.',
    ['db', 'route'],
    buckets=LATENCY_BUCKETS,
)
HTTP_SQL_QUERIES = Counter(
    'odoo_http_sql_queries_total',
    'SQL queries executed while serving HTTP requests.',
    ['db', 'route'],
)
HTTP_SQL_SECONDS = Counter(
    'odoo_http_sql_duration_seconds_total',
    'Time spent in SQL while serving HTTP requests.',
    ['db', 'route'],
)
HTTP_IN_PROGRESS = Gauge(
    'odoo_http_requests_in_progress',
    'HTTP requests currently being served.',
    multiprocess_mode='livesum',
)
HTTP_SLOW_REQUESTS = Counter(
    'odoo_http_slow_requests_total',
    'Requests slower than the configured slow-request threshold.',
    ['db', 'route'],
)
SQL_SLOW_QUERIES = Counter(
    'odoo_sql_slow_queries_total',
    'SQL queries slower than the configured slow-query threshold.',
    ['db'],
)
RPC_CALLS = Counter(
    'odoo_rpc_calls_total',
    'ORM calls made through /web/dataset/call_kw, by model and method.',
    ['db', 'model', 'method'],
)
RPC_SECONDS = Counter(
    'odoo_rpc_duration_seconds_total',
    'Time spent in ORM calls made through /web/dataset/call_kw.',
    ['db', 'model', 'method'],
)
CRON_RUNS = Counter(
    'odoo_cron_runs_total',
    'Scheduled action executions, by outcome.',
    ['db', 'cron', 'status'],
)
CRON_DURATION = Histogram(
    'odoo_cron_duration_seconds',
    'Duration of scheduled action executions.',
    ['db', 'cron'],
    buckets=CRON_BUCKETS,
)
LOG_MESSAGES = Counter(
    'odoo_log_messages_total',
    'Log records emitted at WARNING level or above.',
    ['level'],
)
WORKER_MEMORY = Gauge(
    'odoo_worker_memory_rss_bytes',
    'Resident memory of each live Odoo process (labelled by pid).',
    multiprocess_mode='liveall',
)
INFO = Gauge(
    'odoo_info',
    'Constant 1, labelled with the Odoo version.',
    ['version'],
    multiprocess_mode='max',
)
INFO.labels(version=odoo.release.version).set(1)


def render_metrics() -> tuple[bytes, str]:
    """Return the exposition payload and its content type."""
    if MULTIPROC_DIR:
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
    else:
        registry = REGISTRY
    return generate_latest(registry), CONTENT_TYPE_LATEST


def mark_process_dead(pid: int) -> None:
    """Drop the live gauges of a worker that the prefork master reaped."""
    if MULTIPROC_DIR:
        multiprocess.mark_process_dead(pid)
