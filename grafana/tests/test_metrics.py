from unittest.mock import patch

from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from ..controllers import metrics as metrics_controller


@tagged('post_install', '-at_install')
class TestMetricsEndpoint(HttpCase):

    def test_metrics_exposes_odoo_series(self):
        self.url_open('/web/login')
        response = self.url_open('/metrics')
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/plain', response.headers['Content-Type'])
        body = response.text
        self.assertIn('odoo_http_requests_total', body)
        self.assertIn('odoo_http_request_duration_seconds_bucket', body)
        self.assertIn('odoo_info', body)

    def test_metrics_requires_token_when_configured(self):
        with patch.object(metrics_controller, '_expected_token', return_value='s3cret'):
            self.assertEqual(self.url_open('/metrics').status_code, 401)
            wrong = self.url_open('/metrics', headers={'Authorization': 'Bearer nope'})
            self.assertEqual(wrong.status_code, 401)
            ok = self.url_open('/metrics', headers={'Authorization': 'Bearer s3cret'})
            self.assertEqual(ok.status_code, 200)

    def test_rpc_calls_are_labelled_by_model_and_method(self):
        self.authenticate('admin', 'admin')
        self.make_jsonrpc_request('/web/dataset/call_kw/res.partner/search_count', {
            'model': 'res.partner', 'method': 'search_count', 'args': [[]], 'kwargs': {},
        })
        body = self.url_open('/metrics').text
        # prometheus_client sorts labels alphabetically
        sample = f'odoo_rpc_calls_total{{db="{self.env.cr.dbname}",method="search_count",model="res.partner"}}'
        self.assertIn(sample, body)

    @mute_logger('odoo.http')
    def test_unknown_rpc_method_is_not_labelled(self):
        self.authenticate('admin', 'admin')
        self.url_open(
            '/web/dataset/call_kw/res.partner/zz_no_such_method',
            data='{"jsonrpc": "2.0", "method": "call", "params": {"model": "res.partner", '
                 '"method": "zz_no_such_method", "args": [], "kwargs": {}}}',
            headers={'Content-Type': 'application/json'},
        )
        self.assertNotIn('zz_no_such_method', self.url_open('/metrics').text)

    def test_slow_request_is_logged(self):
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('grafana.slow_log_enabled', 'True')
        icp.set_param('grafana.slow_request_threshold_ms', '0')
        icp.set_param('grafana.slow_query_threshold_ms', '0')
        self.authenticate('admin', 'admin')
        self.make_jsonrpc_request('/web/dataset/call_kw/res.partner/search_read', {
            'model': 'res.partner', 'method': 'search_read', 'args': [[]], 'kwargs': {'limit': 1},
        })
        log = self.env['grafana.slow.request'].search([('rpc_method', '=', 'search_read')], limit=1)
        self.assertTrue(log, "the request should have been logged with a 0 ms threshold")
        self.assertEqual(log.rpc_model, 'res.partner')
        self.assertEqual(log.route, '/web/dataset/call_kw/<path:path>')
        self.assertEqual(log.user_id, self.env.ref('base.user_admin'))
        self.assertGreater(log.query_count, 0)
        self.assertTrue(log.slow_query_ids)
        self.assertNotIn("'", log.slow_query_ids[0].query.split('WHERE')[-1].replace("''", ''),
                         "queries are stored with placeholders, not literal values")

    def test_slow_log_disabled(self):
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('grafana.slow_log_enabled', False)
        icp.set_param('grafana.slow_request_threshold_ms', '0')
        before = self.env['grafana.slow.request'].search_count([])
        self.url_open('/web/login')
        self.assertEqual(self.env['grafana.slow.request'].search_count([]), before)
