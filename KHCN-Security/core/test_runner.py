"""Keep adversarial HTTP test output readable without hiding application errors."""

import logging
from contextlib import contextmanager

from django.core.exceptions import PermissionDenied
from django.test.runner import DiscoverRunner

REQUEST_LOGGERS = ("django.request", "django.security.csrf")
CLIENT_STATUSES = frozenset((400, 401, 403, 404, 405, 409, 413, 429))


class ExpectedClientErrorFilter(logging.Filter):
    """Filter routine 4xx warnings only; never alter a response or exception."""

    def filter(self, record):
        status = getattr(record, "status_code", None)
        if (
            record.name not in REQUEST_LOGGERS
            or record.levelno != logging.WARNING
            or status not in CLIENT_STATUSES
        ):
            return True
        if record.exc_info:
            # Django logs the expected admin denial with a traceback. Keep any
            # other exception, even if a caller assigned it a 4xx status.
            return not (
                status == 403
                and isinstance(record.exc_info, tuple)
                and isinstance(record.exc_info[1], PermissionDenied)
            )
        return False


@contextmanager
def quiet_client_error_logs():
    log_filter = ExpectedClientErrorFilter()
    loggers = [logging.getLogger(name) for name in REQUEST_LOGGERS]
    for logger in loggers:
        logger.addFilter(log_filter)
    try:
        yield
    finally:
        for logger in loggers:
            logger.removeFilter(log_filter)


class SecurityTestRunner(DiscoverRunner):
    def run_tests(self, test_labels, **kwargs):
        # Only this invocation is affected, including when setup or a test fails.
        # Production/runserver logging and unittest failure output are untouched.
        with quiet_client_error_logs():
            return super().run_tests(test_labels, **kwargs)
