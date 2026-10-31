"""Per-request instrumentation of the Odoo WSGI application.

The patches stay as thin as possible:

* ``Application.__call__`` times the whole request, captures the status code
  and installs a SQL hook through ``threading.current_thread().query_hooks``,
  the extension point ``odoo.sql_db.Cursor.execute`` already provides (the
  profiler uses the same one), so ``execute`` itself is left untouched. The
  hook runs before the query and returns a callback that receives its
  duration once it is done.
* ``Request._serve_ir_http`` records the matched route pattern (low
  cardinality, unlike the raw path), the RPC model/method of web client
  (``/web/dataset/call_kw``) and JSON-2 (``/json/2``) calls and the
  per-database thresholds, read from ``ir.config_parameter`` while a cursor
  is still open.

Slow requests and their slow queries are persisted after the response is
built, on a fresh cursor, so they survive a rollback of the request
transaction.
"""
import logging
import re
import threading
import time
from collections.abc import Callable

import psutil

from odoo import SUPERUSER_ID, api, http
from odoo.modules.registry import Registry
from odoo.tools import config, str2bool

from . import metrics

_logger = logging.getLogger(__name__)

# Long-lived or self-referential endpoints that would skew latency metrics.
SKIPPED_PREFIXES = ('/websocket', '/longpolling', '/metrics')
CALL_KW_PREFIX = '/web/dataset/call_kw'
JSON2_ROUTE = '/json/2/<__model__>/<__method__>'
METHOD_NAME_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,63}')
MAX_QUERY_LENGTH = 4000
MAX_SLOW_QUERIES_PER_REQUEST = 50

ICP_LOG_ENABLED = 'grafana.slow_log_enabled'
ICP_SLOW_REQUEST_MS = 'grafana.slow_request_threshold_ms'
ICP_SLOW_QUERY_MS = 'grafana.slow_query_threshold_ms'

_process = psutil.Process()


def _config_ms(key: str, default: int) -> float:
    try:
        return float(config.get(key) or default) / 1000.0
    except (TypeError, ValueError):
        return default / 1000.0


class RequestStats:
    """Mutable per-request state, stored on the serving thread."""

    __slots__ = (
        'route', 'model', 'method', 'uid', 'slow_queries', 'log_enabled',
        'slow_request_threshold', 'slow_query_threshold',
    )

    def __init__(self):
        self.route = 'unmatched'
        self.model = None
        self.method = None
        self.uid = None
        self.slow_queries = []
        self.log_enabled = False
        # server-wide defaults from odoo.conf, overridden per database
        self.slow_request_threshold = _config_ms('grafana_slow_request_ms', 2000)
        self.slow_query_threshold = _config_ms('grafana_slow_query_ms', 500)

    def query_hook(self, cr, query, params, start, delay) -> Callable[[float], None]:
        # Called before the query runs (``delay`` is a placeholder), the
        # returned callback gets the real duration once the query is done.
        def on_query_end(delay: float) -> None:
            if delay >= self.slow_query_threshold and len(self.slow_queries) < MAX_SLOW_QUERIES_PER_REQUEST:
                # The parametrised text (placeholders, no values) is kept on
                # purpose: it groups identical queries and never stores user data.
                text = query.decode(errors='replace') if isinstance(query, bytes) else str(query)
                self.slow_queries.append((text[:MAX_QUERY_LENGTH], delay))
        return on_query_end

    def load_thresholds(self, env) -> None:
        if 'grafana.slow.request' not in env.registry:
            return  # module not installed in this database
        # sudo: reading technical parameters, whatever the (maybe public) user
        icp = env['ir.config_parameter'].sudo()
        # a Boolean settings field deletes the parameter when unticked
        self.log_enabled = str2bool(icp.get_param(ICP_LOG_ENABLED, 'False'), default=False)
        try:
            self.slow_request_threshold = float(icp.get_param(ICP_SLOW_REQUEST_MS, 2000)) / 1000.0
            self.slow_query_threshold = float(icp.get_param(ICP_SLOW_QUERY_MS, 500)) / 1000.0
        except ValueError:
            _logger.warning("Invalid slow-log threshold in ir.config_parameter, keeping defaults")


def current_stats() -> RequestStats | None:
    return getattr(threading.current_thread(), 'grafana_stats', None)


def update_worker_memory() -> None:
    try:
        metrics.WORKER_MEMORY.set(_process.memory_info().rss)
    except psutil.Error:
        pass


def _persist_slow_request(dbname: str, vals: dict, queries: list) -> None:
    registry = Registry.registries.get(dbname)
    if registry is None or 'grafana.slow.request' not in registry:
        return
    thread = threading.current_thread()
    # keep the werkzeug access log figures about the request, not this insert
    saved = getattr(thread, 'query_count', None), getattr(thread, 'query_time', None)
    try:
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            env['grafana.slow.request']._log_slow_request(vals, queries)
    except Exception:
        _logger.warning("Could not store slow request log for %s", vals.get('path'), exc_info=True)
    finally:
        if saved[0] is not None:
            thread.query_count, thread.query_time = saved


def _record(environ: dict, stats: RequestStats, status: str, duration: float) -> None:
    thread = threading.current_thread()
    db = getattr(thread, 'dbname', None) or ''
    route = stats.route
    query_count = getattr(thread, 'query_count', 0)
    query_time = getattr(thread, 'query_time', 0.0)
    status_code = status.split(' ', 1)[0] if status else '500'

    metrics.HTTP_REQUESTS.labels(db, route, environ.get('REQUEST_METHOD', ''), status_code).inc()
    metrics.HTTP_DURATION.labels(db, route).observe(duration)
    metrics.HTTP_SQL_QUERIES.labels(db, route).inc(query_count)
    metrics.HTTP_SQL_SECONDS.labels(db, route).inc(query_time)
    if stats.model:
        metrics.RPC_CALLS.labels(db, stats.model, stats.method).inc()
        metrics.RPC_SECONDS.labels(db, stats.model, stats.method).inc(duration)
    if stats.slow_queries:
        metrics.SQL_SLOW_QUERIES.labels(db).inc(len(stats.slow_queries))

    is_slow = duration >= stats.slow_request_threshold
    if is_slow:
        metrics.HTTP_SLOW_REQUESTS.labels(db, route).inc()
    update_worker_memory()

    if db and stats.log_enabled and (is_slow or stats.slow_queries):
        _persist_slow_request(db, {
            'path': (environ.get('PATH_INFO') or '/')[:1024],
            'route': route,
            'http_method': environ.get('REQUEST_METHOD', ''),
            'status_code': int(status_code) if status_code.isdigit() else 0,
            'rpc_model': stats.model,
            'rpc_method': stats.method,
            'user_id': stats.uid or False,
            'duration_ms': duration * 1000.0,
            'query_count': query_count,
            'query_time_ms': query_time * 1000.0,
        }, stats.slow_queries)


def _instrumented_call(original):
    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO') or ''
        if path.startswith(SKIPPED_PREFIXES):
            return original(self, environ, start_response)

        thread = threading.current_thread()
        stats = RequestStats()
        thread.grafana_stats = stats
        if not hasattr(thread, 'query_hooks'):
            thread.query_hooks = []
        thread.query_hooks.append(stats.query_hook)

        status_holder = []

        def _start_response(status, headers, *args):
            status_holder.append(status)
            return start_response(status, headers, *args)

        metrics.HTTP_IN_PROGRESS.inc()
        start = time.perf_counter()
        try:
            return original(self, environ, _start_response)
        finally:
            duration = time.perf_counter() - start
            metrics.HTTP_IN_PROGRESS.dec()
            thread.query_hooks.remove(stats.query_hook)
            thread.grafana_stats = None
            try:
                _record(environ, stats, status_holder[-1] if status_holder else '', duration)
            except Exception:
                _logger.warning("grafana: failed to record request metrics", exc_info=True)
    return __call__


def _instrumented_serve_ir_http(original):
    def _serve_ir_http(self, rule, args):
        stats = current_stats()
        if stats is None:
            return original(self, rule, args)
        stats.route = rule.rule
        stats.uid = self.session.uid
        stats.load_thresholds(self.env)
        try:
            return original(self, rule, args)
        finally:
            model = method = None
            if rule.rule.startswith(CALL_KW_PREFIX):
                params = getattr(self, 'params', None) or {}
                model, method = params.get('model'), params.get('method')
            elif rule.rule == JSON2_ROUTE:
                model, method = args.get('__model__'), args.get('__method__')
            # Only label real model methods: both values come from the
            # client and must not create unbounded metric series.
            if (isinstance(model, str) and isinstance(method, str)
                    and model in self.registry
                    and METHOD_NAME_RE.fullmatch(method)
                    and callable(getattr(self.registry[model], method, None))):
                stats.model, stats.method = model, method
    return _serve_ir_http


def _labelled(original, route_label):
    def wrapper(self, *args, **kwargs):
        stats = current_stats()
        if stats is not None:
            stats.route = route_label
        return original(self, *args, **kwargs)
    return wrapper


def patch_http() -> None:
    http.Application.__call__ = _instrumented_call(http.Application.__call__)
    http.Request._serve_ir_http = _instrumented_serve_ir_http(http.Request._serve_ir_http)
    http.Request._serve_static = _labelled(http.Request._serve_static, 'static')
    http.Request._serve_nodb = _labelled(http.Request._serve_nodb, 'nodb')
    http.Request._serve_ir_http_fallback = _labelled(http.Request._serve_ir_http_fallback, 'fallback')
