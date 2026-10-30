{
    'name': 'Grafana',
    'version': '18.0.1.0.0',
    'category': 'Extra Tools',
    'summary': 'Monitor Odoo with Grafana: Prometheus metrics, slow request/SQL log, JSON logs for Loki, '
               'dashboards embedded in Odoo',
    'description': """
Grafana
=======
Observability for Odoo 18 with the Grafana stack (Prometheus, Loki, Grafana):

* ``/metrics`` Prometheus endpoint, aggregated across prefork workers: HTTP
  latency per route, SQL count/time, ORM calls per model/method, cron runs
  and duration, worker memory, warning/error log rate.
* Slow request and slow SQL query log, browsable in Odoo and queried by
  Grafana from PostgreSQL.
* One-JSON-object-per-line log format, ready for Loki.
* Grafana dashboards embedded in the Odoo backend.

Load it server-wide so the instrumentation is active in every process::

    server_wide_modules = base,web,grafana
    grafana_log_json = True

A ready-to-run Docker stack (Prometheus, Loki, Alloy, Grafana,
postgres-exporter) and the provisioned dashboards ship in the ``deploy``
folder of the module, see ``deploy/README.md``.
    """,
    'author': 'Gout',
    'maintainer': 'Gout',
    'license': 'LGPL-3',
    'depends': ['base_setup', 'web'],
    'external_dependencies': {
        'python': ['prometheus_client', 'psutil'],
    },
    'data': [
        'security/grafana_security.xml',
        'security/ir.model.access.csv',
        'data/grafana_data.xml',
        'views/grafana_dashboard_views.xml',
        'views/grafana_slow_request_views.xml',
        'views/grafana_slow_query_views.xml',
        'views/res_config_settings_views.xml',
        'views/menuitems.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'grafana/static/src/**/*',
        ],
    },
    'images': ['static/description/banner.png'],
    'post_load': 'post_load',
    'installable': True,
    'application': True,
}
