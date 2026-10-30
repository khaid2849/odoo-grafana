import logging

from odoo.service import server

from . import metrics
from .http_instrumentation import patch_http
from .logging_json import setup_logging

_logger = logging.getLogger(__name__)
_installed = False


def _patch_prefork() -> None:
    """Let the prefork master clean up the live gauges of reaped workers."""
    original = server.PreforkServer.worker_pop

    def worker_pop(self, pid):
        original(self, pid)
        metrics.mark_process_dead(pid)

    server.PreforkServer.worker_pop = worker_pop


def install() -> None:
    global _installed  # noqa: PLW0603
    if _installed:
        return
    _installed = True
    patch_http()
    _patch_prefork()
    setup_logging()
    _logger.info(
        "grafana instrumentation active (multiprocess dir: %s)",
        metrics.MULTIPROC_DIR or 'disabled',
    )
