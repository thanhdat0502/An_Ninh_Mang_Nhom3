import secrets
from datetime import timedelta
from io import StringIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.cache import cache
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import Role
from topics.models import Topic
from topics.roles import sync_topic_permissions

from .models import Registration
from .roles import sync_registration_permissions

User = get_user_model()


@override_settings(DEBUG=True, SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=["localhost"])
class RegistrationAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        sync_topic_permissions()
        sync_registration_permissions()
        cls.password = secrets.token_urlsafe(24)

        def member(email, role=None, **flags):
            user = User.objects.create_user(
                email, cls.password, full_name=email.split("@")[0], **flags
            )
            if role:
                user.groups.add(Group.objects.get(name=role))
            return user

        cls.admin = member("admin@example.com", Role.ADMIN, is_staff=True)
        cls.lecturer = member("lecturer-a@example.com", Role.LECTURER)
        cls.other_lecturer = member("lecturer-b@example.com", Role.LECTURER)
        cls.student = member("student-a@example.com", Role.STUDENT)
        cls.other_student = member("student-b@example.com", Role.STUDENT)
        cls.unassigned = member("unassigned@example.com")

        def topic(code, lecturer, status=Topic.Status.OPEN):
            return Topic.objects.create(
                code=code,
                title=f"Nghiên cứu {code}",
                description="Mô tả nghiên cứu",
                lecturer=lecturer,
                status=status,
            )

        cls.opened = topic("OWN-OPEN", cls.lecturer)
        cls.fresh = topic("NEW-OPEN", cls.lecturer)
        cls.foreign_topic = topic("OTHER-OPEN", cls.other_lecturer)
        cls.closed = topic("OWN-CLOSED", cls.lecturer, Topic.Status.CLOSED)
        cls.completed = topic("OWN-COMPLETED", cls.lecturer, Topic.Status.COMPLETED)
        cls.draft = topic("OWN-DRAFT", cls.lecturer, Topic.Status.DRAFT)
        cls.own = Registration.objects.create(student=cls.student, topic=cls.opened)
        cls.other = Registration.objects.create(
            student=cls.other_student, topic=cls.opened
        )
        cls.foreign = Registration.objects.create(
            student=cls.student, topic=cls.foreign_topic
        )
        cls.foreign_done = Registration.objects.create(
            student=cls.other_student,
            topic=cls.foreign_topic,
            status=Registration.Status.APPROVED,
        )

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

    def post(self, url, data=None, **headers):
        headers.setdefault("HTTP_X_CSRFTOKEN", self.csrf())
        return self.client.post(url, data or {}, format="json", **headers)

    def url(self, registration=None, action=None):
        suffix = f"{action}/" if action else ""
        return f"/api/registrations/{(registration or self.own).pk}/{suffix}"

    def test_student_registers_open_topic_as_self_pending(self):
        self.login(self.student)
        response = self.post("/api/registrations/", {"topic": self.fresh.pk})
        self.assertEqual(response.status_code, 201)
        record = Registration.objects.get(student=self.student, topic=self.fresh)
        self.assertEqual(record.status, Registration.Status.PENDING)
        self.assertIsNone(record.reviewed_by_id)
        self.assertIsNone(record.reviewed_at)
        self.assertEqual(response.data["student"], self.student.pk)
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_duplicate_registration_is_rejected_for_all_existing_states(self):
        self.login(self.student)
        for state in Registration.Status.values:
            Registration.objects.filter(pk=self.own.pk).update(status=state)
            response = self.post("/api/registrations/", {"topic": self.opened.pk})
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.data["code"], "duplicate_registration")
        self.assertEqual(
            Registration.objects.filter(
                student=self.student, topic=self.opened
            ).count(),
            1,
        )

    def test_closed_and_completed_topics_cannot_receive_registrations(self):
        self.login(self.student)
        for topic in (self.closed, self.completed):
            response = self.post("/api/registrations/", {"topic": topic.pk})
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.data["code"], "topic_not_open")

    def test_draft_and_missing_topics_return_404(self):
        self.login(self.student)
        for topic_id in (self.draft.pk, 999999):
            self.assertEqual(
                self.post("/api/registrations/", {"topic": topic_id}).status_code, 404
            )

    def test_lecturer_cannot_register_as_student(self):
        self.login(self.lecturer)
        self.assertEqual(
            self.post("/api/registrations/", {"topic": self.fresh.pk}).status_code, 403
        )

    def test_admin_cannot_register_as_student(self):
        self.login(self.admin)
        self.assertEqual(
            self.post("/api/registrations/", {"topic": self.fresh.pk}).status_code, 403
        )

    def test_multi_group_reviewer_cannot_register_as_student(self):
        for user in (self.admin, self.lecturer):
            user.groups.add(Group.objects.get(name=Role.STUDENT))
            self.login(user)
            self.assertEqual(
                self.post("/api/registrations/", {"topic": self.fresh.pk}).status_code,
                403,
            )

    def test_client_cannot_supply_student_status_role_or_audit_fields(self):
        self.login(self.student)
        for extra in (
            {"student": self.other_student.pk},
            {"student_id": self.other_student.pk},
            {"status": "APPROVED"},
            {"role": "ADMIN"},
            {"id": 100},
            {"reviewed_by": self.admin.pk},
            {"reviewed_at": "2026-01-01T00:00:00Z"},
        ):
            self.assertEqual(
                self.post(
                    "/api/registrations/", {"topic": self.fresh.pk} | extra
                ).status_code,
                400,
            )
        self.assertFalse(Registration.objects.filter(topic=self.fresh).exists())

    def test_query_and_header_cannot_change_student_identity(self):
        self.login(self.student)
        response = self.post(
            f"/api/registrations/?student={self.other_student.pk}&role=ADMIN",
            {"topic": self.fresh.pk},
            HTTP_X_ROLE="ADMIN",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["student"], self.student.pk)

    def test_student_list_contains_only_own_registrations(self):
        self.login(self.student)
        response = self.client.get("/api/registrations/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        self.assertTrue(
            all(item["student"] == self.student.pk for item in response.data["results"])
        )
        self.assertFalse(self.other_student.email.encode() in response.content)

    def test_student_cannot_read_another_students_registration(self):
        self.login(self.student)
        foreign = self.client.get(self.url(self.other))
        missing = self.client.get("/api/registrations/999999/")
        self.assertEqual(foreign.status_code, 404)
        self.assertTrue(foreign.data == missing.data)
        self.assertEqual(self.client.get(self.url()).status_code, 200)

    def test_lecturer_list_and_detail_are_scoped_to_supervised_topics(self):
        self.login(self.lecturer)
        response = self.client.get("/api/registrations/")
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(self.client.get(self.url(self.other)).status_code, 200)
        self.assertEqual(self.client.get(self.url(self.foreign)).status_code, 404)
        self.assertFalse(self.foreign_topic.code.encode() in response.content)

    def test_lecturer_can_approve_pending_registration_and_audit_is_saved(self):
        self.login(self.lecturer)
        started = timezone.now()
        response = self.post(self.url(action="approve"))
        self.assertEqual(response.status_code, 200)
        self.own.refresh_from_db()
        self.assertEqual(self.own.status, Registration.Status.APPROVED)
        self.assertEqual(self.own.reviewed_by_id, self.lecturer.pk)
        self.assertTrue(started <= self.own.reviewed_at <= timezone.now())
        self.assertEqual(response.data["reviewer_name"], self.lecturer.full_name)

    def test_lecturer_can_reject_pending_registration(self):
        self.login(self.lecturer)
        response = self.post(self.url(action="reject"))
        self.assertEqual(response.status_code, 200)
        self.own.refresh_from_db()
        self.assertEqual(self.own.status, Registration.Status.REJECTED)
        self.assertEqual(self.own.reviewed_by_id, self.lecturer.pk)

    def test_lecturer_cannot_review_other_lecturers_registration(self):
        self.login(self.lecturer)
        for action in ("approve", "reject"):
            self.assertEqual(self.post(self.url(self.foreign, action)).status_code, 404)
        self.foreign.refresh_from_db()
        self.assertEqual(self.foreign.status, Registration.Status.PENDING)

    def test_student_cannot_approve_or_reject_even_with_change_permission(self):
        self.student.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="registrations", codename="change_registration"
            )
        )
        self.login(self.student)
        for action in ("approve", "reject"):
            self.assertEqual(self.post(self.url(action=action)).status_code, 403)

    def test_role_in_signed_jwt_does_not_grant_review_permission(self):
        self.login(self.student)
        token = AccessToken(self.client.cookies[settings.JWT_ACCESS_COOKIE].value)
        token["role"] = "ADMIN"
        self.client.cookies[settings.JWT_ACCESS_COOKIE] = str(token)
        self.assertEqual(self.post(self.url(action="approve")).status_code, 403)

    def test_admin_sees_all_and_can_review_foreign_registrations(self):
        self.login(self.admin)
        self.assertEqual(self.client.get("/api/registrations/").data["count"], 4)
        self.assertEqual(self.post(self.url(self.foreign, "approve")).status_code, 200)
        self.assertEqual(self.post(self.url(self.other, "reject")).status_code, 200)
        self.foreign.refresh_from_db()
        self.assertEqual(self.foreign.reviewed_by_id, self.admin.pk)

    def test_unauthenticated_requests_return_401(self):
        for url in (
            "/api/registrations/",
            self.url(),
            "/api/registrations/capabilities/",
        ):
            self.assertEqual(self.client.get(url).status_code, 401)
        self.assertEqual(
            self.post("/api/registrations/", {"topic": self.fresh.pk}).status_code, 401
        )
        self.assertEqual(self.post(self.url(action="approve")).status_code, 401)

    def test_invalid_and_expired_jwt_are_rejected(self):
        self.login(self.student)
        token = AccessToken(self.client.cookies[settings.JWT_ACCESS_COOKIE].value)
        token.set_exp(lifetime=timedelta(seconds=-1))
        for value in ("malformed", str(token)):
            self.client.cookies[settings.JWT_ACCESS_COOKIE] = value
            self.assertEqual(self.client.get("/api/registrations/").status_code, 401)
            self.assertEqual(
                self.post("/api/registrations/", {"topic": self.fresh.pk}).status_code,
                401,
            )

    def test_inactive_actor_cannot_read_or_mutate(self):
        for actor, url, data in (
            (self.student, "/api/registrations/", {"topic": self.fresh.pk}),
            (self.lecturer, self.url(action="approve"), {}),
        ):
            self.login(actor)
            User.objects.filter(pk=actor.pk).update(is_active=False)
            self.assertEqual(self.client.get("/api/registrations/").status_code, 401)
            self.assertEqual(self.post(url, data).status_code, 401)
            User.objects.filter(pk=actor.pk).update(is_active=True)

    def test_session_authentication_is_not_a_jwt_substitute(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/api/registrations/").status_code, 401)

    def test_user_without_business_group_is_denied(self):
        User.objects.filter(pk=self.unassigned.pk).update(
            is_staff=True, is_superuser=True
        )
        self.login(self.unassigned)
        self.assertEqual(self.client.get("/api/registrations/").status_code, 403)
        self.assertEqual(self.post(self.url(action="approve")).status_code, 403)

    def test_register_requires_csrf_cookie_and_header(self):
        self.login(self.student)
        response = self.client.post(
            "/api/registrations/", {"topic": self.fresh.pk}, format="json"
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Registration.objects.filter(topic=self.fresh).exists())

    def test_review_requires_csrf(self):
        self.login(self.lecturer)
        for action in ("approve", "reject"):
            self.assertEqual(
                self.client.post(
                    self.url(action=action), {}, format="json"
                ).status_code,
                403,
            )
        self.own.refresh_from_db()
        self.assertEqual(self.own.status, Registration.Status.PENDING)

    def test_wrong_csrf_and_cross_origin_are_rejected(self):
        self.login(self.student)
        self.assertEqual(
            self.post(
                "/api/registrations/",
                {"topic": self.fresh.pk},
                HTTP_X_CSRFTOKEN=secrets.token_hex(16),
            ).status_code,
            403,
        )
        self.login(self.lecturer)
        self.assertEqual(
            self.post(
                self.url(action="approve"), HTTP_ORIGIN="https://evil.example"
            ).status_code,
            403,
        )

    def test_terminal_states_cannot_be_reviewed(self):
        self.login(self.lecturer)
        for state in (
            Registration.Status.APPROVED,
            Registration.Status.REJECTED,
            Registration.Status.WITHDRAWN,
        ):
            Registration.objects.filter(pk=self.own.pk).update(status=state)
            for action in ("approve", "reject"):
                response = self.post(self.url(action=action))
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.data["code"], "already_processed")

    def test_second_review_preserves_original_decision_and_audit(self):
        self.login(self.lecturer)
        self.assertEqual(self.post(self.url(action="approve")).status_code, 200)
        self.own.refresh_from_db()
        original = (self.own.status, self.own.reviewed_by_id, self.own.reviewed_at)
        self.login(self.admin)
        self.assertEqual(self.post(self.url(action="reject")).status_code, 409)
        self.own.refresh_from_db()
        self.assertTrue(
            (self.own.status, self.own.reviewed_by_id, self.own.reviewed_at) == original
        )

    def test_generic_update_delete_and_reopen_are_not_exposed(self):
        self.login(self.admin)
        for method in ("patch", "put", "delete"):
            response = getattr(self.client, method)(
                self.url(),
                {"status": "APPROVED"},
                format="json",
                HTTP_X_CSRFTOKEN=self.csrf(),
            )
            self.assertEqual(response.status_code, 405)
        self.own.refresh_from_db()
        self.assertEqual(self.own.status, Registration.Status.PENDING)

    def test_review_body_cannot_override_decision_actor_or_audit(self):
        self.login(self.lecturer)
        for payload in (
            {"status": "REJECTED"},
            {"reviewed_by": self.admin.pk},
            {"reviewed_at": "2000-01-01"},
            {"student_id": self.other_student.pk},
            {"role": "ADMIN"},
        ):
            self.assertEqual(
                self.post(self.url(action="approve"), payload).status_code, 400
            )
        self.own.refresh_from_db()
        self.assertEqual(self.own.status, Registration.Status.PENDING)

    def test_filters_are_applied_after_scope_and_do_not_leak_other_users(self):
        self.login(self.student)
        self.assertEqual(
            self.client.get(
                "/api/registrations/", {"student": self.other_student.pk}
            ).data["count"],
            0,
        )
        self.login(self.lecturer)
        self.assertEqual(
            self.client.get(
                "/api/registrations/", {"topic": self.foreign_topic.pk}
            ).data["count"],
            0,
        )
        self.login(self.admin)
        response = self.client.get(
            "/api/registrations/",
            {
                "student": self.other_student.pk,
                "topic": self.foreign_topic.pk,
                "status": "APPROVED",
            },
        )
        self.assertEqual(response.data["count"], 1)

    def test_pending_filter_and_pagination_count_are_scoped(self):
        topics = Topic.objects.bulk_create(
            [
                Topic(
                    code=f"PAGE-{index:03}",
                    title="Phân trang",
                    description="Mô tả",
                    lecturer=self.lecturer,
                    status=Topic.Status.OPEN,
                )
                for index in range(15)
            ]
        )
        Registration.objects.bulk_create(
            [Registration(student=self.student, topic=topic) for topic in topics]
        )
        self.login(self.student)
        first = self.client.get("/api/registrations/?status=PENDING&page_size=5&page=1")
        second = self.client.get(
            "/api/registrations/?status=PENDING&page_size=5&page=2"
        )
        self.assertEqual(first.data["count"], 17)
        self.assertEqual(len(first.data["results"]), 5)
        self.assertFalse(
            {item["id"] for item in first.data["results"]}
            & {item["id"] for item in second.data["results"]}
        )
        self.assertEqual(
            self.client.get("/api/registrations/?page=999").status_code, 404
        )

    def test_query_and_create_input_limits(self):
        self.login(self.student)
        for query in (
            {"status": "INVALID"},
            {"page": "-1"},
            {"page_size": "101"},
            {"topic": "abc"},
            {"student": "0"},
        ):
            self.assertEqual(
                self.client.get("/api/registrations/", query).status_code, 400
            )
        for payload in ({}, {"topic": 0}, {"topic": "wrong"}):
            self.assertEqual(self.post("/api/registrations/", payload).status_code, 400)
        response = self.client.post(
            "/api/registrations/",
            '{"topic":"' + "x" * 65536 + '"}',
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self.csrf(),
        )
        self.assertEqual(response.status_code, 413)

    def test_permission_revocation_is_effective_with_existing_jwt(self):
        self.login(self.student)
        Group.objects.get(name=Role.STUDENT).permissions.remove(
            Permission.objects.get(
                content_type__app_label="registrations", codename="add_registration"
            )
        )
        self.assertEqual(
            self.post("/api/registrations/", {"topic": self.fresh.pk}).status_code, 403
        )
        self.login(self.lecturer)
        Group.objects.get(name=Role.LECTURER).permissions.remove(
            Permission.objects.get(
                content_type__app_label="registrations", codename="change_registration"
            )
        )
        self.assertEqual(self.post(self.url(action="approve")).status_code, 403)

    def test_missing_view_permission_is_403(self):
        self.login(self.student)
        Group.objects.get(name=Role.STUDENT).permissions.remove(
            Permission.objects.get(
                content_type__app_label="registrations", codename="view_registration"
            )
        )
        self.assertEqual(self.client.get("/api/registrations/").status_code, 403)

    def test_topic_reassignment_changes_reviewer_scope_immediately(self):
        self.login(self.lecturer)
        Topic.objects.filter(pk=self.opened.pk).update(lecturer=self.other_lecturer)
        self.assertEqual(self.post(self.url(action="approve")).status_code, 404)
        self.login(self.other_lecturer)
        self.assertEqual(self.post(self.url(action="approve")).status_code, 200)

    def test_closing_topic_stops_new_requests_but_not_pending_review(self):
        Topic.objects.filter(pk=self.opened.pk).update(status=Topic.Status.CLOSED)
        self.login(self.lecturer)
        self.assertEqual(self.post(self.url(action="approve")).status_code, 200)

    def test_historical_student_group_change_does_not_corrupt_review(self):
        self.student.groups.clear()
        self.login(self.lecturer)
        self.assertEqual(self.post(self.url(action="reject")).status_code, 200)

    def test_reviewer_is_protected_from_deletion(self):
        self.login(self.admin)
        self.assertEqual(self.post(self.url(action="approve")).status_code, 200)
        with self.assertRaises(ProtectedError):
            self.admin.delete()

    def test_database_audit_fields_must_be_paired_and_pending_has_no_audit(self):
        for values in (
            {"reviewed_at": timezone.now()},
            {"reviewed_at": timezone.now(), "reviewed_by": self.admin},
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                Registration.objects.filter(pk=self.own.pk).update(**values)

    def test_legacy_resolved_records_without_audit_remain_readable(self):
        self.login(self.admin)
        response = self.client.get(self.url(self.foreign_done))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["reviewed_by"])
        self.assertIsNone(response.data["reviewed_at"])

    def test_readonly_django_admin_cannot_bypass_review_workflow(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            f"/admin/registrations/registration/{self.own.pk}/change/",
            {"status": "APPROVED"},
            format="multipart",
            HTTP_X_CSRFTOKEN=self.csrf(),
        )
        self.assertEqual(response.status_code, 403)
        self.own.refresh_from_db()
        self.assertEqual(self.own.status, Registration.Status.PENDING)

    def test_staff_flag_does_not_open_private_registration_admin(self):
        for actor in (self.lecturer, self.student):
            User.objects.filter(pk=actor.pk).update(is_staff=True)
            self.client.force_login(actor)
            response = self.client.get(
                f"/admin/registrations/registration/{self.other.pk}/change/"
            )
            self.assertEqual(response.status_code, 403)

    def test_capabilities_and_permission_sync_are_role_based_and_idempotent(self):
        call_command("sync_registration_permissions", stdout=StringIO())
        call_command("sync_registration_permissions", stdout=StringIO())
        for actor, register, review in (
            (self.student, True, False),
            (self.lecturer, False, True),
            (self.admin, False, True),
        ):
            self.login(actor)
            data = self.client.get("/api/registrations/capabilities/").data
            self.assertEqual(data["can_register"], register)
            self.assertEqual(data["can_review"], review)
        self.assertEqual(
            Group.objects.get(name=Role.STUDENT)
            .permissions.filter(content_type__app_label="registrations")
            .count(),
            2,
        )

    def test_registration_page_contains_no_embedded_private_records(self):
        response = self.client.get("/dang-ky/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-registration-workspace")
        self.assertFalse(self.student.email.encode() in response.content)
        self.assertFalse(self.other_student.email.encode() in response.content)
