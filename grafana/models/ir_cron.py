import time

from odoo import models

from ..monitoring import metrics
from ..monitoring.http_instrumentation import update_worker_memory


class IrCron(models.Model):
    _inherit = 'ir.cron'

    def _callback(self, cron_name: str, server_action_id: int) -> None:
        start = time.perf_counter()
        status = 'success'
        try:
            return super()._callback(cron_name, server_action_id)
        except Exception:
            status = 'failed'
            raise
        finally:
            db = self.env.cr.dbname
            metrics.CRON_RUNS.labels(db, cron_name, status).inc()
            metrics.CRON_DURATION.labels(db, cron_name).observe(time.perf_counter() - start)
            update_worker_memory()
