"""Structured (one JSON object per line) logging for Loki.

Odoo's text format spreads tracebacks over many lines and mixes free text
with the access-log perf figures, which makes Loki queries fragile. When
``grafana_log_json = True`` is set in odoo.conf (or ``ODOO_LOG_JSON=1`` in the
environment) the formatter of every root handler is replaced by
:class:`JsonFormatter`. A counting handler feeding ``odoo_log_messages_total``
is always installed.
"""
import datetime
import json
import logging
import os
import re
import threading

from odoo.tools import config, str2bool

from . import metrics

ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


class JsonFormatter(logging.Formatter):

    def format(self, record: logging.LogRecord) -> str:
        thread = threading.current_thread()
        payload = {
            'ts': datetime.datetime.fromtimestamp(record.created, tz=datetime.timezone.utc)
                  .isoformat(timespec='milliseconds'),
            'level': record.levelname,
            'logger': record.name,
            'pid': os.getpid(),
            'db': getattr(thread, 'dbname', None),
            'uid': getattr(thread, 'uid', None),
            'message': record.getMessage(),
        }
        self._add_access_log_fields(record, payload)
        if record.exc_info:
            payload['exception'] = self.formatException(record.exc_info)
        if record.stack_info:
            payload['stack'] = self.formatStack(record.stack_info)
        return json.dumps(payload, default=str, ensure_ascii=False)

    @staticmethod
    def _add_access_log_fields(record: logging.LogRecord, payload: dict) -> None:
        # werkzeug access lines: '"%s" %s %s' % (request_line, code, size), plus
        # Odoo's PerfFilter figures "query_count query_time remaining_time".
        perf = ANSI_RE.sub('', getattr(record, 'perf_info', '') or '').split()
        if len(perf) >= 3 and perf[0] != '-':
            try:
                payload['query_count'] = int(perf[0])
                payload['query_time'] = float(perf[1])
                payload['remaining_time'] = float(perf[2])
            except ValueError:
                pass
        if record.name == 'werkzeug' and isinstance(record.args, tuple) and len(record.args) == 3:
            request_line, status, _size = record.args
            parts = str(request_line).split(' ')
            if len(parts) >= 2:
                payload['http_method'], payload['path'] = parts[0], parts[1].split('?', 1)[0]
            payload['status'] = str(status)


class MetricsLogHandler(logging.Handler):
    """Counts WARNING+ records so error spikes are visible in Prometheus."""

    def __init__(self):
        super().__init__(level=logging.WARNING)

    def emit(self, record: logging.LogRecord) -> None:
        metrics.LOG_MESSAGES.labels(level=record.levelname).inc()


def _json_enabled() -> bool:
    value = os.environ.get('ODOO_LOG_JSON') or config.get('grafana_log_json') or 'False'
    return str2bool(str(value), default=False)


def setup_logging() -> None:
    root = logging.getLogger()
    root.addHandler(MetricsLogHandler())
    if _json_enabled():
        formatter = JsonFormatter()
        for handler in root.handlers:
            if not isinstance(handler, MetricsLogHandler):
                handler.setFormatter(formatter)
