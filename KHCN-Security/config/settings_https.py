"""Local HTTPS deployment: Caddy terminates TLS; Waitress normalizes its scheme.

Use explicitly with --settings=config.settings_https. Development settings and
secrets in .env are unchanged. This profile binds only loopback, not the Internet.
"""

import os

from django.core.exceptions import ImproperlyConfigured
from dotenv import dotenv_values

from .settings import *  # noqa: F403
from .settings import BASE_DIR, MIDDLEWARE, SIMPLE_JWT

_https_env = dotenv_values(BASE_DIR / ".env.https")


def https_secret(name):
    value = os.environ.get(name) or _https_env.get(name) or ""
    if len(value) < 50 or len(set(value)) < 10:
        raise ImproperlyConfigured(
            f"{name} cần giá trị ngẫu nhiên riêng, ít nhất 50 ký tự."
        )
    return value


DEBUG = False
SECRET_KEY = https_secret("KHCN_HTTPS_SECRET_KEY")
JWT_SIGNING_KEY = https_secret("KHCN_HTTPS_JWT_SIGNING_KEY")
if SECRET_KEY == JWT_SIGNING_KEY:
    raise ImproperlyConfigured("Hai khóa HTTPS phải độc lập.")
SIMPLE_JWT = {**SIMPLE_JWT, "SIGNING_KEY": JWT_SIGNING_KEY}

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
CSRF_TRUSTED_ORIGINS = ["https://localhost:8443", "https://127.0.0.1:8443"]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_DOMAIN = None
CSRF_COOKIE_DOMAIN = None
# Separate names: localhost cookies are not isolated by TCP port. Keep the
# HTTP development session usable without collisions with the HTTPS profile.
SESSION_COOKIE_NAME = "__Host-khcn_sessionid"
CSRF_COOKIE_NAME = "__Host-khcn_csrftoken"
JWT_ACCESS_COOKIE = "__Secure-khcn_access"
JWT_REFRESH_COOKIE = "__Secure-khcn_refresh"

SECURE_SSL_REDIRECT = True
SECURE_SSL_HOST = "localhost:8443"
# Waitress trusts ONLY the immediate loopback proxy's X-Forwarded-Proto and
# converts it into wsgi.url_scheme. Django never trusts raw forwarded headers.
SECURE_PROXY_SSL_HEADER = None
USE_X_FORWARDED_HOST = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
DATA_UPLOAD_MAX_MEMORY_SIZE = 128 * 1024
MIDDLEWARE = ["core.middleware.SecurityHeadersMiddleware", *MIDDLEWARE]
