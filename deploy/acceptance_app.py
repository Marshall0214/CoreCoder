"""Validation image only: predictable long-running processes for crash testing."""

from service.app import create_app as service_app


def create_app():
    return service_app(worker_module='tests.service_worker_stub')
