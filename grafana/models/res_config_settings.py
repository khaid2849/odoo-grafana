from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    grafana_url = fields.Char(
        string='Grafana URL', config_parameter='grafana.grafana_url', default='/grafana',
        help="Base URL of Grafana as seen by the browser. A same-origin path behind the reverse proxy "
             "(e.g. /grafana) keeps the Grafana session cookie working inside the embedded iframe.",
    )
    grafana_slow_log_enabled = fields.Boolean(
        string='Log Slow Requests', config_parameter='grafana.slow_log_enabled',
    )
    grafana_slow_request_threshold_ms = fields.Integer(
        string='Slow Request Threshold (ms)', config_parameter='grafana.slow_request_threshold_ms',
        default=2000,
    )
    grafana_slow_query_threshold_ms = fields.Integer(
        string='Slow Query Threshold (ms)', config_parameter='grafana.slow_query_threshold_ms',
        default=500,
    )
    grafana_log_retention_days = fields.Integer(
        string='Log Retention (days)', config_parameter='grafana.log_retention_days', default=30,
    )
