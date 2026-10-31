import json
import logging

from odoo.tests import TransactionCase, tagged

from ..monitoring.logging_json import JsonFormatter


@tagged('post_install', '-at_install')
class TestJsonLogging(TransactionCase):

    def _format(self, name, msg, **extra):
        record = logging.LogRecord(name, logging.INFO, __file__, 1, msg, None, None)
        record.__dict__.update(extra)
        return json.loads(JsonFormatter().format(record))

    def test_access_log_fields(self):
        payload = self._format(
            'odoo.http.server', '127.0.0.1 - - [31/Oct/2026 10:00:00] "POST ..." 200 512 12 0.0041 0.0102 rw',
            http_request_line='POST /web/dataset/call_kw/res.partner/search_read?debug=1'
                              '#res.partner.search_read HTTP/1.1',
            http_response_status=200, query_count=12, query_time=0.00412, remaining_time=0.01021,
        )
        self.assertEqual(payload['logger'], 'odoo.http.server')
        self.assertEqual(payload['http_method'], 'POST')
        self.assertEqual(payload['path'], '/web/dataset/call_kw/res.partner/search_read')
        self.assertEqual(payload['rpc'], 'res.partner.search_read')
        self.assertEqual(payload['status'], '200')
        self.assertEqual(payload['query_count'], 12)
        self.assertEqual(payload['query_time'], 0.004)
        self.assertEqual(payload['remaining_time'], 0.01)

    def test_regular_record_has_no_access_fields(self):
        payload = self._format('odoo.addons.base', 'hello')
        self.assertEqual(payload['message'], 'hello')
        self.assertNotIn('status', payload)
        self.assertNotIn('query_count', payload)
