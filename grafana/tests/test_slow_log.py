import datetime
from unittest.mock import patch

from prometheus_client import CollectorRegistry, multiprocess

from odoo import fields
from odoo.tests import TransactionCase, tagged

from ..monitoring import metrics


@tagged('post_install', '-at_install')
class TestSlowLog(TransactionCase):

    def _log(self, **overrides):
        vals = {
            'path': '/web/dataset/call_kw/sale.order/read',
            'route': '/web/dataset/call_kw/<path:path>',
            'http_method': 'POST',
            'status_code': 200,
            'rpc_model': 'sale.order',
            'rpc_method': 'read',
            'user_id': self.env.uid,
            'duration_ms': 3000.0,
            'query_count': 120,
            'query_time_ms': 1200.0,
        }
        vals.update(overrides)
        return self.env['grafana.slow.request']._log_slow_request(vals, [
            ('SELECT  "sale_order"."id"\n FROM "sale_order" WHERE id IN %s', 0.8),
            ('SELECT "sale_order"."id" FROM "sale_order" WHERE id IN %s', 0.6),
        ])

    def test_log_slow_request(self):
        log = self._log()
        self.assertEqual(log.python_time_ms, 1800.0)
        self.assertEqual(log.slow_query_count, 2)
        self.assertEqual(log.slow_query_ids.mapped('duration_ms'), [800.0, 600.0])
        hashes = set(log.slow_query_ids.mapped('query_hash'))
        self.assertEqual(len(hashes), 1, "whitespace differences must not change the fingerprint")

    def test_autovacuum_purges_old_logs(self):
        self.env['ir.config_parameter'].sudo().set_int('grafana.log_retention_days', 7)
        old, recent = self._log(), self._log()
        old.request_date = fields.Datetime.now() - datetime.timedelta(days=8)
        old_queries = old.slow_query_ids
        self.env['grafana.slow.request']._gc_slow_logs()
        self.assertFalse(old.exists())
        self.assertFalse(old_queries.exists())
        self.assertTrue(recent.exists())

    def test_embed_config(self):
        dashboard = self.env.ref('grafana.dashboard_performance')
        self.env['ir.config_parameter'].sudo().set_str('grafana.grafana_url', 'https://grafana.example/')
        config = self.env['grafana.dashboard'].get_embed_config()
        entry = next(d for d in config['dashboards'] if d['id'] == dashboard.id)
        self.assertTrue(entry['url'].startswith('https://grafana.example/d/odoo-performance?orgId=1'))
        self.assertIn('kiosk', entry['url'])
        self.assertIn('hideLogo=true', entry['url'])

    def test_cron_metrics(self):
        cron = self.env['ir.cron'].create({
            'name': 'grafana test cron',
            'model_id': self.env.ref('base.model_res_partner').id,
            'state': 'code',
            'code': 'model.search_count([])',
        })
        sample = ('odoo_cron_runs_total', {'db': self.env.cr.dbname, 'cron': cron.cron_name, 'status': 'success'})
        before = self._sample(*sample)
        # _callback commits its own transaction, which the test cursor forbids
        with patch.object(self.env.cr, 'commit'), patch.object(self.env.cr, 'rollback'):
            cron._callback(cron.cron_name, cron.ir_actions_server_id.id)
        self.assertEqual(self._sample(*sample), before + 1)

    @staticmethod
    def _sample(name, labels):
        registry = metrics.REGISTRY
        if metrics.MULTIPROC_DIR:
            # samples live in the mmap files, the default registry is empty
            registry = CollectorRegistry()
            multiprocess.MultiProcessCollector(registry)
        return registry.get_sample_value(name, labels) or 0.0
