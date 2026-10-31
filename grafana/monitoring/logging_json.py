"""Structured (one JSON object per line) logging for Loki.

Odoo's text format spreads tracebacks over many lines and packs the access
log figures in the message text, which makes Loki queries fragile. When
``grafana_log_json = True`` is set in odoo.conf (or ``ODOO_LOG_JSON=1`` in the
environment) the formatter of every root handler is replaced by
:class:`JsonFormatter`. A counting handler feeding ``odoo_log_messages_total``
is always installed.
"""
import datetime
import json
import logging
import os
import threading

from odoo.tools import config, str2bool

from . import metrics


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
        # odoo.http.server access lines carry their figures as record
        # attributes; the request line is "METHOD target[#model.method] HTTP/x".
        request_line = getattr(record, 'http_request_line', None)
        if not request_line:
            return
        parts = str(request_line).split(' ')
        if len(parts) < 2 or parts[0] == '-':
            return
        target, _sep, rpc = parts[1].partition('#')
        payload['http_method'], payload['path'] = parts[0], target.split('?', 1)[0]
        if rpc:
            payload['rpc'] = rpc
        status = getattr(record, 'http_response_status', '-')
        if status != '-':
            payload['status'] = str(int(status))
        try:
            payload['query_count'] = int(record.query_count)
            payload['query_time'] = round(float(record.query_time), 3)
            payload['remaining_time'] = round(float(record.remaining_time), 3)
        except (AttributeError, TypeError, ValueError):
            pass


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
