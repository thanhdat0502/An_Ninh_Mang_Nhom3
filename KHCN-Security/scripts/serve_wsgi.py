"""Private WSGI upstream for the local Caddy HTTPS demo, never a public port."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings_https"
    from django.conf import settings
    from waitress import serve

    from config.wsgi import application

    if settings.DEBUG or not settings.SESSION_COOKIE_SECURE:
        raise RuntimeError("WSGI HTTPS demo cần cấu hình triển khai an toàn.")
    serve(
        application,
        host="127.0.0.1",
        port=8003,
        threads=4,
        trusted_proxy="127.0.0.1",
        trusted_proxy_count=1,
        trusted_proxy_headers={"x-forwarded-proto"},
        clear_untrusted_proxy_headers=True,
        max_request_body_size=128 * 1024,
        max_request_header_size=16384,
        channel_timeout=30,
        ident="",
    )


if __name__ == "__main__":
    main()
