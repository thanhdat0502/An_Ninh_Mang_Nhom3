"""Regression checks for the isolated HTTPS profile and its security headers."""

import os
import runpy
import secrets
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import Client, RequestFactory, SimpleTestCase, override_settings
from rest_framework.test import APIClient

from core.middleware import CONTENT_SECURITY_POLICY


def load_https_profile(**overrides):
    values = {
        "KHCN_HTTPS_SECRET_KEY": secrets.token_urlsafe(64),
        "KHCN_HTTPS_JWT_SIGNING_KEY": secrets.token_urlsafe(64),
        **overrides,
    }
    with patch.dict(os.environ, values), patch("dotenv.dotenv_values", return_value={}):
        return runpy.run_module("config.settings_https")


class HTTPSProfileTests(SimpleTestCase):
    def profile_override(self):
        config = load_https_profile()
        names = (
            "DEBUG",
            "SECRET_KEY",
            "ALLOWED_HOSTS",
            "CSRF_TRUSTED_ORIGINS",
            "SESSION_COOKIE_NAME",
            "CSRF_COOKIE_NAME",
            "SESSION_COOKIE_SECURE",
            "CSRF_COOKIE_SECURE",
            "SECURE_SSL_REDIRECT",
            "SECURE_SSL_HOST",
            "SECURE_PROXY_SSL_HEADER",
            "USE_X_FORWARDED_HOST",
            "SECURE_HSTS_SECONDS",
            "MIDDLEWARE",
            "SECURE_REFERRER_POLICY",
            "SECURE_CROSS_ORIGIN_OPENER_POLICY",
        )
        return override_settings(**{name: config[name] for name in names})

    def test_https_profile_disables_debug_and_requires_independent_strong_keys(self):
        config = load_https_profile()
        self.assertFalse(config["DEBUG"])
        self.assertTrue(config["SECRET_KEY"] != config["JWT_SIGNING_KEY"])
        self.assertTrue(len(config["JWT_SIGNING_KEY"]) >= 50)
        self.assertTrue(config["SESSION_COOKIE_SECURE"])
        self.assertTrue(config["CSRF_COOKIE_SECURE"])
        self.assertTrue(config["SECURE_SSL_REDIRECT"])

    def test_missing_or_short_https_key_is_rejected(self):
        for value in ("", "short"):
            with (
                self.subTest(value_length=len(value)),
                self.assertRaises(ImproperlyConfigured),
            ):
                load_https_profile(KHCN_HTTPS_SECRET_KEY=value)

    def test_identical_signing_and_django_keys_are_rejected(self):
        value = secrets.token_urlsafe(64)
        with self.assertRaises(ImproperlyConfigured):
            load_https_profile(
                KHCN_HTTPS_SECRET_KEY=value, KHCN_HTTPS_JWT_SIGNING_KEY=value
            )

    def test_cookie_names_are_separate_from_http_development(self):
        from django.conf import settings

        config = load_https_profile()
        for name in (
            "JWT_ACCESS_COOKIE",
            "JWT_REFRESH_COOKIE",
            "CSRF_COOKIE_NAME",
            "SESSION_COOKIE_NAME",
        ):
            self.assertNotEqual(config[name], getattr(settings, name))
        self.assertTrue(config["JWT_ACCESS_COOKIE"].startswith("__Secure-"))
        self.assertTrue(config["JWT_REFRESH_COOKIE"].startswith("__Secure-"))
        self.assertTrue(config["CSRF_COOKIE_NAME"].startswith("__Host-"))
        self.assertIsNone(config["CSRF_COOKIE_DOMAIN"])
        self.assertIsNone(config["SESSION_COOKIE_DOMAIN"])

    def test_django_does_not_trust_raw_forwarded_headers(self):
        with self.profile_override():
            request = RequestFactory().get("/", HTTP_X_FORWARDED_PROTO="https")
            self.assertFalse(request.is_secure())
            request = RequestFactory().get(
                "/", secure=True, HTTP_X_FORWARDED_PROTO="http"
            )
            self.assertTrue(request.is_secure())

    def test_http_redirect_is_canonical_even_with_spoofed_forwarded_headers(self):
        with self.profile_override():
            response = Client(HTTP_HOST="localhost:8003").get(
                "/dang-nhap/",
                HTTP_X_FORWARDED_PROTO="https",
                HTTP_X_FORWARDED_HOST="evil.example",
            )
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "https://localhost:8443/dang-nhap/")

    def test_https_headers_and_local_hsts_policy(self):
        with self.profile_override():
            response = Client(HTTP_HOST="localhost:8443").get(
                "/dang-nhap/", secure=True
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Security-Policy"], CONTENT_SECURITY_POLICY)
        self.assertNotIn("unsafe-inline", response["Content-Security-Policy"])
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertEqual(response["Cross-Origin-Opener-Policy"], "same-origin")
        self.assertIn("camera=()", response["Permissions-Policy"])
        self.assertNotIn("Strict-Transport-Security", response)

    def test_csrf_cookie_is_secure_httponly_and_host_only_on_https(self):
        with self.profile_override():
            client = APIClient(enforce_csrf_checks=True, HTTP_HOST="localhost:8443")
            response = client.get("/api/auth/csrf/", secure=True)
        self.assertEqual(response.status_code, 200)
        cookie = response.cookies["__Host-khcn_csrftoken"]
        self.assertTrue(cookie["secure"])
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertEqual(cookie["path"], "/")
        self.assertFalse(cookie["domain"])

    def test_https_login_csrf_checks_real_origin_and_header(self):
        with self.profile_override():
            client = APIClient(enforce_csrf_checks=True, HTTP_HOST="localhost:8443")
            token = client.get("/api/auth/csrf/", secure=True).data["csrfToken"]
            response = client.post("/api/auth/login/", {}, format="json", secure=True)
            self.assertEqual(response.status_code, 403)
            response = client.post(
                "/api/auth/login/",
                {},
                format="json",
                secure=True,
                HTTP_X_CSRFTOKEN=token,
                HTTP_ORIGIN="https://evil.example",
            )
            self.assertEqual(response.status_code, 403)
            response = client.post(
                "/api/auth/login/",
                {},
                format="json",
                secure=True,
                HTTP_X_CSRFTOKEN=token,
                HTTP_ORIGIN="https://localhost:8443",
            )
            # CSRF passes, then the serializer rejects missing credentials.
            self.assertEqual(response.status_code, 400)

    def test_bad_https_host_is_rejected_without_debug_information(self):
        with (
            self.profile_override(),
            self.assertLogs("django.security.DisallowedHost", "ERROR"),
        ):
            response = Client(HTTP_HOST="evil.example").get(
                "/api/auth/csrf/", secure=True
            )
        self.assertEqual(response.status_code, 400)
        self.assertNotContains(response, "Traceback", status_code=400)

    def test_development_still_ignores_raw_forwarded_header(self):
        from django.conf import settings

        self.assertNotIn(
            "core.middleware.SecurityHeadersMiddleware", settings.MIDDLEWARE
        )
        with override_settings(
            DEBUG=True, SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=["localhost"]
        ):
            response = Client(HTTP_HOST="localhost").get(
                "/dang-nhap/", HTTP_X_FORWARDED_PROTO="https"
            )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Content-Security-Policy", response)
