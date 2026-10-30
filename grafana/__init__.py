from . import controllers
from . import models
from .monitoring import install


def post_load():
    """Install the HTTP/cron/logging instrumentation.

    Runs once per process when the module is imported. Load the module
    server-wide (``server_wide_modules = base,web,grafana``) so it is
    imported by the prefork master before the workers fork.
    """
    install()
