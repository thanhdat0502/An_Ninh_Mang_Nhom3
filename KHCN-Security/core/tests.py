import os
import secrets
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.models import Role
from core.demo_data import DEMO_ACCOUNTS, DEMO_TOPICS
from topics.models import Topic


def seed_passwords():
    return {variable: secrets.token_urlsafe(24) for _, _, _, variable in DEMO_ACCOUNTS}


class DemoSeedTests(TestCase):
    def seed(self):
        call_command("seed_demo", stdout=StringIO())

    def test_seed_is_idempotent_and_does_not_reset_passwords_or_topics(self):
        with patch.dict(os.environ, seed_passwords()):
            self.seed()
            User = get_user_model()
            admin = User.objects.get(email=DEMO_ACCOUNTS[0][0])
            lecturer = User.objects.get(email=DEMO_ACCOUNTS[1][0])
            student = User.objects.get(email=DEMO_ACCOUNTS[2][0])
            self.assertEqual(User.objects.count(), 3)
            self.assertEqual(Group.objects.filter(name__in=Role.values).count(), 3)
            self.assertEqual(Topic.objects.count(), len(DEMO_TOPICS))
            self.assertGreaterEqual(Topic.objects.count(), 10)
            for topic in Topic.objects.all():
                topic.full_clean()
                self.assertEqual(topic.lecturer, lecturer)
            for email, _, role, variable in DEMO_ACCOUNTS:
                user = User.objects.get(email=email)
                self.assertTrue(user.check_password(os.environ[variable]))
                self.assertTrue(user.groups.filter(name=role).exists())
            self.assertTrue(admin.is_staff)
            self.assertFalse(admin.is_superuser)
            self.assertTrue(admin.has_perm("accounts.change_user"))
            self.assertTrue(admin.has_perm("topics.change_topic"))
            self.assertTrue(admin.has_perm("registrations.change_registration"))
            self.assertFalse(lecturer.is_staff)
            self.assertFalse(student.has_perm("topics.change_topic"))
            original_hash = student.password
            Topic.objects.filter(code=DEMO_TOPICS[0][0]).update(
                title="Nội dung đã chỉnh sửa"
            )
        with patch.dict(os.environ, seed_passwords()):
            self.seed()
        self.assertEqual(User.objects.count(), 3)
        self.assertEqual(Topic.objects.count(), len(DEMO_TOPICS))
        student.refresh_from_db()
        self.assertEqual(student.password, original_hash)
        self.assertEqual(
            Topic.objects.get(code=DEMO_TOPICS[0][0]).title, "Nội dung đã chỉnh sửa"
        )

    def test_missing_password_writes_nothing(self):
        values = seed_passwords()
        values["DEMO_STUDENT_PASSWORD"] = ""
        with patch.dict(os.environ, values), self.assertRaises(CommandError):
            self.seed()
        self.assertFalse(get_user_model().objects.exists())
        self.assertFalse(Group.objects.exists())
        self.assertFalse(Topic.objects.exists())

    def test_invalid_or_reused_password_writes_nothing(self):
        values = seed_passwords()
        values["DEMO_ADMIN_PASSWORD"] = "1"
        with patch.dict(os.environ, values), self.assertRaises(CommandError):
            self.seed()
        self.assertFalse(Group.objects.exists())
        values = seed_passwords()
        values["DEMO_ADMIN_PASSWORD"] = values["DEMO_STUDENT_PASSWORD"]
        with patch.dict(os.environ, values), self.assertRaises(CommandError):
            self.seed()
        self.assertFalse(Group.objects.exists())

    def test_seed_refuses_existing_unrelated_account_and_rolls_back(self):
        get_user_model().objects.create_user(
            DEMO_ACCOUNTS[0][0], full_name="Tài khoản có trước"
        )
        with patch.dict(os.environ, seed_passwords()), self.assertRaises(CommandError):
            self.seed()
        self.assertFalse(Group.objects.exists())
        self.assertFalse(Topic.objects.exists())
        self.assertFalse(get_user_model().objects.get().is_staff)


class HomeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        with patch.dict(os.environ, seed_passwords()):
            call_command("seed_demo", stdout=StringIO())

    def test_home_shows_seeded_data_and_local_bootstrap(self):
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, DEMO_TOPICS[0][1])
        self.assertContains(response, "/static/vendor/bootstrap/bootstrap.min.css")
        self.assertContains(response, 'lang="vi"')
        self.assertEqual(len(response.context["page_obj"]), len(DEMO_TOPICS))

    def test_drafts_hidden_and_search_status_filter_work(self):
        Topic.objects.filter(code="KHCN-001").update(status=Topic.Status.DRAFT)
        Topic.objects.filter(code="KHCN-002").update(status=Topic.Status.CLOSED)
        response = self.client.get("/", {"q": "KHCN-001"})
        self.assertEqual(response.context["page_obj"].paginator.count, 0)
        response = self.client.get("/", {"status": Topic.Status.CLOSED})
        self.assertEqual(response.context["page_obj"].paginator.count, 1)
        response = self.client.get(
            "/", {"q": "KHCN-002", "status": Topic.Status.CLOSED}
        )
        self.assertContains(response, DEMO_TOPICS[1][1])
        response = self.client.get("/", {"status": "INVALID"})
        self.assertEqual(response.context["selected_status"], "")

    def test_query_and_database_content_are_html_escaped(self):
        malicious = "<script>alert(1)</script>"
        Topic.objects.filter(code="KHCN-001").update(title=malicious)
        response = self.client.get("/")
        self.assertNotContains(response, malicious)
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")
        response = self.client.get("/", {"q": malicious})
        self.assertNotContains(response, malicious)
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")

    def test_pagination_and_invalid_page_are_handled(self):
        original = Topic.objects.get(code="KHCN-001")
        Topic.objects.create(
            code="EXTRA-001",
            title="Đề tài thêm",
            description="Mô tả",
            lecturer=original.lecturer,
            status=Topic.Status.OPEN,
        )
        response = self.client.get("/", {"page": "2"})
        self.assertEqual(len(response.context["page_obj"]), 1)
        response = self.client.get("/", {"page": "invalid"})
        self.assertEqual(response.status_code, 200)

    def test_admin_requires_login_and_student_cannot_access(self):
        response = self.client.get("/admin/")
        self.assertRedirects(
            response, "/admin/login/?next=/admin/", fetch_redirect_response=False
        )
        self.client.force_login(get_user_model().objects.get(email=DEMO_ACCOUNTS[2][0]))
        self.assertEqual(self.client.get("/admin/").status_code, 302)

    def test_demo_admin_can_open_custom_user_forms(self):
        self.client.force_login(get_user_model().objects.get(email=DEMO_ACCOUNTS[0][0]))
        self.assertEqual(self.client.get("/admin/accounts/user/").status_code, 200)
        self.assertEqual(self.client.get("/admin/accounts/user/add/").status_code, 200)
        user = get_user_model().objects.get(email=DEMO_ACCOUNTS[2][0])
        response = self.client.get(f"/admin/accounts/user/{user.pk}/change/")
        self.assertEqual(response.status_code, 200)

    def test_health_checks_database(self):
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "database": "ok"})
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_read_only_routes_reject_post(self):
        self.assertEqual(self.client.post("/").status_code, 405)
        self.assertEqual(self.client.post("/health/").status_code, 405)


class HealthFailureTests(SimpleTestCase):
    def test_health_failure_is_sanitized(self):
        with patch("core.views.connection") as database:
            database.cursor.side_effect = OperationalError("private diagnostic")
            response = self.client.get("/health/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(), {"status": "unavailable", "database": "unavailable"}
        )
        self.assertNotContains(response, "private diagnostic", status_code=503)
