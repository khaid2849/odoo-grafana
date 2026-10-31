import datetime
import logging

from odoo import Command, api, fields, models

_logger = logging.getLogger(__name__)

ICP_RETENTION_DAYS = 'grafana.log_retention_days'


class GrafanaSlowRequest(models.Model):
    _name = 'grafana.slow.request'
    _description = 'Slow HTTP Request'
    _order = 'request_date desc, id desc'
    _rec_name = 'path'

    request_date = fields.Datetime(default=fields.Datetime.now, required=True, index=True, readonly=True)
    path = fields.Char(required=True, readonly=True)
    route = fields.Char(readonly=True, index=True, help="Matched route pattern, e.g. /web/dataset/call_kw/<path:path>")
    http_method = fields.Char(string='HTTP Method', readonly=True)
    status_code = fields.Integer(readonly=True)
    rpc_model = fields.Char(string='Model', readonly=True, index=True)
    rpc_method = fields.Char(string='Method', readonly=True)
    user_id = fields.Many2one('res.users', string='User', readonly=True, index=True, ondelete='set null')
    duration_ms = fields.Float(string='Duration (ms)', readonly=True, digits=(16, 1))
    query_count = fields.Integer(string='SQL Queries', readonly=True)
    query_time_ms = fields.Float(string='SQL Time (ms)', readonly=True, digits=(16, 1))
    python_time_ms = fields.Float(
        string='Python Time (ms)', readonly=True, digits=(16, 1),
        help="Duration minus SQL time: ORM, business logic, rendering.",
    )
    slow_query_ids = fields.One2many('grafana.slow.query', 'request_id', string='Slow Queries', readonly=True)
    slow_query_count = fields.Integer(readonly=True)

    @api.model
    def _log_slow_request(self, vals: dict, queries: list[tuple[str, float]]) -> 'GrafanaSlowRequest':
        """Store one slow request; called by the instrumentation as superuser."""
        now = fields.Datetime.now()
        vals = dict(
            vals,
            request_date=now,
            python_time_ms=max(vals['duration_ms'] - vals['query_time_ms'], 0.0),
            slow_query_count=len(queries),
            slow_query_ids=[
                Command.create({'query': query, 'duration_ms': delay * 1000.0, 'request_date': now})
                for query, delay in queries
            ],
        )
        return self.create(vals)

    @api.autovacuum
    def _gc_slow_logs(self) -> None:
        days = self.env['ir.config_parameter'].sudo().get_int(ICP_RETENTION_DAYS, 30) or 30
        limit_date = fields.Datetime.now() - datetime.timedelta(days=days)
        # slow queries are removed by the ondelete='cascade' foreign key
        records = self.search([('request_date', '<', limit_date)])
        _logger.info("grafana: purging %s slow request logs older than %s days", len(records), days)
        records.unlink()
