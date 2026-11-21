"""Live HTTPS adversarial checks on a newly created, isolated PostgreSQL DB.

Never edits existing business data. Cookies, JWTs and credentials stay in memory.
Starts its own loopback Caddy/Waitress and removes only its own test database.
"""

import copy
import json
import os
import secrets
import sys
import time
from datetime import timedelta
from http.cookiejar import CookieJar
from http.cookies import SimpleCookie
from io import StringIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import (
    HTTPCookieProcessor,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings_https"

from scripts.check_tls import NoRedirect, trusted_context, verify_tls  # noqa: E402
from scripts.serve_https_demo import check_ports, running_servers  # noqa: E402

BASE = "https://127.0.0.1:8443"
EVIDENCE = ROOT / ".runtime/evidence/https-security.json"


class HTTPSClient:
    def __init__(self):
        self.jar = CookieJar()
        self.opener = build_opener(
            ProxyHandler({}),
            HTTPSHandler(context=trusted_context()),
            HTTPCookieProcessor(self.jar),
            NoRedirect(),
        )
        self.private_values = []

    def call(self, path, method="GET", data=None, *, csrf=True, headers=None):
        if not path.startswith("/api/") and method != "GET":
            raise RuntimeError("Unsafe request outside the local API refused.")
        request_headers = {"Accept": "application/json", **(headers or {})}
        body = None
        if method not in ("GET", "HEAD", "OPTIONS"):
            request_headers.setdefault("Origin", BASE)
            if csrf:
                response = self.call("/api/auth/csrf/")
                request_headers["X-CSRFToken"] = json.loads(response[1])["csrfToken"]
            if data is not None:
                request_headers["Content-Type"] = "application/json"
                body = json.dumps(data).encode()
        request = Request(
            BASE + path, data=body, headers=request_headers, method=method
        )
        try:
            response = self.opener.open(request, timeout=15)
        except HTTPError as error:
            response = error
        with response:
            result = response.status, response.read(512 * 1024), response.headers
        self.private_values.extend(cookie.value for cookie in self.jar)
        return result

    def cookie(self, name):
        return copy.copy(next(cookie for cookie in self.jar if cookie.name == name))


class Evidence:
    def __init__(self):
        self.rows = []

    def expect(self, label, response, status):
        self.rows.append(
            {
                "case": label,
                "expected": status,
                "actual": response[0],
                "pass": response[0] == status,
            }
        )
        if response[0] != status:
            raise RuntimeError(label)
        print(f"PASS {label}: HTTP {status}", flush=True)
        return (
            json.loads(response[1])
            if response[1] and "application/json" in response[2].get("Content-Type", "")
            else None
        )

    def check(self, label, condition):
        self.rows.append(
            {
                "case": label,
                "expected": True,
                "actual": bool(condition),
                "pass": bool(condition),
            }
        )
        if not condition:
            raise RuntimeError(label)
        print(f"PASS {label}", flush=True)

    def save(self, complete=False):
        EVIDENCE.parent.mkdir(exist_ok=True)
        EVIDENCE.write_text(
            json.dumps({"complete": complete, "cases": self.rows}, indent=2),
            encoding="utf-8",
        )


def snapshot(models):
    # Only compared in memory; no record/password/hash contents enter evidence.
    return [list(model.objects.order_by("pk").values()) for model in models]


def run_cases(evidence):
    from django.conf import settings
    from django.contrib.auth.models import Group
    from django.utils import timezone
    from rest_framework_simplejwt.tokens import AccessToken

    from accounts.models import Role, User
    from core.demo_data import DEMO_ACCOUNTS
    from registrations.models import Registration
    from topics.models import Topic

    clients, users, passwords = {}, {}, {}
    for email, _, role, variable in DEMO_ACCOUNTS:
        users[role] = User.objects.get(email=email)
        passwords[role] = os.environ[variable]
        clients[role] = HTTPSClient()
    admin, lecturer, student = (
        clients[role] for role in (Role.ADMIN, Role.LECTURER, Role.STUDENT)
    )
    anonymous = HTTPSClient()
    evidence.expect("anonymous protected API", anonymous.call("/api/topics/"), 401)
    bad_credentials = {
        "email": users[Role.STUDENT].email,
        "password": secrets.token_urlsafe(32),
    }
    evidence.expect(
        "wrong login password",
        anonymous.call("/api/auth/login/", "POST", bad_credentials),
        401,
    )
    evidence.expect(
        "login requires CSRF",
        anonymous.call("/api/auth/login/", "POST", bad_credentials, csrf=False),
        403,
    )

    for role, client in clients.items():
        credentials = {"email": users[role].email, "password": passwords[role]}
        response = client.call("/api/auth/login/", "POST", credentials)
        data = evidence.expect(f"{role} valid login", response, 200)
        evidence.check(
            f"{role} JSON contains no JWT", not ({"access", "refresh"} & set(data))
        )
        cookies = SimpleCookie()
        for header in response[2].get_all("Set-Cookie", []):
            cookies.load(header)
        evidence.check(
            f"{role} JWT Secure/HttpOnly/SameSite/path policy",
            all(
                cookies[name]["secure"]
                and cookies[name]["httponly"]
                and cookies[name]["samesite"] == "Lax"
                and cookies[name]["path"] == path
                and not cookies[name]["domain"]
                for name, path in (
                    (settings.JWT_ACCESS_COOKIE, "/api/"),
                    (settings.JWT_REFRESH_COOKIE, "/api/auth/"),
                )
            ),
        )
    response = student.call("/api/auth/me/")
    evidence.expect("valid JWT business authentication", response, 200)
    evidence.check(
        "HTTPS response security headers",
        all(
            response[2].get(name) == value
            for name, value in {
                "X-Frame-Options": "DENY",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "same-origin",
                "Cross-Origin-Opener-Policy": "same-origin",
            }.items()
        )
        and "frame-ancestors 'none'" in response[2].get("Content-Security-Policy", ""),
    )
    evidence.expect(
        "client proxy headers cannot downgrade HTTPS",
        student.call(
            "/api/auth/me/",
            headers={
                "X-Forwarded-Proto": "http",
                "Forwarded": "proto=http;host=evil.example",
                "X-Forwarded-Host": "evil.example",
            },
        ),
        200,
    )
    original_access = student.cookie(settings.JWT_ACCESS_COOKIE)
    expired = AccessToken.for_user(users[Role.STUDENT])
    expired.set_exp(
        from_time=timezone.now() - timedelta(minutes=10), lifetime=timedelta(seconds=1)
    )
    token_cookie = copy.copy(original_access)
    token_cookie.value = str(expired)
    student.private_values.append(token_cookie.value)
    student.jar.set_cookie(token_cookie)
    evidence.expect("expired signed JWT rejected", student.call("/api/auth/me/"), 401)
    token_cookie.value = original_access.value.rsplit(".", 1)[0] + "." + ("A" * 43)
    student.private_values.append(token_cookie.value)
    student.jar.set_cookie(token_cookie)
    evidence.expect(
        "tampered JWT signature rejected", student.call("/api/auth/me/"), 401
    )
    student.jar.set_cookie(original_access)
    forged_role = AccessToken.for_user(users[Role.STUDENT])
    forged_role["role"] = "ADMIN"
    forged_role["roles"] = ["ADMIN"]
    token_cookie.value = str(forged_role)
    student.private_values.append(token_cookie.value)
    student.jar.set_cookie(token_cookie)
    evidence.expect(
        "signed role claims cannot grant Admin access",
        student.call("/api/accounts/"),
        403,
    )
    student.jar.set_cookie(original_access)
    User.objects.filter(pk=users[Role.STUDENT].pk).update(is_active=False)
    evidence.expect(
        "inactive user valid JWT rejected", student.call("/api/topics/"), 401
    )
    User.objects.filter(pk=users[Role.STUDENT].pk).update(is_active=True)

    topic_data = {
        "code": "TLS-CRUD",
        "title": "Topic TLS",
        "description": "Only in isolated test database.",
        "lecturer": users[Role.LECTURER].pk,
        "status": "OPEN",
    }
    count = Topic.objects.count()
    evidence.expect(
        "Admin create requires CSRF",
        admin.call("/api/topics/", "POST", topic_data, csrf=False),
        403,
    )
    evidence.check("missing CSRF did not create topic", Topic.objects.count() == count)
    topic = evidence.expect(
        "Admin creates topic", admin.call("/api/topics/", "POST", topic_data), 201
    )
    url = f"/api/topics/{topic['id']}/"
    evidence.expect(
        "Admin edits topic",
        admin.call(url, "PATCH", {"title": "Updated TLS topic"}),
        200,
    )
    evidence.expect(
        "duplicate topic code rejected",
        admin.call("/api/topics/", "POST", topic_data),
        400,
    )
    evidence.expect(
        "Student cannot create topic",
        student.call("/api/topics/", "POST", {**topic_data, "code": "TLS-DENIED"}),
        403,
    )
    evidence.expect(
        "Student cannot edit topic",
        student.call(url, "PATCH", {"title": "Denied"}),
        403,
    )
    evidence.expect("Student cannot delete topic", student.call(url, "DELETE"), 403)
    evidence.expect(
        "Lecturer cannot administer topic",
        lecturer.call(url, "PATCH", {"title": "Denied"}),
        403,
    )
    evidence.expect(
        "Student cannot manage accounts", student.call("/api/accounts/"), 403
    )
    evidence.expect(
        "Student cannot set own role",
        student.call(
            f"/api/accounts/{users[Role.STUDENT].pk}/", "PATCH", {"roles": ["ADMIN"]}
        ),
        403,
    )
    evidence.expect(
        "Admin account mass assignment rejected",
        admin.call(
            f"/api/accounts/{users[Role.STUDENT].pk}/", "PATCH", {"is_superuser": True}
        ),
        400,
    )
    evidence.check(
        "Student server role unchanged",
        list(users[Role.STUDENT].groups.values_list("name", flat=True))
        == [Role.STUDENT],
    )

    evidence.expect(
        "Student registration requires CSRF",
        student.call("/api/registrations/", "POST", {"topic": topic["id"]}, csrf=False),
        403,
    )
    registration = evidence.expect(
        "Student registers as own identity",
        student.call("/api/registrations/", "POST", {"topic": topic["id"]}),
        201,
    )
    evidence.check(
        "registration identity taken from server user",
        registration["student"] == users[Role.STUDENT].pk
        and registration["status"] == "PENDING",
    )
    evidence.expect(
        "duplicate registration rejected",
        student.call("/api/registrations/", "POST", {"topic": topic["id"]}),
        409,
    )
    reg_url = f"/api/registrations/{registration['id']}/"
    evidence.expect(
        "Student cannot approve own registration",
        student.call(reg_url + "approve/", "POST", {}),
        403,
    )
    evidence.expect(
        "review requires CSRF",
        lecturer.call(reg_url + "approve/", "POST", {}, csrf=False),
        403,
    )
    evidence.expect(
        "cross-origin review rejected",
        lecturer.call(
            reg_url + "approve/", "POST", {}, headers={"Origin": "https://evil.example"}
        ),
        403,
    )
    evidence.check(
        "denied review kept PENDING",
        Registration.objects.get(pk=registration["id"]).status == "PENDING",
    )
    approved = evidence.expect(
        "assigned Lecturer approves",
        lecturer.call(reg_url + "approve/", "POST", {}),
        200,
    )
    evidence.check(
        "review audit is server controlled",
        approved["reviewed_by"] == users[Role.LECTURER].pk
        and bool(approved["reviewed_at"]),
    )
    evidence.expect(
        "second decision rejected", lecturer.call(reg_url + "reject/", "POST", {}), 409
    )
    evidence.expect(
        "registered topic protected from deletion", admin.call(url, "DELETE"), 409
    )

    outsiders = []
    for role in (Role.STUDENT, Role.LECTURER):
        password = secrets.token_urlsafe(32)
        outsider = User.objects.create_user(
            f"other-{role.lower()}@example.com",
            password,
            full_name="Isolated test user",
        )
        outsider.groups.add(Group.objects.get(name=role))
        client = HTTPSClient()
        outsiders.append((client, password))
        evidence.expect(
            f"other {role} login",
            client.call(
                "/api/auth/login/",
                "POST",
                {"email": outsider.email, "password": password},
            ),
            200,
        )
        evidence.expect(f"{role} IDOR detail denied", client.call(reg_url), 404)
        listing = evidence.expect(
            f"{role} scoped registration list", client.call("/api/registrations/"), 200
        )
        evidence.check(f"{role} scoped count hides other record", listing["count"] == 0)
        if role == Role.LECTURER:
            evidence.expect(
                "out-of-scope Lecturer review denied",
                client.call(reg_url + "reject/", "POST", {}),
                404,
            )

    empty = evidence.expect(
        "Admin creates disposable topic",
        admin.call("/api/topics/", "POST", {**topic_data, "code": "TLS-DELETE"}),
        201,
    )
    evidence.expect(
        "Admin deletes unreferenced topic",
        admin.call(f"/api/topics/{empty['id']}/", "DELETE"),
        204,
    )
    injected = evidence.expect(
        "SQL injection treated as search text",
        student.call("/api/topics/?" + urlencode({"search": "' OR 1=1 --"})),
        200,
    )
    evidence.check("SQL injection did not widen results", injected["count"] == 0)
    xss = '<img src=x onerror="alert(1)">'
    evidence.expect(
        "create plain-text XSS fixture",
        admin.call(
            "/api/topics/", "POST", {**topic_data, "code": "TLS-XSS", "title": xss}
        ),
        201,
    )
    html = anonymous.call("/?q=TLS-XSS")
    evidence.check(
        "public HTML escapes stored XSS",
        html[0] == 200 and xss.encode() not in html[1] and b"&lt;img" in html[1],
    )
    cors = anonymous.call("/api/auth/csrf/", headers={"Origin": "https://evil.example"})
    evidence.check(
        "CORS does not grant foreign origin credentials",
        "Access-Control-Allow-Origin" not in cors[2]
        and "Access-Control-Allow-Credentials" not in cors[2],
    )
    # Test the API's 64 KiB contract, below the separate edge/WSGI 128 KiB limit.
    oversized = admin.call("/api/topics/", "POST", {"description": "a" * 66000})
    evidence.expect("oversized JSON rejected by API parser", oversized, 413)
    evidence.expect("private environment file not served", anonymous.call("/.env"), 404)
    evidence.expect(
        "private key path not served", anonymous.call("/.runtime/tls/server.key"), 404
    )

    old_refresh = student.cookie(settings.JWT_REFRESH_COOKIE)
    evidence.expect(
        "refresh requires CSRF",
        student.call("/api/auth/refresh/", "POST", {}, csrf=False),
        403,
    )
    evidence.expect(
        "refresh rotates", student.call("/api/auth/refresh/", "POST", {}), 200
    )
    rotated = student.cookie(settings.JWT_REFRESH_COOKIE)
    student.jar.set_cookie(old_refresh)
    evidence.expect(
        "rotated refresh replay rejected",
        student.call("/api/auth/refresh/", "POST", {}),
        401,
    )
    student.jar.set_cookie(rotated)
    last_access = student.cookie(settings.JWT_ACCESS_COOKIE)
    evidence.expect(
        "logout requires CSRF",
        student.call("/api/auth/logout/", "POST", {}, csrf=False),
        403,
    )
    evidence.expect(
        "logout clears cookies", student.call("/api/auth/logout/", "POST", {}), 204
    )
    evidence.check(
        "JWT cookies absent after logout",
        not any(
            cookie.name in {settings.JWT_ACCESS_COOKIE, settings.JWT_REFRESH_COOKIE}
            for cookie in student.jar
        ),
    )
    evidence.expect(
        "me without cookies after logout", student.call("/api/auth/me/"), 401
    )
    student.jar.set_cookie(rotated)
    evidence.expect(
        "logout refresh replay rejected",
        student.call("/api/auth/refresh/", "POST", {}),
        401,
    )
    student.jar.set_cookie(last_access)
    evidence.expect(
        "documented access lifetime after logout", student.call("/api/auth/me/"), 200
    )
    student.jar.clear()
    statuses = []
    for index in range(12):
        response = anonymous.call(
            "/api/auth/login/",
            "POST",
            bad_credentials,
            headers={"X-Forwarded-For": f"192.0.2.{index + 1}"},
        )
        statuses.append(response[0])
        if response[0] == 429:
            break
    evidence.check(
        "login throttling rejects spoofed IP rotation",
        statuses[-1] == 429 and all(status == 401 for status in statuses[:-1]),
    )
    values = [
        *passwords.values(),
        *[password for _, password in outsiders],
        settings.SECRET_KEY,
        settings.JWT_SIGNING_KEY,
    ]
    for client in [*clients.values(), anonymous, *[client for client, _ in outsiders]]:
        values.extend(client.private_values)
    for log in (ROOT / ".runtime").glob("*.log"):
        text = log.read_text(encoding="utf-8", errors="replace")
        evidence.check(
            f"no credential/JWT/key values in {log.name}",
            not any(value and value in text for value in values),
        )


def main():
    import django

    django.setup()
    check_ports()
    from django.core.management import call_command
    from django.db import connection

    from accounts.models import User
    from core.demo_data import DEMO_ACCOUNTS
    from registrations.models import Registration
    from topics.models import Topic

    evidence = Evidence()
    models = (User, Topic, Registration)
    original = snapshot(models)
    original_name = connection.settings_dict["NAME"]
    name = "khcn_tls_verify_" + secrets.token_hex(6)
    created = False
    complete = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", [name])
            if cursor.fetchone() or name == original_name:
                raise RuntimeError("Refusing to reuse/drop an existing database.")
        connection.settings_dict["TEST"]["NAME"] = name
        created = True  # Safe to clean this unique, previously absent name on failure.
        connection.creation.create_test_db(
            verbosity=0, autoclobber=False, serialize=False
        )
        for _, _, _, variable in DEMO_ACCOUNTS:
            os.environ[variable] = secrets.token_urlsafe(32)
        call_command("seed_demo", stdout=StringIO())
        with running_servers(database=name) as children:
            for _ in range(80):
                try:
                    if HTTPSClient().call("/health/")[0] == 200:
                        break
                except (URLError, ConnectionError):
                    pass
                if any(child.poll() is not None for child in children):
                    raise RuntimeError("Owned TLS server did not start.")
                time.sleep(0.25)
            else:
                raise RuntimeError("Owned TLS server readiness timed out.")
            verify_tls()
            run_cases(evidence)
        complete = True
    finally:
        if created:
            # Never derive a drop target from HTTP input or touch the original DB.
            connection.settings_dict["NAME"] = name
            connection.creation.destroy_test_db(original_name, verbosity=0)
        evidence.check(
            "original business records unchanged", snapshot(models) == original
        )
        evidence.save(complete=complete and all(row["pass"] for row in evidence.rows))
        print(
            "Owned test database removed; existing business records preserved.",
            flush=True,
        )
    print(
        f"HTTPS security checks: {len(evidence.rows)} PASS, 0 FAIL; no sensitive values in evidence."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(
            "HTTPS security verification FAILED. Review case names only; no secrets printed.",
            file=sys.stderr,
        )
        sys.exit(1)
