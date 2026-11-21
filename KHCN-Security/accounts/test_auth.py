"""Real cookie/CSRF requests: no force_authenticate or CSRF bypass in this suite."""

import os
import runpy
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.db import close_old_connections, connections
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.urls import include
from django.urls import path as url_path
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.test import APIClient
from rest_framework.views import APIView
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from accounts.models import Role
from accounts.services import rotate_refresh

User = get_user_model()


class ProtectedWriteView(APIView):
    """Test-only consumer of the global API authentication policy."""

    def post(self, request):
        User.objects.filter(pk=request.user.pk).update(full_name="Tên đã cập nhật")
        return Response({"updated": True})


urlpatterns = [
    url_path("", include("config.urls")),
    url_path("api/test-write/", ProtectedWriteView.as_view()),
]


@override_settings(
    DEBUG=True,
    SECURE_SSL_REDIRECT=False,
    CSRF_COOKIE_SECURE=False,
    ALLOWED_HOSTS=["localhost", "127.0.0.1", "testserver", "evil.example"],
    ROOT_URLCONF="accounts.test_auth",
)
class CookieJWTTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = secrets.token_urlsafe(24)
        cls.user = User.objects.create_user(
            "student@example.com",
            cls.password,
            full_name="Sinh viên kiểm thử",
        )
        cls.user.groups.add(Group.objects.create(name=Role.STUDENT))

    def setUp(self):
        cache.clear()
        self.client = APIClient(enforce_csrf_checks=True, HTTP_HOST="localhost")

    def csrf(self, *, secure=False):
        response = self.client.get("/api/auth/csrf/", secure=secure)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        return response.data["csrfToken"]

    def post(self, url, data=None, *, secure=False, **headers):
        headers.setdefault("HTTP_X_CSRFTOKEN", self.csrf(secure=secure))
        if secure:
            headers.setdefault("HTTP_ORIGIN", "https://localhost")
        return self.client.post(
            url, data or {}, format="json", secure=secure, **headers
        )

    def login(self, *, secure=False, **data):
        credentials = {"email": self.user.email, "password": self.password}
        credentials.update(data)
        return self.post("/api/auth/login/", credentials, secure=secure)

    def logged_in(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        return response

    def test_login_email_roles_and_no_tokens_in_json_or_session(self):
        response = self.login(email="STUDENT@EXAMPLE.COM")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["user"]["email"], self.user.email)
        self.assertEqual(response.data["user"]["roles"], [Role.STUDENT])
        self.assertTrue(set(response.data) == {"user", "csrfToken"})
        self.assertFalse(settings.SESSION_COOKIE_NAME in response.cookies)
        for name in (settings.JWT_ACCESS_COOKIE, settings.JWT_REFRESH_COOKIE):
            self.assertFalse(response.cookies[name].value.encode() in response.content)
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 200)

    def test_wrong_password_and_unknown_email_have_same_generic_error(self):
        wrong = self.login(password=secrets.token_urlsafe(24))
        unknown = self.login(email="unknown@example.com")
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(unknown.status_code, 401)
        self.assertTrue(wrong.data == unknown.data)
        self.assertFalse(settings.JWT_ACCESS_COOKIE in wrong.cookies)
        self.assertFalse(settings.JWT_REFRESH_COOKIE in wrong.cookies)

    def test_inactive_user_cannot_login(self):
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        response = self.login()
        self.assertEqual(response.status_code, 401)
        self.assertFalse(settings.JWT_ACCESS_COOKIE in response.cookies)

    def test_invalid_input_returns_400_without_secrets(self):
        response = self.login(email="not-an-email")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.password.encode() in response.content)

    def test_me_without_jwt_returns_401(self):
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 401)
        self.assertTrue(response["WWW-Authenticate"].startswith("JWT"))

    def test_django_session_does_not_authenticate_api(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)
        self.assertEqual(self.post("/api/test-write/").status_code, 401)

    def test_authorization_header_alone_does_not_authenticate_cookie_api(self):
        self.logged_in()
        access = self.client.cookies[settings.JWT_ACCESS_COOKIE].value
        self.client.cookies.clear()
        response = self.client.get(
            "/api/auth/me/", HTTP_AUTHORIZATION=f"Bearer {access}"
        )
        self.assertEqual(response.status_code, 401)

    def test_tampered_or_malformed_access_token_is_rejected(self):
        self.logged_in()
        raw = self.client.cookies[settings.JWT_ACCESS_COOKIE].value
        parts = raw.split(".")
        parts[2] = ("A" if parts[2][0] != "A" else "B") + parts[2][1:]
        for value in ("malformed", ".".join(parts)):
            with self.subTest(kind="invalid access"):
                self.client.cookies[settings.JWT_ACCESS_COOKIE] = value
                self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)

    def test_wrong_key_none_algorithm_and_wrong_audience_are_rejected(self):
        self.logged_in()
        payload = AccessToken(
            self.client.cookies[settings.JWT_ACCESS_COOKIE].value
        ).payload
        candidates = (
            jwt.encode(payload, secrets.token_urlsafe(48), algorithm="HS256"),
            jwt.encode(payload, "", algorithm="none"),
            jwt.encode(
                payload | {"aud": "another-app"},
                settings.JWT_SIGNING_KEY,
                algorithm="HS256",
            ),
            jwt.encode(
                payload | {"iss": "another-issuer"},
                settings.JWT_SIGNING_KEY,
                algorithm="HS256",
            ),
        )
        for token in candidates:
            self.client.cookies[settings.JWT_ACCESS_COOKIE] = token
            self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)

    def test_expired_access_token_is_rejected(self):
        self.logged_in()
        token = AccessToken(self.client.cookies[settings.JWT_ACCESS_COOKIE].value)
        token.set_exp(lifetime=timedelta(seconds=-1))
        self.client.cookies[settings.JWT_ACCESS_COOKIE] = str(token)
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)

    def test_refresh_cannot_be_used_as_access(self):
        self.logged_in()
        self.client.cookies[settings.JWT_ACCESS_COOKIE] = self.client.cookies[
            settings.JWT_REFRESH_COOKIE
        ].value
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)

    def test_cookie_flags_http_localhost_and_expiration(self):
        response = self.logged_in()
        for name, path, seconds in (
            (settings.JWT_ACCESS_COOKIE, "/api/", 300),
            (settings.JWT_REFRESH_COOKIE, "/api/auth/", 86400),
        ):
            cookie = response.cookies[name]
            self.assertTrue(cookie["httponly"])
            self.assertFalse(cookie["secure"])
            self.assertEqual(cookie["samesite"], "Lax")
            self.assertEqual(cookie["path"], path)
            self.assertEqual(cookie["domain"], "")
            self.assertEqual(cookie["max-age"], seconds)
            self.assertTrue(bool(cookie["expires"]))

    def test_https_debug_still_sets_secure_jwt_cookies(self):
        response = self.login(secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.cookies[settings.JWT_ACCESS_COOKIE]["secure"])
        self.assertTrue(response.cookies[settings.JWT_REFRESH_COOKIE]["secure"])

    @override_settings(DEBUG=False, CSRF_COOKIE_SECURE=True)
    def test_production_requires_https_and_sets_secure_cookies(self):
        response = self.client.get("/api/auth/csrf/")
        self.assertEqual(response.status_code, 403)
        response = self.login(secure=True)
        self.assertEqual(response.status_code, 200)
        for name in (
            settings.JWT_ACCESS_COOKIE,
            settings.JWT_REFRESH_COOKIE,
            settings.CSRF_COOKIE_NAME,
        ):
            self.assertTrue(response.cookies[name]["secure"])

    @override_settings(DEBUG=False, SECURE_SSL_REDIRECT=True)
    def test_production_http_is_redirected_to_https(self):
        response = self.client.get("/dang-nhap/")
        self.assertEqual(response.status_code, 301)
        self.assertTrue(response["Location"].startswith("https://"))

    def test_debug_does_not_allow_insecure_remote_host(self):
        response = self.client.get("/api/auth/csrf/", HTTP_HOST="evil.example")
        self.assertEqual(response.status_code, 403)

    def test_login_requires_csrf_even_when_anonymous(self):
        response = self.client.post(
            "/api/auth/login/",
            {"email": self.user.email, "password": self.password},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(BlacklistedToken.objects.exists())

    def test_csrf_cookie_alone_is_not_sufficient(self):
        self.csrf()
        response = self.client.post(
            "/api/auth/login/",
            {"email": self.user.email, "password": self.password},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_csrf_header_without_cookie_is_not_sufficient(self):
        token = self.csrf()
        self.client.cookies.clear()
        response = self.client.post(
            "/api/auth/login/",
            {"email": self.user.email, "password": self.password},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(response.status_code, 403)

    def test_wrong_csrf_and_untrusted_origin_are_rejected(self):
        response = self.post(
            "/api/auth/login/",
            {"email": self.user.email, "password": self.password},
            HTTP_X_CSRFTOKEN=secrets.token_hex(16),
        )
        self.assertEqual(response.status_code, 403)
        response = self.post(
            "/api/auth/login/",
            {"email": self.user.email, "password": self.password},
            HTTP_ORIGIN="https://evil.example",
        )
        self.assertEqual(response.status_code, 403)

    def test_https_referer_is_checked_without_origin(self):
        token = self.csrf(secure=True)
        data = {"email": self.user.email, "password": self.password}
        response = self.client.post(
            "/api/auth/login/",
            data,
            format="json",
            secure=True,
            HTTP_X_CSRFTOKEN=token,
            HTTP_REFERER="https://evil.example/",
        )
        self.assertEqual(response.status_code, 403)

    def test_login_rotates_csrf_secret(self):
        self.csrf()
        old = self.client.cookies[settings.CSRF_COOKIE_NAME].value
        self.logged_in()
        self.assertTrue(self.client.cookies[settings.CSRF_COOKIE_NAME].value != old)

    def test_protected_write_requires_jwt_and_csrf_before_mutation(self):
        self.assertEqual(self.post("/api/test-write/").status_code, 401)
        self.logged_in()
        response = self.client.post("/api/test-write/", {}, format="json")
        self.assertEqual(response.status_code, 403)
        self.user.refresh_from_db()
        self.assertEqual(self.user.full_name, "Sinh viên kiểm thử")
        self.assertEqual(self.post("/api/test-write/").status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.full_name, "Tên đã cập nhật")

    def test_refresh_and_logout_missing_csrf_do_not_revoke(self):
        self.logged_in()
        for url in ("/api/auth/refresh/", "/api/auth/logout/"):
            response = self.client.post(url, {}, format="json")
            self.assertEqual(response.status_code, 403)
            self.assertFalse(settings.JWT_ACCESS_COOKIE in response.cookies)
        self.assertFalse(BlacklistedToken.objects.exists())

    def test_refresh_rotates_and_old_refresh_is_rejected(self):
        self.logged_in()
        old = self.client.cookies[settings.JWT_REFRESH_COOKIE].value
        old_jti = RefreshToken(old)["jti"]
        response = self.post("/api/auth/refresh/")
        self.assertEqual(response.status_code, 200)
        new = self.client.cookies[settings.JWT_REFRESH_COOKIE].value
        self.assertTrue(old != new)
        self.assertTrue(BlacklistedToken.objects.filter(token__jti=old_jti).exists())
        self.assertFalse(any(key in response.data for key in ("access", "refresh")))
        self.client.cookies[settings.JWT_REFRESH_COOKIE] = old
        self.assertEqual(self.post("/api/auth/refresh/").status_code, 401)
        self.client.cookies[settings.JWT_REFRESH_COOKIE] = new
        self.assertEqual(self.post("/api/auth/refresh/").status_code, 200)

    def test_refresh_works_when_access_expired(self):
        self.logged_in()
        access = AccessToken(self.client.cookies[settings.JWT_ACCESS_COOKIE].value)
        access.set_exp(lifetime=timedelta(seconds=-1))
        self.client.cookies[settings.JWT_ACCESS_COOKIE] = str(access)
        self.assertEqual(self.post("/api/auth/refresh/").status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 200)

    def test_missing_expired_or_access_token_as_refresh_is_rejected(self):
        self.assertEqual(self.post("/api/auth/refresh/").status_code, 401)
        self.logged_in()
        old = self.client.cookies[settings.JWT_REFRESH_COOKIE].value
        token = RefreshToken(old)
        token.set_exp(lifetime=timedelta(seconds=-1))
        for raw in (
            str(token),
            self.client.cookies[settings.JWT_ACCESS_COOKIE].value,
            "malformed",
        ):
            self.client.cookies[settings.JWT_REFRESH_COOKIE] = raw
            self.assertEqual(self.post("/api/auth/refresh/").status_code, 401)

    def test_locked_user_cannot_use_access_or_refresh(self):
        self.logged_in()
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)
        self.assertEqual(self.post("/api/auth/refresh/").status_code, 401)

    def test_changed_password_revokes_access_and_refresh(self):
        self.logged_in()
        self.user.set_password(secrets.token_urlsafe(24))
        self.user.save()
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)
        self.assertEqual(self.post("/api/auth/refresh/").status_code, 401)

    def test_deleted_user_cannot_refresh(self):
        self.logged_in()
        self.user.delete()
        self.assertEqual(self.post("/api/auth/refresh/").status_code, 401)

    def test_logout_clears_cookies_revokes_refresh_and_access_limit_is_explicit(self):
        self.logged_in()
        access = self.client.cookies[settings.JWT_ACCESS_COOKIE].value
        refresh = self.client.cookies[settings.JWT_REFRESH_COOKIE].value
        jti = RefreshToken(refresh)["jti"]
        response = self.post("/api/auth/logout/")
        self.assertEqual(response.status_code, 204)
        for name, path in (
            (settings.JWT_ACCESS_COOKIE, "/api/"),
            (settings.JWT_REFRESH_COOKIE, "/api/auth/"),
        ):
            self.assertEqual(response.cookies[name]["max-age"], 0)
            self.assertEqual(response.cookies[name]["path"], path)
            self.assertTrue(response.cookies[name].value == "")
            self.assertTrue(response.cookies[name]["httponly"])
        self.assertTrue(BlacklistedToken.objects.filter(token__jti=jti).exists())
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)
        self.client.cookies[settings.JWT_REFRESH_COOKIE] = refresh
        self.assertEqual(self.post("/api/auth/refresh/").status_code, 401)
        # A previously copied access token remains valid until its five-minute exp.
        self.client.cookies[settings.JWT_ACCESS_COOKIE] = access
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 200)

    def test_logout_is_idempotent_and_accepts_expired_access(self):
        self.assertEqual(self.post("/api/auth/logout/").status_code, 204)
        self.logged_in()
        self.client.cookies[settings.JWT_ACCESS_COOKIE] = "expired-or-malformed"
        self.assertEqual(self.post("/api/auth/logout/").status_code, 204)
        self.assertEqual(self.post("/api/auth/logout/").status_code, 204)

    def test_login_replaces_and_revokes_previous_refresh(self):
        self.logged_in()
        old_jti = RefreshToken(self.client.cookies[settings.JWT_REFRESH_COOKIE].value)[
            "jti"
        ]
        self.logged_in()
        self.assertTrue(BlacklistedToken.objects.filter(token__jti=old_jti).exists())

    def test_user_roles_are_read_live_from_groups(self):
        self.logged_in()
        self.user.groups.clear()
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.data["roles"], [])

    def test_login_page_and_existing_catalog_remain_accessible(self):
        response = self.client.get("/dang-nhap/?next=https://evil.example")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="login-form"')
        self.assertContains(response, 'autocomplete="current-password"')
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_login_throttle_returns_429(self):
        for _ in range(10):
            response = self.login(password=secrets.token_urlsafe(24))
            self.assertEqual(response.status_code, 401)
        self.assertEqual(self.login().status_code, 429)

    def test_spoofed_forwarded_for_cannot_bypass_login_throttle(self):
        credentials = {
            "email": self.user.email,
            "password": secrets.token_urlsafe(24),
        }
        for index in range(11):
            response = self.post(
                "/api/auth/login/",
                credentials,
                HTTP_X_FORWARDED_FOR=f"198.51.100.{index}",
            )
            self.assertEqual(response.status_code, 401 if index < 10 else 429)


class ProductionSettingsTests(SimpleTestCase):
    def test_production_settings_enforce_https_and_secure_cookies(self):
        with patch.dict(
            os.environ,
            {"DJANGO_DEBUG": "False", "JWT_SIGNING_KEY": secrets.token_urlsafe(48)},
        ):
            config = runpy.run_path(Path(settings.BASE_DIR) / "config" / "settings.py")
        self.assertTrue(config["SECURE_SSL_REDIRECT"])
        self.assertTrue(config["SESSION_COOKIE_SECURE"])
        self.assertTrue(config["CSRF_COOKIE_SECURE"])

    def test_production_cannot_silently_reuse_django_key(self):
        with patch.dict(os.environ, {"DJANGO_DEBUG": "False", "JWT_SIGNING_KEY": ""}):
            with self.assertRaises(ImproperlyConfigured):
                runpy.run_path(Path(settings.BASE_DIR) / "config" / "settings.py")


class RefreshConcurrencyTests(TransactionTestCase):
    def test_simultaneous_refresh_requests_have_only_one_winner(self):
        user = User.objects.create_user(
            "race@example.com", full_name="Kiểm thử cạnh tranh"
        )
        raw = str(RefreshToken.for_user(user))
        barrier = Barrier(2)

        def worker():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                rotate_refresh(raw)
                return "issued"
            except APIException:
                return "rejected"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: worker(), range(2)))
        self.assertEqual(results.count("issued"), 1)
        self.assertEqual(results.count("rejected"), 1)
