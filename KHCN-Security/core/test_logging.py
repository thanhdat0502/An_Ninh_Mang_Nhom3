import logging
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.test import Client, SimpleTestCase, override_settings
from django.test.runner import DiscoverRunner
from django.urls import path

from .test_runner import (
    CLIENT_STATUSES,
    REQUEST_LOGGERS,
    ExpectedClientErrorFilter,
    SecurityTestRunner,
    quiet_client_error_logs,
)


def denied_view(request):
    raise PermissionDenied


def broken_view(request):
    raise RuntimeError("test-only failure")


# Test-only URLConf; not mounted in config.urls.
urlpatterns = [path("denied/", denied_view), path("broken/", broken_view)]


class TestLoggingPolicyTests(SimpleTestCase):
    def record(
        self, status=403, *, name="django.request", level=logging.WARNING, error=None
    ):
        record = logging.LogRecord(
            name, level, __file__, 1, "test HTTP response", (), None
        )
        record.status_code = status
        if error is not None:
            record.exc_info = (type(error), error, None)
        return record

    def test_routine_client_warnings_are_filtered(self):
        policy = ExpectedClientErrorFilter()
        for name in REQUEST_LOGGERS:
            for status in CLIENT_STATUSES:
                with self.subTest(logger=name, status=status):
                    self.assertFalse(policy.filter(self.record(status, name=name)))

    def test_permission_denied_trace_is_filtered_only_for_warning_403(self):
        policy = ExpectedClientErrorFilter()
        self.assertFalse(policy.filter(self.record(error=PermissionDenied())))
        self.assertTrue(policy.filter(self.record(500, error=PermissionDenied())))
        self.assertTrue(
            policy.filter(self.record(level=logging.ERROR, error=PermissionDenied()))
        )

    def test_unexpected_exception_trace_is_kept_even_with_4xx_status(self):
        record = self.record(error=RuntimeError("test-only failure"))
        original = record.exc_info
        self.assertTrue(ExpectedClientErrorFilter().filter(record))
        self.assertIs(record.exc_info, original)

    def test_server_errors_and_error_level_client_logs_are_kept(self):
        policy = ExpectedClientErrorFilter()
        for status in (500, 502, 503):
            self.assertTrue(policy.filter(self.record(status)))
            self.assertTrue(policy.filter(self.record(status, level=logging.ERROR)))
        for status in CLIENT_STATUSES:
            self.assertTrue(policy.filter(self.record(status, level=logging.ERROR)))
        for level in (logging.DEBUG, logging.INFO, logging.CRITICAL):
            self.assertTrue(policy.filter(self.record(level=level)))

    def test_unclassified_records_and_other_security_loggers_are_kept(self):
        policy = ExpectedClientErrorFilter()
        for name in (
            "application",
            "django.security.DisallowedHost",
            "django.db.backends",
        ):
            self.assertTrue(policy.filter(self.record(name=name)))
        for status in (None, 200, 402, 418):
            self.assertTrue(policy.filter(self.record(status)))

    def test_logging_configuration_is_restored_on_exit_or_exception(self):
        loggers = [logging.getLogger(name) for name in REQUEST_LOGGERS]
        originals = [
            (
                list(logger.filters),
                logger.level,
                list(logger.handlers),
                logger.propagate,
            )
            for logger in loggers
        ]
        for failure in (False, True):
            try:
                with quiet_client_error_logs():
                    for logger in loggers:
                        self.assertTrue(
                            any(
                                isinstance(item, ExpectedClientErrorFilter)
                                for item in logger.filters
                            )
                        )
                    if failure:
                        raise RuntimeError("test-only failure")
            except RuntimeError:
                pass
            for logger, original in zip(loggers, originals, strict=True):
                self.assertEqual(
                    (logger.filters, logger.level, logger.handlers, logger.propagate),
                    original,
                )

    def test_runner_keeps_failure_result_and_restores_logging(self):
        logger = logging.getLogger("django.request")
        original = list(logger.filters)
        with patch.object(DiscoverRunner, "run_tests", return_value=2):
            # Nonzero means failing tests; the wrapper must not turn it into OK.
            self.assertEqual(SecurityTestRunner().run_tests(["core"]), 2)
        self.assertEqual(logger.filters, original)

    def test_runner_propagates_setup_or_execution_exception(self):
        logger = logging.getLogger("django.request")
        original = list(logger.filters)
        with (
            patch.object(DiscoverRunner, "run_tests", side_effect=RuntimeError),
            self.assertRaises(RuntimeError),
        ):
            SecurityTestRunner().run_tests(["core"])
        self.assertEqual(logger.filters, original)

    @override_settings(
        ROOT_URLCONF=__name__,
        DEBUG=True,
        SECURE_SSL_REDIRECT=False,
        ALLOWED_HOSTS=["localhost"],
    )
    def test_real_permission_denied_is_still_http_403_without_noisy_trace(self):
        client = Client(enforce_csrf_checks=True, HTTP_HOST="localhost")
        with (
            quiet_client_error_logs(),
            self.assertNoLogs("django.request", logging.WARNING),
        ):
            response = client.get("/denied/")
        self.assertEqual(response.status_code, 403)

    @override_settings(
        ROOT_URLCONF=__name__,
        DEBUG=False,
        SECURE_SSL_REDIRECT=False,
        ALLOWED_HOSTS=["localhost"],
    )
    def test_real_unhandled_error_keeps_500_trace_and_test_client_exception(self):
        client = Client(enforce_csrf_checks=True, HTTP_HOST="localhost")
        with (
            quiet_client_error_logs(),
            self.assertLogs("django.request", logging.ERROR) as captured,
            self.assertRaises(RuntimeError),
        ):
            client.get("/broken/")
        record = captured.records[0]
        self.assertEqual(record.status_code, 500)
        self.assertIs(record.exc_info[0], RuntimeError)
        self.assertIsNotNone(record.exc_info[2])
