import secrets
from datetime import timedelta
from io import StringIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import Role
from registrations.models import Registration
from topics.models import Topic
from topics.roles import sync_topic_permissions

User = get_user_model()


@override_settings(DEBUG=True, SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=["localhost"])
class TopicAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        sync_topic_permissions()
        cls.password = secrets.token_urlsafe(24)

        def member(email, role=None, **flags):
            user = User.objects.create_user(
                email, cls.password, full_name=email.split("@")[0], **flags
            )
            if role:
                user.groups.add(Group.objects.get(name=role))
            return user

        cls.admin = member("admin@example.com", Role.ADMIN, is_staff=True)
        cls.lecturer = member("lecturer@example.com", Role.LECTURER)
        cls.other = member("other@example.com", Role.LECTURER)
        cls.student = member("student@example.com", Role.STUDENT)
        cls.unassigned = member("unassigned@example.com")

        def topic(code, lecturer, status):
            return Topic.objects.create(
                code=code,
                title=f"Nghiên cứu mạng {code}",
                description="Nội dung nghiên cứu",
                lecturer=lecturer,
                status=status,
            )

        cls.opened = topic("OWN-OPEN", cls.lecturer, Topic.Status.OPEN)
        cls.draft = topic("OWN-DRAFT", cls.lecturer, Topic.Status.DRAFT)
        cls.closed = topic("OWN-CLOSED", cls.lecturer, Topic.Status.CLOSED)
        cls.foreign = topic("OTHER-OPEN", cls.other, Topic.Status.OPEN)
        cls.foreign_draft = topic("OTHER-DRAFT", cls.other, Topic.Status.DRAFT)
        cls.completed = topic("OTHER-COMPLETED", cls.other, Topic.Status.COMPLETED)

    def setUp(self):
        cache.clear()
        self.client = APIClient(enforce_csrf_checks=True, HTTP_HOST="localhost")

    def csrf(self):
        response = self.client.get("/api/auth/csrf/")
        self.assertEqual(response.status_code, 200)
        return response.data["csrfToken"]

    def login(self, user):
        self.client.cookies.clear()
        response = self.client.post(
            "/api/auth/login/",
            {"email": user.email, "password": self.password},
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf(),
        )
        self.assertEqual(response.status_code, 200)

    def write(self, method, url, data=None, **headers):
        headers.setdefault("HTTP_X_CSRFTOKEN", self.csrf())
        return getattr(self.client, method.lower())(
            url, data=data, format="json", **headers
        )

    def payload(self, **changes):
        data = {
            "code": "NEW-001",
            "title": "Đề tài mới",
            "description": "Mô tả nghiên cứu",
            "lecturer": self.lecturer.pk,
            "status": Topic.Status.OPEN,
        }
        return data | changes

    def url(self, topic=None):
        return f"/api/topics/{(topic or self.opened).pk}/"

    def test_admin_can_create_topic(self):
        self.login(self.admin)
        response = self.write("post", "/api/topics/", self.payload())
        self.assertEqual(response.status_code, 201)
        created = Topic.objects.get(code="NEW-001")
        self.assertEqual(created.lecturer_id, self.lecturer.pk)
        self.assertEqual(response.data["lecturer_name"], self.lecturer.full_name)
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_admin_can_patch_topic(self):
        self.login(self.admin)
        response = self.write(
            "patch",
            self.url(),
            {"title": "Tên cập nhật", "status": Topic.Status.CLOSED},
        )
        self.assertEqual(response.status_code, 200)
        self.opened.refresh_from_db()
        self.assertEqual(self.opened.title, "Tên cập nhật")
        self.assertEqual(self.opened.status, Topic.Status.CLOSED)

    def test_admin_can_put_topic(self):
        self.login(self.admin)
        response = self.write("put", self.url(), self.payload(code=self.opened.code))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Topic.objects.count(), 6)

    def test_admin_can_delete_unreferenced_topic(self):
        self.login(self.admin)
        self.assertEqual(self.write("delete", self.url()).status_code, 204)
        self.assertFalse(Topic.objects.filter(pk=self.opened.pk).exists())

    def test_duplicate_code_create_and_update_are_rejected(self):
        self.login(self.admin)
        response = self.write(
            "post", "/api/topics/", self.payload(code=self.opened.code)
        )
        self.assertEqual(response.status_code, 400)
        self.assertTrue("code" in response.data)
        response = self.write(
            "patch", self.url(self.foreign), {"code": self.opened.code}
        )
        self.assertEqual(response.status_code, 400)
        self.foreign.refresh_from_db()
        self.assertEqual(self.foreign.code, "OTHER-OPEN")

    def test_protected_deletion_is_409_without_related_user_data(self):
        registration = Registration.objects.create(
            student=self.student, topic=self.opened
        )
        self.login(self.admin)
        for state in Registration.Status.values:
            Registration.objects.filter(pk=registration.pk).update(status=state)
            response = self.write("delete", self.url())
            self.assertEqual(response.status_code, 409)
            self.assertTrue(Topic.objects.filter(pk=self.opened.pk).exists())
            self.assertFalse(self.student.email.encode() in response.content)
        self.assertEqual(Registration.objects.count(), 1)

    def test_unauthenticated_api_returns_401(self):
        for url in (
            "/api/topics/",
            self.url(),
            "/api/topics/capabilities/",
            "/api/topics/lecturers/",
        ):
            self.assertEqual(self.client.get(url).status_code, 401)
        self.assertEqual(
            self.write("post", "/api/topics/", self.payload()).status_code, 401
        )

    def test_django_admin_session_cannot_authenticate_topic_api(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/api/topics/").status_code, 401)

    def test_student_cannot_create_update_or_delete(self):
        self.login(self.student)
        for method, url, data in (
            ("post", "/api/topics/", self.payload()),
            ("patch", self.url(), {"title": "Trái phép"}),
            ("put", self.url(), self.payload()),
            ("delete", self.url(), None),
        ):
            self.assertEqual(self.write(method, url, data).status_code, 403)
        self.opened.refresh_from_db()
        self.assertEqual(self.opened.title, "Nghiên cứu mạng OWN-OPEN")
        self.assertEqual(Topic.objects.count(), 6)

    def test_lecturer_cannot_administer_even_owned_topics(self):
        self.login(self.lecturer)
        for method, url, data in (
            ("post", "/api/topics/", self.payload()),
            ("patch", self.url(), {"title": "Trái phép"}),
            ("delete", self.url(), None),
            ("patch", self.url(self.foreign), {"title": "Trái phép"}),
        ):
            self.assertEqual(self.write(method, url, data).status_code, 403)

    def test_client_role_fields_and_headers_cannot_escalate_privileges(self):
        self.login(self.student)
        response = self.write(
            "post",
            "/api/topics/?role=ADMIN",
            self.payload(role="ADMIN", is_staff=True),
            HTTP_X_ROLE="ADMIN",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Topic.objects.filter(code="NEW-001").exists())

    def test_role_claim_in_signed_jwt_does_not_override_server_groups(self):
        self.login(self.student)
        token = AccessToken(self.client.cookies[settings.JWT_ACCESS_COOKIE].value)
        token["role"] = "ADMIN"
        token["roles"] = ["ADMIN"]
        self.client.cookies[settings.JWT_ACCESS_COOKIE] = str(token)
        self.assertEqual(
            self.write("post", "/api/topics/", self.payload()).status_code, 403
        )

    def test_student_cannot_change_own_role_via_me(self):
        self.login(self.student)
        response = self.write(
            "patch",
            "/api/auth/me/",
            {"roles": ["ADMIN"], "is_staff": True, "is_superuser": True},
        )
        self.assertEqual(response.status_code, 405)
        self.student.refresh_from_db()
        self.assertFalse(self.student.is_staff)
        self.assertEqual(
            list(self.student.groups.values_list("name", flat=True)), [Role.STUDENT]
        )

    def test_accidentally_granted_student_write_permissions_do_not_bypass_role(self):
        self.student.user_permissions.add(
            *Permission.objects.filter(content_type__app_label="topics")
        )
        self.login(self.student)
        self.assertEqual(
            self.write("post", "/api/topics/", self.payload()).status_code, 403
        )

    def test_admin_requires_real_model_permission_for_each_operation(self):
        self.login(self.admin)
        group = Group.objects.get(name=Role.ADMIN)
        for codename, method, url, data in (
            ("add_topic", "post", "/api/topics/", self.payload()),
            ("change_topic", "patch", self.url(), {"title": "Không được"}),
            ("delete_topic", "delete", self.url(), None),
        ):
            group.permissions.remove(
                Permission.objects.get(
                    content_type__app_label="topics", codename=codename
                )
            )
            self.assertEqual(self.write(method, url, data).status_code, 403)

    def test_view_permission_removal_is_effective_on_next_request(self):
        self.login(self.student)
        self.assertEqual(self.client.get("/api/topics/").status_code, 200)
        Group.objects.get(name=Role.STUDENT).permissions.clear()
        self.assertEqual(self.client.get("/api/topics/").status_code, 403)

    def test_role_removal_is_effective_without_reissuing_jwt(self):
        self.login(self.admin)
        self.admin.groups.clear()
        self.assertEqual(self.client.get("/api/topics/").status_code, 403)
        self.assertEqual(
            self.write("post", "/api/topics/", self.payload()).status_code, 403
        )

    def test_authenticated_user_without_business_group_is_denied(self):
        self.login(self.unassigned)
        self.assertEqual(self.client.get("/api/topics/").status_code, 403)
        self.assertEqual(self.client.get(self.url()).status_code, 403)

    def test_staff_or_superuser_flag_does_not_select_business_role(self):
        User.objects.filter(pk=self.unassigned.pk).update(
            is_staff=True, is_superuser=True
        )
        self.login(self.unassigned)
        self.assertEqual(self.client.get("/api/topics/").status_code, 403)

    def test_inactive_user_is_rejected_before_business_execution(self):
        self.login(self.admin)
        User.objects.filter(pk=self.admin.pk).update(is_active=False)
        self.assertEqual(self.client.get("/api/topics/").status_code, 401)
        self.assertEqual(
            self.write("post", "/api/topics/", self.payload()).status_code, 401
        )
        self.assertEqual(Topic.objects.count(), 6)

    def test_invalid_and_expired_jwt_are_rejected(self):
        self.login(self.admin)
        token = AccessToken(self.client.cookies[settings.JWT_ACCESS_COOKIE].value)
        token.set_exp(lifetime=timedelta(seconds=-1))
        for value in ("malformed", str(token)):
            self.client.cookies[settings.JWT_ACCESS_COOKIE] = value
            self.assertEqual(self.client.get("/api/topics/").status_code, 401)
            self.assertEqual(
                self.write("post", "/api/topics/", self.payload()).status_code, 401
            )

    def test_mutations_require_csrf_with_valid_cookie_jwt(self):
        self.login(self.admin)
        for method, url, data in (
            ("post", "/api/topics/", self.payload()),
            ("patch", self.url(), {"title": "Không CSRF"}),
            ("delete", self.url(), None),
        ):
            response = getattr(self.client, method)(url, data=data, format="json")
            self.assertEqual(response.status_code, 403)
        self.assertEqual(Topic.objects.count(), 6)

    def test_wrong_csrf_or_cross_origin_does_not_mutate(self):
        self.login(self.admin)
        self.assertEqual(
            self.write(
                "post",
                "/api/topics/",
                self.payload(),
                HTTP_X_CSRFTOKEN=secrets.token_hex(16),
            ).status_code,
            403,
        )
        self.assertEqual(
            self.write(
                "patch",
                self.url(),
                {"title": "Không"},
                HTTP_ORIGIN="https://evil.example",
            ).status_code,
            403,
        )
        self.assertEqual(Topic.objects.count(), 6)

    def test_lecturer_queryset_and_detail_are_scoped(self):
        self.login(self.lecturer)
        response = self.client.get("/api/topics/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 3)
        self.assertTrue(
            all(
                item["lecturer"] == self.lecturer.pk
                for item in response.data["results"]
            )
        )
        self.assertEqual(self.client.get(self.url(self.draft)).status_code, 200)
        for topic in (self.foreign, self.foreign_draft, self.completed):
            self.assertEqual(self.client.get(self.url(topic)).status_code, 404)

    def test_out_of_scope_and_missing_objects_have_consistent_404(self):
        self.login(self.lecturer)
        foreign = self.client.get(self.url(self.foreign))
        missing = self.client.get("/api/topics/999999/")
        self.assertEqual(foreign.status_code, 404)
        self.assertTrue(foreign.data == missing.data)

    def test_student_sees_only_published_topics(self):
        self.login(self.student)
        response = self.client.get("/api/topics/")
        self.assertEqual(response.data["count"], 4)
        self.assertTrue(
            all(
                item["status"] != Topic.Status.DRAFT
                for item in response.data["results"]
            )
        )
        self.assertEqual(self.client.get(self.url(self.foreign)).status_code, 200)
        self.assertEqual(self.client.get(self.url(self.draft)).status_code, 404)
        self.assertEqual(self.client.get("/api/topics/?status=DRAFT").data["count"], 0)

    def test_admin_can_view_all_including_drafts(self):
        self.login(self.admin)
        self.assertEqual(self.client.get("/api/topics/").data["count"], 6)
        self.assertEqual(self.client.get(self.url(self.foreign_draft)).status_code, 200)

    def test_multi_group_lecturer_cannot_widen_scope_via_student_membership(self):
        self.lecturer.groups.add(Group.objects.get(name=Role.STUDENT))
        self.login(self.lecturer)
        self.assertEqual(self.client.get("/api/topics/").data["count"], 3)
        self.assertEqual(self.client.get(self.url(self.foreign)).status_code, 404)

    def test_query_cannot_override_scope_or_role(self):
        self.login(self.lecturer)
        response = self.client.get(
            "/api/topics/", {"lecturer": self.other.pk, "role": "ADMIN"}
        )
        self.assertEqual(response.data["count"], 3)
        self.assertTrue(
            all(
                item["lecturer"] == self.lecturer.pk
                for item in response.data["results"]
            )
        )

    def test_search_code_title_status_and_combined_filters(self):
        self.login(self.admin)
        self.assertEqual(
            self.client.get("/api/topics/?search=OWN-OPEN").data["count"], 1
        )
        self.assertEqual(
            self.client.get("/api/topics/", {"search": "nghiên cứu mạng"}).data[
                "count"
            ],
            6,
        )
        response = self.client.get("/api/topics/", {"search": "OWN", "status": "DRAFT"})
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.draft.pk)
        self.assertEqual(
            self.client.get("/api/topics/", {"search": "' OR 1=1 --"}).data["count"], 0
        )

    def test_pagination_is_stable_and_count_is_scoped(self):
        Topic.objects.bulk_create(
            [
                Topic(
                    code=f"PAGE-{index:03}",
                    title="Đề tài phân trang",
                    description="Mô tả",
                    lecturer=self.lecturer,
                    status=Topic.Status.OPEN,
                )
                for index in range(15)
            ]
        )
        self.login(self.lecturer)
        first = self.client.get("/api/topics/?page_size=5&page=1")
        second = self.client.get("/api/topics/?page_size=5&page=2")
        self.assertEqual(first.data["count"], 18)
        self.assertEqual(len(first.data["results"]), 5)
        self.assertTrue(bool(first.data["next"]))
        self.assertFalse(
            {item["id"] for item in first.data["results"]}
            & {item["id"] for item in second.data["results"]}
        )
        self.assertEqual(self.client.get("/api/topics/?page=999").status_code, 404)

    def test_bad_filters_and_excessive_limits_are_rejected(self):
        self.login(self.admin)
        for query in (
            {"status": "INVALID"},
            {"page_size": "101"},
            {"page_size": "0"},
            {"page": "-1"},
            {"page": "wrong"},
            {"search": "a" * 151},
        ):
            self.assertEqual(self.client.get("/api/topics/", query).status_code, 400)

    def test_validation_rejects_bad_fields_and_keeps_database_unchanged(self):
        self.login(self.admin)
        for changes in (
            {"code": "lower case"},
            {"title": " "},
            {"description": " "},
            {"status": "INVALID"},
            {"title": "a" * 256},
            {"description": "a" * 10001},
        ):
            self.assertEqual(
                self.write("post", "/api/topics/", self.payload(**changes)).status_code,
                400,
            )
        self.assertEqual(Topic.objects.count(), 6)

    def test_lecturer_must_exist_be_active_and_belong_to_lecturer_group(self):
        self.login(self.admin)
        for lecturer_id in (999999, self.student.pk):
            self.assertEqual(
                self.write(
                    "post", "/api/topics/", self.payload(lecturer=lecturer_id)
                ).status_code,
                400,
            )
        User.objects.filter(pk=self.other.pk).update(is_active=False)
        self.assertEqual(
            self.write(
                "post", "/api/topics/", self.payload(lecturer=self.other.pk)
            ).status_code,
            400,
        )

    def test_unknown_and_readonly_fields_are_rejected(self):
        self.login(self.admin)
        for changes in (
            {"roles": ["ADMIN"]},
            {"id": 100},
            {"created_at": "2000-01-01"},
            {"is_superuser": True},
            {"lecturer_name": "Giả mạo"},
        ):
            self.assertEqual(
                self.write("post", "/api/topics/", self.payload(**changes)).status_code,
                400,
            )
        self.assertEqual(Topic.objects.count(), 6)

    def test_json_body_size_is_bounded(self):
        self.login(self.admin)
        response = self.client.post(
            "/api/topics/",
            data='{"description":"' + "x" * 65536 + '"}',
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self.csrf(),
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(Topic.objects.count(), 6)

    def test_capabilities_reflect_real_server_permissions(self):
        self.login(self.admin)
        response = self.client.get("/api/topics/capabilities/")
        self.assertTrue(response.data["can_create"])
        Group.objects.get(name=Role.ADMIN).permissions.remove(
            Permission.objects.get(
                content_type__app_label="topics", codename="change_topic"
            )
        )
        self.assertFalse(self.client.get("/api/topics/capabilities/").data["can_edit"])
        self.login(self.student)
        response = self.client.get("/api/topics/capabilities/")
        self.assertFalse(
            response.data["can_create"]
            or response.data["can_edit"]
            or response.data["can_delete"]
        )
        self.assertIsNone(response.data["account_management_url"])

    def test_lecturer_selector_is_admin_only_and_contains_no_email(self):
        self.login(self.admin)
        response = self.client.get("/api/topics/lecturers/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        self.assertTrue(
            all(set(item) == {"id", "full_name"} for item in response.data["results"])
        )
        for user in (self.student, self.lecturer):
            self.login(user)
            self.assertEqual(self.client.get("/api/topics/lecturers/").status_code, 403)

    def test_permission_sync_is_idempotent_and_does_not_change_users(self):
        before = User.objects.count()
        call_command("sync_topic_permissions", stdout=StringIO())
        call_command("sync_topic_permissions", stdout=StringIO())
        self.assertEqual(User.objects.count(), before)
        self.assertEqual(Group.objects.get(name=Role.STUDENT).permissions.count(), 1)
        self.assertEqual(Group.objects.get(name=Role.ADMIN).permissions.count(), 4)

    def test_workspace_and_detail_html_do_not_embed_protected_records(self):
        private_text = "PRIVATE-DRAFT-CONTENT-ONLY-FOR-ASSIGNED-LECTURER"
        Topic.objects.filter(pk=self.foreign_draft.pk).update(description=private_text)
        self.assertContains(self.client.get("/de-tai/"), "data-topic-workspace")
        response = self.client.get(f"/de-tai/{self.foreign_draft.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.foreign_draft.title.encode() in response.content)
        self.assertFalse(private_text.encode() in response.content)
