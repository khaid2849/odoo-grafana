from urllib.parse import urlencode

from odoo import api, fields, models

ICP_GRAFANA_URL = 'grafana.grafana_url'


class GrafanaDashboard(models.Model):
    _name = 'grafana.dashboard'
    _description = 'Grafana Dashboard'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    uid = fields.Char(string='Dashboard UID', required=True, help="UID of the dashboard in Grafana (the /d/<uid> part).")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text(translate=True)
    kiosk = fields.Boolean(default=True, help="Hide the Grafana navigation chrome and branding footer in the embedded view.")
    time_from = fields.Char(string='Default Time Range', default='now-6h', required=True)
    refresh = fields.Char(string='Auto Refresh', default='30s', help="Grafana refresh interval, e.g. 30s, 1m. Empty disables it.")

    _uid_unique = models.Constraint('unique(uid)', "A dashboard with this UID already exists.")

    def _get_embed_url(self, base_url: str) -> str:
        self.ensure_one()
        params = {'orgId': 1, 'from': self.time_from, 'to': 'now'}
        if self.refresh:
            params['refresh'] = self.refresh
        query = urlencode(params)
        if self.kiosk:
            # hideLogo drops the "Powered by Grafana" footer that covers the bottom panels
            query += '&kiosk&hideLogo=true'
        return f"{base_url.rstrip('/')}/d/{self.uid}?{query}"

    @api.model
    def get_embed_config(self) -> dict:
        """Dashboards visible to the current user, with ready-to-embed URLs."""
        # sudo: the Grafana URL is a technical parameter users cannot read directly
        base_url = self.env['ir.config_parameter'].sudo().get_str(ICP_GRAFANA_URL, '/grafana')
        dashboards = self.search([])
        return {
            'base_url': base_url,
            'dashboards': [{
                'id': dashboard.id,
                'name': dashboard.name,
                'description': dashboard.description or '',
                'url': dashboard._get_embed_url(base_url),
            } for dashboard in dashboards],
        }
