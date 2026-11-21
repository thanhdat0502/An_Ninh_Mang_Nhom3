"""Local HTTP smoke test. Cookies/passwords stay in memory and are never printed."""

import argparse
import copy
import json
import os
from http.cookiejar import CookieJar
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

from dotenv import load_dotenv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    target = urlsplit(base)
    if target.scheme != "http" or target.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise RuntimeError("Smoke test chỉ chạy trên HTTP loopback cục bộ.")
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    if os.getenv("DJANGO_DEBUG", "False").lower() not in {"true", "1"}:
        raise RuntimeError("Smoke test HTTP cần DEBUG=True.")
    password = os.getenv("DEMO_STUDENT_PASSWORD")
    if not password:
        raise RuntimeError("Thiếu DEMO_STUDENT_PASSWORD.")
    jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))

    def request(path, *, data=None, csrf=None):
        headers = {"Accept": "application/json"}
        body = None
        if data is not None:
            headers["Content-Type"] = "application/json"
            headers["Origin"] = base
            body = json.dumps(data).encode()
        if csrf:
            headers["X-CSRFToken"] = csrf
        req = Request(base + path, data=body, headers=headers)
        try:
            response = opener.open(req, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.read(), response.headers

    def expect(label, result, expected):
        if result[0] != expected:
            raise RuntimeError(f"{label}: HTTP {result[0]}, expected {expected}")
        print(f"PASS {label}: HTTP {expected}")

    def csrf():
        result = request("/api/auth/csrf/")
        if result[0] != 200:
            raise RuntimeError("Không lấy được CSRF.")
        return json.loads(result[1])["csrfToken"]

    logged_in = False
    try:
        expect("health", request("/health/"), 200)
        expect("catalog", request("/"), 200)
        expect("login page", request("/dang-nhap/"), 200)
        expect("anonymous me", request("/api/auth/me/"), 401)
        credentials = {"email": "student@khcn.example", "password": password}
        expect("login without CSRF", request("/api/auth/login/", data=credentials), 403)
        result = request("/api/auth/login/", data=credentials, csrf=csrf())
        expect("login", result, 200)
        logged_in = True
        payload = json.loads(result[1])
        if any(key in payload for key in ("access", "refresh")):
            raise RuntimeError("JWT unexpectedly returned in JSON.")
        cookies = SimpleCookie()
        for header in result[2].get_all("Set-Cookie", []):
            cookies.load(header)
        for name in ("khcn_access", "khcn_refresh"):
            if (
                not cookies[name]["httponly"]
                or cookies[name]["secure"]
                or cookies[name]["samesite"] != "Lax"
            ):
                raise RuntimeError("Unexpected cookie security flags.")
        print("PASS JWT cookies: HttpOnly, SameSite=Lax, localhost HTTP policy")
        expect("authenticated me", request("/api/auth/me/"), 200)
        expect("refresh without CSRF", request("/api/auth/refresh/", data={}), 403)
        expect("refresh", request("/api/auth/refresh/", data={}, csrf=csrf()), 200)
        previous = next(
            copy.copy(cookie) for cookie in jar if cookie.name == "khcn_refresh"
        )
        expect("logout without CSRF", request("/api/auth/logout/", data={}), 403)
        expect("logout", request("/api/auth/logout/", data={}, csrf=csrf()), 204)
        logged_in = False
        expect("me after logout", request("/api/auth/me/"), 401)
        jar.set_cookie(previous)
        expect(
            "revoked refresh replay",
            request("/api/auth/refresh/", data={}, csrf=csrf()),
            401,
        )
        print("HTTP smoke: PASS; no credentials or token values displayed.")
    finally:
        if logged_in:
            request("/api/auth/logout/", data={}, csrf=csrf())
        jar.clear()


if __name__ == "__main__":
    main()
