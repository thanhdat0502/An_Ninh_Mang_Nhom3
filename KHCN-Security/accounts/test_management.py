"""Real JWT cookies and enforced CSRF for the small account management adapter."""

import secrets

from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from .models import Role, User


@override_settings(DEBUG=True, SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=["localhost"])
class AccountManagementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = secrets.token_urlsafe(24)
        cls.members = {}
        for role in Role.values:
            group = Group.objects.create(name=role)
            user = User.objects.create_user(
                f"{role.lower()}@example.com", cls.password, full_name=role
            )
            user.groups.add(group)
            cls.members[role] = user
        cls.admin = cls.members[Role.ADMIN]
        cls.student = cls.members[Role.STUDENT]
        Group.objects.get(name=Role.ADMIN).permissions.add(
            *Permission.objects.filter(
                content_type__app_label="accounts",
                codename__in=("view_user", "change_user"),
            )
        )
        cls.root = User.objects.create_superuser(
            "root@example.com", cls.password, full_name="Quản trị cấp cao"
        )

    def setUp(self):
        cache.clear()
        self.client = APIClient(enforce_csrf_checks=True, HTTP_HOST="localhost")

    def csrf(self):
        return self.client.get("/api/auth/csrf/").data["csrfToken"]

    def login(self, user=None):
        self.client.cookies.clear()
        response = self.client.post(
            "/api/auth/login/",
            {"email": (user or self.admin).email, "password": self.password},
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf(),
        )
        self.assertEqual(response.status_code, 200)

    def patch(self, user=None, data=None, **headers):
        headers.setdefault("HTTP_X_CSRFTOKEN", self.csrf())
        return self.client.patch(
            f"/api/accounts/{(user or self.student).pk}/",
            data or {"full_name": "Họ tên cập nhật"},
            format="json",
            **headers,
        )

    def test_missing_jwt_is_401(self):
        for url in (
            "/api/accounts/",
            "/api/accounts/capabilities/",
            "/api/accounts/1/",
        ):
            self.assertEqual(self.client.get(url).status_code, 401)

    def test_session_cannot_replace_jwt(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/api/accounts/").status_code, 401)

    def test_invalid_jwt_is_401(self):
        self.client.cookies[settings.JWT_ACCESS_COOKIE] = "invalid"
        self.assertEqual(self.client.get("/api/accounts/").status_code, 401)

    def test_inactive_admin_with_previously_valid_jwt_is_401(self):
        self.login()
        User.objects.filter(pk=self.admin.pk).update(is_active=False)
        self.assertEqual(self.client.get("/api/accounts/").status_code, 401)

    def test_student_and_lecturer_denied_even_with_account_permissions(self):
        permissions = Permission.objects.filter(
            content_type__app_label="accounts",
            codename__in=("view_user", "change_user"),
        )
        for role in (Role.STUDENT, Role.LECTURER):
            user = self.members[role]
            user.user_permissions.add(*permissions)
            self.login(user)
            self.assertEqual(self.client.get("/api/accounts/").status_code, 403)
            self.assertEqual(
                self.client.get(f"/api/accounts/{self.student.pk}/").status_code, 403
            )
            self.assertEqual(self.patch().status_code, 403)
            self.assertEqual(
                self.client.get("/api/accounts/capabilities/").status_code, 403
            )

    def test_client_role_claim_does_not_grant_access(self):
        token = AccessToken.for_user(self.student)
        token["role"] = Role.ADMIN
        self.client.cookies[settings.JWT_ACCESS_COOKIE] = str(token)
        self.assertEqual(self.client.get("/api/accounts/").status_code, 403)

    def test_admin_still_requires_model_permission(self):
        self.login()
        Group.objects.get(name=Role.ADMIN).permissions.clear()
        self.assertEqual(self.client.get("/api/accounts/").status_code, 403)

    def test_view_only_admin_cannot_edit(self):
        self.login()
        group = Group.objects.get(name=Role.ADMIN)
        group.permissions.remove(Permission.objects.get(codename="change_user"))
        result = self.client.get("/api/accounts/")
        self.assertEqual(result.status_code, 200)
        self.assertTrue(all(not row["can_edit"] for row in result.data["results"]))
        self.assertEqual(self.patch().status_code, 403)

    def test_admin_lists_only_allowed_fields_without_staff_requirement(self):
        self.login()
        result = self.client.get("/api/accounts/")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result["Cache-Control"], "no-store")
        self.assertEqual(result.data["count"], 4)
        expected = {"id", "full_name", "email", "roles", "is_active", "can_edit"}
        for row in result.data["results"]:
            self.assertEqual(set(row), expected)
        self.assertFalse(self.admin.is_staff)

    def test_admin_updates_profile_without_changing_privileges(self):
        self.login()
        result = self.patch(
            data={"full_name": "Sinh viên mới", "email": "NEW@EXAMPLE.COM"}
        )
        self.assertEqual(result.status_code, 200)
        self.student.refresh_from_db()
        self.assertEqual(self.student.email, "new@example.com")
        self.assertEqual(self.student.full_name, "Sinh viên mới")
        self.assertEqual(
            list(self.student.groups.values_list("name", flat=True)), [Role.STUDENT]
        )
        self.assertFalse(self.student.is_staff)
        self.assertTrue(self.student.check_password(self.password))

    def test_lock_and_unlock_account(self):
        self.login()
        self.assertEqual(self.patch(data={"is_active": False}).status_code, 200)
        self.student.refresh_from_db()
        self.assertFalse(self.student.is_active)
        self.assertEqual(self.patch(data={"is_active": True}).status_code, 200)
        self.student.refresh_from_db()
        self.assertTrue(self.student.is_active)

    def test_cannot_lock_own_account(self):
        self.login()
        self.assertEqual(self.patch(self.admin, {"is_active": False}).status_code, 400)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_superuser_edit_is_blocked_for_normal_admin(self):
        self.login()
        response = self.client.get(f"/api/accounts/{self.root.pk}/")
        self.assertFalse(response.data["can_edit"])
        self.assertEqual(self.patch(self.root).status_code, 403)

    def test_duplicate_email_case_insensitive_is_rejected(self):
        self.login()
        self.assertEqual(
            self.patch(data={"email": self.admin.email.upper()}).status_code, 400
        )
        self.student.refresh_from_db()
        self.assertEqual(self.student.email, "student@example.com")

    def test_invalid_input_and_privilege_fields_are_rejected(self):
        self.login()
        for data in (
            {"full_name": " "},
            {"email": "invalid"},
            {"full_name": "a" * 151},
            {"roles": [Role.ADMIN]},
            {"groups": [1]},
            {"password": "not-allowed"},
            {"is_staff": True},
            {"is_superuser": True},
            {"user_permissions": [1]},
            {"id": self.admin.pk},
        ):
            with self.subTest(field=next(iter(data))):
                self.assertEqual(self.patch(data=data).status_code, 400)

    def test_missing_csrf_is_403_and_does_not_write(self):
        self.login()
        response = self.client.patch(
            f"/api/accounts/{self.student.pk}/", {"full_name": "Changed"}, format="json"
        )
        self.assertEqual(response.status_code, 403)
        self.student.refresh_from_db()
        self.assertEqual(self.student.full_name, Role.STUDENT)

    def test_invalid_csrf_or_foreign_origin_is_403(self):
        self.login()
        self.assertEqual(self.patch(HTTP_X_CSRFTOKEN="invalid").status_code, 403)
        self.assertEqual(
            self.patch(HTTP_ORIGIN="https://evil.example").status_code, 403
        )

    def test_search_role_active_filter_and_pagination(self):
        self.login()
        User.objects.filter(pk=self.student.pk).update(is_active=False)
        response = self.client.get(
            "/api/accounts/",
            {"search": "STUDENT", "role": Role.STUDENT, "active": "false"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.student.pk)
        response = self.client.get("/api/accounts/", {"page_size": 1, "page": 2})
        self.assertEqual(len(response.data["results"]), 1)
        self.assertTrue(response.data["previous"])
        self.assertTrue(response.data["next"])

    def test_invalid_query_and_oversized_json_rejected(self):
        self.login()
        for query in (
            {"page": 0},
            {"page_size": 101},
            {"role": "ROOT"},
            {"active": "yes"},
        ):
            self.assertEqual(self.client.get("/api/accounts/", query).status_code, 400)
        self.assertEqual(self.patch(data={"full_name": "a" * 66000}).status_code, 413)

    def test_no_create_delete_or_full_update_endpoints(self):
        self.login()
        headers = {"HTTP_X_CSRFTOKEN": self.csrf()}
        self.assertEqual(
            self.client.post(
                "/api/accounts/", {}, format="json", **headers
            ).status_code,
            405,
        )
        url = f"/api/accounts/{self.student.pk}/"
        self.assertEqual(self.client.delete(url, **headers).status_code, 405)
        self.assertEqual(
            self.client.put(url, {}, format="json", **headers).status_code, 405
        )

    def test_new_html_shells_do_not_expose_private_data(self):
        for route, marker in (
            ("/tong-quan/", "data-dashboard"),
            ("/tai-khoan/", "data-account-workspace"),
        ):
            response = self.client.get(route)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, marker)
            self.assertNotContains(response, self.student.email)
            self.assertNotContains(response, self.admin.email)
            self.assertEqual(response["Cache-Control"].split(",")[0], "max-age=0")
            self.assertEqual(
                self.client.post(route, HTTP_X_CSRFTOKEN=self.csrf()).status_code,
                405,
            )
