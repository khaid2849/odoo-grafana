import hashlib
import re

from odoo import api, fields, models

WHITESPACE_RE = re.compile(r'\s+')


class GrafanaSlowQuery(models.Model):
    _name = 'grafana.slow.query'
    _description = 'Slow SQL Query'
    _order = 'request_date desc, duration_ms desc'
    _rec_name = 'query_hash'

    request_id = fields.Many2one(
        'grafana.slow.request', string='Request', required=True, index=True, ondelete='cascade', readonly=True,
    )
    request_date = fields.Datetime(required=True, index=True, readonly=True)
    query = fields.Text(required=True, readonly=True, help="Parametrised SQL text (placeholders, no values).")
    query_hash = fields.Char(
        compute='_compute_query_hash', store=True, index=True,
        help="Fingerprint of the normalised query, used to group identical queries.",
    )
    duration_ms = fields.Float(string='Duration (ms)', readonly=True, digits=(16, 1))
    path = fields.Char(related='request_id.path')
    user_id = fields.Many2one(related='request_id.user_id')

    @api.depends('query')
    def _compute_query_hash(self) -> None:
        for record in self:
            normalized = WHITESPACE_RE.sub(' ', record.query or '').strip()
            record.query_hash = hashlib.md5(normalized.encode(), usedforsecurity=False).hexdigest()[:16]
