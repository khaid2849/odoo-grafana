import hmac
import os

from odoo import http
from odoo.http import request
from odoo.tools import config

from ..monitoring import metrics


def _expected_token() -> str:
    return os.environ.get('ODOO_METRICS_TOKEN') or config.get('grafana_metrics_token') or ''


class MetricsController(http.Controller):

    @http.route('/metrics', type='http', auth='none', methods=['GET'], csrf=False, save_session=False)
    def metrics(self, **kwargs):
        """Prometheus exposition endpoint, aggregated over all workers.

        Protected by a bearer token when ``grafana_metrics_token`` (odoo.conf)
        or ``ODOO_METRICS_TOKEN`` is set. Keep it off the public reverse proxy
        either way: Prometheus scrapes the Odoo container directly.
        """
        token = _expected_token()
        if token:
            header = request.httprequest.headers.get('Authorization', '')
            if not hmac.compare_digest(header.encode(), f'Bearer {token}'.encode()):
                return request.make_response('Unauthorized', status=401, headers=[
                    ('WWW-Authenticate', 'Bearer'),
                ])
        payload, content_type = metrics.render_metrics()
        return request.make_response(payload, headers=[
            ('Content-Type', content_type),
            ('Cache-Control', 'no-store'),
        ])
